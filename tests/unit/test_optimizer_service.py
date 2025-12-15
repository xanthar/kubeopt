"""
Unit tests for the optimizer service.
"""

import pytest
from pathlib import Path

from kubeopt_ai.app import create_app
from kubeopt_ai.config import TestConfig
from kubeopt_ai.extensions import db
from kubeopt_ai.core.optimizer_service import (
    OptimizerService,
    OptimizationError,
    create_optimizer_service,
)
from kubeopt_ai.core.models import (
    OptimizationRun,
    WorkloadSnapshot,
    Suggestion,
    RunStatus,
)


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


@pytest.fixture
def optimizer_service(app):
    """Create optimizer service for testing."""
    with app.app_context():
        return OptimizerService(use_mock_llm=True)


class TestOptimizerService:
    """Tests for OptimizerService."""

    def test_run_optimization_success(self, app, optimizer_service):
        """Test successful optimization run."""
        with app.app_context():
            run = optimizer_service.run_optimization(
                manifest_path=str(FIXTURES_DIR),
                lookback_days=7,
                skip_metrics=True,
            )

            assert run.id is not None
            assert run.status == RunStatus.COMPLETED
            assert run.manifest_source_path == str(FIXTURES_DIR)
            assert run.lookback_days == 7
            assert run.error_message is None

    def test_run_optimization_creates_snapshots(self, app, optimizer_service):
        """Test that optimization creates workload snapshots."""
        with app.app_context():
            run = optimizer_service.run_optimization(
                manifest_path=str(FIXTURES_DIR),
                lookback_days=7,
                skip_metrics=True,
            )

            snapshots = WorkloadSnapshot.query.filter_by(run_id=run.id).all()

            # Should have snapshots for each workload in fixtures
            assert len(snapshots) >= 4  # deployment, statefulset, daemonset, api-server

            # Verify snapshot details
            web_app = next(
                (s for s in snapshots if s.name == "web-app"),
                None
            )
            assert web_app is not None
            assert web_app.namespace == "production"
            assert web_app.kind.value == "Deployment"

    def test_run_optimization_creates_suggestions(self, app, optimizer_service):
        """Test that optimization creates suggestions."""
        with app.app_context():
            run = optimizer_service.run_optimization(
                manifest_path=str(FIXTURES_DIR),
                lookback_days=7,
                skip_metrics=True,
            )

            # Get all suggestions for this run
            snapshot_ids = [
                s.id for s in WorkloadSnapshot.query.filter_by(run_id=run.id).all()
            ]
            suggestions = Suggestion.query.filter(
                Suggestion.workload_snapshot_id.in_(snapshot_ids)
            ).all()

            # Should have at least one suggestion per workload
            assert len(suggestions) >= 4

    def test_run_optimization_invalid_path(self, app, optimizer_service):
        """Test optimization with invalid manifest path."""
        with app.app_context():
            with pytest.raises(OptimizationError) as exc_info:
                optimizer_service.run_optimization(
                    manifest_path="/nonexistent/path",
                    lookback_days=7,
                    skip_metrics=True,
                )

            assert "Failed to scan manifests" in str(exc_info.value)

            # Run should be marked as failed
            runs = OptimizationRun.query.filter_by(status=RunStatus.FAILED).all()
            assert len(runs) == 1

    def test_run_optimization_single_file(self, app, optimizer_service):
        """Test optimization with single manifest file."""
        with app.app_context():
            manifest_file = FIXTURES_DIR / "deployment.yaml"
            run = optimizer_service.run_optimization(
                manifest_path=str(manifest_file),
                lookback_days=14,
                skip_metrics=True,
            )

            assert run.status == RunStatus.COMPLETED
            assert run.lookback_days == 14

            snapshots = WorkloadSnapshot.query.filter_by(run_id=run.id).all()
            assert len(snapshots) == 1
            assert snapshots[0].name == "web-app"

    def test_get_run_details(self, app, optimizer_service):
        """Test retrieving run details."""
        with app.app_context():
            run = optimizer_service.run_optimization(
                manifest_path=str(FIXTURES_DIR),
                lookback_days=7,
                skip_metrics=True,
            )

            details = optimizer_service.get_run_details(run.id)

            assert details is not None
            assert details["run"]["id"] == run.id
            assert details["run"]["status"] == "completed"
            assert len(details["workloads"]) >= 4
            assert len(details["suggestions"]) >= 4
            assert details["summary"]["workload_count"] >= 4
            assert details["summary"]["suggestion_count"] >= 4

    def test_get_run_details_not_found(self, app, optimizer_service):
        """Test get_run_details with non-existent run."""
        with app.app_context():
            details = optimizer_service.get_run_details("nonexistent-id")
            assert details is None


class TestCreateOptimizerService:
    """Tests for create_optimizer_service factory."""

    def test_create_with_config(self, app):
        """Test creating service with configuration."""
        with app.app_context():
            config = {
                "PROMETHEUS_BASE_URL": "http://prometheus:9090",
                "LLM_API_KEY": "test-key",
                "LLM_MODEL_NAME": "claude-sonnet-4-20250514",
            }

            service = create_optimizer_service(config)

            assert service._llm_client is not None

    def test_create_with_mock_llm(self, app):
        """Test creating service with mock LLM."""
        with app.app_context():
            service = create_optimizer_service(use_mock_llm=True)

            assert service._llm_client is not None

    def test_create_without_llm_key(self, app):
        """Test creating service without LLM API key."""
        with app.app_context():
            service = create_optimizer_service(app_config={})

            assert service._llm_client is None
