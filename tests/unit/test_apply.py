"""
Unit tests for recommendation auto-apply feature (F022).

Tests cover:
- GuardrailService: Resource change validation, blackout windows, exclusions
- K8sApplyService: Patch building, apply operations (mocked K8s client)
- ApplyService: Request lifecycle, approval workflow, rollback
- Apply API routes: Policy CRUD, request operations
"""

import pytest
from unittest.mock import patch, Mock, MagicMock
from datetime import datetime, timezone, timedelta
from freezegun import freeze_time

from kubeopt_ai.core.models import (
    ApplyPolicy,
    ApplyRequest,
    ApplyBatch,
    ApplyMode,
    ApplyRequestStatus,
    GuardrailCheckStatus,
    Cluster,
    ClusterStatus,
    ClusterProvider,
    Suggestion,
    WorkloadSnapshot,
    WorkloadKind,
    OptimizationRun,
    RunStatus,
)
from kubeopt_ai.core.guardrails import (
    GuardrailService,
    GuardrailCheckResult,
    parse_k8s_resource,
    calculate_percent_change,
)
from kubeopt_ai.core.k8s_apply import (
    K8sApplyService,
    K8sApplyError,
    K8sConnectionError,
    K8sResourceNotFoundError,
    ApplyResult,
    ResourcePatch,
)
from kubeopt_ai.core.apply_service import (
    ApplyService,
    ApplyServiceError,
    ApplyRequestNotFoundError,
    InvalidApplyStateError,
)


# =============================================================================
# Resource Parsing Tests
# =============================================================================

class TestResourceParsing:
    """Tests for Kubernetes resource string parsing."""

    def test_parse_cpu_millicores(self):
        """Test parsing CPU in millicores."""
        assert parse_k8s_resource("100m") == 0.1
        assert parse_k8s_resource("500m") == 0.5
        assert parse_k8s_resource("1000m") == 1.0
        assert parse_k8s_resource("2500m") == 2.5

    def test_parse_cpu_cores(self):
        """Test parsing CPU in whole cores."""
        assert parse_k8s_resource("1") == 1.0
        assert parse_k8s_resource("2") == 2.0
        assert parse_k8s_resource("0.5") == 0.5

    def test_parse_memory_mi(self):
        """Test parsing memory in MiB."""
        assert parse_k8s_resource("128Mi") == 128 * 1024 ** 2
        assert parse_k8s_resource("256Mi") == 256 * 1024 ** 2
        assert parse_k8s_resource("1024Mi") == 1024 * 1024 ** 2

    def test_parse_memory_gi(self):
        """Test parsing memory in GiB."""
        assert parse_k8s_resource("1Gi") == 1024 ** 3
        assert parse_k8s_resource("2Gi") == 2 * 1024 ** 3

    def test_parse_memory_ki(self):
        """Test parsing memory in KiB."""
        assert parse_k8s_resource("1024Ki") == 1024 * 1024

    def test_parse_memory_decimal_units(self):
        """Test parsing memory with decimal units (KB, MB, GB)."""
        assert parse_k8s_resource("1000K") == 1000 * 1000
        assert parse_k8s_resource("100M") == 100 * 1000 ** 2
        assert parse_k8s_resource("1G") == 1000 ** 3

    def test_parse_zero(self):
        """Test parsing zero value."""
        assert parse_k8s_resource("0") == 0.0
        assert parse_k8s_resource("") == 0.0
        assert parse_k8s_resource(None) == 0.0

    def test_parse_invalid_returns_zero(self):
        """Test parsing invalid value returns 0."""
        assert parse_k8s_resource("invalid") == 0.0


class TestPercentChangeCalculation:
    """Tests for percentage change calculation."""

    def test_calculate_increase(self):
        """Test calculating percentage increase."""
        assert calculate_percent_change(100, 150) == 50.0
        assert calculate_percent_change(100, 200) == 100.0

    def test_calculate_decrease(self):
        """Test calculating percentage decrease."""
        assert calculate_percent_change(100, 50) == -50.0
        assert calculate_percent_change(200, 100) == -50.0

    def test_calculate_no_change(self):
        """Test calculating no change."""
        assert calculate_percent_change(100, 100) == 0.0

    def test_calculate_from_zero(self):
        """Test calculating change from zero."""
        assert calculate_percent_change(0, 100) == 100.0
        assert calculate_percent_change(0, 0) == 0.0


# =============================================================================
# GuardrailService Tests
# =============================================================================

class TestGuardrailService:
    """Tests for GuardrailService."""

    @pytest.fixture
    def guardrail_service(self):
        """Create a GuardrailService instance."""
        return GuardrailService()

    @pytest.fixture
    def default_policy(self, app, db_session):
        """Create a default apply policy."""
        policy = ApplyPolicy(
            name="test-policy",
            require_approval=True,
            auto_approve_below_threshold=True,
            approval_threshold_cpu_percent=20.0,
            approval_threshold_memory_percent=20.0,
            max_cpu_increase_percent=200.0,
            max_cpu_decrease_percent=50.0,
            max_memory_increase_percent=200.0,
            max_memory_decrease_percent=50.0,
            min_cpu_request="10m",
            min_memory_request="32Mi",
            blackout_windows=[],
            excluded_namespaces=["kube-system", "kube-public"],
            excluded_workload_patterns=[".*-canary$", "test-.*"],
        )
        db_session.add(policy)
        db_session.commit()
        return policy

    def test_check_cpu_request_increase_within_limit(self, guardrail_service, default_policy):
        """Test CPU request increase within limit passes."""
        current = {"requests": {"cpu": "100m"}}
        proposed = {"requests": {"cpu": "200m"}}

        result = guardrail_service.check_cpu_request_change(
            current, proposed, default_policy
        )

        assert result.status == GuardrailCheckStatus.PASSED
        assert "100.0%" in result.message

    def test_check_cpu_request_increase_exceeds_limit(self, guardrail_service, default_policy):
        """Test CPU request increase exceeding limit fails."""
        current = {"requests": {"cpu": "100m"}}
        proposed = {"requests": {"cpu": "500m"}}  # 400% increase

        result = guardrail_service.check_cpu_request_change(
            current, proposed, default_policy
        )

        assert result.status == GuardrailCheckStatus.FAILED
        assert "exceeds limit" in result.message

    def test_check_cpu_request_decrease_within_limit(self, guardrail_service, default_policy):
        """Test CPU request decrease within limit passes."""
        current = {"requests": {"cpu": "200m"}}
        proposed = {"requests": {"cpu": "150m"}}  # 25% decrease

        result = guardrail_service.check_cpu_request_change(
            current, proposed, default_policy
        )

        assert result.status == GuardrailCheckStatus.PASSED

    def test_check_cpu_request_decrease_exceeds_limit(self, guardrail_service, default_policy):
        """Test CPU request decrease exceeding limit fails."""
        current = {"requests": {"cpu": "200m"}}
        proposed = {"requests": {"cpu": "50m"}}  # 75% decrease

        result = guardrail_service.check_cpu_request_change(
            current, proposed, default_policy
        )

        assert result.status == GuardrailCheckStatus.FAILED
        assert "exceeds limit" in result.message

    def test_check_memory_request_within_limit(self, guardrail_service, default_policy):
        """Test memory request change within limits passes."""
        current = {"requests": {"memory": "128Mi"}}
        proposed = {"requests": {"memory": "256Mi"}}  # 100% increase

        result = guardrail_service.check_memory_request_change(
            current, proposed, default_policy
        )

        assert result.status == GuardrailCheckStatus.PASSED

    def test_check_minimum_cpu_passes(self, guardrail_service, default_policy):
        """Test proposed CPU above minimum passes."""
        proposed = {"requests": {"cpu": "50m"}}

        result = guardrail_service.check_minimum_cpu(proposed, default_policy)

        assert result.status == GuardrailCheckStatus.PASSED

    def test_check_minimum_cpu_fails(self, guardrail_service, default_policy):
        """Test proposed CPU below minimum fails."""
        proposed = {"requests": {"cpu": "5m"}}  # Below 10m minimum

        result = guardrail_service.check_minimum_cpu(proposed, default_policy)

        assert result.status == GuardrailCheckStatus.FAILED
        assert "below minimum" in result.message

    def test_check_minimum_memory_passes(self, guardrail_service, default_policy):
        """Test proposed memory above minimum passes."""
        proposed = {"requests": {"memory": "64Mi"}}

        result = guardrail_service.check_minimum_memory(proposed, default_policy)

        assert result.status == GuardrailCheckStatus.PASSED

    def test_check_minimum_memory_fails(self, guardrail_service, default_policy):
        """Test proposed memory below minimum fails."""
        proposed = {"requests": {"memory": "16Mi"}}  # Below 32Mi minimum

        result = guardrail_service.check_minimum_memory(proposed, default_policy)

        assert result.status == GuardrailCheckStatus.FAILED

    @freeze_time("2025-01-15 14:30:00")  # Wednesday at 14:30 UTC
    def test_check_blackout_window_inside(self, guardrail_service, app, db_session):
        """Test check fails when inside blackout window."""
        policy = ApplyPolicy(
            name="blackout-policy",
            blackout_windows=[
                {"day_of_week": 2, "start_time": "14:00", "end_time": "15:00"}  # Wednesday
            ],
            excluded_namespaces=[],
            excluded_workload_patterns=[],
        )
        db_session.add(policy)
        db_session.commit()

        result = guardrail_service.check_blackout_window(policy)

        assert result.status == GuardrailCheckStatus.FAILED
        assert "blackout window" in result.message.lower()

    @freeze_time("2025-01-15 16:00:00")  # Wednesday at 16:00 UTC
    def test_check_blackout_window_outside(self, guardrail_service, app, db_session):
        """Test check passes when outside blackout window."""
        policy = ApplyPolicy(
            name="blackout-policy",
            blackout_windows=[
                {"day_of_week": 2, "start_time": "14:00", "end_time": "15:00"}
            ],
            excluded_namespaces=[],
            excluded_workload_patterns=[],
        )
        db_session.add(policy)
        db_session.commit()

        result = guardrail_service.check_blackout_window(policy)

        assert result.status == GuardrailCheckStatus.PASSED

    def test_check_namespace_exclusions_excluded(self, guardrail_service, default_policy):
        """Test excluded namespace fails."""
        result = guardrail_service.check_namespace_exclusions(
            "kube-system", default_policy
        )

        assert result.status == GuardrailCheckStatus.FAILED
        assert "excluded" in result.message

    def test_check_namespace_exclusions_not_excluded(self, guardrail_service, default_policy):
        """Test non-excluded namespace passes."""
        result = guardrail_service.check_namespace_exclusions(
            "production", default_policy
        )

        assert result.status == GuardrailCheckStatus.PASSED

    def test_check_workload_exclusions_matching_pattern(self, guardrail_service, default_policy):
        """Test workload matching exclusion pattern fails."""
        result = guardrail_service.check_workload_exclusions(
            "my-app-canary", default_policy
        )

        assert result.status == GuardrailCheckStatus.FAILED
        assert "matches exclusion pattern" in result.message

    def test_check_workload_exclusions_test_prefix(self, guardrail_service, default_policy):
        """Test workload with test- prefix fails."""
        result = guardrail_service.check_workload_exclusions(
            "test-deployment", default_policy
        )

        assert result.status == GuardrailCheckStatus.FAILED

    def test_check_workload_exclusions_no_match(self, guardrail_service, default_policy):
        """Test workload not matching exclusion pattern passes."""
        result = guardrail_service.check_workload_exclusions(
            "production-app", default_policy
        )

        assert result.status == GuardrailCheckStatus.PASSED

    def test_should_auto_approve_small_change(self, guardrail_service, app, db_session):
        """Test small change qualifies for auto-approval."""
        policy = ApplyPolicy(
            name="auto-approve-policy",
            auto_approve_below_threshold=True,
            approval_threshold_cpu_percent=20.0,
            approval_threshold_memory_percent=20.0,
            excluded_namespaces=[],
            excluded_workload_patterns=[],
        )
        db_session.add(policy)
        db_session.commit()

        # Create mock suggestion with small change
        suggestion = Mock()
        suggestion.suggestion_type = "resources"
        suggestion.current_config = {
            "requests": {"cpu": "100m", "memory": "128Mi"}
        }
        suggestion.proposed_config = {
            "requests": {"cpu": "110m", "memory": "140Mi"}  # 10% changes
        }

        result = guardrail_service.should_auto_approve(suggestion, policy)

        assert result is True

    def test_should_auto_approve_large_change_rejected(self, guardrail_service, app, db_session):
        """Test large change does not qualify for auto-approval."""
        policy = ApplyPolicy(
            name="auto-approve-policy",
            auto_approve_below_threshold=True,
            approval_threshold_cpu_percent=20.0,
            approval_threshold_memory_percent=20.0,
            excluded_namespaces=[],
            excluded_workload_patterns=[],
        )
        db_session.add(policy)
        db_session.commit()

        # Create mock suggestion with large change
        suggestion = Mock()
        suggestion.suggestion_type = "resources"
        suggestion.current_config = {
            "requests": {"cpu": "100m", "memory": "128Mi"}
        }
        suggestion.proposed_config = {
            "requests": {"cpu": "200m", "memory": "128Mi"}  # 100% CPU change
        }

        result = guardrail_service.should_auto_approve(suggestion, policy)

        assert result is False

    def test_should_auto_approve_hpa_always_requires_approval(self, guardrail_service, app, db_session):
        """Test HPA suggestions always require approval."""
        policy = ApplyPolicy(
            name="auto-approve-policy",
            auto_approve_below_threshold=True,
            approval_threshold_cpu_percent=100.0,  # Very high threshold
            excluded_namespaces=[],
            excluded_workload_patterns=[],
        )
        db_session.add(policy)
        db_session.commit()

        suggestion = Mock()
        suggestion.suggestion_type = "hpa"

        result = guardrail_service.should_auto_approve(suggestion, policy)

        assert result is False

    def test_has_any_failure_with_failure(self, guardrail_service):
        """Test has_any_failure returns True when failure exists."""
        results = [
            GuardrailCheckResult("check1", GuardrailCheckStatus.PASSED, "OK"),
            GuardrailCheckResult("check2", GuardrailCheckStatus.FAILED, "Failed"),
            GuardrailCheckResult("check3", GuardrailCheckStatus.PASSED, "OK"),
        ]

        assert guardrail_service.has_any_failure(results) is True

    def test_has_any_failure_all_pass(self, guardrail_service):
        """Test has_any_failure returns False when all pass."""
        results = [
            GuardrailCheckResult("check1", GuardrailCheckStatus.PASSED, "OK"),
            GuardrailCheckResult("check2", GuardrailCheckStatus.PASSED, "OK"),
        ]

        assert guardrail_service.has_any_failure(results) is False

    def test_results_to_dict(self, guardrail_service):
        """Test conversion of results to dictionary."""
        results = [
            GuardrailCheckResult("check1", GuardrailCheckStatus.PASSED, "OK"),
            GuardrailCheckResult("check2", GuardrailCheckStatus.FAILED, "Failed"),
        ]

        result_dict = guardrail_service.results_to_dict(results)

        assert "checks" in result_dict
        assert len(result_dict["checks"]) == 2
        assert result_dict["all_passed"] is False
        assert result_dict["failed_count"] == 1


# =============================================================================
# K8sApplyService Tests
# =============================================================================

class TestK8sApplyService:
    """Tests for K8sApplyService."""

    @pytest.fixture
    def mock_cluster(self, app, db_session):
        """Create a mock cluster."""
        cluster = Cluster(
            name="test-cluster",
            provider=ClusterProvider.AWS,
            status=ClusterStatus.ACTIVE,
            kubeconfig="apiVersion: v1\nkind: Config\nclusters: []",
        )
        db_session.add(cluster)
        db_session.commit()
        return cluster

    @pytest.fixture
    def k8s_service(self, mock_cluster):
        """Create K8sApplyService with mock cluster."""
        return K8sApplyService(mock_cluster)

    @patch('kubeopt_ai.core.k8s_apply.K8sApplyService._get_api_client')
    def test_test_connection_success(self, mock_get_client, k8s_service):
        """Test successful connection test."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        with patch.object(k8s_service, '_get_core_v1') as mock_core:
            mock_core.return_value.get_api_resources.return_value = {}

            result = k8s_service.test_connection()

            assert result.success is True
            assert "Connected" in result.message

    @patch('kubeopt_ai.core.k8s_apply.K8sApplyService._get_api_client')
    def test_test_connection_failure(self, mock_get_client, k8s_service):
        """Test failed connection test."""
        mock_get_client.side_effect = K8sConnectionError("Connection failed")

        result = k8s_service.test_connection()

        assert result.success is False
        assert "failed" in result.message.lower()

    def test_build_patch_from_suggestion_resources(self, k8s_service):
        """Test building patch from resource suggestion."""
        # Create mock suggestion
        workload = Mock()
        workload.namespace = "default"
        workload.kind = WorkloadKind.DEPLOYMENT
        workload.name = "test-app"

        suggestion = Mock()
        suggestion.workload_snapshot = workload
        suggestion.suggestion_type = "resources"
        suggestion.container_name = "main"
        suggestion.proposed_config = {
            "requests": {"cpu": "200m", "memory": "256Mi"},
            "limits": {"cpu": "500m", "memory": "512Mi"},
        }

        patch = k8s_service.build_patch_from_suggestion(suggestion)

        assert isinstance(patch, ResourcePatch)
        assert patch.namespace == "default"
        assert patch.kind == "Deployment"
        assert patch.name == "test-app"
        assert patch.container_name == "main"
        assert "containers" in patch.patch["spec"]["template"]["spec"]

    @patch('kubeopt_ai.core.k8s_apply.K8sApplyService._get_apps_v1')
    def test_apply_patch_dry_run_success(self, mock_apps_v1, k8s_service):
        """Test successful dry-run patch."""
        mock_api = MagicMock()
        mock_apps_v1.return_value = mock_api

        # Mock successful patch
        mock_result = MagicMock()
        mock_result.metadata.resource_version = "12345"
        mock_api.patch_namespaced_deployment.return_value = mock_result

        patch = {"spec": {"template": {"spec": {"containers": []}}}}
        result = k8s_service.apply_patch(
            namespace="default",
            kind="deployment",
            name="test-app",
            patch=patch,
            dry_run=True
        )

        assert result.success is True
        assert result.dry_run is True
        assert "validated" in result.message.lower()
        mock_api.patch_namespaced_deployment.assert_called_once()

    @patch('kubeopt_ai.core.k8s_apply.K8sApplyService._get_apps_v1')
    def test_apply_patch_actual_apply_success(self, mock_apps_v1, k8s_service):
        """Test successful actual patch application."""
        mock_api = MagicMock()
        mock_apps_v1.return_value = mock_api

        mock_result = MagicMock()
        mock_result.metadata.resource_version = "12346"
        mock_api.patch_namespaced_deployment.return_value = mock_result

        patch = {"spec": {"template": {"spec": {"containers": []}}}}
        result = k8s_service.apply_patch(
            namespace="default",
            kind="deployment",
            name="test-app",
            patch=patch,
            dry_run=False
        )

        assert result.success is True
        assert result.dry_run is False
        assert "applied" in result.message.lower()

    @patch('kubeopt_ai.core.k8s_apply.K8sApplyService._get_apps_v1')
    def test_apply_patch_failure(self, mock_apps_v1, k8s_service):
        """Test patch application failure."""
        mock_api = MagicMock()
        mock_apps_v1.return_value = mock_api

        # Mock API exception
        from kubernetes.client.rest import ApiException
        mock_api.patch_namespaced_deployment.side_effect = ApiException(
            status=404, reason="Not Found"
        )

        patch = {"spec": {"template": {"spec": {"containers": []}}}}
        result = k8s_service.apply_patch(
            namespace="default",
            kind="deployment",
            name="test-app",
            patch=patch,
            dry_run=False
        )

        assert result.success is False
        assert "failed" in result.message.lower()

    @patch('kubeopt_ai.core.k8s_apply.K8sApplyService._get_apps_v1')
    def test_apply_patch_unsupported_kind(self, mock_apps_v1, k8s_service):
        """Test patch with unsupported resource kind."""
        mock_api = MagicMock()
        mock_apps_v1.return_value = mock_api

        patch = {"spec": {}}
        result = k8s_service.apply_patch(
            namespace="default",
            kind="unsupported",
            name="test",
            patch=patch,
            dry_run=True
        )

        assert result.success is False
        assert "Unsupported" in result.message

    @patch('kubeopt_ai.core.k8s_apply.K8sApplyService._get_apps_v1')
    def test_rollback_success(self, mock_apps_v1, k8s_service):
        """Test successful rollback."""
        mock_api = MagicMock()
        mock_apps_v1.return_value = mock_api

        mock_result = MagicMock()
        mock_result.metadata.resource_version = "12347"
        mock_api.patch_namespaced_deployment.return_value = mock_result

        previous_config = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": "main",
                                "resources": {
                                    "requests": {"cpu": "100m", "memory": "128Mi"}
                                }
                            }
                        ]
                    }
                }
            }
        }

        result = k8s_service.rollback(
            namespace="default",
            kind="deployment",
            name="test-app",
            previous_config=previous_config
        )

        assert result.success is True
        mock_api.patch_namespaced_deployment.assert_called_once()


# =============================================================================
# ApplyService Tests
# =============================================================================

class TestApplyService:
    """Tests for ApplyService."""

    @pytest.fixture
    def apply_service(self):
        """Create ApplyService instance."""
        return ApplyService()

    @pytest.fixture
    def test_cluster(self, app, db_session):
        """Create a test cluster."""
        cluster = Cluster(
            name="test-cluster",
            provider=ClusterProvider.AWS,
            status=ClusterStatus.ACTIVE,
        )
        db_session.add(cluster)
        db_session.commit()
        return cluster

    @pytest.fixture
    def test_suggestion(self, app, db_session, test_cluster):
        """Create a test suggestion with required dependencies."""
        # Create optimization run
        run = OptimizationRun(
            manifest_source_path="/test/path",
            lookback_days=7,
            status=RunStatus.COMPLETED,
        )
        db_session.add(run)
        db_session.flush()

        # Create workload snapshot
        workload = WorkloadSnapshot(
            run_id=run.id,
            name="test-deployment",
            namespace="default",
            kind=WorkloadKind.DEPLOYMENT,
            current_config={"replicas": 3},
        )
        db_session.add(workload)
        db_session.flush()

        # Create suggestion
        suggestion = Suggestion(
            workload_snapshot_id=workload.id,
            container_name="main",
            suggestion_type="resources",
            current_config={
                "requests": {"cpu": "100m", "memory": "128Mi"},
                "limits": {"cpu": "500m", "memory": "512Mi"},
            },
            proposed_config={
                "requests": {"cpu": "200m", "memory": "256Mi"},
                "limits": {"cpu": "1", "memory": "1Gi"},
            },
            reasoning="Test suggestion",
        )
        db_session.add(suggestion)
        db_session.commit()
        return suggestion

    def test_create_apply_request_dry_run(
        self, apply_service, app, db_session, test_suggestion, test_cluster
    ):
        """Test creating apply request in dry-run mode."""
        with app.app_context():
            request = apply_service.create_apply_request(
                suggestion_id=test_suggestion.id,
                cluster_id=test_cluster.id,
                mode=ApplyMode.DRY_RUN,
            )

            assert request.status == ApplyRequestStatus.APPROVED
            assert request.mode == ApplyMode.DRY_RUN
            assert request.requires_approval is False
            assert request.suggestion_id == test_suggestion.id
            assert request.cluster_id == test_cluster.id

    def test_create_apply_request_requires_approval(
        self, apply_service, app, db_session, test_suggestion, test_cluster
    ):
        """Test creating apply request that requires approval."""
        # Create policy requiring approval
        policy = ApplyPolicy(
            name="approval-policy",
            require_approval=True,
            auto_approve_below_threshold=False,
            excluded_namespaces=[],
            excluded_workload_patterns=[],
        )
        db_session.add(policy)
        db_session.commit()

        with app.app_context():
            request = apply_service.create_apply_request(
                suggestion_id=test_suggestion.id,
                cluster_id=test_cluster.id,
                mode=ApplyMode.APPLY,
            )

            assert request.status == ApplyRequestStatus.PENDING_APPROVAL
            assert request.requires_approval is True

    def test_create_apply_request_suggestion_not_found(
        self, apply_service, app, test_cluster
    ):
        """Test creating request with non-existent suggestion."""
        with app.app_context():
            with pytest.raises(ApplyServiceError, match="Suggestion not found"):
                apply_service.create_apply_request(
                    suggestion_id="non-existent-id",
                    cluster_id=test_cluster.id,
                    mode=ApplyMode.DRY_RUN,
                )

    def test_create_apply_request_cluster_not_found(
        self, apply_service, app, test_suggestion
    ):
        """Test creating request with non-existent cluster."""
        with app.app_context():
            with pytest.raises(ApplyServiceError, match="Cluster not found"):
                apply_service.create_apply_request(
                    suggestion_id=test_suggestion.id,
                    cluster_id="non-existent-id",
                    mode=ApplyMode.DRY_RUN,
                )

    def test_approve_request_success(
        self, apply_service, app, db_session, test_suggestion, test_cluster
    ):
        """Test approving a pending request."""
        # Create pending request
        request = ApplyRequest(
            suggestion_id=test_suggestion.id,
            cluster_id=test_cluster.id,
            mode=ApplyMode.APPLY,
            status=ApplyRequestStatus.PENDING_APPROVAL,
            requires_approval=True,
            proposed_config=test_suggestion.proposed_config,
        )
        db_session.add(request)
        db_session.commit()

        with app.app_context():
            result = apply_service.approve_request(request.id, "approver-123")

            assert result.status == ApplyRequestStatus.APPROVED
            assert result.approved_by_id == "approver-123"
            assert result.approved_at is not None

    def test_approve_request_wrong_status(
        self, apply_service, app, db_session, test_suggestion, test_cluster
    ):
        """Test approving request in wrong status fails."""
        request = ApplyRequest(
            suggestion_id=test_suggestion.id,
            cluster_id=test_cluster.id,
            mode=ApplyMode.APPLY,
            status=ApplyRequestStatus.COMPLETED,  # Already completed
            proposed_config=test_suggestion.proposed_config,
        )
        db_session.add(request)
        db_session.commit()

        with app.app_context():
            with pytest.raises(InvalidApplyStateError):
                apply_service.approve_request(request.id, "approver-123")

    def test_reject_request_success(
        self, apply_service, app, db_session, test_suggestion, test_cluster
    ):
        """Test rejecting a pending request."""
        request = ApplyRequest(
            suggestion_id=test_suggestion.id,
            cluster_id=test_cluster.id,
            mode=ApplyMode.APPLY,
            status=ApplyRequestStatus.PENDING_APPROVAL,
            proposed_config=test_suggestion.proposed_config,
        )
        db_session.add(request)
        db_session.commit()

        with app.app_context():
            result = apply_service.reject_request(
                request.id, "rejector-123", "Not approved by security team"
            )

            assert result.status == ApplyRequestStatus.REJECTED
            assert result.rejection_reason == "Not approved by security team"

    @patch('kubeopt_ai.core.apply_service.K8sApplyService')
    def test_execute_request_success(
        self, mock_k8s_service, apply_service, app, db_session, test_suggestion, test_cluster
    ):
        """Test executing an approved request."""
        # Setup mock K8s service
        mock_service_instance = MagicMock()
        mock_k8s_service.return_value = mock_service_instance
        mock_service_instance.build_patch_from_suggestion.return_value = ResourcePatch(
            namespace="default",
            kind="Deployment",
            name="test-app",
            patch={"spec": {}},
        )
        mock_service_instance.apply_patch.return_value = ApplyResult(
            success=True,
            message="Applied successfully",
            duration_ms=150,
        )

        # Create approved request
        request = ApplyRequest(
            suggestion_id=test_suggestion.id,
            cluster_id=test_cluster.id,
            mode=ApplyMode.DRY_RUN,
            status=ApplyRequestStatus.APPROVED,
            proposed_config=test_suggestion.proposed_config,
        )
        db_session.add(request)
        db_session.commit()

        with app.app_context():
            result = apply_service.execute_request(request.id)

            assert result.status == ApplyRequestStatus.COMPLETED
            assert result.completed_at is not None

    def test_execute_request_not_approved(
        self, apply_service, app, db_session, test_suggestion, test_cluster
    ):
        """Test executing non-approved request fails."""
        request = ApplyRequest(
            suggestion_id=test_suggestion.id,
            cluster_id=test_cluster.id,
            mode=ApplyMode.APPLY,
            status=ApplyRequestStatus.PENDING_APPROVAL,
            proposed_config=test_suggestion.proposed_config,
        )
        db_session.add(request)
        db_session.commit()

        with app.app_context():
            with pytest.raises(InvalidApplyStateError):
                apply_service.execute_request(request.id)

    @patch('kubeopt_ai.core.apply_service.K8sApplyService')
    def test_rollback_request_success(
        self, mock_k8s_service, apply_service, app, db_session, test_suggestion, test_cluster
    ):
        """Test rolling back a completed request."""
        mock_service_instance = MagicMock()
        mock_k8s_service.return_value = mock_service_instance
        mock_service_instance.rollback.return_value = ApplyResult(
            success=True,
            message="Rolled back successfully",
        )

        # Create completed request with previous config
        request = ApplyRequest(
            suggestion_id=test_suggestion.id,
            cluster_id=test_cluster.id,
            mode=ApplyMode.APPLY,
            status=ApplyRequestStatus.COMPLETED,
            proposed_config=test_suggestion.proposed_config,
            previous_config=test_suggestion.current_config,
        )
        db_session.add(request)
        db_session.commit()

        with app.app_context():
            result = apply_service.rollback_request(
                request.id, "Performance degradation", "user-123"
            )

            assert result.status == ApplyRequestStatus.ROLLED_BACK
            assert result.rolled_back is True
            assert result.rollback_reason == "Performance degradation"

    def test_rollback_request_no_previous_config(
        self, apply_service, app, db_session, test_suggestion, test_cluster
    ):
        """Test rollback fails without previous config."""
        request = ApplyRequest(
            suggestion_id=test_suggestion.id,
            cluster_id=test_cluster.id,
            mode=ApplyMode.APPLY,
            status=ApplyRequestStatus.COMPLETED,
            proposed_config=test_suggestion.proposed_config,
            previous_config=None,  # No previous config
        )
        db_session.add(request)
        db_session.commit()

        with app.app_context():
            with pytest.raises(InvalidApplyStateError, match="No previous configuration"):
                apply_service.rollback_request(request.id, "Reason", "user-123")

    def test_list_requests_with_filters(
        self, apply_service, app, db_session, test_suggestion, test_cluster
    ):
        """Test listing requests with filters."""
        # Create multiple requests
        for status in [ApplyRequestStatus.PENDING_APPROVAL, ApplyRequestStatus.COMPLETED]:
            request = ApplyRequest(
                suggestion_id=test_suggestion.id,
                cluster_id=test_cluster.id,
                mode=ApplyMode.APPLY,
                status=status,
                proposed_config=test_suggestion.proposed_config,
            )
            db_session.add(request)
        db_session.commit()

        with app.app_context():
            # Filter by status
            pending = apply_service.list_requests(
                status=ApplyRequestStatus.PENDING_APPROVAL
            )
            assert len(pending) == 1

            # Filter by cluster
            cluster_requests = apply_service.list_requests(
                cluster_id=test_cluster.id
            )
            assert len(cluster_requests) == 2


# =============================================================================
# Apply Routes Tests
# =============================================================================

class TestApplyRoutes:
    """Tests for apply API routes."""

    def test_create_policy_success(self, client, app, db_session):
        """Test successful policy creation."""
        response = client.post(
            "/api/v1/apply-policies",
            json={
                "name": "test-policy",
                "description": "A test policy",
                "require_approval": True,
                "max_cpu_increase_percent": 150.0,
            }
        )

        assert response.status_code == 201
        data = response.get_json()
        assert data["name"] == "test-policy"
        assert data["require_approval"] is True

    def test_create_policy_missing_name(self, client):
        """Test policy creation with missing name fails."""
        response = client.post(
            "/api/v1/apply-policies",
            json={"description": "No name provided"}
        )

        assert response.status_code == 400

    def test_list_policies(self, client, app, db_session):
        """Test listing policies."""
        # Create some policies
        for i in range(3):
            policy = ApplyPolicy(
                name=f"policy-{i}",
                excluded_namespaces=[],
                excluded_workload_patterns=[],
            )
            db_session.add(policy)
        db_session.commit()

        response = client.get("/api/v1/apply-policies")

        assert response.status_code == 200
        data = response.get_json()
        assert len(data["policies"]) == 3

    def test_get_policy_success(self, client, app, db_session):
        """Test getting a policy by ID."""
        policy = ApplyPolicy(
            name="get-test-policy",
            excluded_namespaces=[],
            excluded_workload_patterns=[],
        )
        db_session.add(policy)
        db_session.commit()

        response = client.get(f"/api/v1/apply-policies/{policy.id}")

        assert response.status_code == 200
        data = response.get_json()
        assert data["name"] == "get-test-policy"

    def test_get_policy_not_found(self, client):
        """Test getting non-existent policy."""
        response = client.get("/api/v1/apply-policies/non-existent-id")

        assert response.status_code == 404

    def test_update_policy_success(self, client, app, db_session):
        """Test updating a policy."""
        policy = ApplyPolicy(
            name="update-test-policy",
            require_approval=True,
            excluded_namespaces=[],
            excluded_workload_patterns=[],
        )
        db_session.add(policy)
        db_session.commit()

        response = client.put(
            f"/api/v1/apply-policies/{policy.id}",
            json={"require_approval": False, "priority": 10}
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["require_approval"] is False
        assert data["priority"] == 10

    def test_delete_policy_success(self, client, app, db_session):
        """Test deleting a policy."""
        policy = ApplyPolicy(
            name="delete-test-policy",
            excluded_namespaces=[],
            excluded_workload_patterns=[],
        )
        db_session.add(policy)
        db_session.commit()
        policy_id = policy.id

        response = client.delete(f"/api/v1/apply-policies/{policy_id}")

        assert response.status_code == 204

        # Verify deleted
        response = client.get(f"/api/v1/apply-policies/{policy_id}")
        assert response.status_code == 404

    def test_create_apply_request_missing_fields(self, client):
        """Test creating apply request with missing fields fails."""
        response = client.post(
            "/api/v1/apply",
            json={"suggestion_id": "some-id"}  # Missing cluster_id
        )

        assert response.status_code == 400

    def test_list_apply_requests(self, client, app, db_session):
        """Test listing apply requests."""
        # Create cluster and suggestion first
        cluster = Cluster(
            name="list-test-cluster",
            provider=ClusterProvider.AWS,
            status=ClusterStatus.ACTIVE,
        )
        db_session.add(cluster)
        db_session.flush()

        run = OptimizationRun(
            manifest_source_path="/test",
            lookback_days=7,
            status=RunStatus.COMPLETED,
        )
        db_session.add(run)
        db_session.flush()

        workload = WorkloadSnapshot(
            run_id=run.id,
            name="test",
            namespace="default",
            kind=WorkloadKind.DEPLOYMENT,
            current_config={},
        )
        db_session.add(workload)
        db_session.flush()

        suggestion = Suggestion(
            workload_snapshot_id=workload.id,
            container_name="main",
            current_config={},
            proposed_config={},
        )
        db_session.add(suggestion)
        db_session.flush()

        # Create some requests
        for i in range(3):
            req = ApplyRequest(
                suggestion_id=suggestion.id,
                cluster_id=cluster.id,
                mode=ApplyMode.DRY_RUN,
                status=ApplyRequestStatus.PENDING_APPROVAL,
                proposed_config={},
            )
            db_session.add(req)
        db_session.commit()

        response = client.get("/api/v1/apply/requests")

        assert response.status_code == 200
        data = response.get_json()
        assert len(data["requests"]) == 3

    def test_get_apply_request_not_found(self, client):
        """Test getting non-existent apply request."""
        response = client.get("/api/v1/apply/requests/non-existent-id")

        assert response.status_code == 404

    def test_reject_request_missing_reason(self, client, app, db_session):
        """Test rejecting request without reason fails."""
        # Create a pending request
        cluster = Cluster(
            name="reject-test-cluster",
            provider=ClusterProvider.AWS,
            status=ClusterStatus.ACTIVE,
        )
        db_session.add(cluster)
        db_session.flush()

        run = OptimizationRun(
            manifest_source_path="/test",
            lookback_days=7,
            status=RunStatus.COMPLETED,
        )
        db_session.add(run)
        db_session.flush()

        workload = WorkloadSnapshot(
            run_id=run.id,
            name="test",
            namespace="default",
            kind=WorkloadKind.DEPLOYMENT,
            current_config={},
        )
        db_session.add(workload)
        db_session.flush()

        suggestion = Suggestion(
            workload_snapshot_id=workload.id,
            container_name="main",
            current_config={},
            proposed_config={},
        )
        db_session.add(suggestion)
        db_session.flush()

        req = ApplyRequest(
            suggestion_id=suggestion.id,
            cluster_id=cluster.id,
            mode=ApplyMode.APPLY,
            status=ApplyRequestStatus.PENDING_APPROVAL,
            proposed_config={},
        )
        db_session.add(req)
        db_session.commit()

        response = client.post(
            f"/api/v1/apply/requests/{req.id}/reject",
            json={}  # Missing reason
        )

        assert response.status_code == 400

    def test_apply_history_endpoint(self, client, app, db_session):
        """Test apply history endpoint."""
        response = client.get("/api/v1/apply/history")

        assert response.status_code == 200
        data = response.get_json()
        assert "requests" in data
        assert "total" in data
        assert "page" in data
