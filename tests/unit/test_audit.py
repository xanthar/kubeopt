"""
Unit tests for audit logging functionality.
"""

import json
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch

from kubeopt_ai.app import create_app
from kubeopt_ai.config import TestConfig
from kubeopt_ai.extensions import db
from kubeopt_ai.core.models import AuditLog, AuditAction
from kubeopt_ai.core.audit import (
    AuditService,
    AuditContext,
    audit_action,
    create_audit_service,
)


@pytest.fixture
def app():
    """Create Flask test application with fresh database."""
    app = create_app(TestConfig())
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture
def audit_service(app):
    """Create audit service with app context."""
    with app.app_context():
        yield create_audit_service(enabled=True, retention_days=90)


class TestAuditService:
    """Tests for AuditService class."""

    def test_log_creates_audit_entry(self, app, audit_service):
        """Test that log() creates an audit entry in the database."""
        with app.app_context():
            context = AuditContext(
                user_id="user-123",
                user_email="test@example.com",
                ip_address="192.168.1.1",
                user_agent="TestClient/1.0",
                request_method="POST",
                request_path="/api/v1/optimize/run",
            )

            result = audit_service.log(
                action=AuditAction.CREATE,
                resource_type="optimization_run",
                resource_id="run-456",
                details={"manifest_path": "/path/to/manifests"},
                context=context,
                response_status=202,
                duration_ms=150,
            )

            assert result is not None
            assert result.id is not None
            assert result.action == AuditAction.CREATE
            assert result.resource_type == "optimization_run"
            assert result.resource_id == "run-456"
            assert result.user_id == "user-123"
            assert result.user_email == "test@example.com"
            assert result.ip_address == "192.168.1.1"
            assert result.response_status == 202
            assert result.duration_ms == 150

    def test_log_disabled_returns_none(self, app):
        """Test that log() returns None when audit logging is disabled."""
        with app.app_context():
            service = create_audit_service(enabled=False)

            result = service.log(
                action=AuditAction.CREATE,
                resource_type="test",
            )

            assert result is None

    def test_log_without_context(self, app, audit_service):
        """Test that log() works without explicit context."""
        with app.app_context():
            result = audit_service.log(
                action=AuditAction.READ,
                resource_type="suggestion",
                resource_id="sug-789",
            )

            assert result is not None
            assert result.action == AuditAction.READ
            assert result.resource_type == "suggestion"

    def test_query_returns_results(self, app, audit_service):
        """Test that query() returns matching audit logs."""
        with app.app_context():
            # Create some audit logs
            for i in range(5):
                audit_service.log(
                    action=AuditAction.CREATE,
                    resource_type="optimization_run",
                    resource_id=f"run-{i}",
                )

            results, total = audit_service.query(
                action=AuditAction.CREATE,
                resource_type="optimization_run",
            )

            assert total == 5
            assert len(results) == 5

    def test_query_with_filters(self, app, audit_service):
        """Test that query() filters correctly."""
        with app.app_context():
            # Create logs with different actions
            audit_service.log(
                action=AuditAction.CREATE,
                resource_type="optimization_run",
            )
            audit_service.log(
                action=AuditAction.READ,
                resource_type="optimization_run",
            )
            audit_service.log(
                action=AuditAction.DELETE,
                resource_type="webhook",
            )

            # Filter by action
            results, total = audit_service.query(action=AuditAction.CREATE)
            assert total == 1
            assert results[0].action == AuditAction.CREATE

            # Filter by resource type
            results, total = audit_service.query(resource_type="webhook")
            assert total == 1
            assert results[0].resource_type == "webhook"

    def test_query_with_time_range(self, app, audit_service):
        """Test that query() filters by time range."""
        with app.app_context():
            # Create a log
            audit_service.log(
                action=AuditAction.CREATE,
                resource_type="test",
            )

            now = datetime.now(timezone.utc)
            yesterday = now - timedelta(days=1)
            tomorrow = now + timedelta(days=1)

            # Should find the log within range
            results, total = audit_service.query(
                start_time=yesterday,
                end_time=tomorrow,
            )
            assert total == 1

            # Should not find the log before yesterday
            results, total = audit_service.query(
                start_time=now - timedelta(days=3),
                end_time=yesterday,
            )
            assert total == 0

    def test_query_pagination(self, app, audit_service):
        """Test that query() supports pagination."""
        with app.app_context():
            # Create 10 logs
            for i in range(10):
                audit_service.log(
                    action=AuditAction.READ,
                    resource_type="test",
                    resource_id=f"id-{i}",
                )

            # Get first page
            results, total = audit_service.query(limit=3, offset=0)
            assert total == 10
            assert len(results) == 3

            # Get second page
            results, total = audit_service.query(limit=3, offset=3)
            assert len(results) == 3

            # Get last page
            results, total = audit_service.query(limit=3, offset=9)
            assert len(results) == 1

    def test_get_by_id(self, app, audit_service):
        """Test that get_by_id() returns the correct log."""
        with app.app_context():
            created = audit_service.log(
                action=AuditAction.UPDATE,
                resource_type="test",
            )

            retrieved = audit_service.get_by_id(created.id)

            assert retrieved is not None
            assert retrieved.id == created.id
            assert retrieved.action == AuditAction.UPDATE

    def test_get_by_id_not_found(self, app, audit_service):
        """Test that get_by_id() returns None for non-existent ID."""
        with app.app_context():
            result = audit_service.get_by_id("non-existent-id")
            assert result is None

    def test_export_csv(self, app, audit_service):
        """Test that export_csv() generates valid CSV."""
        with app.app_context():
            audit_service.log(
                action=AuditAction.CREATE,
                resource_type="optimization_run",
                resource_id="run-123",
                details={"key": "value"},
            )

            csv_data = audit_service.export_csv()

            assert "id" in csv_data
            assert "timestamp" in csv_data
            assert "action" in csv_data
            assert "create" in csv_data
            assert "optimization_run" in csv_data
            assert "run-123" in csv_data

    def test_export_json(self, app, audit_service):
        """Test that export_json() generates valid JSON list."""
        with app.app_context():
            audit_service.log(
                action=AuditAction.DELETE,
                resource_type="webhook",
                resource_id="wh-456",
            )

            json_data = audit_service.export_json()

            assert isinstance(json_data, list)
            assert len(json_data) == 1
            assert json_data[0]["action"] == "delete"
            assert json_data[0]["resource_type"] == "webhook"
            assert json_data[0]["resource_id"] == "wh-456"

    def test_cleanup_old_logs(self, app):
        """Test that cleanup_old_logs() removes old entries."""
        with app.app_context():
            service = create_audit_service(enabled=True, retention_days=30)

            # Create an old log manually
            old_log = AuditLog(
                action=AuditAction.READ,
                resource_type="test",
                timestamp=datetime.now(timezone.utc) - timedelta(days=60),
            )
            db.session.add(old_log)
            db.session.commit()

            # Create a recent log
            service.log(action=AuditAction.READ, resource_type="test")

            # Clean up old logs
            deleted = service.cleanup_old_logs()

            assert deleted == 1

            # Verify only recent log remains
            _, total = service.query()
            assert total == 1


class TestAuditDecorator:
    """Tests for audit_action decorator."""

    def test_decorator_logs_action(self, app):
        """Test that decorator logs the action."""
        with app.app_context():
            service = create_audit_service(enabled=True)

            @audit_action(AuditAction.CREATE, "test_resource")
            def test_endpoint():
                return {"status": "ok"}, 200

            with patch("kubeopt_ai.core.audit.get_audit_service", return_value=service):
                result = test_endpoint()

            assert result == ({"status": "ok"}, 200)

            # Check that log was created
            logs, total = service.query(
                action=AuditAction.CREATE,
                resource_type="test_resource",
            )
            assert total == 1

    def test_decorator_extracts_resource_id(self, app):
        """Test that decorator can extract resource ID from response."""
        with app.app_context():
            service = create_audit_service(enabled=True)

            def extract_id(result, *args, **kwargs):
                if isinstance(result, tuple):
                    return result[0].get("id")
                return None

            @audit_action(
                AuditAction.CREATE,
                "test_resource",
                get_resource_id=extract_id,
            )
            def test_endpoint():
                return {"id": "resource-789", "status": "created"}, 201

            with patch("kubeopt_ai.core.audit.get_audit_service", return_value=service):
                test_endpoint()

            logs, _ = service.query(resource_type="test_resource")
            assert logs[0].resource_id == "resource-789"


class TestAuditAPI:
    """Tests for audit API endpoints."""

    def test_list_audit_logs(self, client, app):
        """Test GET /api/v1/audit/logs endpoint."""
        with app.app_context():
            service = create_audit_service(enabled=True)
            service.log(
                action=AuditAction.CREATE,
                resource_type="optimization_run",
            )

        response = client.get("/api/v1/audit/logs")

        assert response.status_code == 200
        data = response.get_json()
        assert "logs" in data
        assert "pagination" in data
        assert len(data["logs"]) >= 1

    def test_list_audit_logs_with_filters(self, client, app):
        """Test GET /api/v1/audit/logs with query filters."""
        with app.app_context():
            service = create_audit_service(enabled=True)
            service.log(action=AuditAction.CREATE, resource_type="type_a")
            service.log(action=AuditAction.READ, resource_type="type_b")

        response = client.get("/api/v1/audit/logs?action=create")

        assert response.status_code == 200
        data = response.get_json()
        assert len(data["logs"]) == 1
        assert data["logs"][0]["action"] == "create"

    def test_get_audit_log_by_id(self, client, app):
        """Test GET /api/v1/audit/logs/<id> endpoint."""
        with app.app_context():
            service = create_audit_service(enabled=True)
            log = service.log(
                action=AuditAction.UPDATE,
                resource_type="webhook",
            )
            log_id = log.id

        response = client.get(f"/api/v1/audit/logs/{log_id}")

        assert response.status_code == 200
        data = response.get_json()
        assert data["id"] == log_id
        assert data["action"] == "update"

    def test_get_audit_log_not_found(self, client):
        """Test GET /api/v1/audit/logs/<id> with non-existent ID."""
        response = client.get("/api/v1/audit/logs/non-existent-id")

        assert response.status_code == 404
        data = response.get_json()
        assert data["code"] == "NOT_FOUND"

    def test_export_audit_logs_json(self, client, app):
        """Test GET /api/v1/audit/logs/export with JSON format."""
        with app.app_context():
            service = create_audit_service(enabled=True)
            service.log(action=AuditAction.DELETE, resource_type="test")

        response = client.get("/api/v1/audit/logs/export?format=json")

        assert response.status_code == 200
        data = response.get_json()
        assert "logs" in data
        assert "count" in data

    def test_export_audit_logs_csv(self, client, app):
        """Test GET /api/v1/audit/logs/export with CSV format."""
        with app.app_context():
            service = create_audit_service(enabled=True)
            service.log(action=AuditAction.CREATE, resource_type="test")

        response = client.get("/api/v1/audit/logs/export?format=csv")

        assert response.status_code == 200
        assert response.content_type == "text/csv; charset=utf-8"
        assert b"id" in response.data
        assert b"create" in response.data

    def test_list_audit_actions(self, client):
        """Test GET /api/v1/audit/actions endpoint."""
        response = client.get("/api/v1/audit/actions")

        assert response.status_code == 200
        data = response.get_json()
        assert "actions" in data
        assert "create" in data["actions"]
        assert "delete" in data["actions"]
        assert "read" in data["actions"]

    def test_get_audit_stats(self, client, app):
        """Test GET /api/v1/audit/stats endpoint."""
        with app.app_context():
            service = create_audit_service(enabled=True)
            service.log(action=AuditAction.CREATE, resource_type="run")
            service.log(action=AuditAction.CREATE, resource_type="run")
            service.log(action=AuditAction.READ, resource_type="webhook")

        response = client.get("/api/v1/audit/stats")

        assert response.status_code == 200
        data = response.get_json()
        assert data["total_logs"] == 3
        assert "by_action" in data
        assert "by_resource_type" in data


class TestAuditLogModel:
    """Tests for AuditLog model."""

    def test_to_dict(self, app):
        """Test AuditLog.to_dict() method."""
        with app.app_context():
            log = AuditLog(
                action=AuditAction.CREATE,
                resource_type="test",
                resource_id="123",
                user_id="user-456",
                ip_address="10.0.0.1",
                details={"key": "value"},
            )
            db.session.add(log)
            db.session.commit()

            result = log.to_dict()

            assert result["id"] == log.id
            assert result["action"] == "create"
            assert result["resource_type"] == "test"
            assert result["resource_id"] == "123"
            assert result["user_id"] == "user-456"
            assert result["ip_address"] == "10.0.0.1"
            assert result["details"] == {"key": "value"}

    def test_repr(self, app):
        """Test AuditLog.__repr__() method."""
        with app.app_context():
            log = AuditLog(
                action=AuditAction.UPDATE,
                resource_type="webhook",
            )

            repr_str = repr(log)

            assert "AuditLog" in repr_str
            assert "action=AuditAction.UPDATE" in repr_str
            assert "resource=webhook" in repr_str
