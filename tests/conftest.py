"""
Shared pytest fixtures for KubeOpt AI tests.
"""

import pytest
from pathlib import Path

from kubeopt_ai.app import create_app
from kubeopt_ai.config import TestConfig
from kubeopt_ai.extensions import db


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "manifests"


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
def db_session(app):
    """Provide database session for tests."""
    with app.app_context():
        yield db.session
        db.session.rollback()


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture
def app_context(app):
    """Provide Flask application context."""
    with app.app_context():
        yield


@pytest.fixture
def optimization_run(client):
    """
    Create an optimization run and return its run_id.

    This fixture creates a complete optimization run using the test fixtures,
    which can then be used for insights API testing.
    """
    response = client.post(
        "/api/v1/optimize/run",
        json={"manifest_path": str(FIXTURES_DIR)},
    )
    assert response.status_code == 202
    data = response.get_json()
    return data["run_id"]


@pytest.fixture
def sample_workload_data():
    """Sample workload data for mocking."""
    return {
        "workload_name": "test-deployment",
        "namespace": "default",
        "kind": "Deployment",
        "replicas": 3,
        "containers": [
            {
                "name": "main",
                "cpu_request": "100m",
                "cpu_limit": "500m",
                "memory_request": "128Mi",
                "memory_limit": "512Mi",
            }
        ],
    }


@pytest.fixture
def sample_metrics_data():
    """Sample metrics data for mocking."""
    return {
        "cpu_avg": 0.15,
        "cpu_max": 0.45,
        "memory_avg": 256 * 1024 * 1024,  # 256 MiB in bytes
        "memory_max": 400 * 1024 * 1024,  # 400 MiB in bytes
    }
