"""
Unit tests for the Kubernetes manifest scanner.
"""

import pytest
from pathlib import Path

from kubeopt_ai.core.k8s_scanner import (
    K8sScanner,
    scan_manifests,
    ManifestScanError,
)
from kubeopt_ai.core.schemas import WorkloadKind


# Get path to test fixtures
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "manifests"


class TestK8sScanner:
    """Tests for K8sScanner class."""

    @pytest.fixture
    def scanner(self):
        """Create a scanner instance for testing."""
        return K8sScanner()

    def test_scan_deployment(self, scanner):
        """Test scanning a Deployment manifest."""
        manifest_path = FIXTURES_DIR / "deployment.yaml"
        workloads = scanner.scan_directory(str(manifest_path))

        assert len(workloads) == 1
        workload = workloads[0]

        assert workload.kind == WorkloadKind.DEPLOYMENT
        assert workload.name == "web-app"
        assert workload.namespace == "production"
        assert workload.replicas == 3

        # Check containers
        assert len(workload.containers) == 2

        # Check main container
        web_container = next(c for c in workload.containers if c.name == "web")
        assert web_container.image == "nginx:1.21"
        assert web_container.resources.requests.cpu == "100m"
        assert web_container.resources.requests.memory == "128Mi"
        assert web_container.resources.limits.cpu == "500m"
        assert web_container.resources.limits.memory == "512Mi"

        # Check sidecar container
        sidecar = next(c for c in workload.containers if c.name == "sidecar")
        assert sidecar.image == "fluentd:v1.14"
        assert sidecar.resources.requests.cpu == "50m"

    def test_scan_statefulset(self, scanner):
        """Test scanning a StatefulSet manifest."""
        manifest_path = FIXTURES_DIR / "statefulset.yaml"
        workloads = scanner.scan_directory(str(manifest_path))

        assert len(workloads) == 1
        workload = workloads[0]

        assert workload.kind == WorkloadKind.STATEFULSET
        assert workload.name == "postgres"
        assert workload.namespace == "production"
        assert workload.replicas == 1

        # Check container
        assert len(workload.containers) == 1
        container = workload.containers[0]
        assert container.name == "postgres"
        assert container.resources.limits.memory == "2Gi"

    def test_scan_daemonset(self, scanner):
        """Test scanning a DaemonSet manifest."""
        manifest_path = FIXTURES_DIR / "daemonset.yaml"
        workloads = scanner.scan_directory(str(manifest_path))

        assert len(workloads) == 1
        workload = workloads[0]

        assert workload.kind == WorkloadKind.DAEMONSET
        assert workload.name == "node-exporter"
        assert workload.namespace == "monitoring"
        # DaemonSets don't have replicas
        assert workload.replicas is None

    def test_scan_with_hpa(self, scanner):
        """Test that HPA is correctly associated with its target workload."""
        # First scan the deployment
        workloads = scanner.scan_directory(str(FIXTURES_DIR))

        # Find the web-app deployment
        web_app = next(
            (w for w in workloads if w.name == "web-app" and w.namespace == "production"),
            None
        )
        assert web_app is not None

        # Check HPA is associated
        assert web_app.hpa is not None
        assert web_app.hpa.min_replicas == 2
        assert web_app.hpa.max_replicas == 10
        assert web_app.hpa.target_cpu_percent == 70
        assert web_app.hpa.target_memory_percent == 80

    def test_scan_multi_document_yaml(self, scanner):
        """Test scanning a multi-document YAML file."""
        manifest_path = FIXTURES_DIR / "multi-document.yaml"
        workloads = scanner.scan_directory(str(manifest_path))

        # Should only find the Deployment, not the Service
        assert len(workloads) == 1
        assert workloads[0].name == "api-server"
        assert workloads[0].kind == WorkloadKind.DEPLOYMENT

    def test_scan_directory(self, scanner):
        """Test scanning an entire directory of manifests."""
        workloads = scanner.scan_directory(str(FIXTURES_DIR))

        # Should find all supported workloads
        names = {w.name for w in workloads}
        assert "web-app" in names
        assert "postgres" in names
        assert "node-exporter" in names
        assert "api-server" in names

    def test_scan_nonexistent_path(self, scanner):
        """Test scanning a path that doesn't exist."""
        with pytest.raises(ManifestScanError) as exc_info:
            scanner.scan_directory("/nonexistent/path")

        assert "does not exist" in str(exc_info.value)

    def test_scan_non_yaml_file(self, scanner):
        """Test scanning a non-YAML file."""
        # Create a temporary non-YAML file path
        with pytest.raises(ManifestScanError) as exc_info:
            scanner.scan_directory("/etc/passwd")

        assert "Not a YAML file" in str(exc_info.value)

    def test_scan_manifest_content(self, scanner):
        """Test scanning YAML content directly."""
        content = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: test-deployment
  namespace: test
spec:
  replicas: 2
  selector:
    matchLabels:
      app: test
  template:
    metadata:
      labels:
        app: test
    spec:
      containers:
        - name: main
          image: test:latest
          resources:
            requests:
              cpu: "100m"
              memory: "128Mi"
"""
        workloads = scanner.scan_manifest_content(content)

        assert len(workloads) == 1
        assert workloads[0].name == "test-deployment"
        assert workloads[0].namespace == "test"
        assert workloads[0].replicas == 2

    def test_scan_empty_directory(self, scanner, tmp_path):
        """Test scanning an empty directory."""
        workloads = scanner.scan_directory(str(tmp_path))
        assert workloads == []

    def test_workload_labels_preserved(self, scanner):
        """Test that workload labels are preserved in the descriptor."""
        manifest_path = FIXTURES_DIR / "deployment.yaml"
        workloads = scanner.scan_directory(str(manifest_path))

        assert len(workloads) == 1
        assert workloads[0].labels.get("app") == "web-app"
        assert workloads[0].labels.get("tier") == "frontend"

    def test_manifest_path_recorded(self, scanner):
        """Test that the manifest path is recorded in the descriptor."""
        manifest_path = FIXTURES_DIR / "deployment.yaml"
        workloads = scanner.scan_directory(str(manifest_path))

        assert len(workloads) == 1
        assert str(manifest_path) in workloads[0].manifest_path


class TestScanManifestsFunction:
    """Tests for the module-level scan_manifests function."""

    def test_scan_manifests_function(self):
        """Test the convenience function."""
        workloads = scan_manifests(str(FIXTURES_DIR))

        assert len(workloads) >= 4  # At least 4 workloads in fixtures
        assert all(hasattr(w, "kind") for w in workloads)

    def test_scan_manifests_single_file(self):
        """Test scanning a single file via the function."""
        manifest_path = FIXTURES_DIR / "deployment.yaml"
        workloads = scan_manifests(str(manifest_path))

        assert len(workloads) == 1
        assert workloads[0].name == "web-app"
