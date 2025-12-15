"""
Workload Anomaly Detection for KubeOpt AI.

This module provides ML-based detection of abnormal resource usage patterns
in Kubernetes workloads. It uses statistical analysis to identify:
- Memory leaks (steadily increasing memory usage)
- CPU spikes (sudden usage increases)
- Resource drift (gradual divergence from baseline)
- Unusual patterns (outliers and anomalies)

Detection algorithms:
- Z-Score for point anomalies
- IQR (Interquartile Range) for outlier detection
- Rolling averages for trend analysis
- Linear regression for drift detection
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional
from statistics import mean, stdev, median, quantiles

import requests

logger = logging.getLogger(__name__)


class AnomalyType(str, Enum):
    """Types of detected anomalies."""
    MEMORY_LEAK = "memory_leak"
    CPU_SPIKE = "cpu_spike"
    MEMORY_SPIKE = "memory_spike"
    CPU_DRIFT = "cpu_drift"
    MEMORY_DRIFT = "memory_drift"
    RESOURCE_UNDERUTILIZATION = "resource_underutilization"
    RESOURCE_SATURATION = "resource_saturation"
    UNUSUAL_PATTERN = "unusual_pattern"


class AlertSeverity(str, Enum):
    """Severity levels for anomaly alerts."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class DataPoint:
    """A single time-series data point."""
    timestamp: datetime
    value: float


@dataclass
class AnomalyAlert:
    """An anomaly detection alert."""
    anomaly_type: AnomalyType
    severity: AlertSeverity
    workload_name: str
    namespace: str
    container_name: str
    resource_type: str  # 'cpu' or 'memory'
    description: str
    current_value: float
    threshold: float
    score: float  # Anomaly score (e.g., Z-score)
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    recommendation: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class AnomalyAnalysis:
    """Complete anomaly analysis for a workload."""
    workload_name: str
    namespace: str
    analysis_period_hours: int
    alerts: list[AnomalyAlert]
    health_score: float  # 0-100, 100 being healthy
    analyzed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class StatisticalAnalyzer:
    """Statistical methods for anomaly detection."""

    @staticmethod
    def z_score(value: float, data: list[float]) -> float:
        """
        Calculate Z-score for a value against a dataset.

        Z-score measures how many standard deviations a value is from the mean.
        |Z| > 2 suggests unusual, |Z| > 3 suggests anomaly.

        Args:
            value: The value to score.
            data: Historical data points.

        Returns:
            Z-score (0 if insufficient data).
        """
        if len(data) < 2:
            return 0.0

        data_mean = mean(data)
        data_stdev = stdev(data)

        if data_stdev == 0:
            return 0.0

        return (value - data_mean) / data_stdev

    @staticmethod
    def iqr_outlier_bounds(data: list[float], k: float = 1.5) -> tuple[float, float]:
        """
        Calculate IQR-based outlier bounds.

        Values outside [Q1 - k*IQR, Q3 + k*IQR] are outliers.

        Args:
            data: Dataset to analyze.
            k: Multiplier for IQR (1.5 for outliers, 3.0 for extreme).

        Returns:
            Tuple of (lower_bound, upper_bound).
        """
        if len(data) < 4:
            return (min(data) if data else 0, max(data) if data else 0)

        q1, q3 = quantiles(data, n=4)[0], quantiles(data, n=4)[2]
        iqr = q3 - q1

        lower = q1 - k * iqr
        upper = q3 + k * iqr

        return (lower, upper)

    @staticmethod
    def linear_trend(data: list[float]) -> tuple[float, float]:
        """
        Calculate linear trend (slope and intercept) using least squares.

        Args:
            data: Time series values (assumed equal spacing).

        Returns:
            Tuple of (slope, intercept). Slope > 0 means increasing trend.
        """
        n = len(data)
        if n < 2:
            return (0.0, 0.0)

        x_values = list(range(n))
        x_mean = mean(x_values)
        y_mean = mean(data)

        numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, data))
        denominator = sum((x - x_mean) ** 2 for x in x_values)

        if denominator == 0:
            return (0.0, y_mean)

        slope = numerator / denominator
        intercept = y_mean - slope * x_mean

        return (slope, intercept)

    @staticmethod
    def rolling_mean(data: list[float], window: int) -> list[float]:
        """
        Calculate rolling mean with given window size.

        Args:
            data: Input data series.
            window: Window size.

        Returns:
            List of rolling mean values.
        """
        if len(data) < window:
            return [mean(data)] if data else []

        result = []
        for i in range(len(data) - window + 1):
            window_data = data[i:i + window]
            result.append(mean(window_data))

        return result

    @staticmethod
    def coefficient_of_variation(data: list[float]) -> float:
        """
        Calculate coefficient of variation (CV).

        CV = stdev / mean. Higher values indicate more variability.

        Args:
            data: Dataset to analyze.

        Returns:
            CV value (0 if insufficient data or mean is 0).
        """
        if len(data) < 2:
            return 0.0

        data_mean = mean(data)
        if data_mean == 0:
            return 0.0

        return stdev(data) / data_mean


class AnomalyDetector:
    """
    Detect anomalies in Kubernetes workload metrics.

    Uses multiple statistical techniques to identify various
    types of resource anomalies.
    """

    # Thresholds for anomaly detection
    Z_SCORE_WARNING = 2.0
    Z_SCORE_CRITICAL = 3.0

    MEMORY_LEAK_SLOPE_THRESHOLD = 0.01  # 1% increase per data point
    MEMORY_LEAK_MIN_INCREASE_PERCENT = 10  # Min 10% total increase

    SPIKE_Z_THRESHOLD = 2.5
    DRIFT_PERCENT_THRESHOLD = 20  # 20% drift from baseline

    UNDERUTILIZATION_THRESHOLD = 0.2  # Using < 20% of requests
    SATURATION_THRESHOLD = 0.9  # Using > 90% of limits

    def __init__(self, prometheus_url: Optional[str] = None):
        """
        Initialize the anomaly detector.

        Args:
            prometheus_url: URL for Prometheus server.
        """
        self.prometheus_url = prometheus_url
        self.analyzer = StatisticalAnalyzer()

    def _query_prometheus_range(
        self,
        query: str,
        hours: int = 24,
        step: str = "5m",
    ) -> list[DataPoint]:
        """
        Query Prometheus for range data.

        Args:
            query: PromQL query.
            hours: Number of hours to look back.
            step: Resolution step.

        Returns:
            List of DataPoint objects.
        """
        if not self.prometheus_url:
            return []

        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=hours)

        try:
            response = requests.get(
                f"{self.prometheus_url}/api/v1/query_range",
                params={
                    "query": query,
                    "start": start_time.timestamp(),
                    "end": end_time.timestamp(),
                    "step": step,
                },
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()

            points = []
            if data.get("status") == "success":
                results = data.get("data", {}).get("result", [])
                if results:
                    for ts, val in results[0].get("values", []):
                        points.append(DataPoint(
                            timestamp=datetime.fromtimestamp(ts, tz=timezone.utc),
                            value=float(val),
                        ))

            return points

        except Exception as e:
            logger.warning(f"Prometheus query failed: {e}")
            return []

    def detect_memory_leak(
        self,
        data_points: list[float],
        workload_name: str,
        namespace: str,
        container_name: str,
    ) -> Optional[AnomalyAlert]:
        """
        Detect memory leak patterns (steadily increasing memory usage).

        Args:
            data_points: Memory usage values over time.
            workload_name: Name of workload.
            namespace: Kubernetes namespace.
            container_name: Container name.

        Returns:
            AnomalyAlert if leak detected, None otherwise.
        """
        if len(data_points) < 10:
            return None

        slope, _ = self.analyzer.linear_trend(data_points)

        # Normalize slope to percentage of mean
        data_mean = mean(data_points)
        if data_mean == 0:
            return None

        normalized_slope = slope / data_mean

        # Check if there's a consistent upward trend
        if normalized_slope < self.MEMORY_LEAK_SLOPE_THRESHOLD:
            return None

        # Verify total increase percentage
        total_increase = (data_points[-1] - data_points[0]) / data_points[0] * 100
        if total_increase < self.MEMORY_LEAK_MIN_INCREASE_PERCENT:
            return None

        # Determine severity based on slope
        if normalized_slope > 0.05:  # 5% per point
            severity = AlertSeverity.CRITICAL
        elif normalized_slope > 0.03:  # 3% per point
            severity = AlertSeverity.HIGH
        elif normalized_slope > 0.02:  # 2% per point
            severity = AlertSeverity.MEDIUM
        else:
            severity = AlertSeverity.LOW

        return AnomalyAlert(
            anomaly_type=AnomalyType.MEMORY_LEAK,
            severity=severity,
            workload_name=workload_name,
            namespace=namespace,
            container_name=container_name,
            resource_type="memory",
            description=(
                f"Potential memory leak detected: memory usage increased "
                f"{total_increase:.1f}% over the analysis period with "
                f"consistent upward trend (slope: {normalized_slope:.4f})"
            ),
            current_value=data_points[-1],
            threshold=data_points[0] * (1 + self.MEMORY_LEAK_MIN_INCREASE_PERCENT / 100),
            score=normalized_slope,
            recommendation=(
                "Investigate for memory leaks. Consider profiling the application, "
                "reviewing recent code changes, and checking for unclosed resources "
                "or growing caches."
            ),
            metadata={
                "slope": slope,
                "normalized_slope": normalized_slope,
                "total_increase_percent": total_increase,
                "start_value": data_points[0],
                "end_value": data_points[-1],
            },
        )

    def detect_spike(
        self,
        data_points: list[float],
        workload_name: str,
        namespace: str,
        container_name: str,
        resource_type: str,
    ) -> Optional[AnomalyAlert]:
        """
        Detect resource spikes (sudden usage increases).

        Args:
            data_points: Resource usage values.
            workload_name: Name of workload.
            namespace: Kubernetes namespace.
            container_name: Container name.
            resource_type: 'cpu' or 'memory'.

        Returns:
            AnomalyAlert if spike detected, None otherwise.
        """
        if len(data_points) < 5:
            return None

        # Use recent value vs baseline
        recent_values = data_points[-3:]
        baseline_values = data_points[:-3]

        if not baseline_values:
            return None

        recent_avg = mean(recent_values)
        z_score = self.analyzer.z_score(recent_avg, baseline_values)

        if abs(z_score) < self.SPIKE_Z_THRESHOLD:
            return None

        # Determine severity
        if abs(z_score) > 4.0:
            severity = AlertSeverity.CRITICAL
        elif abs(z_score) > 3.0:
            severity = AlertSeverity.HIGH
        else:
            severity = AlertSeverity.MEDIUM

        anomaly_type = (
            AnomalyType.CPU_SPIKE if resource_type == "cpu"
            else AnomalyType.MEMORY_SPIKE
        )

        return AnomalyAlert(
            anomaly_type=anomaly_type,
            severity=severity,
            workload_name=workload_name,
            namespace=namespace,
            container_name=container_name,
            resource_type=resource_type,
            description=(
                f"{resource_type.upper()} spike detected: recent usage "
                f"({recent_avg:.2f}) is {abs(z_score):.1f} standard deviations "
                f"from the baseline (mean: {mean(baseline_values):.2f})"
            ),
            current_value=recent_avg,
            threshold=mean(baseline_values) + self.SPIKE_Z_THRESHOLD * stdev(baseline_values),
            score=z_score,
            recommendation=(
                f"Investigate the cause of the {resource_type} spike. Check for "
                f"traffic increases, inefficient code paths, or external factors. "
                f"Consider scaling or adding resource limits if spikes are expected."
            ),
            metadata={
                "z_score": z_score,
                "baseline_mean": mean(baseline_values),
                "baseline_stdev": stdev(baseline_values),
                "recent_mean": recent_avg,
            },
        )

    def detect_underutilization(
        self,
        usage_value: float,
        request_value: float,
        workload_name: str,
        namespace: str,
        container_name: str,
        resource_type: str,
    ) -> Optional[AnomalyAlert]:
        """
        Detect resource underutilization.

        Args:
            usage_value: Average usage value.
            request_value: Requested resource value.
            workload_name: Name of workload.
            namespace: Kubernetes namespace.
            container_name: Container name.
            resource_type: 'cpu' or 'memory'.

        Returns:
            AnomalyAlert if underutilization detected, None otherwise.
        """
        if request_value <= 0:
            return None

        utilization_ratio = usage_value / request_value

        if utilization_ratio >= self.UNDERUTILIZATION_THRESHOLD:
            return None

        # Determine severity based on waste
        if utilization_ratio < 0.05:  # < 5%
            severity = AlertSeverity.HIGH
        elif utilization_ratio < 0.1:  # < 10%
            severity = AlertSeverity.MEDIUM
        else:
            severity = AlertSeverity.LOW

        wasted_percent = (1 - utilization_ratio) * 100

        return AnomalyAlert(
            anomaly_type=AnomalyType.RESOURCE_UNDERUTILIZATION,
            severity=severity,
            workload_name=workload_name,
            namespace=namespace,
            container_name=container_name,
            resource_type=resource_type,
            description=(
                f"{resource_type.upper()} underutilization: only using "
                f"{utilization_ratio:.1%} of requested {resource_type} "
                f"({usage_value:.4f} of {request_value:.4f}). "
                f"Wasting {wasted_percent:.1f}% of allocated resources."
            ),
            current_value=usage_value,
            threshold=request_value * self.UNDERUTILIZATION_THRESHOLD,
            score=1 - utilization_ratio,
            recommendation=(
                f"Consider reducing {resource_type} requests to match actual usage "
                f"with headroom. This could save costs without impacting performance."
            ),
            metadata={
                "utilization_ratio": utilization_ratio,
                "wasted_percent": wasted_percent,
                "request_value": request_value,
            },
        )

    def detect_saturation(
        self,
        usage_value: float,
        limit_value: float,
        workload_name: str,
        namespace: str,
        container_name: str,
        resource_type: str,
    ) -> Optional[AnomalyAlert]:
        """
        Detect resource saturation (approaching limits).

        Args:
            usage_value: Average/p95 usage value.
            limit_value: Resource limit value.
            workload_name: Name of workload.
            namespace: Kubernetes namespace.
            container_name: Container name.
            resource_type: 'cpu' or 'memory'.

        Returns:
            AnomalyAlert if saturation detected, None otherwise.
        """
        if limit_value <= 0:
            return None

        utilization_ratio = usage_value / limit_value

        if utilization_ratio < self.SATURATION_THRESHOLD:
            return None

        # Determine severity
        if utilization_ratio >= 0.99:
            severity = AlertSeverity.CRITICAL
        elif utilization_ratio >= 0.95:
            severity = AlertSeverity.HIGH
        else:
            severity = AlertSeverity.MEDIUM

        return AnomalyAlert(
            anomaly_type=AnomalyType.RESOURCE_SATURATION,
            severity=severity,
            workload_name=workload_name,
            namespace=namespace,
            container_name=container_name,
            resource_type=resource_type,
            description=(
                f"{resource_type.upper()} saturation: using {utilization_ratio:.1%} "
                f"of limit ({usage_value:.4f} of {limit_value:.4f}). "
                f"Risk of throttling or OOM."
            ),
            current_value=usage_value,
            threshold=limit_value * self.SATURATION_THRESHOLD,
            score=utilization_ratio,
            recommendation=(
                f"Increase {resource_type} limits to prevent throttling/OOM. "
                f"Consider vertical scaling or horizontal pod autoscaling."
            ),
            metadata={
                "utilization_ratio": utilization_ratio,
                "limit_value": limit_value,
            },
        )

    def analyze_workload(
        self,
        workload_name: str,
        namespace: str,
        container_metrics: list[dict],
        container_configs: list[dict],
        hours: int = 24,
    ) -> AnomalyAnalysis:
        """
        Perform comprehensive anomaly analysis for a workload.

        Args:
            workload_name: Name of the workload.
            namespace: Kubernetes namespace.
            container_metrics: List of container metrics dicts.
            container_configs: List of container config dicts with resources.
            hours: Analysis period in hours.

        Returns:
            AnomalyAnalysis with all detected anomalies.
        """
        alerts = []

        # Create lookup for container configs
        config_lookup = {c.get("name"): c for c in container_configs}

        for metrics in container_metrics:
            container_name = metrics.get("container_name", "unknown")
            config = config_lookup.get(container_name, {})
            resources = config.get("resources", {})
            requests = resources.get("requests", {})
            limits = resources.get("limits", {})

            # CPU analysis
            avg_cpu = metrics.get("avg_cpu_usage")
            p95_cpu = metrics.get("p95_cpu_usage")
            max_cpu = metrics.get("max_cpu_usage")

            if avg_cpu is not None:
                # Check CPU underutilization
                cpu_request = self._parse_cpu(requests.get("cpu"))
                if cpu_request > 0:
                    alert = self.detect_underutilization(
                        avg_cpu, cpu_request,
                        workload_name, namespace, container_name, "cpu"
                    )
                    if alert:
                        alerts.append(alert)

                # Check CPU saturation
                cpu_limit = self._parse_cpu(limits.get("cpu"))
                if cpu_limit > 0 and p95_cpu is not None:
                    alert = self.detect_saturation(
                        p95_cpu, cpu_limit,
                        workload_name, namespace, container_name, "cpu"
                    )
                    if alert:
                        alerts.append(alert)

            # Memory analysis
            avg_mem = metrics.get("avg_memory_usage")
            p95_mem = metrics.get("p95_memory_usage")
            max_mem = metrics.get("max_memory_usage")

            if avg_mem is not None:
                # Check memory underutilization
                mem_request = self._parse_memory(requests.get("memory"))
                if mem_request > 0:
                    alert = self.detect_underutilization(
                        avg_mem, mem_request,
                        workload_name, namespace, container_name, "memory"
                    )
                    if alert:
                        alerts.append(alert)

                # Check memory saturation
                mem_limit = self._parse_memory(limits.get("memory"))
                if mem_limit > 0 and p95_mem is not None:
                    alert = self.detect_saturation(
                        p95_mem, mem_limit,
                        workload_name, namespace, container_name, "memory"
                    )
                    if alert:
                        alerts.append(alert)

        # Calculate health score (100 = healthy, decreases with alerts)
        health_score = self._calculate_health_score(alerts)

        return AnomalyAnalysis(
            workload_name=workload_name,
            namespace=namespace,
            analysis_period_hours=hours,
            alerts=alerts,
            health_score=health_score,
        )

    def _parse_cpu(self, cpu_str: Optional[str]) -> float:
        """Parse CPU string to cores."""
        if not cpu_str:
            return 0.0

        cpu_str = str(cpu_str).strip()
        if cpu_str.endswith("m"):
            return float(cpu_str[:-1]) / 1000
        return float(cpu_str)

    def _parse_memory(self, mem_str: Optional[str]) -> float:
        """Parse memory string to bytes."""
        if not mem_str:
            return 0.0

        mem_str = str(mem_str).strip()
        multipliers = {
            "Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4,
            "K": 1000, "M": 1000**2, "G": 1000**3, "T": 1000**4,
        }

        for suffix, mult in multipliers.items():
            if mem_str.endswith(suffix):
                return float(mem_str[:-len(suffix)]) * mult

        return float(mem_str)

    def _calculate_health_score(self, alerts: list[AnomalyAlert]) -> float:
        """Calculate health score based on alerts."""
        if not alerts:
            return 100.0

        # Deduct points based on severity
        deductions = {
            AlertSeverity.CRITICAL: 30,
            AlertSeverity.HIGH: 20,
            AlertSeverity.MEDIUM: 10,
            AlertSeverity.LOW: 5,
        }

        total_deduction = sum(
            deductions.get(alert.severity, 5) for alert in alerts
        )

        return max(0.0, 100.0 - total_deduction)


def analyze_optimization_run_anomalies(
    optimization_run_details: dict,
    prometheus_url: Optional[str] = None,
) -> list[AnomalyAnalysis]:
    """
    Analyze anomalies for all workloads in an optimization run.

    Args:
        optimization_run_details: Details dict from OptimizerService.get_run_details()
        prometheus_url: Optional Prometheus URL for time-series analysis.

    Returns:
        List of AnomalyAnalysis objects, one per workload.
    """
    detector = AnomalyDetector(prometheus_url=prometheus_url)
    analyses = []

    for workload in optimization_run_details.get("workloads", []):
        workload_name = workload.get("name", "unknown")
        namespace = workload.get("namespace", "default")
        current_config = workload.get("current_config", {})
        metrics_summary = workload.get("metrics_summary", {})

        containers = current_config.get("containers", [])
        container_metrics = metrics_summary.get("container_metrics", [])

        analysis = detector.analyze_workload(
            workload_name=workload_name,
            namespace=namespace,
            container_metrics=container_metrics,
            container_configs=containers,
        )
        analyses.append(analysis)

    return analyses
