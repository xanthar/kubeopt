"""
Audit logging service for KubeOpt AI.

Provides comprehensive audit trail functionality for tracking user actions,
system events, and API requests for security and compliance purposes.
"""

import csv
import io
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from functools import wraps
from typing import Any, Callable, Optional

from flask import current_app, g, request, Response

from kubeopt_ai.core.models import AuditLog, AuditAction
from kubeopt_ai.extensions import db

logger = logging.getLogger(__name__)


@dataclass
class AuditContext:
    """Context information for audit logging."""

    user_id: Optional[str] = None
    user_email: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    request_method: Optional[str] = None
    request_path: Optional[str] = None


class AuditService:
    """
    Service for managing audit logs.

    Provides methods for creating, querying, and exporting audit logs.
    """

    def __init__(self, enabled: bool = True, retention_days: int = 90):
        """
        Initialize the audit service.

        Args:
            enabled: Whether audit logging is enabled.
            retention_days: Number of days to retain audit logs.
        """
        self.enabled = enabled
        self.retention_days = retention_days

    def log(
        self,
        action: AuditAction,
        resource_type: str,
        resource_id: Optional[str] = None,
        details: Optional[dict] = None,
        context: Optional[AuditContext] = None,
        response_status: Optional[int] = None,
        duration_ms: Optional[int] = None,
    ) -> Optional[AuditLog]:
        """
        Create an audit log entry.

        Args:
            action: The action being performed.
            resource_type: Type of resource being acted upon.
            resource_id: ID of the specific resource (if applicable).
            details: Additional details about the action.
            context: Request context information.
            response_status: HTTP response status code.
            duration_ms: Request duration in milliseconds.

        Returns:
            The created AuditLog entry, or None if logging is disabled.
        """
        if not self.enabled:
            return None

        # Use provided context or extract from Flask request
        if context is None:
            context = self._extract_context()

        try:
            audit_log = AuditLog(
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                details=details or {},
                user_id=context.user_id,
                user_email=context.user_email,
                ip_address=context.ip_address,
                user_agent=context.user_agent,
                request_method=context.request_method,
                request_path=context.request_path,
                response_status=response_status,
                duration_ms=duration_ms,
            )

            db.session.add(audit_log)
            db.session.commit()

            logger.debug(
                f"Audit log created: action={action.value}, "
                f"resource_type={resource_type}, resource_id={resource_id}"
            )

            return audit_log

        except Exception as e:
            logger.error(f"Failed to create audit log: {e}")
            db.session.rollback()
            return None

    def query(
        self,
        action: Optional[AuditAction] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        user_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[AuditLog], int]:
        """
        Query audit logs with filtering.

        Args:
            action: Filter by action type.
            resource_type: Filter by resource type.
            resource_id: Filter by resource ID.
            user_id: Filter by user ID.
            start_time: Filter logs after this time.
            end_time: Filter logs before this time.
            limit: Maximum number of results.
            offset: Number of results to skip.

        Returns:
            Tuple of (list of matching AuditLog entries, total count).
        """
        query = AuditLog.query

        if action is not None:
            query = query.filter(AuditLog.action == action)
        if resource_type is not None:
            query = query.filter(AuditLog.resource_type == resource_type)
        if resource_id is not None:
            query = query.filter(AuditLog.resource_id == resource_id)
        if user_id is not None:
            query = query.filter(AuditLog.user_id == user_id)
        if start_time is not None:
            query = query.filter(AuditLog.timestamp >= start_time)
        if end_time is not None:
            query = query.filter(AuditLog.timestamp <= end_time)

        # Get total count before pagination
        total = query.count()

        # Apply ordering and pagination
        results = (
            query.order_by(AuditLog.timestamp.desc())
            .offset(offset)
            .limit(min(limit, 1000))  # Cap at 1000
            .all()
        )

        return results, total

    def get_by_id(self, log_id: str) -> Optional[AuditLog]:
        """
        Get a specific audit log by ID.

        Args:
            log_id: The audit log ID.

        Returns:
            The AuditLog entry or None if not found.
        """
        return db.session.get(AuditLog, log_id)

    def export_csv(
        self,
        action: Optional[AuditAction] = None,
        resource_type: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> str:
        """
        Export audit logs to CSV format.

        Args:
            action: Filter by action type.
            resource_type: Filter by resource type.
            start_time: Filter logs after this time.
            end_time: Filter logs before this time.

        Returns:
            CSV string of audit logs.
        """
        logs, _ = self.query(
            action=action,
            resource_type=resource_type,
            start_time=start_time,
            end_time=end_time,
            limit=10000,  # Higher limit for exports
        )

        output = io.StringIO()
        writer = csv.writer(output)

        # Write header
        writer.writerow([
            "id",
            "timestamp",
            "user_id",
            "user_email",
            "action",
            "resource_type",
            "resource_id",
            "details",
            "ip_address",
            "request_method",
            "request_path",
            "response_status",
            "duration_ms",
        ])

        # Write data rows
        for log in logs:
            writer.writerow([
                log.id,
                log.timestamp.isoformat() if log.timestamp else "",
                log.user_id or "",
                log.user_email or "",
                log.action.value if log.action else "",
                log.resource_type,
                log.resource_id or "",
                json.dumps(log.details) if log.details else "",
                log.ip_address or "",
                log.request_method or "",
                log.request_path or "",
                log.response_status or "",
                log.duration_ms or "",
            ])

        return output.getvalue()

    def export_json(
        self,
        action: Optional[AuditAction] = None,
        resource_type: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> list[dict]:
        """
        Export audit logs to JSON format.

        Args:
            action: Filter by action type.
            resource_type: Filter by resource type.
            start_time: Filter logs after this time.
            end_time: Filter logs before this time.

        Returns:
            List of audit log dictionaries.
        """
        logs, _ = self.query(
            action=action,
            resource_type=resource_type,
            start_time=start_time,
            end_time=end_time,
            limit=10000,
        )

        return [log.to_dict() for log in logs]

    def cleanup_old_logs(self) -> int:
        """
        Delete audit logs older than retention period.

        Returns:
            Number of deleted logs.
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=self.retention_days)

        deleted = (
            AuditLog.query
            .filter(AuditLog.timestamp < cutoff_date)
            .delete(synchronize_session=False)
        )

        db.session.commit()

        logger.info(f"Cleaned up {deleted} audit logs older than {self.retention_days} days")

        return deleted

    def _extract_context(self) -> AuditContext:
        """
        Extract audit context from Flask request.

        Returns:
            AuditContext with request information.
        """
        try:
            # Get user info from Flask g object if set by auth middleware
            user_id = getattr(g, "user_id", None)
            user_email = getattr(g, "user_email", None)

            # Get IP address (handle proxies)
            ip_address = request.headers.get(
                "X-Forwarded-For",
                request.remote_addr
            )
            if ip_address and "," in ip_address:
                ip_address = ip_address.split(",")[0].strip()

            return AuditContext(
                user_id=user_id,
                user_email=user_email,
                ip_address=ip_address,
                user_agent=request.headers.get("User-Agent"),
                request_method=request.method,
                request_path=request.path,
            )
        except RuntimeError:
            # Not in request context
            return AuditContext()


def audit_action(
    action: AuditAction,
    resource_type: str,
    get_resource_id: Optional[Callable[..., str]] = None,
    get_details: Optional[Callable[..., dict]] = None,
) -> Callable:
    """
    Decorator for automatically logging route actions.

    Args:
        action: The action type to log.
        resource_type: The type of resource being acted upon.
        get_resource_id: Function to extract resource ID from response or args.
        get_details: Function to extract additional details.

    Returns:
        Decorated function with audit logging.

    Example:
        @audit_action(AuditAction.CREATE, "optimization_run")
        def create_optimization_run():
            ...
    """
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start_time = time.time()

            # Execute the wrapped function
            result = f(*args, **kwargs)

            # Calculate duration
            duration_ms = int((time.time() - start_time) * 1000)

            # Extract response status
            response_status = None
            if isinstance(result, tuple) and len(result) >= 2:
                response_status = result[1]
            elif isinstance(result, Response):
                response_status = result.status_code

            # Extract resource ID if function provided
            resource_id = None
            if get_resource_id is not None:
                try:
                    resource_id = get_resource_id(result, *args, **kwargs)
                except Exception:
                    pass

            # Extract details if function provided
            details = None
            if get_details is not None:
                try:
                    details = get_details(result, *args, **kwargs)
                except Exception:
                    pass

            # Log the action
            try:
                audit_service = get_audit_service()
                audit_service.log(
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    details=details,
                    response_status=response_status,
                    duration_ms=duration_ms,
                )
            except Exception as e:
                logger.warning(f"Failed to log audit action: {e}")

            return result

        return wrapper

    return decorator


# Module-level singleton
_audit_service: Optional[AuditService] = None


def get_audit_service() -> AuditService:
    """
    Get or create the audit service singleton.

    Returns:
        The AuditService instance.
    """
    global _audit_service

    if _audit_service is None:
        enabled = current_app.config.get("AUDIT_LOG_ENABLED", True)
        retention_days = current_app.config.get("AUDIT_LOG_RETENTION_DAYS", 90)
        _audit_service = AuditService(enabled=enabled, retention_days=retention_days)

    return _audit_service


def create_audit_service(enabled: bool = True, retention_days: int = 90) -> AuditService:
    """
    Create a new audit service instance.

    Useful for testing or when not in Flask application context.

    Args:
        enabled: Whether audit logging is enabled.
        retention_days: Number of days to retain audit logs.

    Returns:
        A new AuditService instance.
    """
    return AuditService(enabled=enabled, retention_days=retention_days)
