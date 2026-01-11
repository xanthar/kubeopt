"""
Unit tests for YAML diff generation.
"""

import pytest

from kubeopt_ai.core.yaml_diff import (
    YAMLDiffGenerator,
    generate_diff_for_suggestion,
    generate_all_diffs,
    ContainerDiff,
)
from kubeopt_ai.core.schemas import (
    WorkloadSuggestion,
    ContainerSuggestion,
    HPASuggestion,
    ContainerResources,
    ResourceRequirements,
    HPAConfig,
)


@pytest.fixture
def sample_container_suggestion():
    """Create a sample container suggestion."""
    return ContainerSuggestion(
        container="web",
        current=ContainerResources(
            requests=ResourceRequirements(cpu="100m", memory="128Mi"),
            limits=ResourceRequirements(cpu="500m", memory="512Mi"),
        ),
        proposed=ContainerResources(
            requests=ResourceRequirements(cpu="200m", memory="256Mi"),
            limits=ResourceRequirements(cpu="1000m", memory="1Gi"),
        ),
        reasoning="Increased based on p95 usage metrics.",
    )


@pytest.fixture
def sample_hpa_suggestion():
    """Create a sample HPA suggestion."""
    return HPASuggestion(
        current=HPAConfig(min_replicas=1, max_replicas=3, target_cpu_percent=80),
        proposed=HPAConfig(min_replicas=2, max_replicas=5, target_cpu_percent=70),
        reasoning="Better scaling configuration.",
    )


@pytest.fixture
def sample_workload_suggestion(sample_container_suggestion, sample_hpa_suggestion):
    """Create a sample workload suggestion."""
    return WorkloadSuggestion(
        name="web-app",
        namespace="production",
        kind="Deployment",
        suggestions=[sample_container_suggestion],
        hpa=sample_hpa_suggestion,
    )


@pytest.fixture
def sample_manifest():
    """Create a sample Kubernetes manifest."""
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": "web-app",
            "namespace": "production",
        },
        "spec": {
            "replicas": 3,
            "template": {
                "spec": {
                    "containers": [
                        {
                            "name": "web",
                            "image": "nginx:1.21",
                            "resources": {
                                "requests": {
                                    "cpu": "100m",
                                    "memory": "128Mi",
                                },
                                "limits": {
                                    "cpu": "500m",
                                    "memory": "512Mi",
                                },
                            },
                        }
                    ],
                },
            },
        },
    }


class TestYAMLDiffGenerator:
    """Tests for YAMLDiffGenerator class."""

    @pytest.fixture
    def generator(self):
        """Create a diff generator instance."""
        return YAMLDiffGenerator()

    def test_generate_workload_diff(self, generator, sample_workload_suggestion):
        """Test generating a complete workload diff."""
        diff = generator.generate_workload_diff(sample_workload_suggestion)

        assert diff.workload_name == "web-app"
        assert diff.namespace == "production"
        assert diff.kind == "Deployment"
        assert len(diff.container_diffs) == 1
        assert diff.hpa_diff is not None

    def test_generate_container_diff(self, generator, sample_container_suggestion):
        """Test generating container resource diff."""
        diff = generator._generate_container_diff(sample_container_suggestion)

        assert diff.container_name == "web"
        assert len(diff.changes) == 4  # cpu/memory for requests and limits

        # Check for specific changes
        paths = [c.path for c in diff.changes]
        assert "resources.requests.cpu" in paths
        assert "resources.requests.memory" in paths
        assert "resources.limits.cpu" in paths
        assert "resources.limits.memory" in paths

    def test_generate_hpa_diff(self, generator, sample_hpa_suggestion):
        """Test generating HPA configuration diff."""
        diff = generator._generate_hpa_diff(sample_hpa_suggestion)

        assert len(diff.changes) == 3  # min, max, target_cpu

        paths = [c.path for c in diff.changes]
        assert "spec.minReplicas" in paths
        assert "spec.maxReplicas" in paths
        assert "spec.metrics[cpu].target.averageUtilization" in paths

    def test_format_diff_text(self, generator, sample_workload_suggestion):
        """Test formatting diff as text."""
        diff = generator.generate_workload_diff(sample_workload_suggestion)
        text = generator.format_diff_text(diff)

        # Check for header
        assert "# Deployment: production/web-app" in text

        # Check for container section
        assert "## Container: web" in text

        # Check for diff markers
        assert "- resources.requests.cpu: 100m" in text
        assert "+ resources.requests.cpu: 200m" in text

        # Check for reasoning
        assert "Reasoning:" in text

    def test_format_diff_text_hpa(self, generator, sample_workload_suggestion):
        """Test that HPA changes are included in diff text."""
        diff = generator.generate_workload_diff(sample_workload_suggestion)
        text = generator.format_diff_text(diff)

        assert "## HorizontalPodAutoscaler" in text
        assert "spec.minReplicas" in text
        assert "spec.maxReplicas" in text

    def test_generate_yaml_patch(self, generator, sample_workload_suggestion, sample_manifest):
        """Test generating an updated manifest."""
        diff = generator.generate_workload_diff(sample_workload_suggestion)
        updated = generator.generate_yaml_patch(diff, sample_manifest)

        container = updated["spec"]["template"]["spec"]["containers"][0]
        assert container["resources"]["requests"]["cpu"] == "200m"
        assert container["resources"]["requests"]["memory"] == "256Mi"
        assert container["resources"]["limits"]["cpu"] == "1000m"
        assert container["resources"]["limits"]["memory"] == "1Gi"

    def test_generate_yaml_patch_preserves_other_fields(
        self, generator, sample_workload_suggestion, sample_manifest
    ):
        """Test that unrelated fields are preserved in patch."""
        diff = generator.generate_workload_diff(sample_workload_suggestion)
        updated = generator.generate_yaml_patch(diff, sample_manifest)

        assert updated["apiVersion"] == "apps/v1"
        assert updated["kind"] == "Deployment"
        assert updated["metadata"]["name"] == "web-app"
        assert updated["spec"]["replicas"] == 3

    def test_dump_yaml(self, generator):
        """Test YAML dumping."""
        data = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "test"},
        }

        yaml_str = generator.dump_yaml(data)

        assert "apiVersion: apps/v1" in yaml_str
        assert "kind: Deployment" in yaml_str
        assert "name: test" in yaml_str


class TestDiffWithNoChanges:
    """Tests for cases with no changes."""

    def test_no_resource_changes(self):
        """Test suggestion where current equals proposed."""
        suggestion = ContainerSuggestion(
            container="web",
            current=ContainerResources(
                requests=ResourceRequirements(cpu="100m", memory="128Mi"),
                limits=ResourceRequirements(cpu="500m", memory="512Mi"),
            ),
            proposed=ContainerResources(
                requests=ResourceRequirements(cpu="100m", memory="128Mi"),
                limits=ResourceRequirements(cpu="500m", memory="512Mi"),
            ),
            reasoning="No changes needed.",
        )

        generator = YAMLDiffGenerator()
        diff = generator._generate_container_diff(suggestion)

        assert len(diff.changes) == 0

    def test_no_hpa(self):
        """Test workload without HPA suggestion."""
        suggestion = WorkloadSuggestion(
            name="api-server",
            namespace="default",
            kind="Deployment",
            suggestions=[],
            hpa=None,
        )

        generator = YAMLDiffGenerator()
        diff = generator.generate_workload_diff(suggestion)

        assert diff.hpa_diff is None


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_generate_diff_for_suggestion(self, sample_workload_suggestion):
        """Test the convenience function."""
        diff_text = generate_diff_for_suggestion(sample_workload_suggestion)

        assert "web-app" in diff_text
        assert "production" in diff_text
        assert "100m" in diff_text
        assert "200m" in diff_text

    def test_generate_all_diffs(self, sample_workload_suggestion):
        """Test generating diffs for multiple suggestions."""
        suggestions = [
            sample_workload_suggestion,
            WorkloadSuggestion(
                name="api-server",
                namespace="default",
                kind="Deployment",
                suggestions=[
                    ContainerSuggestion(
                        container="api",
                        current=ContainerResources(
                            requests=ResourceRequirements(cpu="200m", memory="256Mi"),
                        ),
                        proposed=ContainerResources(
                            requests=ResourceRequirements(cpu="400m", memory="512Mi"),
                        ),
                        reasoning="Increased for API workload.",
                    ),
                ],
            ),
        ]

        results = generate_all_diffs(suggestions)

        assert len(results) == 2
        assert results[0][0] == "web-app"
        assert results[1][0] == "api-server"
        assert "web-app" in results[0][1]
        assert "api-server" in results[1][1]


class TestEdgeCases:
    """Tests for edge cases."""

    def test_missing_current_resources(self):
        """Test suggestion with missing current resources."""
        suggestion = ContainerSuggestion(
            container="web",
            current=ContainerResources(),  # Empty
            proposed=ContainerResources(
                requests=ResourceRequirements(cpu="100m", memory="128Mi"),
            ),
            reasoning="Adding resources where none existed.",
        )

        generator = YAMLDiffGenerator()
        diff = generator._generate_container_diff(suggestion)

        # Should not fail, just have no changes to compare
        assert isinstance(diff, ContainerDiff)

    def test_new_hpa_recommendation(self):
        """Test HPA suggestion where no HPA previously existed."""
        suggestion = HPASuggestion(
            current=None,
            proposed=HPAConfig(min_replicas=2, max_replicas=5, target_cpu_percent=70),
            reasoning="HPA recommended for this workload.",
        )

        generator = YAMLDiffGenerator()
        diff = generator._generate_hpa_diff(suggestion)

        # Should show only new values
        assert len(diff.changes) >= 2
        for change in diff.changes:
            assert change.old_value is None
            assert change.new_value is not None
