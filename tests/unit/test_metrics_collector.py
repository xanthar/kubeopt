"""
Unit tests for the Prometheus metrics collector.
"""

import pytest
import responses

from kubeopt_ai.core.metrics_collector import (
    MetricsCollector,
    PrometheusClient,
    PrometheusConfig,
    MetricsCollectionError,
    collect_workload_metrics,
)
from kubeopt_ai.core.schemas import (
    WorkloadDescriptor,
    WorkloadKind,
    ContainerConfig,
    ContainerResources,
    ResourceRequirements,
)


PROMETHEUS_URL = "http://prometheus:9090"


@pytest.fixture
def prometheus_config():
    """Create a test Prometheus configuration."""
    return PrometheusConfig(
        base_url=PROMETHEUS_URL,
        timeout=10,
        verify_ssl=False,
    )


@pytest.fixture
def prometheus_client(prometheus_config):
    """Create a test Prometheus client."""
    return PrometheusClient(prometheus_config)


@pytest.fixture
def metrics_collector():
    """Create a test metrics collector."""
    return MetricsCollector(prometheus_url=PROMETHEUS_URL, timeout=10)


@pytest.fixture
def sample_workload():
    """Create a sample workload descriptor for testing."""
    return WorkloadDescriptor(
        kind=WorkloadKind.DEPLOYMENT,
        name="web-app",
        namespace="production",
        replicas=3,
        containers=[
            ContainerConfig(
                name="web",
                image="nginx:1.21",
                resources=ContainerResources(
                    requests=ResourceRequirements(cpu="100m", memory="128Mi"),
                    limits=ResourceRequirements(cpu="500m", memory="512Mi"),
                ),
            ),
        ],
    )


def make_prometheus_response(value: float) -> dict:
    """Create a mock Prometheus instant query response."""
    return {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [
                {
                    "metric": {},
                    "value": [1702500000, str(value)],
                }
            ],
        },
    }


def make_empty_prometheus_response() -> dict:
    """Create a mock empty Prometheus response."""
    return {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [],
        },
    }


def make_error_prometheus_response(error: str) -> dict:
    """Create a mock error Prometheus response."""
    return {
        "status": "error",
        "errorType": "bad_data",
        "error": error,
    }


class TestPrometheusClient:
    """Tests for PrometheusClient class."""

    @responses.activate
    def test_query_success(self, prometheus_client):
        """Test successful instant query."""
        responses.add(
            responses.GET,
            f"{PROMETHEUS_URL}/api/v1/query",
            json=make_prometheus_response(0.5),
            status=200,
        )

        result = prometheus_client.query("up{job='test'}")

        assert result == 0.5
        assert len(responses.calls) == 1

    @responses.activate
    def test_query_empty_result(self, prometheus_client):
        """Test query with empty result."""
        responses.add(
            responses.GET,
            f"{PROMETHEUS_URL}/api/v1/query",
            json=make_empty_prometheus_response(),
            status=200,
        )

        result = prometheus_client.query("nonexistent_metric")

        assert result is None

    @responses.activate
    def test_query_error_response(self, prometheus_client):
        """Test query with error response status."""
        responses.add(
            responses.GET,
            f"{PROMETHEUS_URL}/api/v1/query",
            json=make_error_prometheus_response("bad query"),
            status=200,
        )

        result = prometheus_client.query("invalid{query")

        assert result is None

    @responses.activate
    def test_query_http_error(self, prometheus_client):
        """Test query with HTTP error."""
        responses.add(
            responses.GET,
            f"{PROMETHEUS_URL}/api/v1/query",
            status=500,
        )

        with pytest.raises(MetricsCollectionError):
            prometheus_client.query("up")

    @responses.activate
    def test_query_connection_error(self, prometheus_client):
        """Test query with connection error."""
        responses.add(
            responses.GET,
            f"{PROMETHEUS_URL}/api/v1/query",
            body=ConnectionError("Connection refused"),
        )

        # responses library raises ConnectionError directly
        with pytest.raises((MetricsCollectionError, ConnectionError)):
            prometheus_client.query("up")


class TestMetricsCollector:
    """Tests for MetricsCollector class."""

    @responses.activate
    def test_get_workload_metrics(self, metrics_collector, sample_workload):
        """Test collecting metrics for a workload."""
        # Mock all the expected Prometheus queries
        # CPU metrics
        responses.add(
            responses.GET,
            f"{PROMETHEUS_URL}/api/v1/query",
            json=make_prometheus_response(0.1),  # avg CPU
            status=200,
        )
        responses.add(
            responses.GET,
            f"{PROMETHEUS_URL}/api/v1/query",
            json=make_prometheus_response(0.3),  # p95 CPU
            status=200,
        )
        responses.add(
            responses.GET,
            f"{PROMETHEUS_URL}/api/v1/query",
            json=make_prometheus_response(0.5),  # max CPU
            status=200,
        )
        # Memory metrics
        responses.add(
            responses.GET,
            f"{PROMETHEUS_URL}/api/v1/query",
            json=make_prometheus_response(100_000_000),  # avg memory
            status=200,
        )
        responses.add(
            responses.GET,
            f"{PROMETHEUS_URL}/api/v1/query",
            json=make_prometheus_response(200_000_000),  # p95 memory
            status=200,
        )
        responses.add(
            responses.GET,
            f"{PROMETHEUS_URL}/api/v1/query",
            json=make_prometheus_response(300_000_000),  # max memory
            status=200,
        )
        # Replica metrics
        responses.add(
            responses.GET,
            f"{PROMETHEUS_URL}/api/v1/query",
            json=make_prometheus_response(3.0),  # avg replicas
            status=200,
        )
        responses.add(
            responses.GET,
            f"{PROMETHEUS_URL}/api/v1/query",
            json=make_prometheus_response(5.0),  # max replicas
            status=200,
        )

        metrics = metrics_collector.get_workload_metrics(sample_workload, lookback_days=7)

        assert metrics.workload_name == "web-app"
        assert metrics.namespace == "production"
        assert metrics.lookback_days == 7

        # Check container metrics
        assert len(metrics.container_metrics) == 1
        container = metrics.container_metrics[0]
        assert container.container_name == "web"
        assert container.avg_cpu_usage == 0.1
        assert container.p95_cpu_usage == 0.3
        assert container.max_cpu_usage == 0.5
        assert container.avg_memory_usage == 100_000_000
        assert container.p95_memory_usage == 200_000_000
        assert container.max_memory_usage == 300_000_000

        # Check replica metrics
        assert metrics.avg_replica_count == 3.0
        assert metrics.max_replica_count == 5

    @responses.activate
    def test_get_workload_metrics_no_data(self, metrics_collector, sample_workload):
        """Test collecting metrics when Prometheus has no data."""
        # Return empty responses for all queries
        for _ in range(8):  # 6 container metrics + 2 replica metrics
            responses.add(
                responses.GET,
                f"{PROMETHEUS_URL}/api/v1/query",
                json=make_empty_prometheus_response(),
                status=200,
            )

        metrics = metrics_collector.get_workload_metrics(sample_workload)

        assert metrics.workload_name == "web-app"
        assert len(metrics.container_metrics) == 1

        container = metrics.container_metrics[0]
        assert container.avg_cpu_usage is None
        assert container.p95_cpu_usage is None
        assert container.avg_memory_usage is None

    @responses.activate
    def test_get_workload_metrics_partial_failure(self, metrics_collector, sample_workload):
        """Test collecting metrics with some queries failing."""
        # First query succeeds
        responses.add(
            responses.GET,
            f"{PROMETHEUS_URL}/api/v1/query",
            json=make_prometheus_response(0.1),
            status=200,
        )
        # Second query fails
        responses.add(
            responses.GET,
            f"{PROMETHEUS_URL}/api/v1/query",
            status=500,
        )
        # Remaining queries return empty
        for _ in range(6):
            responses.add(
                responses.GET,
                f"{PROMETHEUS_URL}/api/v1/query",
                json=make_empty_prometheus_response(),
                status=200,
            )

        metrics = metrics_collector.get_workload_metrics(sample_workload)

        # Should still return results for successful queries
        assert metrics.container_metrics[0].avg_cpu_usage == 0.1
        # Failed query should be None
        assert metrics.container_metrics[0].p95_cpu_usage is None

    @responses.activate
    def test_get_workload_metrics_statefulset(self, metrics_collector):
        """Test collecting metrics for a StatefulSet (no replica metrics)."""
        workload = WorkloadDescriptor(
            kind=WorkloadKind.STATEFULSET,
            name="postgres",
            namespace="production",
            replicas=1,
            containers=[
                ContainerConfig(
                    name="postgres",
                    image="postgres:14",
                    resources=ContainerResources(),
                ),
            ],
        )

        # Only mock container metrics (no replica metrics for StatefulSet)
        for _ in range(6):
            responses.add(
                responses.GET,
                f"{PROMETHEUS_URL}/api/v1/query",
                json=make_prometheus_response(0.5),
                status=200,
            )

        metrics = metrics_collector.get_workload_metrics(workload)

        assert metrics.workload_name == "postgres"
        # StatefulSet should not have replica metrics
        assert metrics.avg_replica_count is None
        assert metrics.max_replica_count is None


class TestCollectWorkloadMetricsFunction:
    """Tests for the module-level collect_workload_metrics function."""

    @responses.activate
    def test_collect_workload_metrics(self, sample_workload):
        """Test the convenience function."""
        # Mock metrics responses
        for _ in range(8):
            responses.add(
                responses.GET,
                f"{PROMETHEUS_URL}/api/v1/query",
                json=make_prometheus_response(0.5),
                status=200,
            )

        metrics = collect_workload_metrics(
            sample_workload,
            lookback_days=14,
            prometheus_url=PROMETHEUS_URL,
        )

        assert metrics.workload_name == "web-app"
        assert metrics.lookback_days == 14


class TestPromQLQueries:
    """Tests for PromQL query templates."""

    def test_query_formatting(self):
        """Test that query templates format correctly."""
        from kubeopt_ai.core.metrics_collector import PromQLQueries

        queries = PromQLQueries()
        params = {
            "namespace": "production",
            "workload_name": "web-app",
            "container_name": "nginx",
            "lookback": "7d",
        }

        formatted = queries.AVG_CPU_USAGE.format(**params)

        assert "namespace=\"production\"" in formatted
        assert "pod=~\"web-app-.*\"" in formatted
        assert "container=\"nginx\"" in formatted
        assert "[7d:5m]" in formatted

    def test_memory_query_formatting(self):
        """Test memory query formatting."""
        from kubeopt_ai.core.metrics_collector import PromQLQueries

        queries = PromQLQueries()
        params = {
            "namespace": "default",
            "workload_name": "api",
            "container_name": "app",
            "lookback": "14d",
        }

        formatted = queries.P95_MEMORY_USAGE.format(**params)

        assert "quantile_over_time(0.95," in formatted
        assert "container_memory_working_set_bytes" in formatted
        assert "namespace=\"default\"" in formatted
