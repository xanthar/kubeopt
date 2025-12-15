"""
API integration tests for KubeOpt AI.
"""

import pytest
from pathlib import Path

from kubeopt_ai.app import create_app
from kubeopt_ai.config import TestConfig
from kubeopt_ai.extensions import db


# Get path to test fixtures
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "manifests"


@pytest.fixture
def app():
    """Create Flask test application."""
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


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    def test_health_endpoint(self, client):
        """Test basic health endpoint."""
        response = client.get("/api/v1/health")

        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "healthy"
        assert data["service"] == "kubeopt-ai"

    def test_liveness_endpoint(self, client):
        """Test liveness probe endpoint."""
        response = client.get("/api/v1/health/live")

        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "alive"

    def test_readiness_endpoint(self, client):
        """Test readiness probe endpoint."""
        response = client.get("/api/v1/health/ready")

        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "ready"
        assert "database" in data["checks"]


class TestOptimizationEndpoints:
    """Tests for optimization API endpoints."""

    def test_create_optimization_run(self, client):
        """Test creating an optimization run."""
        response = client.post(
            "/api/v1/optimize/run",
            json={
                "manifest_path": str(FIXTURES_DIR),
                "lookback_days": 7,
            },
        )

        assert response.status_code == 202
        data = response.get_json()
        assert "run_id" in data
        assert data["status"] == "completed"
        assert data["lookback_days"] == 7
        assert "summary" in data

    def test_create_optimization_run_default_lookback(self, client):
        """Test creating optimization run with default lookback."""
        response = client.post(
            "/api/v1/optimize/run",
            json={"manifest_path": str(FIXTURES_DIR)},
        )

        assert response.status_code == 202
        data = response.get_json()
        assert data["lookback_days"] == 7  # Default value

    def test_create_optimization_run_missing_path(self, client):
        """Test creating optimization run without manifest path."""
        response = client.post(
            "/api/v1/optimize/run",
            json={},
        )

        assert response.status_code == 400
        data = response.get_json()
        assert data["code"] == "VALIDATION_ERROR"

    def test_create_optimization_run_invalid_path(self, client):
        """Test creating optimization run with invalid path."""
        response = client.post(
            "/api/v1/optimize/run",
            json={"manifest_path": "/nonexistent/path"},
        )

        assert response.status_code == 500
        data = response.get_json()
        assert data["code"] == "OPTIMIZATION_ERROR"

    def test_get_optimization_run(self, client):
        """Test retrieving an optimization run."""
        # First create a run
        create_response = client.post(
            "/api/v1/optimize/run",
            json={"manifest_path": str(FIXTURES_DIR)},
        )
        run_id = create_response.get_json()["run_id"]

        # Then retrieve it
        response = client.get(f"/api/v1/optimize/run/{run_id}")

        assert response.status_code == 200
        data = response.get_json()
        assert data["run"]["id"] == run_id
        assert data["run"]["status"] == "completed"
        assert len(data["workloads"]) >= 4
        assert len(data["suggestions"]) >= 4

    def test_get_optimization_run_not_found(self, client):
        """Test retrieving non-existent run."""
        response = client.get("/api/v1/optimize/run/nonexistent-id")

        assert response.status_code == 404
        data = response.get_json()
        assert data["code"] == "NOT_FOUND"

    def test_list_optimization_runs(self, client):
        """Test listing optimization runs."""
        # Create a few runs
        for _ in range(3):
            client.post(
                "/api/v1/optimize/run",
                json={"manifest_path": str(FIXTURES_DIR)},
            )

        response = client.get("/api/v1/optimize/runs")

        assert response.status_code == 200
        data = response.get_json()
        assert len(data["runs"]) == 3
        assert data["total"] == 3

    def test_list_optimization_runs_with_pagination(self, client):
        """Test listing runs with pagination."""
        # Create runs
        for _ in range(5):
            client.post(
                "/api/v1/optimize/run",
                json={"manifest_path": str(FIXTURES_DIR)},
            )

        # Get first page
        response = client.get("/api/v1/optimize/runs?limit=2&offset=0")
        data = response.get_json()

        assert len(data["runs"]) == 2
        assert data["total"] == 5
        assert data["limit"] == 2
        assert data["offset"] == 0

        # Get second page
        response = client.get("/api/v1/optimize/runs?limit=2&offset=2")
        data = response.get_json()

        assert len(data["runs"]) == 2
        assert data["offset"] == 2

    def test_list_optimization_runs_empty(self, client):
        """Test listing runs when none exist."""
        response = client.get("/api/v1/optimize/runs")

        assert response.status_code == 200
        data = response.get_json()
        assert data["runs"] == []
        assert data["total"] == 0


class TestErrorHandling:
    """Tests for error handling."""

    def test_404_handler(self, client):
        """Test 404 error handler."""
        response = client.get("/api/v1/nonexistent")

        assert response.status_code == 404
        data = response.get_json()
        assert data["code"] == "NOT_FOUND"

    def test_bad_request_json(self, client):
        """Test bad request with invalid JSON."""
        response = client.post(
            "/api/v1/optimize/run",
            data="not json",
            content_type="application/json",
        )

        # Should handle gracefully (empty dict)
        assert response.status_code == 400
