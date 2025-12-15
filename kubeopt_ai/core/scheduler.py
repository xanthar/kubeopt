"""
Scheduled optimization service for KubeOpt AI.

Provides scheduling infrastructure for automated optimization runs using
APScheduler with cron expression support.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from croniter import croniter
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.base import JobLookupError
import pytz

from kubeopt_ai.extensions import db
from kubeopt_ai.core.models import (
    Schedule,
    ScheduleRun,
    ScheduleStatus,
    ScheduleRunStatus,
    ScheduleTriggerType,
    OptimizationRun,
    RunStatus,
)

logger = logging.getLogger(__name__)


class CronValidationError(Exception):
    """Raised when a cron expression is invalid."""
    pass


class ScheduleNotFoundError(Exception):
    """Raised when a schedule is not found."""
    pass


class SchedulerService:
    """
    Service for managing scheduled optimization runs.

    Provides CRUD operations for schedules and integrates with APScheduler
    for background job execution.
    """

    def __init__(self, optimizer_service=None):
        """
        Initialize the scheduler service.

        Args:
            optimizer_service: Optional optimizer service for running optimizations.
                              Can be set later via set_optimizer_service().
        """
        self._scheduler: Optional[BackgroundScheduler] = None
        self._optimizer_service = optimizer_service
        self._is_running = False

    def set_optimizer_service(self, optimizer_service) -> None:
        """Set the optimizer service for running optimizations."""
        self._optimizer_service = optimizer_service

    @staticmethod
    def validate_cron_expression(cron_expression: str) -> bool:
        """
        Validate a cron expression.

        Args:
            cron_expression: The cron expression to validate.

        Returns:
            True if valid.

        Raises:
            CronValidationError: If the expression is invalid.
        """
        try:
            # croniter expects a base time for validation
            croniter(cron_expression, datetime.now(timezone.utc))
            return True
        except (KeyError, ValueError) as e:
            raise CronValidationError(f"Invalid cron expression: {cron_expression}. Error: {str(e)}")

    @staticmethod
    def get_next_run_time(
        cron_expression: str,
        tz: str = "UTC",
        base_time: Optional[datetime] = None
    ) -> datetime:
        """
        Calculate the next run time for a cron expression.

        Args:
            cron_expression: The cron expression.
            tz: Timezone string (e.g., "UTC", "America/New_York").
            base_time: Base time to calculate from (defaults to now).

        Returns:
            The next scheduled run time as a timezone-aware datetime.
        """
        if base_time is None:
            base_time = datetime.now(timezone.utc)

        try:
            target_tz = pytz.timezone(tz)
        except pytz.exceptions.UnknownTimeZoneError:
            target_tz = pytz.UTC

        # Convert base_time to target timezone
        if base_time.tzinfo is None:
            base_time = pytz.UTC.localize(base_time)
        base_time_local = base_time.astimezone(target_tz)

        # Get next run time in local timezone
        cron = croniter(cron_expression, base_time_local)
        next_time_local = cron.get_next(datetime)

        # Convert back to UTC
        return next_time_local.astimezone(pytz.UTC)

    def start(self) -> None:
        """Start the background scheduler."""
        if self._is_running:
            logger.warning("Scheduler is already running")
            return

        self._scheduler = BackgroundScheduler(
            timezone=pytz.UTC,
            job_defaults={
                'coalesce': True,
                'max_instances': 1,
                'misfire_grace_time': 300,  # 5 minutes
            }
        )
        self._scheduler.start()
        self._is_running = True
        logger.info("Scheduler started")

        # Load existing active schedules
        self._load_active_schedules()

    def stop(self) -> None:
        """Stop the background scheduler."""
        if self._scheduler and self._is_running:
            self._scheduler.shutdown(wait=False)
            self._is_running = False
            logger.info("Scheduler stopped")

    def _load_active_schedules(self) -> None:
        """Load all active schedules and add them to APScheduler."""
        schedules = Schedule.query.filter_by(status=ScheduleStatus.ACTIVE).all()
        for schedule in schedules:
            self._add_job(schedule)
        logger.info(f"Loaded {len(schedules)} active schedules")

    def _add_job(self, schedule: Schedule) -> None:
        """Add a schedule job to APScheduler."""
        if not self._scheduler or not self._is_running:
            logger.warning("Scheduler not running, cannot add job")
            return

        try:
            # Parse cron expression into CronTrigger
            parts = schedule.cron_expression.split()
            if len(parts) == 5:
                minute, hour, day, month, day_of_week = parts
            else:
                logger.error(f"Invalid cron expression for schedule {schedule.id}: {schedule.cron_expression}")
                return

            trigger = CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week,
                timezone=pytz.timezone(schedule.timezone),
            )

            self._scheduler.add_job(
                func=self._execute_schedule,
                trigger=trigger,
                id=f"schedule_{schedule.id}",
                args=[schedule.id],
                replace_existing=True,
            )
            logger.info(f"Added job for schedule {schedule.id} ({schedule.name})")
        except Exception as e:
            logger.error(f"Failed to add job for schedule {schedule.id}: {e}")

    def _remove_job(self, schedule_id: str) -> None:
        """Remove a schedule job from APScheduler."""
        if not self._scheduler:
            return

        try:
            self._scheduler.remove_job(f"schedule_{schedule_id}")
            logger.info(f"Removed job for schedule {schedule_id}")
        except JobLookupError:
            logger.debug(f"Job for schedule {schedule_id} not found (already removed)")

    def _execute_schedule(self, schedule_id: str) -> None:
        """
        Execute a scheduled optimization run.

        This is the callback function invoked by APScheduler.
        """
        from flask import current_app

        # Need app context for database operations
        with current_app.app_context():
            schedule = Schedule.query.get(schedule_id)
            if not schedule:
                logger.error(f"Schedule {schedule_id} not found")
                return

            if schedule.status != ScheduleStatus.ACTIVE:
                logger.info(f"Schedule {schedule_id} is not active, skipping")
                return

            logger.info(f"Executing schedule {schedule.id} ({schedule.name})")

            # Create schedule run record
            schedule_run = ScheduleRun(
                schedule_id=schedule.id,
                status=ScheduleRunStatus.RUNNING,
                trigger_type=ScheduleTriggerType.SCHEDULED,
                scheduled_time=datetime.now(timezone.utc),
                started_at=datetime.now(timezone.utc),
            )
            db.session.add(schedule_run)
            db.session.commit()

            try:
                # Execute optimization
                if self._optimizer_service:
                    optimization_run = self._optimizer_service.run_optimization(
                        manifest_source_path=schedule.manifest_source_path,
                        lookback_days=schedule.lookback_days,
                        cluster_id=schedule.cluster_id,
                        team_id=schedule.team_id,
                    )
                    schedule_run.optimization_run_id = optimization_run.id
                    schedule_run.result_summary = {
                        "optimization_run_id": optimization_run.id,
                        "status": optimization_run.status.value,
                    }
                else:
                    logger.warning("No optimizer service configured, creating placeholder run")
                    # Create a placeholder optimization run
                    optimization_run = OptimizationRun(
                        manifest_source_path=schedule.manifest_source_path,
                        lookback_days=schedule.lookback_days,
                        cluster_id=schedule.cluster_id,
                        team_id=schedule.team_id,
                        status=RunStatus.COMPLETED,
                    )
                    db.session.add(optimization_run)
                    db.session.commit()
                    schedule_run.optimization_run_id = optimization_run.id
                    schedule_run.result_summary = {
                        "optimization_run_id": optimization_run.id,
                        "status": "completed",
                        "note": "Placeholder run (no optimizer service)",
                    }

                # Mark run as completed
                schedule_run.status = ScheduleRunStatus.COMPLETED
                schedule_run.completed_at = datetime.now(timezone.utc)
                if schedule_run.started_at:
                    schedule_run.duration_seconds = int(
                        (schedule_run.completed_at - schedule_run.started_at).total_seconds()
                    )

                # Update schedule stats
                schedule.last_run_at = datetime.now(timezone.utc)
                schedule.run_count += 1
                schedule.consecutive_failures = 0
                schedule.next_run_at = self.get_next_run_time(
                    schedule.cron_expression,
                    schedule.timezone
                )

                db.session.commit()
                logger.info(f"Schedule {schedule.id} completed successfully")

            except Exception as e:
                logger.error(f"Schedule {schedule.id} failed: {e}")

                # Mark run as failed
                schedule_run.status = ScheduleRunStatus.FAILED
                schedule_run.completed_at = datetime.now(timezone.utc)
                schedule_run.error_message = str(e)
                if schedule_run.started_at:
                    schedule_run.duration_seconds = int(
                        (schedule_run.completed_at - schedule_run.started_at).total_seconds()
                    )

                # Update schedule stats
                schedule.last_run_at = datetime.now(timezone.utc)
                schedule.failure_count += 1
                schedule.consecutive_failures += 1
                schedule.next_run_at = self.get_next_run_time(
                    schedule.cron_expression,
                    schedule.timezone
                )

                # Auto-pause on consecutive failures
                if schedule.consecutive_failures >= schedule.max_consecutive_failures:
                    schedule.status = ScheduleStatus.PAUSED
                    self._remove_job(schedule.id)
                    logger.warning(
                        f"Schedule {schedule.id} paused after {schedule.consecutive_failures} "
                        f"consecutive failures"
                    )

                db.session.commit()

    # =========================================================================
    # CRUD Operations
    # =========================================================================

    def create_schedule(
        self,
        name: str,
        cron_expression: str,
        manifest_source_path: str,
        description: Optional[str] = None,
        timezone: str = "UTC",
        lookback_days: int = 7,
        cluster_id: Optional[str] = None,
        team_id: Optional[str] = None,
        created_by_id: Optional[str] = None,
        settings: Optional[dict] = None,
        max_consecutive_failures: int = 3,
    ) -> Schedule:
        """
        Create a new schedule.

        Args:
            name: Schedule name.
            cron_expression: Cron expression for scheduling.
            manifest_source_path: Path to Kubernetes manifests.
            description: Optional description.
            timezone: Timezone for the cron expression.
            lookback_days: Number of days to look back for metrics.
            cluster_id: Optional cluster ID.
            team_id: Optional team ID for multi-tenancy.
            created_by_id: Optional user ID who created the schedule.
            settings: Optional additional settings.
            max_consecutive_failures: Max failures before auto-pause.

        Returns:
            The created Schedule object.

        Raises:
            CronValidationError: If the cron expression is invalid.
        """
        # Validate cron expression
        self.validate_cron_expression(cron_expression)

        # Calculate next run time
        next_run = self.get_next_run_time(cron_expression, timezone)

        schedule = Schedule(
            name=name,
            description=description,
            cron_expression=cron_expression,
            timezone=timezone,
            manifest_source_path=manifest_source_path,
            lookback_days=lookback_days,
            cluster_id=cluster_id,
            team_id=team_id,
            created_by_id=created_by_id,
            settings=settings or {},
            next_run_at=next_run,
            max_consecutive_failures=max_consecutive_failures,
        )

        db.session.add(schedule)
        db.session.commit()

        # Add to scheduler if running
        if self._is_running and schedule.status == ScheduleStatus.ACTIVE:
            self._add_job(schedule)

        logger.info(f"Created schedule {schedule.id} ({schedule.name})")
        return schedule

    def get_schedule(self, schedule_id: str) -> Schedule:
        """
        Get a schedule by ID.

        Args:
            schedule_id: The schedule ID.

        Returns:
            The Schedule object.

        Raises:
            ScheduleNotFoundError: If the schedule is not found.
        """
        schedule = db.session.get(Schedule, schedule_id)
        if not schedule:
            raise ScheduleNotFoundError(f"Schedule {schedule_id} not found")
        return schedule

    def list_schedules(
        self,
        team_id: Optional[str] = None,
        cluster_id: Optional[str] = None,
        status: Optional[ScheduleStatus] = None,
        page: int = 1,
        per_page: int = 50,
    ) -> tuple[list[Schedule], int]:
        """
        List schedules with optional filtering.

        Args:
            team_id: Optional team ID filter.
            cluster_id: Optional cluster ID filter.
            status: Optional status filter.
            page: Page number (1-indexed).
            per_page: Items per page.

        Returns:
            Tuple of (list of schedules, total count).
        """
        query = Schedule.query

        if team_id:
            query = query.filter_by(team_id=team_id)
        if cluster_id:
            query = query.filter_by(cluster_id=cluster_id)
        if status:
            query = query.filter_by(status=status)

        query = query.order_by(Schedule.created_at.desc())

        total = query.count()
        schedules = query.offset((page - 1) * per_page).limit(per_page).all()

        return schedules, total

    def update_schedule(
        self,
        schedule_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        cron_expression: Optional[str] = None,
        timezone: Optional[str] = None,
        manifest_source_path: Optional[str] = None,
        lookback_days: Optional[int] = None,
        cluster_id: Optional[str] = None,
        settings: Optional[dict] = None,
        max_consecutive_failures: Optional[int] = None,
    ) -> Schedule:
        """
        Update a schedule.

        Args:
            schedule_id: The schedule ID.
            name: Optional new name.
            description: Optional new description.
            cron_expression: Optional new cron expression.
            timezone: Optional new timezone.
            manifest_source_path: Optional new manifest path.
            lookback_days: Optional new lookback days.
            cluster_id: Optional new cluster ID.
            settings: Optional new settings.
            max_consecutive_failures: Optional new max failures.

        Returns:
            The updated Schedule object.

        Raises:
            ScheduleNotFoundError: If the schedule is not found.
            CronValidationError: If the cron expression is invalid.
        """
        schedule = self.get_schedule(schedule_id)

        if name is not None:
            schedule.name = name
        if description is not None:
            schedule.description = description
        if cron_expression is not None:
            self.validate_cron_expression(cron_expression)
            schedule.cron_expression = cron_expression
        if timezone is not None:
            schedule.timezone = timezone
        if manifest_source_path is not None:
            schedule.manifest_source_path = manifest_source_path
        if lookback_days is not None:
            schedule.lookback_days = lookback_days
        if cluster_id is not None:
            schedule.cluster_id = cluster_id
        if settings is not None:
            schedule.settings = settings
        if max_consecutive_failures is not None:
            schedule.max_consecutive_failures = max_consecutive_failures

        # Recalculate next run time if cron or timezone changed
        if cron_expression is not None or timezone is not None:
            schedule.next_run_at = self.get_next_run_time(
                schedule.cron_expression,
                schedule.timezone
            )
            # Update APScheduler job
            if self._is_running and schedule.status == ScheduleStatus.ACTIVE:
                self._add_job(schedule)

        db.session.commit()
        logger.info(f"Updated schedule {schedule.id}")
        return schedule

    def delete_schedule(self, schedule_id: str) -> None:
        """
        Delete a schedule.

        Args:
            schedule_id: The schedule ID.

        Raises:
            ScheduleNotFoundError: If the schedule is not found.
        """
        schedule = self.get_schedule(schedule_id)

        # Remove from APScheduler
        self._remove_job(schedule_id)

        db.session.delete(schedule)
        db.session.commit()
        logger.info(f"Deleted schedule {schedule_id}")

    def enable_schedule(self, schedule_id: str) -> Schedule:
        """
        Enable a schedule (set status to ACTIVE).

        Args:
            schedule_id: The schedule ID.

        Returns:
            The updated Schedule object.
        """
        schedule = self.get_schedule(schedule_id)
        schedule.status = ScheduleStatus.ACTIVE
        schedule.next_run_at = self.get_next_run_time(
            schedule.cron_expression,
            schedule.timezone
        )
        db.session.commit()

        # Add to APScheduler
        if self._is_running:
            self._add_job(schedule)

        logger.info(f"Enabled schedule {schedule.id}")
        return schedule

    def disable_schedule(self, schedule_id: str) -> Schedule:
        """
        Disable a schedule (set status to DISABLED).

        Args:
            schedule_id: The schedule ID.

        Returns:
            The updated Schedule object.
        """
        schedule = self.get_schedule(schedule_id)
        schedule.status = ScheduleStatus.DISABLED
        schedule.next_run_at = None
        db.session.commit()

        # Remove from APScheduler
        self._remove_job(schedule_id)

        logger.info(f"Disabled schedule {schedule.id}")
        return schedule

    def pause_schedule(self, schedule_id: str) -> Schedule:
        """
        Pause a schedule (set status to PAUSED).

        Args:
            schedule_id: The schedule ID.

        Returns:
            The updated Schedule object.
        """
        schedule = self.get_schedule(schedule_id)
        schedule.status = ScheduleStatus.PAUSED
        db.session.commit()

        # Remove from APScheduler
        self._remove_job(schedule_id)

        logger.info(f"Paused schedule {schedule.id}")
        return schedule

    def resume_schedule(self, schedule_id: str) -> Schedule:
        """
        Resume a paused schedule (set status to ACTIVE and reset failure count).

        Args:
            schedule_id: The schedule ID.

        Returns:
            The updated Schedule object.
        """
        schedule = self.get_schedule(schedule_id)
        schedule.status = ScheduleStatus.ACTIVE
        schedule.consecutive_failures = 0
        schedule.next_run_at = self.get_next_run_time(
            schedule.cron_expression,
            schedule.timezone
        )
        db.session.commit()

        # Add to APScheduler
        if self._is_running:
            self._add_job(schedule)

        logger.info(f"Resumed schedule {schedule.id}")
        return schedule

    def trigger_schedule(
        self,
        schedule_id: str,
        triggered_by_id: Optional[str] = None,
    ) -> ScheduleRun:
        """
        Manually trigger a schedule run.

        Args:
            schedule_id: The schedule ID.
            triggered_by_id: Optional user ID who triggered the run.

        Returns:
            The created ScheduleRun object.
        """
        schedule = self.get_schedule(schedule_id)

        # Create schedule run record
        schedule_run = ScheduleRun(
            schedule_id=schedule.id,
            status=ScheduleRunStatus.PENDING,
            trigger_type=ScheduleTriggerType.MANUAL,
            triggered_by_id=triggered_by_id,
            scheduled_time=datetime.now(timezone.utc),
        )
        db.session.add(schedule_run)
        db.session.commit()

        # Execute in background (or synchronously for now)
        self._execute_schedule(schedule_id)

        # Refresh to get updated status
        db.session.refresh(schedule_run)
        return schedule_run

    # =========================================================================
    # Schedule Run Operations
    # =========================================================================

    def get_schedule_run(self, run_id: str) -> ScheduleRun:
        """
        Get a schedule run by ID.

        Args:
            run_id: The schedule run ID.

        Returns:
            The ScheduleRun object.

        Raises:
            ScheduleNotFoundError: If the run is not found.
        """
        run = db.session.get(ScheduleRun, run_id)
        if not run:
            raise ScheduleNotFoundError(f"Schedule run {run_id} not found")
        return run

    def list_schedule_runs(
        self,
        schedule_id: Optional[str] = None,
        status: Optional[ScheduleRunStatus] = None,
        page: int = 1,
        per_page: int = 50,
    ) -> tuple[list[ScheduleRun], int]:
        """
        List schedule runs with optional filtering.

        Args:
            schedule_id: Optional schedule ID filter.
            status: Optional status filter.
            page: Page number (1-indexed).
            per_page: Items per page.

        Returns:
            Tuple of (list of runs, total count).
        """
        query = ScheduleRun.query

        if schedule_id:
            query = query.filter_by(schedule_id=schedule_id)
        if status:
            query = query.filter_by(status=status)

        query = query.order_by(ScheduleRun.scheduled_time.desc())

        total = query.count()
        runs = query.offset((page - 1) * per_page).limit(per_page).all()

        return runs, total


# Global scheduler service instance
scheduler_service = SchedulerService()
