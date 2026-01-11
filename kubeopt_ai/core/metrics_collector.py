"""
Prometheus metrics collector for KubeOpt AI.

This module collects CPU and memory usage metrics from Prometheus
for Kubernetes workloads to support optimization analysis.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass

import requests
from requests.exceptions import RequestException

from kubeopt_ai.core.schemas import (
    WorkloadDescriptor,
    WorkloadMetrics,
    ContainerMetrics,
)

logger = logging.getLogger(__name__)


class MetricsCollectionError(Exception):
    """Exception raised when metrics collection fails."""
    pass


@dataclass
class PrometheusConfig:
    """Configuration for Prometheus connection."""
    base_url: str = "http://prometheus:9090"
    timeout: int = 30
    verify_ssl: bool = True


# ============================================================================
# PromQL Query Templates
# ============================================================================

class PromQLQueries:
    """
    PromQL query templates for collecting container metrics.

    All queries are parameterized with:
    - namespace: Kubernetes namespace
    - workload_name: Name of the deployment/statefulset/daemonset
    - container_name: Name of the container
    - lookback: Lookback period (e.g., "7d" for 7 days)
    """

    # CPU metrics (rate over 5m windows, then aggregated over lookback period)
    AVG_CPU_USAGE = """
        avg_over_time(
            sum(
                rate(container_cpu_usage_seconds_total{{
                    namespace="{namespace}",
                    pod=~"{workload_name}-.*",
                    container="{container_name}"
                }}[5m])
            )[{lookback}:5m]
        )
    """

    P95_CPU_USAGE = """
        quantile_over_time(0.95,
            sum(
                rate(container_cpu_usage_seconds_total{{
                    namespace="{namespace}",
                    pod=~"{workload_name}-.*",
                    container="{container_name}"
                }}[5m])
            )[{lookback}:5m]
        )
    """

    MAX_CPU_USAGE = """
        max_over_time(
            sum(
                rate(container_cpu_usage_seconds_total{{
                    namespace="{namespace}",
                    pod=~"{workload_name}-.*",
                    container="{container_name}"
                }}[5m])
            )[{lookback}:5m]
        )
    """

    # Memory metrics (working set bytes)
    AVG_MEMORY_USAGE = """
        avg_over_time(
            sum(
                container_memory_working_set_bytes{{
                    namespace="{namespace}",
                    pod=~"{workload_name}-.*",
                    container="{container_name}"
                }}
            )[{lookback}:5m]
        )
    """

    P95_MEMORY_USAGE = """
        quantile_over_time(0.95,
            sum(
                container_memory_working_set_bytes{{
                    namespace="{namespace}",
                    pod=~"{workload_name}-.*",
                    container="{container_name}"
                }}
            )[{lookback}:5m]
        )
    """

    MAX_MEMORY_USAGE = """
        max_over_time(
            sum(
                container_memory_working_set_bytes{{
                    namespace="{namespace}",
                    pod=~"{workload_name}-.*",
                    container="{container_name}"
                }}
            )[{lookback}:5m]
        )
    """

    # Replica count metrics
    AVG_REPLICA_COUNT = """
        avg_over_time(
            kube_deployment_spec_replicas{{
                namespace="{namespace}",
                deployment="{workload_name}"
            }}[{lookback}]
        )
    """

    MAX_REPLICA_COUNT = """
        max_over_time(
            kube_deployment_spec_replicas{{
                namespace="{namespace}",
                deployment="{workload_name}"
            }}[{lookback}]
        )
    """


class PrometheusClient:
    """
    Client for querying Prometheus metrics.

    Handles HTTP requests to the Prometheus API and parses responses.
    """

    def __init__(self, config: Optional[PrometheusConfig] = None):
        """
        Initialize the Prometheus client.

        Args:
            config: Prometheus connection configuration.
        """
        self.config = config or PrometheusConfig()
        self._session = requests.Session()

    def query(self, promql: str) -> Optional[float]:
        """
        Execute an instant PromQL query and return the scalar result.

        Args:
            promql: The PromQL query string.

        Returns:
            The query result as a float, or None if no data.

        Raises:
            MetricsCollectionError: If the query fails.
        """
        url = f"{self.config.base_url}/api/v1/query"
        params = {"query": promql.strip()}

        try:
            response = self._session.get(
                url,
                params=params,
                timeout=self.config.timeout,
                verify=self.config.verify_ssl,
            )
            response.raise_for_status()
            data = response.json()

            if data.get("status") != "success":
                logger.warning(f"Prometheus query failed: {data.get('error', 'Unknown error')}")
                return None

            result = data.get("data", {}).get("result", [])
            if not result:
                return None

            # Get the value from the first result
            # Result format: [timestamp, "value"]
            value = result[0].get("value", [None, None])
            if len(value) >= 2 and value[1] is not None:
                try:
                    return float(value[1])
                except (ValueError, TypeError):
                    return None

            return None

        except RequestException as e:
            logger.error(f"Prometheus request failed: {e}")
            raise MetricsCollectionError(f"Failed to query Prometheus: {e}")

    def query_range(
        self,
        promql: str,
        start: datetime,
        end: datetime,
        step: str = "5m"
    ) -> list[tuple[datetime, float]]:
        """
        Execute a range PromQL query and return time series data.

        Args:
            promql: The PromQL query string.
            start: Start time for the range.
            end: End time for the range.
            step: Query resolution step (e.g., "5m", "1h").

        Returns:
            List of (timestamp, value) tuples.

        Raises:
            MetricsCollectionError: If the query fails.
        """
        url = f"{self.config.base_url}/api/v1/query_range"
        params = {
            "query": promql.strip(),
            "start": start.timestamp(),
            "end": end.timestamp(),
            "step": step,
        }

        try:
            response = self._session.get(
                url,
                params=params,
                timeout=self.config.timeout,
                verify=self.config.verify_ssl,
            )
            response.raise_for_status()
            data = response.json()

            if data.get("status") != "success":
                logger.warning(f"Prometheus range query failed: {data.get('error')}")
                return []

            result = data.get("data", {}).get("result", [])
            if not result:
                return []

            # Parse values from the first result
            values = result[0].get("values", [])
            return [
                (datetime.fromtimestamp(ts, tz=timezone.utc), float(val))
                for ts, val in values
            ]

        except RequestException as e:
            logger.error(f"Prometheus range request failed: {e}")
            raise MetricsCollectionError(f"Failed to query Prometheus range: {e}")


class MetricsCollector:
    """
    Collects resource usage metrics for Kubernetes workloads.

    Uses Prometheus to gather CPU and memory metrics over a configurable
    lookback period.
    """

    def __init__(
        self,
        prometheus_url: Optional[str] = None,
        timeout: int = 30
    ):
        """
        Initialize the metrics collector.

        Args:
            prometheus_url: Prometheus server URL.
            timeout: Request timeout in seconds.
        """
        config = PrometheusConfig(
            base_url=prometheus_url or "http://prometheus:9090",
            timeout=timeout,
        )
        self._client = PrometheusClient(config)
        self._queries = PromQLQueries()

    def get_workload_metrics(
        self,
        workload: WorkloadDescriptor,
        lookback_days: int = 7
    ) -> WorkloadMetrics:
        """
        Collect metrics for a workload over the specified lookback period.

        Args:
            workload: The workload descriptor to collect metrics for.
            lookback_days: Number of days to look back for metrics.

        Returns:
            WorkloadMetrics containing aggregated metrics for all containers.
        """
        lookback = f"{lookback_days}d"
        container_metrics = []

        for container in workload.containers:
            metrics = self._collect_container_metrics(
                namespace=workload.namespace,
                workload_name=workload.name,
                container_name=container.name,
                lookback=lookback,
            )
            container_metrics.append(metrics)

        # Collect replica metrics (for Deployments)
        avg_replicas = None
        max_replicas = None

        # Check if workload is a Deployment (kind may be enum or string)
        kind_value = workload.kind.value if hasattr(workload.kind, 'value') else workload.kind
        if kind_value == "Deployment":
            avg_replicas, max_replicas = self._collect_replica_metrics(
                namespace=workload.namespace,
                workload_name=workload.name,
                lookback=lookback,
            )

        return WorkloadMetrics(
            workload_name=workload.name,
            namespace=workload.namespace,
            lookback_days=lookback_days,
            container_metrics=container_metrics,
            avg_replica_count=avg_replicas,
            max_replica_count=int(max_replicas) if max_replicas else None,
        )

    def _collect_container_metrics(
        self,
        namespace: str,
        workload_name: str,
        container_name: str,
        lookback: str
    ) -> ContainerMetrics:
        """
        Collect metrics for a single container.

        Args:
            namespace: Kubernetes namespace.
            workload_name: Name of the workload.
            container_name: Name of the container.
            lookback: Lookback period string (e.g., "7d").

        Returns:
            ContainerMetrics with CPU and memory statistics.
        """
        params = {
            "namespace": namespace,
            "workload_name": workload_name,
            "container_name": container_name,
            "lookback": lookback,
        }

        # Collect CPU metrics
        avg_cpu = self._safe_query(self._queries.AVG_CPU_USAGE.format(**params))
        p95_cpu = self._safe_query(self._queries.P95_CPU_USAGE.format(**params))
        max_cpu = self._safe_query(self._queries.MAX_CPU_USAGE.format(**params))

        # Collect memory metrics
        avg_memory = self._safe_query(self._queries.AVG_MEMORY_USAGE.format(**params))
        p95_memory = self._safe_query(self._queries.P95_MEMORY_USAGE.format(**params))
        max_memory = self._safe_query(self._queries.MAX_MEMORY_USAGE.format(**params))

        return ContainerMetrics(
            container_name=container_name,
            avg_cpu_usage=avg_cpu,
            p95_cpu_usage=p95_cpu,
            max_cpu_usage=max_cpu,
            avg_memory_usage=avg_memory,
            p95_memory_usage=p95_memory,
            max_memory_usage=max_memory,
        )

    def _collect_replica_metrics(
        self,
        namespace: str,
        workload_name: str,
        lookback: str
    ) -> tuple[Optional[float], Optional[float]]:
        """
        Collect replica count metrics for a Deployment.

        Args:
            namespace: Kubernetes namespace.
            workload_name: Name of the deployment.
            lookback: Lookback period string.

        Returns:
            Tuple of (avg_replicas, max_replicas).
        """
        params = {
            "namespace": namespace,
            "workload_name": workload_name,
            "lookback": lookback,
        }

        avg_replicas = self._safe_query(self._queries.AVG_REPLICA_COUNT.format(**params))
        max_replicas = self._safe_query(self._queries.MAX_REPLICA_COUNT.format(**params))

        return avg_replicas, max_replicas

    def _safe_query(self, promql: str) -> Optional[float]:
        """
        Execute a Prometheus query safely, catching errors.

        Args:
            promql: The PromQL query string.

        Returns:
            Query result or None if the query fails.
        """
        try:
            return self._client.query(promql)
        except MetricsCollectionError as e:
            logger.warning(f"Metrics query failed: {e}")
            return None


# Module-level collector factory
_collector: Optional[MetricsCollector] = None


def get_metrics_collector(
    prometheus_url: Optional[str] = None,
    timeout: int = 30
) -> MetricsCollector:
    """
    Get or create a metrics collector instance.

    Args:
        prometheus_url: Optional Prometheus URL override.
        timeout: Request timeout in seconds.

    Returns:
        MetricsCollector instance.
    """
    global _collector
    if _collector is None or prometheus_url:
        _collector = MetricsCollector(prometheus_url, timeout)
    return _collector


def collect_workload_metrics(
    workload: WorkloadDescriptor,
    lookback_days: int = 7,
    prometheus_url: Optional[str] = None
) -> WorkloadMetrics:
    """
    Convenience function to collect metrics for a workload.

    Args:
        workload: The workload descriptor.
        lookback_days: Number of days to look back.
        prometheus_url: Optional Prometheus URL override.

    Returns:
        WorkloadMetrics for the workload.
    """
    collector = get_metrics_collector(prometheus_url)
    return collector.get_workload_metrics(workload, lookback_days)
