"""
Notification service for KubeOpt AI.

Provides webhook delivery with retry logic, support for multiple
webhook formats (Slack, generic HTTP), and alert templates.
"""

import hashlib
import hmac
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from string import Template
from typing import Callable, Optional
import uuid

import requests
from requests.exceptions import RequestException

from kubeopt_ai.core.anomaly_detection import AnomalyAlert, AlertSeverity

logger = logging.getLogger(__name__)


class WebhookFormat(str, Enum):
    """Supported webhook payload formats."""

    SLACK = "slack"
    GENERIC = "generic"
    TEAMS = "teams"
    DISCORD = "discord"


@dataclass
class DeliveryResult:
    """Result of a webhook delivery attempt."""

    success: bool
    status_code: Optional[int] = None
    response_body: Optional[str] = None
    error_message: Optional[str] = None
    retry_after: Optional[int] = None  # Seconds until retry


@dataclass
class WebhookEndpoint:
    """Configuration for a webhook endpoint."""

    id: str
    name: str
    url: str
    format: WebhookFormat = WebhookFormat.GENERIC
    secret: Optional[str] = None
    enabled: bool = True
    severity_filter: Optional[str] = None
    custom_headers: dict = field(default_factory=dict)
    template: Optional[str] = None
    max_retries: int = 3
    timeout: int = 10


@dataclass
class DeliveryAttempt:
    """Tracks a delivery attempt for retry logic."""

    webhook_id: str
    alert_id: str
    payload: dict
    attempt_count: int = 0
    max_attempts: int = 3
    next_retry: Optional[datetime] = None
    last_error: Optional[str] = None


# Default alert templates
class AlertTemplates:
    """Default templates for different webhook formats."""

    SLACK_DEFAULT = """
{
    "blocks": [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🚨 KubeOpt Alert: ${severity} - ${anomaly_type}"
            }
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": "*Workload:*\\n${namespace}/${workload_name}"},
                {"type": "mrkdwn", "text": "*Container:*\\n${container_name}"},
                {"type": "mrkdwn", "text": "*Resource:*\\n${resource_type}"},
                {"type": "mrkdwn", "text": "*Score:*\\n${score}"}
            ]
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Description:*\\n${description}"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Recommendation:*\\n${recommendation}"
            }
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "Detected at: ${detected_at}"}
            ]
        }
    ]
}
"""

    TEAMS_DEFAULT = """
{
    "@type": "MessageCard",
    "@context": "http://schema.org/extensions",
    "themeColor": "${theme_color}",
    "summary": "KubeOpt Alert: ${severity} - ${anomaly_type}",
    "sections": [{
        "activityTitle": "🚨 KubeOpt Alert",
        "activitySubtitle": "${namespace}/${workload_name}",
        "facts": [
            {"name": "Severity", "value": "${severity}"},
            {"name": "Type", "value": "${anomaly_type}"},
            {"name": "Container", "value": "${container_name}"},
            {"name": "Resource", "value": "${resource_type}"},
            {"name": "Score", "value": "${score}"}
        ],
        "text": "${description}\\n\\n**Recommendation:** ${recommendation}"
    }]
}
"""

    DISCORD_DEFAULT = """
{
    "embeds": [{
        "title": "🚨 KubeOpt Alert: ${severity}",
        "description": "${description}",
        "color": ${color_code},
        "fields": [
            {"name": "Workload", "value": "${namespace}/${workload_name}", "inline": true},
            {"name": "Container", "value": "${container_name}", "inline": true},
            {"name": "Type", "value": "${anomaly_type}", "inline": true},
            {"name": "Resource", "value": "${resource_type}", "inline": true},
            {"name": "Score", "value": "${score}", "inline": true}
        ],
        "footer": {"text": "Recommendation: ${recommendation}"},
        "timestamp": "${detected_at_iso}"
    }]
}
"""

    GENERIC_DEFAULT = """
{
    "alert_id": "${alert_id}",
    "anomaly_type": "${anomaly_type}",
    "severity": "${severity}",
    "workload_name": "${workload_name}",
    "namespace": "${namespace}",
    "container_name": "${container_name}",
    "resource_type": "${resource_type}",
    "description": "${description}",
    "current_value": ${current_value},
    "threshold": ${threshold},
    "score": ${score},
    "recommendation": "${recommendation}",
    "detected_at": "${detected_at}"
}
"""


def _severity_to_color(severity: AlertSeverity) -> dict:
    """Convert severity to color codes for different formats."""
    colors = {
        AlertSeverity.CRITICAL: {
            "hex": "#FF0000",
            "theme": "FF0000",
            "discord": 16711680,
        },
        AlertSeverity.HIGH: {
            "hex": "#FF6600",
            "theme": "FF6600",
            "discord": 16737280,
        },
        AlertSeverity.MEDIUM: {
            "hex": "#FFCC00",
            "theme": "FFCC00",
            "discord": 16763904,
        },
        AlertSeverity.LOW: {
            "hex": "#00CC00",
            "theme": "00CC00",
            "discord": 52224,
        },
    }
    return colors.get(severity, colors[AlertSeverity.LOW])


class PayloadFormatter:
    """Formats alert payloads for different webhook types."""

    def __init__(self, custom_template: Optional[str] = None):
        """
        Initialize the payload formatter.

        Args:
            custom_template: Optional custom template string.
        """
        self._custom_template = custom_template

    def format_alert(
        self,
        alert: AnomalyAlert,
        webhook_format: WebhookFormat,
    ) -> dict:
        """
        Format an alert for the specified webhook format.

        Args:
            alert: The anomaly alert to format.
            webhook_format: Target webhook format.

        Returns:
            Formatted payload as a dictionary.
        """
        # Build template variables
        colors = _severity_to_color(alert.severity)
        variables = {
            "alert_id": str(uuid.uuid4()),
            "anomaly_type": alert.anomaly_type.value,
            "severity": alert.severity.value.upper(),
            "workload_name": alert.workload_name,
            "namespace": alert.namespace,
            "container_name": alert.container_name or "N/A",
            "resource_type": alert.resource_type,
            "description": alert.description,
            "current_value": alert.current_value,
            "threshold": alert.threshold,
            "score": f"{alert.score:.2f}",
            "recommendation": alert.recommendation,
            "detected_at": alert.detected_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "detected_at_iso": alert.detected_at.isoformat(),
            "theme_color": colors["theme"],
            "color_code": colors["discord"],
        }

        # Select template
        if self._custom_template:
            template_str = self._custom_template
        else:
            template_str = self._get_default_template(webhook_format)

        # Render template
        template = Template(template_str)
        rendered = template.safe_substitute(variables)

        try:
            return json.loads(rendered)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse rendered template: {e}")
            # Fall back to generic format
            return self._fallback_payload(alert, variables)

    def _get_default_template(self, webhook_format: WebhookFormat) -> str:
        """Get the default template for a webhook format."""
        templates = {
            WebhookFormat.SLACK: AlertTemplates.SLACK_DEFAULT,
            WebhookFormat.TEAMS: AlertTemplates.TEAMS_DEFAULT,
            WebhookFormat.DISCORD: AlertTemplates.DISCORD_DEFAULT,
            WebhookFormat.GENERIC: AlertTemplates.GENERIC_DEFAULT,
        }
        return templates.get(webhook_format, AlertTemplates.GENERIC_DEFAULT)

    def _fallback_payload(self, alert: AnomalyAlert, variables: dict) -> dict:
        """Generate a fallback payload if template rendering fails."""
        return {
            "alert_id": variables["alert_id"],
            "anomaly_type": alert.anomaly_type.value,
            "severity": alert.severity.value,
            "workload_name": alert.workload_name,
            "namespace": alert.namespace,
            "container_name": alert.container_name,
            "description": alert.description,
            "recommendation": alert.recommendation,
            "detected_at": alert.detected_at.isoformat(),
        }


class WebhookDelivery:
    """
    Handles webhook delivery with retry logic.

    Supports exponential backoff and signature verification.
    """

    def __init__(
        self,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        backoff_factor: float = 2.0,
    ):
        """
        Initialize webhook delivery.

        Args:
            base_delay: Initial retry delay in seconds.
            max_delay: Maximum retry delay in seconds.
            backoff_factor: Multiplier for exponential backoff.
        """
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._backoff_factor = backoff_factor
        self._session = requests.Session()

    def deliver(
        self,
        endpoint: WebhookEndpoint,
        payload: dict,
    ) -> DeliveryResult:
        """
        Deliver a payload to a webhook endpoint.

        Args:
            endpoint: The webhook endpoint configuration.
            payload: The payload to deliver.

        Returns:
            DeliveryResult with success status and details.
        """
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "KubeOpt-AI/1.0",
        }

        # Add custom headers
        if endpoint.custom_headers:
            headers.update(endpoint.custom_headers)

        # Add signature if secret is configured
        body = json.dumps(payload)
        if endpoint.secret:
            signature = self._generate_signature(body, endpoint.secret)
            headers["X-KubeOpt-Signature"] = signature

        try:
            response = self._session.post(
                endpoint.url,
                data=body,
                headers=headers,
                timeout=endpoint.timeout,
            )

            success = 200 <= response.status_code < 300

            # Check for rate limiting
            retry_after = None
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 60))

            return DeliveryResult(
                success=success,
                status_code=response.status_code,
                response_body=response.text[:1000] if response.text else None,
                retry_after=retry_after,
            )

        except RequestException as e:
            logger.error(f"Webhook delivery failed: {e}")
            return DeliveryResult(
                success=False,
                error_message=str(e),
            )

    def _generate_signature(self, payload: str, secret: str) -> str:
        """Generate HMAC signature for the payload."""
        signature = hmac.new(
            secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        )
        return f"sha256={signature.hexdigest()}"

    def calculate_retry_delay(self, attempt: int) -> float:
        """
        Calculate delay before next retry using exponential backoff.

        Args:
            attempt: The attempt number (0-based).

        Returns:
            Delay in seconds.
        """
        delay = self._base_delay * (self._backoff_factor ** attempt)
        return min(delay, self._max_delay)


class NotificationDispatcher:
    """
    Central notification dispatcher for anomaly alerts.

    Manages webhook endpoints and handles alert distribution.
    """

    def __init__(
        self,
        delivery: Optional[WebhookDelivery] = None,
    ):
        """
        Initialize the notification dispatcher.

        Args:
            delivery: Optional custom delivery handler.
        """
        self._delivery = delivery or WebhookDelivery()
        self._endpoints: dict[str, WebhookEndpoint] = {}
        self._pending_retries: list[DeliveryAttempt] = []
        self._formatters: dict[str, PayloadFormatter] = {}
        self._callbacks: list[Callable[[AnomalyAlert, str, DeliveryResult], None]] = []

    def add_endpoint(self, endpoint: WebhookEndpoint) -> None:
        """
        Add a webhook endpoint to the dispatcher.

        Args:
            endpoint: The webhook endpoint configuration.
        """
        self._endpoints[endpoint.id] = endpoint
        self._formatters[endpoint.id] = PayloadFormatter(endpoint.template)

    def remove_endpoint(self, endpoint_id: str) -> None:
        """Remove a webhook endpoint."""
        self._endpoints.pop(endpoint_id, None)
        self._formatters.pop(endpoint_id, None)

    def get_endpoint(self, endpoint_id: str) -> Optional[WebhookEndpoint]:
        """Get a webhook endpoint by ID."""
        return self._endpoints.get(endpoint_id)

    def list_endpoints(self) -> list[WebhookEndpoint]:
        """List all registered endpoints."""
        return list(self._endpoints.values())

    def add_callback(
        self,
        callback: Callable[[AnomalyAlert, str, DeliveryResult], None],
    ) -> None:
        """
        Add a callback for delivery results.

        Args:
            callback: Function called with (alert, endpoint_id, result).
        """
        self._callbacks.append(callback)

    def dispatch(
        self,
        alert: AnomalyAlert,
        endpoint_ids: Optional[list[str]] = None,
    ) -> dict[str, DeliveryResult]:
        """
        Dispatch an alert to webhook endpoints.

        Args:
            alert: The anomaly alert to dispatch.
            endpoint_ids: Optional list of endpoint IDs. If None, sends to all.

        Returns:
            Dict mapping endpoint IDs to delivery results.
        """
        results = {}
        target_ids = endpoint_ids or list(self._endpoints.keys())

        for endpoint_id in target_ids:
            endpoint = self._endpoints.get(endpoint_id)
            if not endpoint or not endpoint.enabled:
                continue

            # Check severity filter
            if endpoint.severity_filter:
                if alert.severity.value != endpoint.severity_filter:
                    continue

            # Format payload
            formatter = self._formatters.get(endpoint_id, PayloadFormatter())
            payload = formatter.format_alert(alert, endpoint.format)

            # Deliver
            result = self._delivery.deliver(endpoint, payload)
            results[endpoint_id] = result

            # Handle retry on failure
            if not result.success:
                self._queue_retry(endpoint, alert, payload)

            # Trigger callbacks
            for callback in self._callbacks:
                try:
                    callback(alert, endpoint_id, result)
                except Exception as e:
                    logger.error(f"Delivery callback failed: {e}")

        return results

    def _queue_retry(
        self,
        endpoint: WebhookEndpoint,
        alert: AnomalyAlert,
        payload: dict,
    ) -> None:
        """Queue a delivery for retry."""
        attempt = DeliveryAttempt(
            webhook_id=endpoint.id,
            alert_id=str(uuid.uuid4()),
            payload=payload,
            attempt_count=1,
            max_attempts=endpoint.max_retries,
            next_retry=datetime.now(timezone.utc) + timedelta(
                seconds=self._delivery.calculate_retry_delay(0)
            ),
        )
        self._pending_retries.append(attempt)

    def process_retries(self) -> int:
        """
        Process pending delivery retries.

        Returns:
            Number of retries processed.
        """
        now = datetime.now(timezone.utc)
        processed = 0
        remaining = []

        for attempt in self._pending_retries:
            if attempt.next_retry and attempt.next_retry > now:
                remaining.append(attempt)
                continue

            endpoint = self._endpoints.get(attempt.webhook_id)
            if not endpoint:
                continue

            result = self._delivery.deliver(endpoint, attempt.payload)
            processed += 1

            if result.success:
                logger.info(f"Retry succeeded for {attempt.webhook_id}")
            elif attempt.attempt_count < attempt.max_attempts:
                # Queue another retry
                delay = self._delivery.calculate_retry_delay(attempt.attempt_count)
                attempt.attempt_count += 1
                attempt.next_retry = now + timedelta(seconds=delay)
                attempt.last_error = result.error_message
                remaining.append(attempt)
                logger.warning(
                    f"Retry {attempt.attempt_count}/{attempt.max_attempts} "
                    f"scheduled for {attempt.webhook_id}"
                )
            else:
                logger.error(
                    f"Max retries reached for {attempt.webhook_id}: "
                    f"{result.error_message}"
                )

        self._pending_retries = remaining
        return processed

    def get_pending_retries(self) -> list[DeliveryAttempt]:
        """Get all pending retry attempts."""
        return self._pending_retries.copy()


class BackgroundNotificationWorker:
    """
    Background worker for processing notification retries.
    """

    def __init__(
        self,
        dispatcher: NotificationDispatcher,
        check_interval: int = 10,
    ):
        """
        Initialize the background worker.

        Args:
            dispatcher: The notification dispatcher.
            check_interval: Seconds between retry checks.
        """
        self._dispatcher = dispatcher
        self._check_interval = check_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the background worker."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("Notification worker started")

    def stop(self) -> None:
        """Stop the background worker."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Notification worker stopped")

    def _run(self) -> None:
        """Main worker loop."""
        while self._running:
            try:
                processed = self._dispatcher.process_retries()
                if processed > 0:
                    logger.debug(f"Processed {processed} retries")
            except Exception as e:
                logger.error(f"Retry processing failed: {e}")

            time.sleep(self._check_interval)

    @property
    def is_running(self) -> bool:
        """Check if the worker is running."""
        return self._running


# Module-level instances
_dispatcher: Optional[NotificationDispatcher] = None
_worker: Optional[BackgroundNotificationWorker] = None


def get_notification_dispatcher() -> NotificationDispatcher:
    """Get or create the notification dispatcher."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = NotificationDispatcher()
    return _dispatcher


def get_notification_worker() -> BackgroundNotificationWorker:
    """Get or create the background notification worker."""
    global _worker
    if _worker is None:
        _worker = BackgroundNotificationWorker(get_notification_dispatcher())
    return _worker
