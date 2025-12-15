"""
Schedule management API routes for KubeOpt AI.

Provides REST endpoints for managing scheduled optimization runs.
"""

import logging
from flask import Blueprint, request, jsonify

from kubeopt_ai.core.scheduler import (
    scheduler_service,
    CronValidationError,
    ScheduleNotFoundError,
)
from kubeopt_ai.core.models import ScheduleStatus, ScheduleRunStatus

logger = logging.getLogger(__name__)

schedules_bp = Blueprint("schedules", __name__, url_prefix="/api/v1/schedules")


@schedules_bp.route("", methods=["POST"])
def create_schedule():
    """
    Create a new scheduled optimization run.

    Request Body:
        name (str): Schedule name (required)
        cron_expression (str): Cron expression (required)
        manifest_source_path (str): Path to K8s manifests (required)
        description (str): Schedule description
        timezone (str): Timezone for cron expression (default: UTC)
        lookback_days (int): Days to look back for metrics (default: 7)
        cluster_id (str): Target cluster ID
        team_id (str): Owning team ID
        settings (dict): Additional settings
        max_consecutive_failures (int): Max failures before auto-pause (default: 3)

    Returns:
        201: Created schedule object
        400: Invalid request or cron expression
        500: Server error
    """
    data = request.get_json()

    if not data:
        return jsonify({
            "code": "BAD_REQUEST",
            "message": "Request body is required",
        }), 400

    # Validate required fields
    name = data.get("name")
    cron_expression = data.get("cron_expression")
    manifest_source_path = data.get("manifest_source_path")

    if not name:
        return jsonify({
            "code": "BAD_REQUEST",
            "message": "Schedule name is required",
        }), 400

    if not cron_expression:
        return jsonify({
            "code": "BAD_REQUEST",
            "message": "Cron expression is required",
        }), 400

    if not manifest_source_path:
        return jsonify({
            "code": "BAD_REQUEST",
            "message": "Manifest source path is required",
        }), 400

    try:
        schedule = scheduler_service.create_schedule(
            name=name,
            cron_expression=cron_expression,
            manifest_source_path=manifest_source_path,
            description=data.get("description"),
            timezone=data.get("timezone", "UTC"),
            lookback_days=data.get("lookback_days", 7),
            cluster_id=data.get("cluster_id"),
            team_id=data.get("team_id"),
            created_by_id=data.get("created_by_id"),
            settings=data.get("settings"),
            max_consecutive_failures=data.get("max_consecutive_failures", 3),
        )

        return jsonify(schedule.to_dict()), 201

    except CronValidationError as e:
        logger.warning(f"Invalid cron expression: {e}")
        return jsonify({
            "code": "INVALID_CRON",
            "message": str(e),
        }), 400

    except Exception as e:
        logger.error(f"Failed to create schedule: {e}")
        return jsonify({
            "code": "CREATE_FAILED",
            "message": str(e),
        }), 500


@schedules_bp.route("", methods=["GET"])
def list_schedules():
    """
    List scheduled optimization runs.

    Query Parameters:
        team_id (str): Filter by team
        cluster_id (str): Filter by cluster
        status (str): Filter by status (active, paused, disabled)
        page (int): Page number (default: 1)
        per_page (int): Items per page (default: 50, max: 100)

    Returns:
        200: Paginated list of schedules
    """
    team_id = request.args.get("team_id")
    cluster_id = request.args.get("cluster_id")
    status_str = request.args.get("status")
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 50, type=int), 100)

    # Parse status if provided
    status = None
    if status_str:
        try:
            status = ScheduleStatus(status_str)
        except ValueError:
            return jsonify({
                "code": "INVALID_STATUS",
                "message": f"Invalid status: {status_str}. Valid values: active, paused, disabled",
            }), 400

    schedules, total = scheduler_service.list_schedules(
        team_id=team_id,
        cluster_id=cluster_id,
        status=status,
        page=page,
        per_page=per_page,
    )

    return jsonify({
        "schedules": [s.to_dict() for s in schedules],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    })


@schedules_bp.route("/<schedule_id>", methods=["GET"])
def get_schedule(schedule_id: str):
    """
    Get a schedule by ID.

    Path Parameters:
        schedule_id: Schedule UUID

    Returns:
        200: Schedule object
        404: Schedule not found
    """
    try:
        schedule = scheduler_service.get_schedule(schedule_id)
        return jsonify(schedule.to_dict())

    except ScheduleNotFoundError:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Schedule not found: {schedule_id}",
        }), 404


@schedules_bp.route("/<schedule_id>", methods=["PUT"])
def update_schedule(schedule_id: str):
    """
    Update a schedule's configuration.

    Path Parameters:
        schedule_id: Schedule UUID

    Request Body:
        Any schedule fields to update

    Returns:
        200: Updated schedule object
        404: Schedule not found
        400: Update failed or invalid cron expression
    """
    data = request.get_json()

    if not data:
        return jsonify({
            "code": "BAD_REQUEST",
            "message": "Request body is required",
        }), 400

    try:
        schedule = scheduler_service.update_schedule(
            schedule_id,
            name=data.get("name"),
            description=data.get("description"),
            cron_expression=data.get("cron_expression"),
            timezone=data.get("timezone"),
            manifest_source_path=data.get("manifest_source_path"),
            lookback_days=data.get("lookback_days"),
            cluster_id=data.get("cluster_id"),
            settings=data.get("settings"),
            max_consecutive_failures=data.get("max_consecutive_failures"),
        )
        return jsonify(schedule.to_dict())

    except ScheduleNotFoundError:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Schedule not found: {schedule_id}",
        }), 404

    except CronValidationError as e:
        return jsonify({
            "code": "INVALID_CRON",
            "message": str(e),
        }), 400

    except Exception as e:
        logger.error(f"Failed to update schedule: {e}")
        return jsonify({
            "code": "UPDATE_FAILED",
            "message": str(e),
        }), 400


@schedules_bp.route("/<schedule_id>", methods=["DELETE"])
def delete_schedule(schedule_id: str):
    """
    Delete a schedule.

    Path Parameters:
        schedule_id: Schedule UUID

    Returns:
        204: Successfully deleted
        404: Schedule not found
    """
    try:
        scheduler_service.delete_schedule(schedule_id)
        return "", 204

    except ScheduleNotFoundError:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Schedule not found: {schedule_id}",
        }), 404


@schedules_bp.route("/<schedule_id>/enable", methods=["POST"])
def enable_schedule(schedule_id: str):
    """
    Enable a schedule (set status to ACTIVE).

    Path Parameters:
        schedule_id: Schedule UUID

    Returns:
        200: Updated schedule object
        404: Schedule not found
    """
    try:
        schedule = scheduler_service.enable_schedule(schedule_id)
        return jsonify(schedule.to_dict())

    except ScheduleNotFoundError:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Schedule not found: {schedule_id}",
        }), 404


@schedules_bp.route("/<schedule_id>/disable", methods=["POST"])
def disable_schedule(schedule_id: str):
    """
    Disable a schedule (set status to DISABLED).

    Path Parameters:
        schedule_id: Schedule UUID

    Returns:
        200: Updated schedule object
        404: Schedule not found
    """
    try:
        schedule = scheduler_service.disable_schedule(schedule_id)
        return jsonify(schedule.to_dict())

    except ScheduleNotFoundError:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Schedule not found: {schedule_id}",
        }), 404


@schedules_bp.route("/<schedule_id>/pause", methods=["POST"])
def pause_schedule(schedule_id: str):
    """
    Pause a schedule (set status to PAUSED).

    Path Parameters:
        schedule_id: Schedule UUID

    Returns:
        200: Updated schedule object
        404: Schedule not found
    """
    try:
        schedule = scheduler_service.pause_schedule(schedule_id)
        return jsonify(schedule.to_dict())

    except ScheduleNotFoundError:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Schedule not found: {schedule_id}",
        }), 404


@schedules_bp.route("/<schedule_id>/resume", methods=["POST"])
def resume_schedule(schedule_id: str):
    """
    Resume a paused schedule (reset failures and set ACTIVE).

    Path Parameters:
        schedule_id: Schedule UUID

    Returns:
        200: Updated schedule object
        404: Schedule not found
    """
    try:
        schedule = scheduler_service.resume_schedule(schedule_id)
        return jsonify(schedule.to_dict())

    except ScheduleNotFoundError:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Schedule not found: {schedule_id}",
        }), 404


@schedules_bp.route("/<schedule_id>/trigger", methods=["POST"])
def trigger_schedule(schedule_id: str):
    """
    Manually trigger a schedule run.

    Path Parameters:
        schedule_id: Schedule UUID

    Request Body (optional):
        triggered_by_id (str): User ID triggering the run

    Returns:
        200: Schedule run object
        404: Schedule not found
    """
    data = request.get_json() or {}

    try:
        run = scheduler_service.trigger_schedule(
            schedule_id,
            triggered_by_id=data.get("triggered_by_id"),
        )
        return jsonify(run.to_dict())

    except ScheduleNotFoundError:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Schedule not found: {schedule_id}",
        }), 404


@schedules_bp.route("/<schedule_id>/runs", methods=["GET"])
def list_schedule_runs(schedule_id: str):
    """
    List runs for a specific schedule.

    Path Parameters:
        schedule_id: Schedule UUID

    Query Parameters:
        status (str): Filter by status
        page (int): Page number (default: 1)
        per_page (int): Items per page (default: 50, max: 100)

    Returns:
        200: Paginated list of schedule runs
        404: Schedule not found
    """
    # Verify schedule exists
    try:
        scheduler_service.get_schedule(schedule_id)
    except ScheduleNotFoundError:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Schedule not found: {schedule_id}",
        }), 404

    status_str = request.args.get("status")
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 50, type=int), 100)

    # Parse status if provided
    status = None
    if status_str:
        try:
            status = ScheduleRunStatus(status_str)
        except ValueError:
            return jsonify({
                "code": "INVALID_STATUS",
                "message": f"Invalid status: {status_str}",
            }), 400

    runs, total = scheduler_service.list_schedule_runs(
        schedule_id=schedule_id,
        status=status,
        page=page,
        per_page=per_page,
    )

    return jsonify({
        "runs": [r.to_dict() for r in runs],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    })


@schedules_bp.route("/runs/<run_id>", methods=["GET"])
def get_schedule_run(run_id: str):
    """
    Get a schedule run by ID.

    Path Parameters:
        run_id: Schedule run UUID

    Returns:
        200: Schedule run object
        404: Run not found
    """
    try:
        run = scheduler_service.get_schedule_run(run_id)
        return jsonify(run.to_dict())

    except ScheduleNotFoundError:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Schedule run not found: {run_id}",
        }), 404


@schedules_bp.route("/validate-cron", methods=["POST"])
def validate_cron():
    """
    Validate a cron expression and get next run times.

    Request Body:
        cron_expression (str): Cron expression to validate (required)
        timezone (str): Timezone for the expression (default: UTC)
        count (int): Number of next run times to return (default: 5, max: 10)

    Returns:
        200: Validation result with next run times
        400: Invalid cron expression
    """
    data = request.get_json()

    if not data:
        return jsonify({
            "code": "BAD_REQUEST",
            "message": "Request body is required",
        }), 400

    cron_expression = data.get("cron_expression")
    if not cron_expression:
        return jsonify({
            "code": "BAD_REQUEST",
            "message": "Cron expression is required",
        }), 400

    tz = data.get("timezone", "UTC")
    count = min(data.get("count", 5), 10)

    try:
        scheduler_service.validate_cron_expression(cron_expression)

        # Calculate next run times
        next_runs = []
        base_time = None
        for _ in range(count):
            next_time = scheduler_service.get_next_run_time(
                cron_expression, tz, base_time
            )
            next_runs.append(next_time.isoformat())
            base_time = next_time

        return jsonify({
            "valid": True,
            "cron_expression": cron_expression,
            "timezone": tz,
            "next_runs": next_runs,
        })

    except CronValidationError as e:
        return jsonify({
            "valid": False,
            "cron_expression": cron_expression,
            "error": str(e),
        }), 400
