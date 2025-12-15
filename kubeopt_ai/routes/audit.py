"""
Audit log endpoints for KubeOpt AI.

Provides API endpoints for querying and exporting audit logs
for security and compliance purposes.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from flask import Blueprint, jsonify, request, Response
from pydantic import BaseModel, Field, ValidationError

from kubeopt_ai.core.audit import get_audit_service
from kubeopt_ai.core.models import AuditAction

logger = logging.getLogger(__name__)

audit_bp = Blueprint("audit", __name__)


class AuditLogQueryRequest(BaseModel):
    """Request schema for querying audit logs."""

    action: Optional[str] = Field(None, description="Filter by action type")
    resource_type: Optional[str] = Field(None, description="Filter by resource type")
    resource_id: Optional[str] = Field(None, description="Filter by resource ID")
    user_id: Optional[str] = Field(None, description="Filter by user ID")
    start_time: Optional[str] = Field(None, description="Filter logs after this ISO timestamp")
    end_time: Optional[str] = Field(None, description="Filter logs before this ISO timestamp")
    limit: int = Field(100, ge=1, le=1000, description="Maximum results to return")
    offset: int = Field(0, ge=0, description="Number of results to skip")


class AuditLogExportRequest(BaseModel):
    """Request schema for exporting audit logs."""

    action: Optional[str] = Field(None, description="Filter by action type")
    resource_type: Optional[str] = Field(None, description="Filter by resource type")
    start_time: Optional[str] = Field(None, description="Filter logs after this ISO timestamp")
    end_time: Optional[str] = Field(None, description="Filter logs before this ISO timestamp")
    format: str = Field("json", pattern="^(json|csv)$", description="Export format")


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse ISO format datetime string."""
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_action(value: Optional[str]) -> Optional[AuditAction]:
    """Parse action string to AuditAction enum."""
    if value is None:
        return None
    try:
        return AuditAction(value.lower())
    except ValueError:
        return None


@audit_bp.route("/api/v1/audit/logs", methods=["GET"])
def list_audit_logs():
    """
    List audit logs with optional filtering.

    Query Parameters:
        action: Filter by action type (create, update, delete, etc.)
        resource_type: Filter by resource type
        resource_id: Filter by resource ID
        user_id: Filter by user ID
        start_time: Filter logs after this ISO timestamp
        end_time: Filter logs before this ISO timestamp
        limit: Maximum results (default 100, max 1000)
        offset: Pagination offset

    Returns:
        JSON response with audit logs and pagination info.
    """
    try:
        params = AuditLogQueryRequest(
            action=request.args.get("action"),
            resource_type=request.args.get("resource_type"),
            resource_id=request.args.get("resource_id"),
            user_id=request.args.get("user_id"),
            start_time=request.args.get("start_time"),
            end_time=request.args.get("end_time"),
            limit=int(request.args.get("limit", 100)),
            offset=int(request.args.get("offset", 0)),
        )
    except (ValidationError, ValueError) as e:
        return jsonify({
            "code": "VALIDATION_ERROR",
            "message": "Invalid query parameters",
            "details": str(e),
        }), 400

    audit_service = get_audit_service()

    logs, total = audit_service.query(
        action=_parse_action(params.action),
        resource_type=params.resource_type,
        resource_id=params.resource_id,
        user_id=params.user_id,
        start_time=_parse_datetime(params.start_time),
        end_time=_parse_datetime(params.end_time),
        limit=params.limit,
        offset=params.offset,
    )

    return jsonify({
        "logs": [log.to_dict() for log in logs],
        "pagination": {
            "total": total,
            "limit": params.limit,
            "offset": params.offset,
            "has_more": (params.offset + len(logs)) < total,
        },
    }), 200


@audit_bp.route("/api/v1/audit/logs/<log_id>", methods=["GET"])
def get_audit_log(log_id: str):
    """
    Get a specific audit log by ID.

    Args:
        log_id: The audit log ID.

    Returns:
        JSON response with the audit log details.
    """
    audit_service = get_audit_service()
    log = audit_service.get_by_id(log_id)

    if log is None:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Audit log with ID '{log_id}' not found",
        }), 404

    return jsonify(log.to_dict()), 200


@audit_bp.route("/api/v1/audit/logs/export", methods=["GET"])
def export_audit_logs():
    """
    Export audit logs in CSV or JSON format.

    Query Parameters:
        action: Filter by action type
        resource_type: Filter by resource type
        start_time: Filter logs after this ISO timestamp
        end_time: Filter logs before this ISO timestamp
        format: Export format (json or csv, default json)

    Returns:
        Exported audit logs in requested format.
    """
    try:
        params = AuditLogExportRequest(
            action=request.args.get("action"),
            resource_type=request.args.get("resource_type"),
            start_time=request.args.get("start_time"),
            end_time=request.args.get("end_time"),
            format=request.args.get("format", "json"),
        )
    except ValidationError as e:
        return jsonify({
            "code": "VALIDATION_ERROR",
            "message": "Invalid query parameters",
            "details": e.errors(),
        }), 400

    audit_service = get_audit_service()

    action = _parse_action(params.action)
    start_time = _parse_datetime(params.start_time)
    end_time = _parse_datetime(params.end_time)

    if params.format == "csv":
        csv_data = audit_service.export_csv(
            action=action,
            resource_type=params.resource_type,
            start_time=start_time,
            end_time=end_time,
        )

        return Response(
            csv_data,
            mimetype="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=audit_logs.csv"
            },
        )
    else:
        json_data = audit_service.export_json(
            action=action,
            resource_type=params.resource_type,
            start_time=start_time,
            end_time=end_time,
        )

        return jsonify({
            "logs": json_data,
            "count": len(json_data),
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }), 200


@audit_bp.route("/api/v1/audit/actions", methods=["GET"])
def list_audit_actions():
    """
    List all available audit action types.

    Returns:
        JSON response with available action types.
    """
    return jsonify({
        "actions": [action.value for action in AuditAction],
    }), 200


@audit_bp.route("/api/v1/audit/stats", methods=["GET"])
def get_audit_stats():
    """
    Get audit log statistics.

    Query Parameters:
        start_time: Start of time range for statistics
        end_time: End of time range for statistics

    Returns:
        JSON response with audit statistics.
    """
    start_time = _parse_datetime(request.args.get("start_time"))
    end_time = _parse_datetime(request.args.get("end_time"))

    audit_service = get_audit_service()

    # Get total count
    _, total = audit_service.query(
        start_time=start_time,
        end_time=end_time,
        limit=1,
    )

    # Get counts by action
    action_counts = {}
    for action in AuditAction:
        _, count = audit_service.query(
            action=action,
            start_time=start_time,
            end_time=end_time,
            limit=1,
        )
        if count > 0:
            action_counts[action.value] = count

    # Get counts by resource type
    resource_counts = {}
    # Query all unique resource types
    from kubeopt_ai.core.models import AuditLog
    from sqlalchemy import func
    from kubeopt_ai.extensions import db

    resource_query = (
        db.session.query(AuditLog.resource_type, func.count(AuditLog.id))
        .group_by(AuditLog.resource_type)
    )
    if start_time:
        resource_query = resource_query.filter(AuditLog.timestamp >= start_time)
    if end_time:
        resource_query = resource_query.filter(AuditLog.timestamp <= end_time)

    for resource_type, count in resource_query.all():
        resource_counts[resource_type] = count

    return jsonify({
        "total_logs": total,
        "by_action": action_counts,
        "by_resource_type": resource_counts,
        "time_range": {
            "start": start_time.isoformat() if start_time else None,
            "end": end_time.isoformat() if end_time else None,
        },
    }), 200
