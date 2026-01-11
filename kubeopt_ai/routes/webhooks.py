"""
Webhook management API endpoints for KubeOpt AI.

Provides REST API for configuring and managing webhook notifications.
"""

import logging
from flask import Blueprint, jsonify, request
from pydantic import BaseModel, Field, ValidationError
from typing import Optional
from enum import Enum

from kubeopt_ai.extensions import db
from kubeopt_ai.core.models import (
    WebhookConfig,
    WebhookDeliveryLog,
    WebhookType,
    WebhookStatus,
)
from kubeopt_ai.core.notifications import (
    WebhookEndpoint,
    WebhookFormat,
    WebhookDelivery,
    PayloadFormatter,
    get_notification_dispatcher,
)
from kubeopt_ai.core.anomaly_detection import AnomalyAlert, AnomalyType, AlertSeverity

logger = logging.getLogger(__name__)

webhooks_bp = Blueprint("webhooks", __name__)


# Request/Response Schemas
class WebhookTypeEnum(str, Enum):
    """Webhook type options for API."""

    SLACK = "slack"
    GENERIC = "generic"
    TEAMS = "teams"
    DISCORD = "discord"


class CreateWebhookRequest(BaseModel):
    """Request to create a webhook configuration."""

    name: str = Field(..., min_length=1, max_length=255)
    url: str = Field(..., min_length=1)
    webhook_type: WebhookTypeEnum = WebhookTypeEnum.GENERIC
    secret: Optional[str] = None
    enabled: bool = True
    severity_filter: Optional[str] = None
    custom_headers: Optional[dict] = None
    template: Optional[str] = None


class UpdateWebhookRequest(BaseModel):
    """Request to update a webhook configuration."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    url: Optional[str] = Field(None, min_length=1)
    webhook_type: Optional[WebhookTypeEnum] = None
    secret: Optional[str] = None
    enabled: Optional[bool] = None
    severity_filter: Optional[str] = None
    custom_headers: Optional[dict] = None
    template: Optional[str] = None


class TestWebhookRequest(BaseModel):
    """Request to test a webhook."""

    severity: str = "high"
    message: str = "This is a test alert from KubeOpt AI"


def _webhook_type_to_format(wt: WebhookType) -> WebhookFormat:
    """Convert database WebhookType to notification WebhookFormat."""
    mapping = {
        WebhookType.SLACK: WebhookFormat.SLACK,
        WebhookType.GENERIC: WebhookFormat.GENERIC,
        WebhookType.TEAMS: WebhookFormat.TEAMS,
        WebhookType.DISCORD: WebhookFormat.DISCORD,
    }
    return mapping.get(wt, WebhookFormat.GENERIC)


def _db_to_endpoint(config: WebhookConfig) -> WebhookEndpoint:
    """Convert database model to WebhookEndpoint."""
    return WebhookEndpoint(
        id=config.id,
        name=config.name,
        url=config.url,
        format=_webhook_type_to_format(config.webhook_type),
        secret=config.secret,
        enabled=config.enabled,
        severity_filter=config.severity_filter,
        custom_headers=config.custom_headers or {},
        template=config.template,
    )


@webhooks_bp.route("/webhooks", methods=["POST"])
def create_webhook():
    """
    Create a new webhook configuration.

    Request JSON body:
        - name: Display name for the webhook
        - url: Webhook endpoint URL
        - webhook_type: Type (slack, generic, teams, discord)
        - secret: Optional signing secret
        - enabled: Whether the webhook is active
        - severity_filter: Optional severity filter (low, medium, high, critical)
        - custom_headers: Optional custom HTTP headers
        - template: Optional custom payload template

    Returns:
        Created webhook configuration.
    """
    data = request.get_json() or {}

    try:
        req = CreateWebhookRequest.model_validate(data)
    except ValidationError as e:
        return jsonify({
            "code": "VALIDATION_ERROR",
            "message": "Invalid request body",
            "details": e.errors(),
            "trace_id": None,
        }), 400

    # Map string type to enum
    webhook_type_map = {
        "slack": WebhookType.SLACK,
        "generic": WebhookType.GENERIC,
        "teams": WebhookType.TEAMS,
        "discord": WebhookType.DISCORD,
    }
    webhook_type = webhook_type_map.get(req.webhook_type.value, WebhookType.GENERIC)

    # Create database record
    config = WebhookConfig(
        name=req.name,
        url=req.url,
        webhook_type=webhook_type,
        secret=req.secret,
        enabled=req.enabled,
        severity_filter=req.severity_filter,
        custom_headers=req.custom_headers or {},
        template=req.template,
    )

    db.session.add(config)
    db.session.commit()

    # Add to dispatcher
    dispatcher = get_notification_dispatcher()
    dispatcher.add_endpoint(_db_to_endpoint(config))

    logger.info(f"Created webhook: {config.name} ({config.id})")

    return jsonify(config.to_dict()), 201


@webhooks_bp.route("/webhooks", methods=["GET"])
def list_webhooks():
    """
    List all webhook configurations.

    Query parameters:
        - enabled: Filter by enabled status (true/false)
        - type: Filter by webhook type

    Returns:
        List of webhook configurations.
    """
    query = WebhookConfig.query

    # Apply filters
    enabled_filter = request.args.get("enabled")
    if enabled_filter is not None:
        query = query.filter(WebhookConfig.enabled == (enabled_filter.lower() == "true"))

    type_filter = request.args.get("type")
    if type_filter:
        webhook_type_map = {
            "slack": WebhookType.SLACK,
            "generic": WebhookType.GENERIC,
            "teams": WebhookType.TEAMS,
            "discord": WebhookType.DISCORD,
        }
        if type_filter in webhook_type_map:
            query = query.filter(WebhookConfig.webhook_type == webhook_type_map[type_filter])

    configs = query.order_by(WebhookConfig.created_at.desc()).all()

    return jsonify({
        "webhooks": [c.to_dict() for c in configs],
        "total": len(configs),
    }), 200


@webhooks_bp.route("/webhooks/<webhook_id>", methods=["GET"])
def get_webhook(webhook_id: str):
    """
    Get a webhook configuration by ID.

    Args:
        webhook_id: The webhook configuration ID.

    Returns:
        Webhook configuration.
    """
    config = db.session.get(WebhookConfig, webhook_id)
    if not config:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Webhook {webhook_id} not found",
            "details": None,
            "trace_id": None,
        }), 404

    return jsonify(config.to_dict()), 200


@webhooks_bp.route("/webhooks/<webhook_id>", methods=["PUT"])
def update_webhook(webhook_id: str):
    """
    Update a webhook configuration.

    Args:
        webhook_id: The webhook configuration ID.

    Request JSON body:
        Same fields as create, all optional.

    Returns:
        Updated webhook configuration.
    """
    config = db.session.get(WebhookConfig, webhook_id)
    if not config:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Webhook {webhook_id} not found",
            "details": None,
            "trace_id": None,
        }), 404

    data = request.get_json() or {}

    try:
        req = UpdateWebhookRequest.model_validate(data)
    except ValidationError as e:
        return jsonify({
            "code": "VALIDATION_ERROR",
            "message": "Invalid request body",
            "details": e.errors(),
            "trace_id": None,
        }), 400

    # Update fields
    if req.name is not None:
        config.name = req.name
    if req.url is not None:
        config.url = req.url
    if req.webhook_type is not None:
        webhook_type_map = {
            "slack": WebhookType.SLACK,
            "generic": WebhookType.GENERIC,
            "teams": WebhookType.TEAMS,
            "discord": WebhookType.DISCORD,
        }
        config.webhook_type = webhook_type_map.get(req.webhook_type.value, WebhookType.GENERIC)
    if req.secret is not None:
        config.secret = req.secret
    if req.enabled is not None:
        config.enabled = req.enabled
    if req.severity_filter is not None:
        config.severity_filter = req.severity_filter
    if req.custom_headers is not None:
        config.custom_headers = req.custom_headers
    if req.template is not None:
        config.template = req.template

    db.session.commit()

    # Update dispatcher
    dispatcher = get_notification_dispatcher()
    dispatcher.remove_endpoint(webhook_id)
    dispatcher.add_endpoint(_db_to_endpoint(config))

    logger.info(f"Updated webhook: {config.name} ({config.id})")

    return jsonify(config.to_dict()), 200


@webhooks_bp.route("/webhooks/<webhook_id>", methods=["DELETE"])
def delete_webhook(webhook_id: str):
    """
    Delete a webhook configuration.

    Args:
        webhook_id: The webhook configuration ID.

    Returns:
        Success message.
    """
    config = db.session.get(WebhookConfig, webhook_id)
    if not config:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Webhook {webhook_id} not found",
            "details": None,
            "trace_id": None,
        }), 404

    # Remove from dispatcher
    dispatcher = get_notification_dispatcher()
    dispatcher.remove_endpoint(webhook_id)

    # Delete from database
    db.session.delete(config)
    db.session.commit()

    logger.info(f"Deleted webhook: {config.name} ({webhook_id})")

    return jsonify({
        "message": f"Webhook {webhook_id} deleted",
    }), 200


@webhooks_bp.route("/webhooks/<webhook_id>/test", methods=["POST"])
def test_webhook(webhook_id: str):
    """
    Send a test notification to a webhook.

    Args:
        webhook_id: The webhook configuration ID.

    Request JSON body:
        - severity: Alert severity for test (default: high)
        - message: Test message

    Returns:
        Delivery result.
    """
    config = db.session.get(WebhookConfig, webhook_id)
    if not config:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Webhook {webhook_id} not found",
            "details": None,
            "trace_id": None,
        }), 404

    data = request.get_json() or {}

    try:
        req = TestWebhookRequest.model_validate(data)
    except ValidationError as e:
        return jsonify({
            "code": "VALIDATION_ERROR",
            "message": "Invalid request body",
            "details": e.errors(),
            "trace_id": None,
        }), 400

    # Map severity
    severity_map = {
        "low": AlertSeverity.LOW,
        "medium": AlertSeverity.MEDIUM,
        "high": AlertSeverity.HIGH,
        "critical": AlertSeverity.CRITICAL,
    }
    severity = severity_map.get(req.severity.lower(), AlertSeverity.HIGH)

    # Create test alert

    test_alert = AnomalyAlert(
        anomaly_type=AnomalyType.UNUSUAL_PATTERN,
        severity=severity,
        workload_name="test-workload",
        namespace="test-namespace",
        container_name="test-container",
        resource_type="cpu",
        description=req.message,
        current_value=0.85,
        threshold=0.80,
        score=0.75,
        recommendation="This is a test alert. No action required.",
    )

    # Format and deliver
    endpoint = _db_to_endpoint(config)
    formatter = PayloadFormatter(config.template)
    payload = formatter.format_alert(test_alert, endpoint.format)

    delivery = WebhookDelivery()
    result = delivery.deliver(endpoint, payload)

    # Log delivery attempt
    log = WebhookDeliveryLog(
        webhook_config_id=webhook_id,
        alert_id="test",
        status=WebhookStatus.DELIVERED if result.success else WebhookStatus.FAILED,
        attempt_count=1,
        response_status_code=result.status_code,
        response_body=result.response_body,
        error_message=result.error_message,
        payload=payload,
    )
    db.session.add(log)
    db.session.commit()

    return jsonify({
        "success": result.success,
        "status_code": result.status_code,
        "response_body": result.response_body,
        "error_message": result.error_message,
    }), 200 if result.success else 502


@webhooks_bp.route("/webhooks/<webhook_id>/logs", methods=["GET"])
def get_webhook_logs(webhook_id: str):
    """
    Get delivery logs for a webhook.

    Args:
        webhook_id: The webhook configuration ID.

    Query parameters:
        - limit: Maximum logs to return (default: 50)
        - status: Filter by delivery status

    Returns:
        List of delivery logs.
    """
    config = db.session.get(WebhookConfig, webhook_id)
    if not config:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Webhook {webhook_id} not found",
            "details": None,
            "trace_id": None,
        }), 404

    query = WebhookDeliveryLog.query.filter_by(webhook_config_id=webhook_id)

    # Apply status filter
    status_filter = request.args.get("status")
    if status_filter:
        status_map = {
            "pending": WebhookStatus.PENDING,
            "delivered": WebhookStatus.DELIVERED,
            "failed": WebhookStatus.FAILED,
            "retrying": WebhookStatus.RETRYING,
        }
        if status_filter in status_map:
            query = query.filter(WebhookDeliveryLog.status == status_map[status_filter])

    limit = request.args.get("limit", type=int, default=50)
    logs = query.order_by(WebhookDeliveryLog.created_at.desc()).limit(limit).all()

    return jsonify({
        "webhook_id": webhook_id,
        "logs": [log.to_dict() for log in logs],
        "total": len(logs),
    }), 200


@webhooks_bp.route("/webhooks/<webhook_id>/enable", methods=["POST"])
def enable_webhook(webhook_id: str):
    """
    Enable a webhook.

    Args:
        webhook_id: The webhook configuration ID.

    Returns:
        Updated webhook configuration.
    """
    config = db.session.get(WebhookConfig, webhook_id)
    if not config:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Webhook {webhook_id} not found",
            "details": None,
            "trace_id": None,
        }), 404

    config.enabled = True
    db.session.commit()

    # Update dispatcher
    dispatcher = get_notification_dispatcher()
    dispatcher.remove_endpoint(webhook_id)
    dispatcher.add_endpoint(_db_to_endpoint(config))

    return jsonify(config.to_dict()), 200


@webhooks_bp.route("/webhooks/<webhook_id>/disable", methods=["POST"])
def disable_webhook(webhook_id: str):
    """
    Disable a webhook.

    Args:
        webhook_id: The webhook configuration ID.

    Returns:
        Updated webhook configuration.
    """
    config = db.session.get(WebhookConfig, webhook_id)
    if not config:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Webhook {webhook_id} not found",
            "details": None,
            "trace_id": None,
        }), 404

    config.enabled = False
    db.session.commit()

    # Update dispatcher
    dispatcher = get_notification_dispatcher()
    dispatcher.remove_endpoint(webhook_id)

    return jsonify(config.to_dict()), 200
