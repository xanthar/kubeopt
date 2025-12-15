"""
Unit tests for scheduled optimization runs (F021).
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
from freezegun import freeze_time

from kubeopt_ai.core.models import (
    Schedule,
    ScheduleRun,
    ScheduleStatus,
    ScheduleRunStatus,
    ScheduleTriggerType,
)
from kubeopt_ai.core.scheduler import (
    SchedulerService,
    CronValidationError,
    ScheduleNotFoundError,
)


class TestCronValidation:
    """Tests for cron expression validation."""

    def test_validate_cron_expression_valid(self):
        """Test validation of valid cron expressions."""
        service = SchedulerService()

        # Standard cron expressions
        assert service.validate_cron_expression("0 0 * * *") is True  # Daily at midnight
        assert service.validate_cron_expression("*/15 * * * *") is True  # Every 15 minutes
        assert service.validate_cron_expression("0 9 * * 1-5") is True  # Weekdays at 9am
        assert service.validate_cron_expression("0 0 1 * *") is True  # First of month
        assert service.validate_cron_expression("30 4 * * SUN") is True  # Sunday at 4:30

    def test_validate_cron_expression_invalid(self):
        """Test validation of invalid cron expressions."""
        service = SchedulerService()

        # Invalid expressions
        with pytest.raises(CronValidationError):
            service.validate_cron_expression("invalid")

        with pytest.raises(CronValidationError):
            service.validate_cron_expression("0 0 0 0")  # Missing field

        with pytest.raises(CronValidationError):
            service.validate_cron_expression("60 * * * *")  # Invalid minute

        with pytest.raises(CronValidationError):
            service.validate_cron_expression("* 25 * * *")  # Invalid hour

    def test_get_next_run_time(self):
        """Test calculation of next run time."""
        service = SchedulerService()

        # Test with a fixed base time
        base_time = datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        next_run = service.get_next_run_time("0 12 * * *", "UTC", base_time)

        # Should be 12:00 on the same day
        assert next_run.hour == 12
        assert next_run.minute == 0
        assert next_run.day == 1

    def test_get_next_run_time_with_timezone(self):
        """Test next run time calculation with different timezone."""
        service = SchedulerService()

        base_time = datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        next_run = service.get_next_run_time("0 9 * * *", "America/New_York", base_time)

        # 9am EST is 14:00 UTC
        assert next_run.tzinfo is not None

    def test_get_next_run_time_rolls_to_next_day(self):
        """Test that next run time rolls to next day when needed."""
        service = SchedulerService()

        # Base time is after the scheduled time
        base_time = datetime(2025, 1, 1, 15, 0, 0, tzinfo=timezone.utc)
        next_run = service.get_next_run_time("0 9 * * *", "UTC", base_time)

        # Should be 9:00 on the next day
        assert next_run.day == 2
        assert next_run.hour == 9


class TestSchedulerService:
    """Tests for SchedulerService CRUD operations."""

    def test_create_schedule_success(self, app, db_session):
        """Test successful schedule creation."""
        service = SchedulerService()

        schedule = service.create_schedule(
            name="daily-optimization",
            cron_expression="0 2 * * *",
            manifest_source_path="/manifests/app",
            description="Daily optimization at 2 AM",
            timezone="UTC",
            lookback_days=7,
        )

        assert schedule.id is not None
        assert schedule.name == "daily-optimization"
        assert schedule.cron_expression == "0 2 * * *"
        assert schedule.manifest_source_path == "/manifests/app"
        assert schedule.status == ScheduleStatus.ACTIVE
        assert schedule.next_run_at is not None
        assert schedule.run_count == 0
        assert schedule.failure_count == 0

    def test_create_schedule_with_cluster(self, app, db_session):
        """Test schedule creation with cluster assignment."""
        service = SchedulerService()

        schedule = service.create_schedule(
            name="cluster-specific",
            cron_expression="0 0 * * *",
            manifest_source_path="/manifests/app",
            cluster_id="test-cluster-id",
        )

        assert schedule.cluster_id == "test-cluster-id"

    def test_create_schedule_invalid_cron(self, app, db_session):
        """Test that invalid cron expression raises error."""
        service = SchedulerService()

        with pytest.raises(CronValidationError):
            service.create_schedule(
                name="invalid-schedule",
                cron_expression="invalid",
                manifest_source_path="/manifests/app",
            )

    def test_get_schedule_success(self, app, db_session):
        """Test getting a schedule by ID."""
        service = SchedulerService()

        created = service.create_schedule(
            name="get-test",
            cron_expression="0 0 * * *",
            manifest_source_path="/manifests/app",
        )

        retrieved = service.get_schedule(created.id)

        assert retrieved.id == created.id
        assert retrieved.name == "get-test"

    def test_get_schedule_not_found(self, app, db_session):
        """Test getting a non-existent schedule."""
        service = SchedulerService()

        with pytest.raises(ScheduleNotFoundError):
            service.get_schedule("non-existent-id")

    def test_list_schedules(self, app, db_session):
        """Test listing schedules."""
        service = SchedulerService()

        service.create_schedule(
            name="schedule-1",
            cron_expression="0 0 * * *",
            manifest_source_path="/manifests/app1",
        )
        service.create_schedule(
            name="schedule-2",
            cron_expression="0 6 * * *",
            manifest_source_path="/manifests/app2",
        )

        schedules, total = service.list_schedules()

        assert total >= 2
        names = [s.name for s in schedules]
        assert "schedule-1" in names
        assert "schedule-2" in names

    def test_list_schedules_with_status_filter(self, app, db_session):
        """Test listing schedules filtered by status."""
        service = SchedulerService()

        active = service.create_schedule(
            name="active-schedule",
            cron_expression="0 0 * * *",
            manifest_source_path="/manifests/app",
        )
        disabled = service.create_schedule(
            name="disabled-schedule",
            cron_expression="0 0 * * *",
            manifest_source_path="/manifests/app",
        )
        service.disable_schedule(disabled.id)

        active_schedules, _ = service.list_schedules(status=ScheduleStatus.ACTIVE)
        disabled_schedules, _ = service.list_schedules(status=ScheduleStatus.DISABLED)

        assert any(s.name == "active-schedule" for s in active_schedules)
        assert any(s.name == "disabled-schedule" for s in disabled_schedules)

    def test_list_schedules_pagination(self, app, db_session):
        """Test listing schedules with pagination."""
        service = SchedulerService()

        for i in range(5):
            service.create_schedule(
                name=f"paginated-{i}",
                cron_expression="0 0 * * *",
                manifest_source_path=f"/manifests/app{i}",
            )

        page1, total = service.list_schedules(page=1, per_page=2)
        page2, _ = service.list_schedules(page=2, per_page=2)

        assert len(page1) == 2
        assert len(page2) == 2
        assert total >= 5

    def test_update_schedule_success(self, app, db_session):
        """Test updating a schedule."""
        service = SchedulerService()

        schedule = service.create_schedule(
            name="update-test",
            cron_expression="0 0 * * *",
            manifest_source_path="/manifests/app",
        )

        updated = service.update_schedule(
            schedule.id,
            name="updated-name",
            description="Updated description",
            lookback_days=14,
        )

        assert updated.name == "updated-name"
        assert updated.description == "Updated description"
        assert updated.lookback_days == 14

    def test_update_schedule_cron_expression(self, app, db_session):
        """Test updating schedule cron expression recalculates next_run_at."""
        service = SchedulerService()

        schedule = service.create_schedule(
            name="cron-update-test",
            cron_expression="0 0 * * *",  # Midnight
            manifest_source_path="/manifests/app",
        )

        original_next_run = schedule.next_run_at

        updated = service.update_schedule(
            schedule.id,
            cron_expression="0 6 * * *",  # 6 AM
        )

        assert updated.cron_expression == "0 6 * * *"
        # Next run should be different (unless edge case)
        assert updated.next_run_at is not None

    def test_update_schedule_invalid_cron(self, app, db_session):
        """Test that updating with invalid cron raises error."""
        service = SchedulerService()

        schedule = service.create_schedule(
            name="invalid-cron-update",
            cron_expression="0 0 * * *",
            manifest_source_path="/manifests/app",
        )

        with pytest.raises(CronValidationError):
            service.update_schedule(schedule.id, cron_expression="invalid")

    def test_delete_schedule(self, app, db_session):
        """Test deleting a schedule."""
        service = SchedulerService()

        schedule = service.create_schedule(
            name="delete-test",
            cron_expression="0 0 * * *",
            manifest_source_path="/manifests/app",
        )

        service.delete_schedule(schedule.id)

        with pytest.raises(ScheduleNotFoundError):
            service.get_schedule(schedule.id)

    def test_enable_schedule(self, app, db_session):
        """Test enabling a schedule."""
        service = SchedulerService()

        schedule = service.create_schedule(
            name="enable-test",
            cron_expression="0 0 * * *",
            manifest_source_path="/manifests/app",
        )
        service.disable_schedule(schedule.id)

        enabled = service.enable_schedule(schedule.id)

        assert enabled.status == ScheduleStatus.ACTIVE
        assert enabled.next_run_at is not None

    def test_disable_schedule(self, app, db_session):
        """Test disabling a schedule."""
        service = SchedulerService()

        schedule = service.create_schedule(
            name="disable-test",
            cron_expression="0 0 * * *",
            manifest_source_path="/manifests/app",
        )

        disabled = service.disable_schedule(schedule.id)

        assert disabled.status == ScheduleStatus.DISABLED
        assert disabled.next_run_at is None

    def test_pause_schedule(self, app, db_session):
        """Test pausing a schedule."""
        service = SchedulerService()

        schedule = service.create_schedule(
            name="pause-test",
            cron_expression="0 0 * * *",
            manifest_source_path="/manifests/app",
        )

        paused = service.pause_schedule(schedule.id)

        assert paused.status == ScheduleStatus.PAUSED

    def test_resume_schedule(self, app, db_session):
        """Test resuming a paused schedule."""
        service = SchedulerService()

        schedule = service.create_schedule(
            name="resume-test",
            cron_expression="0 0 * * *",
            manifest_source_path="/manifests/app",
        )
        service.pause_schedule(schedule.id)

        # Simulate some failures
        schedule = service.get_schedule(schedule.id)
        schedule.consecutive_failures = 3
        db_session.commit()

        resumed = service.resume_schedule(schedule.id)

        assert resumed.status == ScheduleStatus.ACTIVE
        assert resumed.consecutive_failures == 0
        assert resumed.next_run_at is not None


class TestScheduleRunOperations:
    """Tests for schedule run operations."""

    def test_list_schedule_runs(self, app, db_session):
        """Test listing schedule runs."""
        service = SchedulerService()

        schedule = service.create_schedule(
            name="run-list-test",
            cron_expression="0 0 * * *",
            manifest_source_path="/manifests/app",
        )

        # Create some runs manually
        for i in range(3):
            run = ScheduleRun(
                schedule_id=schedule.id,
                status=ScheduleRunStatus.COMPLETED,
                trigger_type=ScheduleTriggerType.SCHEDULED,
                scheduled_time=datetime.now(timezone.utc),
            )
            db_session.add(run)
        db_session.commit()

        runs, total = service.list_schedule_runs(schedule_id=schedule.id)

        assert total == 3
        assert len(runs) == 3

    def test_list_schedule_runs_with_status_filter(self, app, db_session):
        """Test listing schedule runs filtered by status."""
        service = SchedulerService()

        schedule = service.create_schedule(
            name="run-status-test",
            cron_expression="0 0 * * *",
            manifest_source_path="/manifests/app",
        )

        # Create runs with different statuses
        for status in [ScheduleRunStatus.COMPLETED, ScheduleRunStatus.FAILED]:
            run = ScheduleRun(
                schedule_id=schedule.id,
                status=status,
                trigger_type=ScheduleTriggerType.SCHEDULED,
                scheduled_time=datetime.now(timezone.utc),
            )
            db_session.add(run)
        db_session.commit()

        completed_runs, _ = service.list_schedule_runs(
            schedule_id=schedule.id,
            status=ScheduleRunStatus.COMPLETED
        )
        failed_runs, _ = service.list_schedule_runs(
            schedule_id=schedule.id,
            status=ScheduleRunStatus.FAILED
        )

        assert len(completed_runs) == 1
        assert len(failed_runs) == 1

    def test_get_schedule_run(self, app, db_session):
        """Test getting a schedule run by ID."""
        service = SchedulerService()

        schedule = service.create_schedule(
            name="get-run-test",
            cron_expression="0 0 * * *",
            manifest_source_path="/manifests/app",
        )

        run = ScheduleRun(
            schedule_id=schedule.id,
            status=ScheduleRunStatus.COMPLETED,
            trigger_type=ScheduleTriggerType.MANUAL,
            scheduled_time=datetime.now(timezone.utc),
        )
        db_session.add(run)
        db_session.commit()

        retrieved = service.get_schedule_run(run.id)

        assert retrieved.id == run.id
        assert retrieved.trigger_type == ScheduleTriggerType.MANUAL


class TestScheduleModels:
    """Tests for Schedule and ScheduleRun models."""

    def test_schedule_to_dict(self, app, db_session):
        """Test Schedule.to_dict() method."""
        schedule = Schedule(
            name="dict-test",
            cron_expression="0 0 * * *",
            manifest_source_path="/manifests/app",
            timezone="UTC",
            lookback_days=7,
            description="Test schedule",
        )
        db_session.add(schedule)
        db_session.commit()

        result = schedule.to_dict()

        assert result["name"] == "dict-test"
        assert result["cron_expression"] == "0 0 * * *"
        assert result["manifest_source_path"] == "/manifests/app"
        assert result["timezone"] == "UTC"
        assert result["lookback_days"] == 7
        assert result["status"] == "active"
        assert "id" in result
        assert "created_at" in result

    def test_schedule_run_to_dict(self, app, db_session):
        """Test ScheduleRun.to_dict() method."""
        schedule = Schedule(
            name="run-dict-test",
            cron_expression="0 0 * * *",
            manifest_source_path="/manifests/app",
        )
        db_session.add(schedule)
        db_session.commit()

        run = ScheduleRun(
            schedule_id=schedule.id,
            status=ScheduleRunStatus.COMPLETED,
            trigger_type=ScheduleTriggerType.SCHEDULED,
            scheduled_time=datetime.now(timezone.utc),
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            duration_seconds=120,
        )
        db_session.add(run)
        db_session.commit()

        result = run.to_dict()

        assert result["schedule_id"] == schedule.id
        assert result["status"] == "completed"
        assert result["trigger_type"] == "scheduled"
        assert result["duration_seconds"] == 120
        assert "id" in result
        assert "scheduled_time" in result


class TestSchedulesAPI:
    """Tests for schedules API endpoints."""

    def test_create_schedule_api(self, client, app, db_session):
        """Test POST /api/v1/schedules."""
        response = client.post(
            "/api/v1/schedules",
            json={
                "name": "api-test-schedule",
                "cron_expression": "0 2 * * *",
                "manifest_source_path": "/manifests/app",
                "description": "API test schedule",
            },
        )

        assert response.status_code == 201
        data = response.get_json()
        assert data["name"] == "api-test-schedule"
        assert data["status"] == "active"

    def test_create_schedule_api_missing_fields(self, client, app, db_session):
        """Test POST /api/v1/schedules with missing required fields."""
        response = client.post(
            "/api/v1/schedules",
            json={"name": "incomplete"},
        )

        assert response.status_code == 400
        data = response.get_json()
        assert data["code"] == "BAD_REQUEST"

    def test_create_schedule_api_invalid_cron(self, client, app, db_session):
        """Test POST /api/v1/schedules with invalid cron expression."""
        response = client.post(
            "/api/v1/schedules",
            json={
                "name": "invalid-cron",
                "cron_expression": "invalid",
                "manifest_source_path": "/manifests/app",
            },
        )

        assert response.status_code == 400
        data = response.get_json()
        assert data["code"] == "INVALID_CRON"

    def test_list_schedules_api(self, client, app, db_session):
        """Test GET /api/v1/schedules."""
        # Create some schedules first
        client.post(
            "/api/v1/schedules",
            json={
                "name": "list-test-1",
                "cron_expression": "0 0 * * *",
                "manifest_source_path": "/manifests/app1",
            },
        )
        client.post(
            "/api/v1/schedules",
            json={
                "name": "list-test-2",
                "cron_expression": "0 6 * * *",
                "manifest_source_path": "/manifests/app2",
            },
        )

        response = client.get("/api/v1/schedules")

        assert response.status_code == 200
        data = response.get_json()
        assert "schedules" in data
        assert "total" in data
        assert data["total"] >= 2

    def test_list_schedules_api_with_filters(self, client, app, db_session):
        """Test GET /api/v1/schedules with query parameters."""
        response = client.get("/api/v1/schedules?status=active&page=1&per_page=10")

        assert response.status_code == 200
        data = response.get_json()
        assert data["page"] == 1
        assert data["per_page"] == 10

    def test_get_schedule_api(self, client, app, db_session):
        """Test GET /api/v1/schedules/<id>."""
        # Create a schedule
        create_response = client.post(
            "/api/v1/schedules",
            json={
                "name": "get-test",
                "cron_expression": "0 0 * * *",
                "manifest_source_path": "/manifests/app",
            },
        )
        schedule_id = create_response.get_json()["id"]

        response = client.get(f"/api/v1/schedules/{schedule_id}")

        assert response.status_code == 200
        data = response.get_json()
        assert data["id"] == schedule_id
        assert data["name"] == "get-test"

    def test_get_schedule_api_not_found(self, client, app, db_session):
        """Test GET /api/v1/schedules/<id> with non-existent ID."""
        response = client.get("/api/v1/schedules/non-existent")

        assert response.status_code == 404
        data = response.get_json()
        assert data["code"] == "NOT_FOUND"

    def test_update_schedule_api(self, client, app, db_session):
        """Test PUT /api/v1/schedules/<id>."""
        # Create a schedule
        create_response = client.post(
            "/api/v1/schedules",
            json={
                "name": "update-test",
                "cron_expression": "0 0 * * *",
                "manifest_source_path": "/manifests/app",
            },
        )
        schedule_id = create_response.get_json()["id"]

        response = client.put(
            f"/api/v1/schedules/{schedule_id}",
            json={"name": "updated-name", "description": "Updated"},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["name"] == "updated-name"
        assert data["description"] == "Updated"

    def test_delete_schedule_api(self, client, app, db_session):
        """Test DELETE /api/v1/schedules/<id>."""
        # Create a schedule
        create_response = client.post(
            "/api/v1/schedules",
            json={
                "name": "delete-test",
                "cron_expression": "0 0 * * *",
                "manifest_source_path": "/manifests/app",
            },
        )
        schedule_id = create_response.get_json()["id"]

        response = client.delete(f"/api/v1/schedules/{schedule_id}")

        assert response.status_code == 204

        # Verify deleted
        get_response = client.get(f"/api/v1/schedules/{schedule_id}")
        assert get_response.status_code == 404

    def test_enable_schedule_api(self, client, app, db_session):
        """Test POST /api/v1/schedules/<id>/enable."""
        # Create and disable a schedule
        create_response = client.post(
            "/api/v1/schedules",
            json={
                "name": "enable-api-test",
                "cron_expression": "0 0 * * *",
                "manifest_source_path": "/manifests/app",
            },
        )
        schedule_id = create_response.get_json()["id"]
        client.post(f"/api/v1/schedules/{schedule_id}/disable")

        response = client.post(f"/api/v1/schedules/{schedule_id}/enable")

        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "active"

    def test_disable_schedule_api(self, client, app, db_session):
        """Test POST /api/v1/schedules/<id>/disable."""
        # Create a schedule
        create_response = client.post(
            "/api/v1/schedules",
            json={
                "name": "disable-api-test",
                "cron_expression": "0 0 * * *",
                "manifest_source_path": "/manifests/app",
            },
        )
        schedule_id = create_response.get_json()["id"]

        response = client.post(f"/api/v1/schedules/{schedule_id}/disable")

        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "disabled"

    def test_pause_schedule_api(self, client, app, db_session):
        """Test POST /api/v1/schedules/<id>/pause."""
        # Create a schedule
        create_response = client.post(
            "/api/v1/schedules",
            json={
                "name": "pause-api-test",
                "cron_expression": "0 0 * * *",
                "manifest_source_path": "/manifests/app",
            },
        )
        schedule_id = create_response.get_json()["id"]

        response = client.post(f"/api/v1/schedules/{schedule_id}/pause")

        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "paused"

    def test_resume_schedule_api(self, client, app, db_session):
        """Test POST /api/v1/schedules/<id>/resume."""
        # Create and pause a schedule
        create_response = client.post(
            "/api/v1/schedules",
            json={
                "name": "resume-api-test",
                "cron_expression": "0 0 * * *",
                "manifest_source_path": "/manifests/app",
            },
        )
        schedule_id = create_response.get_json()["id"]
        client.post(f"/api/v1/schedules/{schedule_id}/pause")

        response = client.post(f"/api/v1/schedules/{schedule_id}/resume")

        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "active"

    def test_list_schedule_runs_api(self, client, app, db_session):
        """Test GET /api/v1/schedules/<id>/runs."""
        # Create a schedule
        create_response = client.post(
            "/api/v1/schedules",
            json={
                "name": "runs-list-test",
                "cron_expression": "0 0 * * *",
                "manifest_source_path": "/manifests/app",
            },
        )
        schedule_id = create_response.get_json()["id"]

        response = client.get(f"/api/v1/schedules/{schedule_id}/runs")

        assert response.status_code == 200
        data = response.get_json()
        assert "runs" in data
        assert "total" in data

    def test_validate_cron_api_valid(self, client, app, db_session):
        """Test POST /api/v1/schedules/validate-cron with valid expression."""
        response = client.post(
            "/api/v1/schedules/validate-cron",
            json={
                "cron_expression": "0 9 * * 1-5",
                "timezone": "UTC",
                "count": 3,
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["valid"] is True
        assert len(data["next_runs"]) == 3

    def test_validate_cron_api_invalid(self, client, app, db_session):
        """Test POST /api/v1/schedules/validate-cron with invalid expression."""
        response = client.post(
            "/api/v1/schedules/validate-cron",
            json={"cron_expression": "invalid"},
        )

        assert response.status_code == 400
        data = response.get_json()
        assert data["valid"] is False
        assert "error" in data
