"""
Real-time metrics streaming for KubeOpt AI.

This module provides streaming metrics collection from Prometheus
for real-time anomaly detection and trend analysis.
"""

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Callable, Optional

from kubeopt_ai.core.metrics_collector import (
    PrometheusClient,
    PrometheusConfig,
    MetricsCollectionError,
)
from kubeopt_ai.core.anomaly_detection import (
    AnomalyAlert,
    AnomalyType,
    AlertSeverity,
)

logger = logging.getLogger(__name__)


class TimeWindow(Enum):
    """Configurable time windows for trend analysis."""

    FIVE_MINUTES = "5m"
    FIFTEEN_MINUTES = "15m"
    THIRTY_MINUTES = "30m"
    ONE_HOUR = "1h"
    SIX_HOURS = "6h"
    TWELVE_HOURS = "12h"
    TWENTY_FOUR_HOURS = "24h"

    @property
    def seconds(self) -> int:
        """Convert time window to seconds."""
        mapping = {
            "5m": 300,
            "15m": 900,
            "30m": 1800,
            "1h": 3600,
            "6h": 21600,
            "12h": 43200,
            "24h": 86400,
        }
        return mapping[self.value]


@dataclass
class MetricDataPoint:
    """A single metric data point."""

    timestamp: datetime
    value: float
    labels: dict = field(default_factory=dict)


@dataclass
class MetricStream:
    """A stream of metric data points with sliding window."""

    metric_name: str
    namespace: str
    workload_name: str
    container_name: str
    window_size: int = 100  # Max data points to keep
    data: deque = field(default=None)

    def __post_init__(self):
        """Initialize the deque with the correct maxlen."""
        if self.data is None:
            self.data = deque(maxlen=self.window_size)

    def add(self, point: MetricDataPoint) -> None:
        """Add a data point to the stream."""
        self.data.append(point)

    def get_values(self) -> list[float]:
        """Get all values in the stream."""
        return [p.value for p in self.data]

    def get_latest(self, n: int = 1) -> list[MetricDataPoint]:
        """Get the latest n data points."""
        return list(self.data)[-n:]

    def get_window(self, window: TimeWindow) -> list[MetricDataPoint]:
        """Get data points within the specified time window."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=window.seconds)
        return [p for p in self.data if p.timestamp >= cutoff]

    def clear(self) -> None:
        """Clear all data points."""
        self.data.clear()


class RealTimePromQLQueries:
    """
    PromQL query templates for real-time metrics.

    These queries are optimized for short time ranges and instant metrics.
    """

    # Instant CPU usage (current rate)
    INSTANT_CPU = """
        sum(
            rate(container_cpu_usage_seconds_total{{
                namespace="{namespace}",
                pod=~"{workload_name}-.*",
                container="{container_name}"
            }}[1m])
        )
    """

    # Instant memory usage
    INSTANT_MEMORY = """
        sum(
            container_memory_working_set_bytes{{
                namespace="{namespace}",
                pod=~"{workload_name}-.*",
                container="{container_name}"
            }}
        )
    """

    # CPU trend over window
    CPU_TREND = """
        deriv(
            sum(
                rate(container_cpu_usage_seconds_total{{
                    namespace="{namespace}",
                    pod=~"{workload_name}-.*",
                    container="{container_name}"
                }}[1m])
            )[{window}:1m]
        )
    """

    # Memory trend over window
    MEMORY_TREND = """
        deriv(
            sum(
                container_memory_working_set_bytes{{
                    namespace="{namespace}",
                    pod=~"{workload_name}-.*",
                    container="{container_name}"
                }}
            )[{window}:1m]
        )
    """

    # Average CPU over window
    AVG_CPU_WINDOW = """
        avg_over_time(
            sum(
                rate(container_cpu_usage_seconds_total{{
                    namespace="{namespace}",
                    pod=~"{workload_name}-.*",
                    container="{container_name}"
                }}[1m])
            )[{window}:1m]
        )
    """

    # Average memory over window
    AVG_MEMORY_WINDOW = """
        avg_over_time(
            sum(
                container_memory_working_set_bytes{{
                    namespace="{namespace}",
                    pod=~"{workload_name}-.*",
                    container="{container_name}"
                }}
            )[{window}:1m]
        )
    """

    # Standard deviation for CPU (for anomaly detection)
    STDDEV_CPU_WINDOW = """
        stddev_over_time(
            sum(
                rate(container_cpu_usage_seconds_total{{
                    namespace="{namespace}",
                    pod=~"{workload_name}-.*",
                    container="{container_name}"
                }}[1m])
            )[{window}:1m]
        )
    """

    # Standard deviation for memory
    STDDEV_MEMORY_WINDOW = """
        stddev_over_time(
            sum(
                container_memory_working_set_bytes{{
                    namespace="{namespace}",
                    pod=~"{workload_name}-.*",
                    container="{container_name}"
                }}
            )[{window}:1m]
        )
    """

    # Pod restart count
    POD_RESTARTS = """
        sum(
            increase(
                kube_pod_container_status_restarts_total{{
                    namespace="{namespace}",
                    pod=~"{workload_name}-.*",
                    container="{container_name}"
                }}[{window}]
            )
        )
    """

    # Container throttling
    CPU_THROTTLING = """
        sum(
            rate(container_cpu_cfs_throttled_seconds_total{{
                namespace="{namespace}",
                pod=~"{workload_name}-.*",
                container="{container_name}"
            }}[{window}])
        )
    """


@dataclass
class TrendAnalysis:
    """Result of trend analysis for a metric."""

    metric_name: str
    current_value: float
    average_value: float
    std_deviation: float
    trend_direction: str  # "increasing", "decreasing", "stable"
    trend_rate: float  # Rate of change per second
    window: TimeWindow
    is_anomalous: bool
    anomaly_score: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class WorkloadStatus:
    """Real-time status for a workload."""

    workload_name: str
    namespace: str
    cpu_status: TrendAnalysis
    memory_status: TrendAnalysis
    health_score: float
    active_alerts: list[AnomalyAlert] = field(default_factory=list)
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class StreamingMetricsCollector:
    """
    Collects real-time metrics from Prometheus with streaming support.

    Provides continuous monitoring with configurable polling intervals
    and trend analysis.
    """

    def __init__(
        self,
        prometheus_url: str = "http://prometheus:9090",
        timeout: int = 10,
        default_window: TimeWindow = TimeWindow.FIFTEEN_MINUTES,
    ):
        """
        Initialize the streaming metrics collector.

        Args:
            prometheus_url: Prometheus server URL.
            timeout: Request timeout in seconds.
            default_window: Default time window for analysis.
        """
        config = PrometheusConfig(
            base_url=prometheus_url,
            timeout=timeout,
        )
        self._client = PrometheusClient(config)
        self._queries = RealTimePromQLQueries()
        self._default_window = default_window
        self._streams: dict[str, MetricStream] = {}

    def _stream_key(
        self,
        metric: str,
        namespace: str,
        workload: str,
        container: str,
    ) -> str:
        """Generate a unique key for a metric stream."""
        return f"{metric}:{namespace}/{workload}/{container}"

    def get_instant_metrics(
        self,
        namespace: str,
        workload_name: str,
        container_name: str,
    ) -> dict[str, Optional[float]]:
        """
        Get instant (current) metrics for a container.

        Args:
            namespace: Kubernetes namespace.
            workload_name: Name of the workload.
            container_name: Name of the container.

        Returns:
            Dict with cpu and memory values.
        """
        params = {
            "namespace": namespace,
            "workload_name": workload_name,
            "container_name": container_name,
        }

        cpu = self._safe_query(self._queries.INSTANT_CPU.format(**params))
        memory = self._safe_query(self._queries.INSTANT_MEMORY.format(**params))

        return {
            "cpu": cpu,
            "memory": memory,
            "timestamp": datetime.now(timezone.utc),
        }

    def get_trend_analysis(
        self,
        namespace: str,
        workload_name: str,
        container_name: str,
        window: Optional[TimeWindow] = None,
    ) -> dict[str, TrendAnalysis]:
        """
        Perform trend analysis for a container's metrics.

        Args:
            namespace: Kubernetes namespace.
            workload_name: Name of the workload.
            container_name: Name of the container.
            window: Time window for analysis.

        Returns:
            Dict with cpu and memory trend analyses.
        """
        window = window or self._default_window
        params = {
            "namespace": namespace,
            "workload_name": workload_name,
            "container_name": container_name,
            "window": window.value,
        }

        # Get CPU metrics
        cpu_current = self._safe_query(self._queries.INSTANT_CPU.format(**params))
        cpu_avg = self._safe_query(self._queries.AVG_CPU_WINDOW.format(**params))
        cpu_stddev = self._safe_query(self._queries.STDDEV_CPU_WINDOW.format(**params))
        cpu_trend = self._safe_query(self._queries.CPU_TREND.format(**params))

        # Get memory metrics
        mem_current = self._safe_query(self._queries.INSTANT_MEMORY.format(**params))
        mem_avg = self._safe_query(self._queries.AVG_MEMORY_WINDOW.format(**params))
        mem_stddev = self._safe_query(self._queries.STDDEV_MEMORY_WINDOW.format(**params))
        mem_trend = self._safe_query(self._queries.MEMORY_TREND.format(**params))

        return {
            "cpu": self._build_trend_analysis(
                "cpu",
                cpu_current or 0.0,
                cpu_avg or 0.0,
                cpu_stddev or 0.0,
                cpu_trend or 0.0,
                window,
            ),
            "memory": self._build_trend_analysis(
                "memory",
                mem_current or 0.0,
                mem_avg or 0.0,
                mem_stddev or 0.0,
                mem_trend or 0.0,
                window,
            ),
        }

    def _build_trend_analysis(
        self,
        metric_name: str,
        current: float,
        average: float,
        stddev: float,
        trend_rate: float,
        window: TimeWindow,
    ) -> TrendAnalysis:
        """Build a TrendAnalysis from raw metrics."""
        # Determine trend direction
        if abs(trend_rate) < 0.01:
            direction = "stable"
        elif trend_rate > 0:
            direction = "increasing"
        else:
            direction = "decreasing"

        # Calculate anomaly score using Z-score
        if stddev > 0:
            z_score = abs(current - average) / stddev
            is_anomalous = z_score > 2.0
            anomaly_score = min(z_score / 3.0, 1.0)  # Normalize to 0-1
        else:
            is_anomalous = False
            anomaly_score = 0.0

        return TrendAnalysis(
            metric_name=metric_name,
            current_value=current,
            average_value=average,
            std_deviation=stddev,
            trend_direction=direction,
            trend_rate=trend_rate,
            window=window,
            is_anomalous=is_anomalous,
            anomaly_score=anomaly_score,
        )

    def get_workload_status(
        self,
        namespace: str,
        workload_name: str,
        container_name: str,
        window: Optional[TimeWindow] = None,
    ) -> WorkloadStatus:
        """
        Get comprehensive real-time status for a workload.

        Args:
            namespace: Kubernetes namespace.
            workload_name: Name of the workload.
            container_name: Name of the container.
            window: Time window for analysis.

        Returns:
            WorkloadStatus with current metrics and health.
        """
        window = window or self._default_window
        trends = self.get_trend_analysis(
            namespace, workload_name, container_name, window
        )

        # Calculate health score based on anomaly scores
        cpu_health = 100 - (trends["cpu"].anomaly_score * 50)
        mem_health = 100 - (trends["memory"].anomaly_score * 50)
        health_score = (cpu_health + mem_health) / 2

        # Generate alerts for anomalous conditions
        alerts = []
        if trends["cpu"].is_anomalous:
            alerts.append(
                AnomalyAlert(
                    anomaly_type=AnomalyType.CPU_SPIKE
                    if trends["cpu"].trend_direction == "increasing"
                    else AnomalyType.UNUSUAL_PATTERN,
                    severity=self._severity_from_score(trends["cpu"].anomaly_score),
                    workload_name=workload_name,
                    namespace=namespace,
                    container_name=container_name,
                    resource_type="cpu",
                    description=f"CPU usage {trends['cpu'].trend_direction}: "
                    f"{trends['cpu'].current_value:.3f} cores "
                    f"(avg: {trends['cpu'].average_value:.3f})",
                    current_value=trends["cpu"].current_value,
                    threshold=trends["cpu"].average_value
                    + 2 * trends["cpu"].std_deviation,
                    score=trends["cpu"].anomaly_score,
                    recommendation=self._cpu_recommendation(trends["cpu"]),
                )
            )

        if trends["memory"].is_anomalous:
            alerts.append(
                AnomalyAlert(
                    anomaly_type=AnomalyType.MEMORY_SPIKE
                    if trends["memory"].trend_direction == "increasing"
                    else AnomalyType.UNUSUAL_PATTERN,
                    severity=self._severity_from_score(trends["memory"].anomaly_score),
                    workload_name=workload_name,
                    namespace=namespace,
                    container_name=container_name,
                    resource_type="memory",
                    description=f"Memory usage {trends['memory'].trend_direction}: "
                    f"{trends['memory'].current_value / (1024**3):.2f} GiB "
                    f"(avg: {trends['memory'].average_value / (1024**3):.2f} GiB)",
                    current_value=trends["memory"].current_value,
                    threshold=trends["memory"].average_value
                    + 2 * trends["memory"].std_deviation,
                    score=trends["memory"].anomaly_score,
                    recommendation=self._memory_recommendation(trends["memory"]),
                )
            )

        return WorkloadStatus(
            workload_name=workload_name,
            namespace=namespace,
            cpu_status=trends["cpu"],
            memory_status=trends["memory"],
            health_score=health_score,
            active_alerts=alerts,
        )

    def _severity_from_score(self, score: float) -> AlertSeverity:
        """Convert anomaly score to severity level."""
        if score >= 0.9:
            return AlertSeverity.CRITICAL
        elif score >= 0.7:
            return AlertSeverity.HIGH
        elif score >= 0.5:
            return AlertSeverity.MEDIUM
        else:
            return AlertSeverity.LOW

    def _cpu_recommendation(self, trend: TrendAnalysis) -> str:
        """Generate CPU-specific recommendation."""
        if trend.trend_direction == "increasing":
            return (
                "CPU usage is trending upward. Consider increasing CPU limits "
                "or investigating the workload for performance issues."
            )
        elif trend.is_anomalous:
            return (
                "Unusual CPU usage pattern detected. Review recent deployments "
                "or configuration changes."
            )
        return "Monitor CPU usage for continued stability."

    def _memory_recommendation(self, trend: TrendAnalysis) -> str:
        """Generate memory-specific recommendation."""
        if trend.trend_direction == "increasing":
            return (
                "Memory usage is trending upward. Check for memory leaks "
                "or consider increasing memory limits."
            )
        elif trend.is_anomalous:
            return (
                "Unusual memory usage pattern detected. Review application "
                "behavior and recent changes."
            )
        return "Monitor memory usage for continued stability."

    def _safe_query(self, promql: str) -> Optional[float]:
        """Execute a Prometheus query safely."""
        try:
            return self._client.query(promql)
        except MetricsCollectionError as e:
            logger.warning(f"Real-time metrics query failed: {e}")
            return None


class RealTimeAnomalyPipeline:
    """
    Real-time anomaly detection pipeline.

    Continuously monitors workloads and triggers alerts when anomalies
    are detected.
    """

    def __init__(
        self,
        prometheus_url: str = "http://prometheus:9090",
        default_window: TimeWindow = TimeWindow.FIFTEEN_MINUTES,
        alert_callback: Optional[Callable[[AnomalyAlert], None]] = None,
    ):
        """
        Initialize the anomaly detection pipeline.

        Args:
            prometheus_url: Prometheus server URL.
            default_window: Default time window for analysis.
            alert_callback: Optional callback for new alerts.
        """
        self._collector = StreamingMetricsCollector(
            prometheus_url=prometheus_url,
            default_window=default_window,
        )
        self._default_window = default_window
        self._alert_callback = alert_callback
        self._monitored_workloads: dict[str, dict] = {}
        self._active_alerts: dict[str, list[AnomalyAlert]] = {}

    def add_workload(
        self,
        namespace: str,
        workload_name: str,
        container_name: str,
    ) -> None:
        """
        Add a workload to the monitoring pipeline.

        Args:
            namespace: Kubernetes namespace.
            workload_name: Name of the workload.
            container_name: Name of the container.
        """
        key = f"{namespace}/{workload_name}/{container_name}"
        self._monitored_workloads[key] = {
            "namespace": namespace,
            "workload_name": workload_name,
            "container_name": container_name,
        }
        self._active_alerts[key] = []

    def remove_workload(
        self,
        namespace: str,
        workload_name: str,
        container_name: str,
    ) -> None:
        """Remove a workload from monitoring."""
        key = f"{namespace}/{workload_name}/{container_name}"
        self._monitored_workloads.pop(key, None)
        self._active_alerts.pop(key, None)

    def check_workload(
        self,
        namespace: str,
        workload_name: str,
        container_name: str,
        window: Optional[TimeWindow] = None,
    ) -> WorkloadStatus:
        """
        Check a workload for anomalies.

        Args:
            namespace: Kubernetes namespace.
            workload_name: Name of the workload.
            container_name: Name of the container.
            window: Time window for analysis.

        Returns:
            WorkloadStatus with current status and alerts.
        """
        status = self._collector.get_workload_status(
            namespace, workload_name, container_name, window
        )

        # Trigger callbacks for new alerts
        key = f"{namespace}/{workload_name}/{container_name}"
        if self._alert_callback:
            for alert in status.active_alerts:
                self._alert_callback(alert)

        self._active_alerts[key] = status.active_alerts
        return status

    def check_all_workloads(
        self,
        window: Optional[TimeWindow] = None,
    ) -> list[WorkloadStatus]:
        """
        Check all monitored workloads for anomalies.

        Args:
            window: Time window for analysis.

        Returns:
            List of WorkloadStatus for all monitored workloads.
        """
        statuses = []
        for workload in self._monitored_workloads.values():
            try:
                status = self.check_workload(
                    workload["namespace"],
                    workload["workload_name"],
                    workload["container_name"],
                    window,
                )
                statuses.append(status)
            except Exception as e:
                logger.error(f"Failed to check workload {workload}: {e}")
        return statuses

    def get_all_active_alerts(self) -> list[AnomalyAlert]:
        """Get all active alerts across all workloads."""
        alerts = []
        for workload_alerts in self._active_alerts.values():
            alerts.extend(workload_alerts)
        return alerts


class BackgroundMonitor:
    """
    Background task scheduler for continuous monitoring.

    Runs periodic checks on monitored workloads and manages
    the monitoring lifecycle.
    """

    def __init__(
        self,
        pipeline: RealTimeAnomalyPipeline,
        check_interval: int = 60,
    ):
        """
        Initialize the background monitor.

        Args:
            pipeline: The anomaly detection pipeline to use.
            check_interval: Seconds between checks.
        """
        self._pipeline = pipeline
        self._check_interval = check_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_check: Optional[datetime] = None
        self._check_count = 0

    def start(self) -> None:
        """Start the background monitoring thread."""
        if self._running:
            logger.warning("Background monitor already running")
            return

        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info(f"Background monitor started (interval: {self._check_interval}s)")

    def stop(self) -> None:
        """Stop the background monitoring thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Background monitor stopped")

    def _run(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                self._perform_check()
            except Exception as e:
                logger.error(f"Background check failed: {e}")

            time.sleep(self._check_interval)

    def _perform_check(self) -> None:
        """Perform a single monitoring check."""
        statuses = self._pipeline.check_all_workloads()
        self._last_check = datetime.now(timezone.utc)
        self._check_count += 1

        # Log summary
        total_alerts = sum(len(s.active_alerts) for s in statuses)
        if total_alerts > 0:
            logger.warning(
                f"Background check #{self._check_count}: "
                f"{len(statuses)} workloads, {total_alerts} active alerts"
            )
        else:
            logger.debug(
                f"Background check #{self._check_count}: "
                f"{len(statuses)} workloads, no alerts"
            )

    @property
    def is_running(self) -> bool:
        """Check if the monitor is running."""
        return self._running

    @property
    def last_check(self) -> Optional[datetime]:
        """Get the timestamp of the last check."""
        return self._last_check

    @property
    def check_count(self) -> int:
        """Get the number of checks performed."""
        return self._check_count


# Module-level instances
_streaming_collector: Optional[StreamingMetricsCollector] = None
_anomaly_pipeline: Optional[RealTimeAnomalyPipeline] = None
_background_monitor: Optional[BackgroundMonitor] = None


def get_streaming_collector(
    prometheus_url: Optional[str] = None,
) -> StreamingMetricsCollector:
    """Get or create the streaming metrics collector."""
    global _streaming_collector
    if _streaming_collector is None or prometheus_url:
        _streaming_collector = StreamingMetricsCollector(
            prometheus_url=prometheus_url or "http://prometheus:9090"
        )
    return _streaming_collector


def get_anomaly_pipeline(
    prometheus_url: Optional[str] = None,
    alert_callback: Optional[Callable[[AnomalyAlert], None]] = None,
) -> RealTimeAnomalyPipeline:
    """Get or create the anomaly detection pipeline."""
    global _anomaly_pipeline
    if _anomaly_pipeline is None or prometheus_url:
        _anomaly_pipeline = RealTimeAnomalyPipeline(
            prometheus_url=prometheus_url or "http://prometheus:9090",
            alert_callback=alert_callback,
        )
    return _anomaly_pipeline


def get_background_monitor(
    pipeline: Optional[RealTimeAnomalyPipeline] = None,
    check_interval: int = 60,
) -> BackgroundMonitor:
    """Get or create the background monitor."""
    global _background_monitor
    if _background_monitor is None:
        pipeline = pipeline or get_anomaly_pipeline()
        _background_monitor = BackgroundMonitor(pipeline, check_interval)
    return _background_monitor
