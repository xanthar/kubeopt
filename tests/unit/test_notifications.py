"""
Unit tests for the notification system.
"""

import pytest
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, MagicMock

from kubeopt_ai.core.notifications import (
    WebhookFormat,
    DeliveryResult,
    WebhookEndpoint,
    DeliveryAttempt,
    AlertTemplates,
    PayloadFormatter,
    WebhookDelivery,
    NotificationDispatcher,
    BackgroundNotificationWorker,
    _severity_to_color,
)
from kubeopt_ai.core.anomaly_detection import AnomalyAlert, AnomalyType, AlertSeverity


class TestWebhookFormat:
    """Tests for WebhookFormat enum."""

    def test_webhook_format_values(self):
        """Test all webhook format values."""
        assert WebhookFormat.SLACK.value == "slack"
        assert WebhookFormat.GENERIC.value == "generic"
        assert WebhookFormat.TEAMS.value == "teams"
        assert WebhookFormat.DISCORD.value == "discord"


class TestDeliveryResult:
    """Tests for DeliveryResult dataclass."""

    def test_successful_delivery(self):
        """Test successful delivery result."""
        result = DeliveryResult(
            success=True,
            status_code=200,
            response_body='{"ok": true}',
        )

        assert result.success
        assert result.status_code == 200
        assert result.error_message is None

    def test_failed_delivery(self):
        """Test failed delivery result."""
        result = DeliveryResult(
            success=False,
            status_code=500,
            error_message="Internal server error",
        )

        assert not result.success
        assert result.status_code == 500
        assert result.error_message == "Internal server error"

    def test_rate_limited_delivery(self):
        """Test rate-limited delivery result."""
        result = DeliveryResult(
            success=False,
            status_code=429,
            retry_after=60,
        )

        assert not result.success
        assert result.retry_after == 60


class TestWebhookEndpoint:
    """Tests for WebhookEndpoint dataclass."""

    def test_create_endpoint(self):
        """Test creating a webhook endpoint."""
        endpoint = WebhookEndpoint(
            id="test-id",
            name="Test Webhook",
            url="https://example.com/webhook",
        )

        assert endpoint.id == "test-id"
        assert endpoint.name == "Test Webhook"
        assert endpoint.format == WebhookFormat.GENERIC
        assert endpoint.enabled
        assert endpoint.max_retries == 3

    def test_endpoint_with_all_options(self):
        """Test endpoint with all options."""
        endpoint = WebhookEndpoint(
            id="slack-1",
            name="Slack Alerts",
            url="https://hooks.slack.com/services/xxx",
            format=WebhookFormat.SLACK,
            secret="my-secret",
            enabled=True,
            severity_filter="critical",
            custom_headers={"X-Custom": "value"},
            template="custom template",
            max_retries=5,
            timeout=30,
        )

        assert endpoint.format == WebhookFormat.SLACK
        assert endpoint.secret == "my-secret"
        assert endpoint.severity_filter == "critical"
        assert endpoint.custom_headers == {"X-Custom": "value"}
        assert endpoint.max_retries == 5
        assert endpoint.timeout == 30


class TestSeverityToColor:
    """Tests for severity to color conversion."""

    def test_critical_color(self):
        """Test critical severity color."""
        colors = _severity_to_color(AlertSeverity.CRITICAL)
        assert colors["hex"] == "#FF0000"
        assert colors["discord"] == 16711680

    def test_high_color(self):
        """Test high severity color."""
        colors = _severity_to_color(AlertSeverity.HIGH)
        assert colors["hex"] == "#FF6600"

    def test_medium_color(self):
        """Test medium severity color."""
        colors = _severity_to_color(AlertSeverity.MEDIUM)
        assert colors["hex"] == "#FFCC00"

    def test_low_color(self):
        """Test low severity color."""
        colors = _severity_to_color(AlertSeverity.LOW)
        assert colors["hex"] == "#00CC00"


class TestPayloadFormatter:
    """Tests for PayloadFormatter."""

    @pytest.fixture
    def sample_alert(self):
        """Create a sample alert for testing."""
        return AnomalyAlert(
            anomaly_type=AnomalyType.CPU_SPIKE,
            severity=AlertSeverity.HIGH,
            workload_name="test-deploy",
            namespace="default",
            container_name="main",
            resource_type="cpu",
            description="High CPU usage detected",
            current_value=0.9,
            threshold=0.7,
            score=0.85,
            recommendation="Consider scaling or optimizing",
        )

    def test_format_generic_alert(self, sample_alert):
        """Test formatting an alert for generic webhook."""
        formatter = PayloadFormatter()
        payload = formatter.format_alert(sample_alert, WebhookFormat.GENERIC)

        assert payload["anomaly_type"] == "cpu_spike"
        assert payload["severity"] == "HIGH"
        assert payload["workload_name"] == "test-deploy"
        assert payload["namespace"] == "default"
        assert payload["description"] == "High CPU usage detected"

    def test_format_slack_alert(self, sample_alert):
        """Test formatting an alert for Slack webhook."""
        formatter = PayloadFormatter()
        payload = formatter.format_alert(sample_alert, WebhookFormat.SLACK)

        assert "blocks" in payload
        assert len(payload["blocks"]) > 0

    def test_format_teams_alert(self, sample_alert):
        """Test formatting an alert for Teams webhook."""
        formatter = PayloadFormatter()
        payload = formatter.format_alert(sample_alert, WebhookFormat.TEAMS)

        assert "@type" in payload
        assert payload["@type"] == "MessageCard"

    def test_format_discord_alert(self, sample_alert):
        """Test formatting an alert for Discord webhook."""
        formatter = PayloadFormatter()
        payload = formatter.format_alert(sample_alert, WebhookFormat.DISCORD)

        assert "embeds" in payload
        assert len(payload["embeds"]) > 0

    def test_custom_template(self, sample_alert):
        """Test using a custom template."""
        custom_template = '{"custom": "${workload_name}", "severity": "${severity}"}'
        formatter = PayloadFormatter(custom_template)
        payload = formatter.format_alert(sample_alert, WebhookFormat.GENERIC)

        assert payload["custom"] == "test-deploy"
        assert payload["severity"] == "HIGH"

    def test_fallback_on_invalid_template(self, sample_alert):
        """Test fallback when template is invalid JSON."""
        invalid_template = "not valid json ${workload_name}"
        formatter = PayloadFormatter(invalid_template)
        payload = formatter.format_alert(sample_alert, WebhookFormat.GENERIC)

        # Should return fallback payload
        assert "workload_name" in payload
        assert payload["workload_name"] == "test-deploy"


class TestWebhookDelivery:
    """Tests for WebhookDelivery."""

    def test_create_delivery(self):
        """Test creating a delivery handler."""
        delivery = WebhookDelivery(
            base_delay=2.0,
            max_delay=120.0,
            backoff_factor=3.0,
        )

        assert delivery._base_delay == 2.0
        assert delivery._max_delay == 120.0
        assert delivery._backoff_factor == 3.0

    @patch("kubeopt_ai.core.notifications.requests.Session")
    def test_successful_delivery(self, mock_session_class):
        """Test successful webhook delivery."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"ok": true}'
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session

        delivery = WebhookDelivery()
        delivery._session = mock_session

        endpoint = WebhookEndpoint(
            id="test",
            name="Test",
            url="https://example.com/webhook",
        )

        result = delivery.deliver(endpoint, {"test": "data"})

        assert result.success
        assert result.status_code == 200

    @patch("kubeopt_ai.core.notifications.requests.Session")
    def test_failed_delivery(self, mock_session_class):
        """Test failed webhook delivery."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session

        delivery = WebhookDelivery()
        delivery._session = mock_session

        endpoint = WebhookEndpoint(
            id="test",
            name="Test",
            url="https://example.com/webhook",
        )

        result = delivery.deliver(endpoint, {"test": "data"})

        assert not result.success
        assert result.status_code == 500

    @patch("kubeopt_ai.core.notifications.requests.Session")
    def test_delivery_with_signature(self, mock_session_class):
        """Test delivery with HMAC signature."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"ok": true}'
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session

        delivery = WebhookDelivery()
        delivery._session = mock_session

        endpoint = WebhookEndpoint(
            id="test",
            name="Test",
            url="https://example.com/webhook",
            secret="my-secret",
        )

        result = delivery.deliver(endpoint, {"test": "data"})

        # Check that signature header was added
        call_args = mock_session.post.call_args
        headers = call_args.kwargs.get("headers", {})
        assert "X-KubeOpt-Signature" in headers
        assert headers["X-KubeOpt-Signature"].startswith("sha256=")

    def test_calculate_retry_delay(self):
        """Test retry delay calculation."""
        delivery = WebhookDelivery(
            base_delay=1.0,
            max_delay=60.0,
            backoff_factor=2.0,
        )

        assert delivery.calculate_retry_delay(0) == 1.0
        assert delivery.calculate_retry_delay(1) == 2.0
        assert delivery.calculate_retry_delay(2) == 4.0
        assert delivery.calculate_retry_delay(3) == 8.0
        assert delivery.calculate_retry_delay(10) == 60.0  # Capped at max

    def test_generate_signature(self):
        """Test HMAC signature generation."""
        delivery = WebhookDelivery()
        signature = delivery._generate_signature('{"test": "data"}', "secret123")

        assert signature.startswith("sha256=")
        assert len(signature) > 10


class TestNotificationDispatcher:
    """Tests for NotificationDispatcher."""

    @pytest.fixture
    def dispatcher(self):
        """Create a dispatcher for testing."""
        return NotificationDispatcher()

    @pytest.fixture
    def sample_endpoint(self):
        """Create a sample endpoint."""
        return WebhookEndpoint(
            id="test-endpoint",
            name="Test Webhook",
            url="https://example.com/webhook",
            format=WebhookFormat.GENERIC,
        )

    @pytest.fixture
    def sample_alert(self):
        """Create a sample alert."""
        return AnomalyAlert(
            anomaly_type=AnomalyType.MEMORY_LEAK,
            severity=AlertSeverity.CRITICAL,
            workload_name="leaky-app",
            namespace="production",
            container_name="main",
            resource_type="memory",
            description="Memory leak detected",
            current_value=0.95,
            threshold=0.80,
            score=0.9,
            recommendation="Restart the pod and investigate",
        )

    def test_add_endpoint(self, dispatcher, sample_endpoint):
        """Test adding an endpoint."""
        dispatcher.add_endpoint(sample_endpoint)

        assert "test-endpoint" in dispatcher._endpoints
        assert dispatcher.get_endpoint("test-endpoint") == sample_endpoint

    def test_remove_endpoint(self, dispatcher, sample_endpoint):
        """Test removing an endpoint."""
        dispatcher.add_endpoint(sample_endpoint)
        dispatcher.remove_endpoint("test-endpoint")

        assert "test-endpoint" not in dispatcher._endpoints

    def test_list_endpoints(self, dispatcher, sample_endpoint):
        """Test listing endpoints."""
        dispatcher.add_endpoint(sample_endpoint)
        endpoints = dispatcher.list_endpoints()

        assert len(endpoints) == 1
        assert endpoints[0].id == "test-endpoint"

    @patch.object(WebhookDelivery, "deliver")
    def test_dispatch_alert(self, mock_deliver, dispatcher, sample_endpoint, sample_alert):
        """Test dispatching an alert."""
        mock_deliver.return_value = DeliveryResult(success=True, status_code=200)

        dispatcher.add_endpoint(sample_endpoint)
        results = dispatcher.dispatch(sample_alert)

        assert "test-endpoint" in results
        assert results["test-endpoint"].success

    @patch.object(WebhookDelivery, "deliver")
    def test_dispatch_with_severity_filter(
        self, mock_deliver, dispatcher, sample_endpoint, sample_alert
    ):
        """Test dispatch respects severity filter."""
        mock_deliver.return_value = DeliveryResult(success=True, status_code=200)

        # Set severity filter to high (alert is critical)
        sample_endpoint.severity_filter = "high"
        dispatcher.add_endpoint(sample_endpoint)

        results = dispatcher.dispatch(sample_alert)

        # Should not deliver because filter doesn't match
        assert "test-endpoint" not in results

    @patch.object(WebhookDelivery, "deliver")
    def test_dispatch_disabled_endpoint(
        self, mock_deliver, dispatcher, sample_endpoint, sample_alert
    ):
        """Test dispatch skips disabled endpoints."""
        mock_deliver.return_value = DeliveryResult(success=True, status_code=200)

        sample_endpoint.enabled = False
        dispatcher.add_endpoint(sample_endpoint)

        results = dispatcher.dispatch(sample_alert)

        assert "test-endpoint" not in results

    @patch.object(WebhookDelivery, "deliver")
    def test_dispatch_with_callback(
        self, mock_deliver, dispatcher, sample_endpoint, sample_alert
    ):
        """Test dispatch triggers callbacks."""
        mock_deliver.return_value = DeliveryResult(success=True, status_code=200)

        callback_results = []

        def callback(alert, endpoint_id, result):
            callback_results.append((alert, endpoint_id, result))

        dispatcher.add_endpoint(sample_endpoint)
        dispatcher.add_callback(callback)
        dispatcher.dispatch(sample_alert)

        assert len(callback_results) == 1
        assert callback_results[0][1] == "test-endpoint"

    @patch.object(WebhookDelivery, "deliver")
    def test_retry_queuing(self, mock_deliver, dispatcher, sample_endpoint, sample_alert):
        """Test failed deliveries are queued for retry."""
        mock_deliver.return_value = DeliveryResult(
            success=False, status_code=500, error_message="Server error"
        )

        dispatcher.add_endpoint(sample_endpoint)
        dispatcher.dispatch(sample_alert)

        pending = dispatcher.get_pending_retries()
        assert len(pending) == 1
        assert pending[0].webhook_id == "test-endpoint"

    @patch.object(WebhookDelivery, "deliver")
    def test_process_retries_success(self, mock_deliver, dispatcher, sample_endpoint):
        """Test successful retry processing."""
        mock_deliver.return_value = DeliveryResult(success=True, status_code=200)

        # Add a pending retry
        attempt = DeliveryAttempt(
            webhook_id="test-endpoint",
            alert_id="alert-1",
            payload={"test": "data"},
            attempt_count=1,
            next_retry=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        dispatcher._pending_retries.append(attempt)
        dispatcher.add_endpoint(sample_endpoint)

        processed = dispatcher.process_retries()

        assert processed == 1
        assert len(dispatcher.get_pending_retries()) == 0

    @patch.object(WebhookDelivery, "deliver")
    def test_process_retries_reschedule(self, mock_deliver, dispatcher, sample_endpoint):
        """Test failed retry is rescheduled."""
        mock_deliver.return_value = DeliveryResult(
            success=False, status_code=500, error_message="Still failing"
        )

        # Add a pending retry with attempts remaining
        attempt = DeliveryAttempt(
            webhook_id="test-endpoint",
            alert_id="alert-1",
            payload={"test": "data"},
            attempt_count=1,
            max_attempts=3,
            next_retry=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        dispatcher._pending_retries.append(attempt)
        dispatcher.add_endpoint(sample_endpoint)

        dispatcher.process_retries()

        pending = dispatcher.get_pending_retries()
        assert len(pending) == 1
        assert pending[0].attempt_count == 2


class TestBackgroundNotificationWorker:
    """Tests for BackgroundNotificationWorker."""

    def test_create_worker(self):
        """Test creating a worker."""
        dispatcher = NotificationDispatcher()
        worker = BackgroundNotificationWorker(dispatcher, check_interval=5)

        assert worker._check_interval == 5
        assert not worker.is_running

    def test_start_stop_worker(self):
        """Test starting and stopping the worker."""
        dispatcher = NotificationDispatcher()
        worker = BackgroundNotificationWorker(dispatcher, check_interval=1)

        worker.start()
        assert worker.is_running

        worker.stop()
        assert not worker.is_running


class TestAlertTemplates:
    """Tests for alert template strings."""

    def test_slack_template_valid_json(self):
        """Test Slack template produces valid JSON structure."""
        # Template uses Template substitution, so test with placeholders replaced
        template = AlertTemplates.SLACK_DEFAULT
        assert "blocks" in template
        assert "header" in template

    def test_teams_template_valid_structure(self):
        """Test Teams template has correct structure."""
        template = AlertTemplates.TEAMS_DEFAULT
        assert "@type" in template
        assert "MessageCard" in template

    def test_discord_template_valid_structure(self):
        """Test Discord template has correct structure."""
        template = AlertTemplates.DISCORD_DEFAULT
        assert "embeds" in template

    def test_generic_template_valid_structure(self):
        """Test generic template has correct structure."""
        template = AlertTemplates.GENERIC_DEFAULT
        assert "alert_id" in template
        assert "anomaly_type" in template
