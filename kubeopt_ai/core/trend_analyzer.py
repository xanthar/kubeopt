"""
Historical trend analysis service for KubeOpt AI.

Provides functionality for collecting historical metrics, analyzing trends,
and generating capacity planning recommendations.
"""

import logging
import statistics
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass

from kubeopt_ai.extensions import db
from kubeopt_ai.core.models import (
    MetricsHistory,
    TrendAnalysis,
    TrendDirection,
)
from kubeopt_ai.core.metrics_collector import (
    PrometheusConfig,
    PrometheusClient,
)

logger = logging.getLogger(__name__)


class TrendAnalyzerError(Exception):
    """Exception raised for trend analysis errors."""
    pass


@dataclass
class TrendResult:
    """Result of a single metric trend analysis."""
    direction: TrendDirection
    slope: float
    avg: float
    p95: float
    max_val: float
    std_dev: float
    predicted_7d: float
    predicted_30d: float


class HistoryCollector:
    """
    Collects and stores historical metrics data.

    Periodically queries Prometheus and stores metrics for long-term
    trend analysis.
    """

    def __init__(
        self,
        prometheus_url: Optional[str] = None,
        timeout: int = 30
    ):
        """
        Initialize the history collector.

        Args:
            prometheus_url: Prometheus server URL.
            timeout: Request timeout in seconds.
        """
        config = PrometheusConfig(
            base_url=prometheus_url or "http://prometheus:9090",
            timeout=timeout,
        )
        self._client = PrometheusClient(config)

    def collect_snapshot(
        self,
        cluster_id: Optional[str],
        namespace: str,
        workload_name: str,
        workload_kind: str,
        container_name: str,
        timestamp: Optional[datetime] = None,
    ) -> MetricsHistory:
        """
        Collect a point-in-time metrics snapshot.

        Args:
            cluster_id: Optional cluster ID.
            namespace: Kubernetes namespace.
            workload_name: Workload name.
            workload_kind: Workload kind (Deployment, StatefulSet, etc.).
            container_name: Container name.
            timestamp: Timestamp for the snapshot (defaults to now).

        Returns:
            MetricsHistory record.
        """
        timestamp = timestamp or datetime.now(timezone.utc)

        # Query current metrics from Prometheus
        cpu_usage = self._query_metric(
            f'sum(rate(container_cpu_usage_seconds_total{{namespace="{namespace}",'
            f'pod=~"{workload_name}-.*",container="{container_name}"}}[5m]))'
        )

        memory_usage = self._query_metric(
            f'sum(container_memory_working_set_bytes{{namespace="{namespace}",'
            f'pod=~"{workload_name}-.*",container="{container_name}"}})'
        )

        # Query resource requests/limits
        cpu_request = self._query_metric(
            f'sum(kube_pod_container_resource_requests{{namespace="{namespace}",'
            f'pod=~"{workload_name}-.*",container="{container_name}",resource="cpu"}})'
        )

        cpu_limit = self._query_metric(
            f'sum(kube_pod_container_resource_limits{{namespace="{namespace}",'
            f'pod=~"{workload_name}-.*",container="{container_name}",resource="cpu"}})'
        )

        memory_request = self._query_metric(
            f'sum(kube_pod_container_resource_requests{{namespace="{namespace}",'
            f'pod=~"{workload_name}-.*",container="{container_name}",resource="memory"}})'
        )

        memory_limit = self._query_metric(
            f'sum(kube_pod_container_resource_limits{{namespace="{namespace}",'
            f'pod=~"{workload_name}-.*",container="{container_name}",resource="memory"}})'
        )

        # Query replica count
        replica_count = None
        if workload_kind == "Deployment":
            replica_count_float = self._query_metric(
                f'kube_deployment_spec_replicas{{namespace="{namespace}",deployment="{workload_name}"}}'
            )
            replica_count = int(replica_count_float) if replica_count_float else None

        # Create and store the record
        record = MetricsHistory(
            cluster_id=cluster_id,
            namespace=namespace,
            workload_name=workload_name,
            workload_kind=workload_kind,
            container_name=container_name,
            timestamp=timestamp,
            cpu_usage=cpu_usage,
            cpu_request=cpu_request,
            cpu_limit=cpu_limit,
            memory_usage=memory_usage,
            memory_request=memory_request,
            memory_limit=memory_limit,
            replica_count=replica_count,
        )

        db.session.add(record)
        db.session.commit()

        return record

    def _query_metric(self, promql: str) -> Optional[float]:
        """Query a single metric value from Prometheus."""
        try:
            return self._client.query(promql)
        except Exception as e:
            logger.warning(f"Metric query failed: {e}")
            return None

    def get_history(
        self,
        cluster_id: Optional[str],
        namespace: str,
        workload_name: str,
        container_name: str,
        start_time: datetime,
        end_time: Optional[datetime] = None,
    ) -> list[MetricsHistory]:
        """
        Get historical metrics for a workload container.

        Args:
            cluster_id: Optional cluster ID filter.
            namespace: Kubernetes namespace.
            workload_name: Workload name.
            container_name: Container name.
            start_time: Start of the time range.
            end_time: End of the time range (defaults to now).

        Returns:
            List of MetricsHistory records.
        """
        end_time = end_time or datetime.now(timezone.utc)

        query = MetricsHistory.query.filter(
            MetricsHistory.namespace == namespace,
            MetricsHistory.workload_name == workload_name,
            MetricsHistory.container_name == container_name,
            MetricsHistory.timestamp >= start_time,
            MetricsHistory.timestamp <= end_time,
        )

        if cluster_id:
            query = query.filter(MetricsHistory.cluster_id == cluster_id)

        return query.order_by(MetricsHistory.timestamp).all()


class TrendAnalyzer:
    """
    Analyzes historical metrics to identify trends and generate predictions.

    Uses statistical methods to detect trends, seasonality, and generate
    resource recommendations.
    """

    # Threshold for determining trend direction (slope per day)
    TREND_THRESHOLD = 0.01  # 1% change per day

    # Confidence thresholds
    MIN_DATA_POINTS = 10
    HIGH_CONFIDENCE_POINTS = 100

    def __init__(self):
        """Initialize the trend analyzer."""
        pass

    def analyze(
        self,
        cluster_id: Optional[str],
        namespace: str,
        workload_name: str,
        container_name: str,
        history: list[MetricsHistory],
    ) -> TrendAnalysis:
        """
        Analyze historical metrics and generate trend analysis.

        Args:
            cluster_id: Optional cluster ID.
            namespace: Kubernetes namespace.
            workload_name: Workload name.
            container_name: Container name.
            history: List of MetricsHistory records to analyze.

        Returns:
            TrendAnalysis with computed trends and recommendations.

        Raises:
            TrendAnalyzerError: If analysis fails.
        """
        if not history:
            raise TrendAnalyzerError("No historical data provided")

        if len(history) < 2:
            raise TrendAnalyzerError("Insufficient data points for trend analysis")

        # Extract CPU and memory time series
        cpu_values = [(h.timestamp, h.cpu_usage) for h in history if h.cpu_usage is not None]
        memory_values = [(h.timestamp, h.memory_usage) for h in history if h.memory_usage is not None]

        # Analyze CPU trend
        cpu_trend = self._analyze_metric_trend(cpu_values) if cpu_values else None

        # Analyze memory trend
        memory_trend = self._analyze_metric_trend(memory_values) if memory_values else None

        # Detect seasonality
        seasonality_detected, seasonality_period = self._detect_seasonality(cpu_values)

        # Calculate confidence score
        confidence = self._calculate_confidence(len(history), cpu_trend, memory_trend)

        # Generate recommendations
        cpu_rec_request, cpu_rec_limit = self._recommend_resources(
            cpu_trend, is_memory=False
        ) if cpu_trend else (None, None)

        memory_rec_request, memory_rec_limit = self._recommend_resources(
            memory_trend, is_memory=True
        ) if memory_trend else (None, None)

        # Determine analysis period
        start_time = min(h.timestamp for h in history)
        end_time = max(h.timestamp for h in history)

        # Create analysis record
        analysis = TrendAnalysis(
            cluster_id=cluster_id,
            namespace=namespace,
            workload_name=workload_name,
            container_name=container_name,
            analysis_period_start=start_time,
            analysis_period_end=end_time,
            # CPU trends
            cpu_trend_direction=cpu_trend.direction if cpu_trend else TrendDirection.STABLE,
            cpu_trend_slope=cpu_trend.slope if cpu_trend else None,
            cpu_avg=cpu_trend.avg if cpu_trend else None,
            cpu_p95=cpu_trend.p95 if cpu_trend else None,
            cpu_max=cpu_trend.max_val if cpu_trend else None,
            cpu_predicted_7d=cpu_trend.predicted_7d if cpu_trend else None,
            cpu_predicted_30d=cpu_trend.predicted_30d if cpu_trend else None,
            # Memory trends
            memory_trend_direction=memory_trend.direction if memory_trend else TrendDirection.STABLE,
            memory_trend_slope=memory_trend.slope if memory_trend else None,
            memory_avg=memory_trend.avg if memory_trend else None,
            memory_p95=memory_trend.p95 if memory_trend else None,
            memory_max=memory_trend.max_val if memory_trend else None,
            memory_predicted_7d=memory_trend.predicted_7d if memory_trend else None,
            memory_predicted_30d=memory_trend.predicted_30d if memory_trend else None,
            # Statistics
            cpu_std_dev=cpu_trend.std_dev if cpu_trend else None,
            memory_std_dev=memory_trend.std_dev if memory_trend else None,
            seasonality_detected=seasonality_detected,
            seasonality_period_hours=seasonality_period,
            # Recommendations
            recommended_cpu_request=cpu_rec_request,
            recommended_cpu_limit=cpu_rec_limit,
            recommended_memory_request=memory_rec_request,
            recommended_memory_limit=memory_rec_limit,
            confidence_score=confidence,
            data_points_count=len(history),
        )

        db.session.add(analysis)
        db.session.commit()

        return analysis

    def _analyze_metric_trend(
        self,
        time_series: list[tuple[datetime, float]]
    ) -> TrendResult:
        """
        Analyze a single metric's trend.

        Uses linear regression to determine trend direction and slope.

        Args:
            time_series: List of (timestamp, value) tuples.

        Returns:
            TrendResult with computed statistics.
        """
        if len(time_series) < 2:
            values = [v for _, v in time_series]
            avg_val = values[0] if values else 0
            return TrendResult(
                direction=TrendDirection.STABLE,
                slope=0.0,
                avg=avg_val,
                p95=avg_val,
                max_val=avg_val,
                std_dev=0.0,
                predicted_7d=avg_val,
                predicted_30d=avg_val,
            )

        # Extract values and compute timestamps as hours from start
        start_time = time_series[0][0]
        x_values = [(ts - start_time).total_seconds() / 3600 for ts, _ in time_series]
        y_values = [v for _, v in time_series]

        # Compute basic statistics
        avg_val = statistics.mean(y_values)
        max_val = max(y_values)
        std_dev = statistics.stdev(y_values) if len(y_values) > 1 else 0.0

        # Compute P95
        sorted_values = sorted(y_values)
        p95_idx = int(len(sorted_values) * 0.95)
        p95_val = sorted_values[min(p95_idx, len(sorted_values) - 1)]

        # Linear regression for trend
        slope, intercept = self._linear_regression(x_values, y_values)

        # Determine trend direction based on slope
        # Normalize slope by average value for percentage-based threshold
        normalized_slope = (slope * 24) / avg_val if avg_val > 0 else 0  # slope per day as % of avg

        if abs(normalized_slope) < self.TREND_THRESHOLD:
            direction = TrendDirection.STABLE
        elif normalized_slope > 0:
            direction = TrendDirection.INCREASING
        else:
            direction = TrendDirection.DECREASING

        # Check for volatility (high std dev relative to mean)
        if std_dev > avg_val * 0.5:  # More than 50% variation
            direction = TrendDirection.VOLATILE

        # Predict future values
        total_hours = x_values[-1] if x_values else 0
        predicted_7d = max(0, intercept + slope * (total_hours + 24 * 7))
        predicted_30d = max(0, intercept + slope * (total_hours + 24 * 30))

        return TrendResult(
            direction=direction,
            slope=slope,
            avg=avg_val,
            p95=p95_val,
            max_val=max_val,
            std_dev=std_dev,
            predicted_7d=predicted_7d,
            predicted_30d=predicted_30d,
        )

    def _linear_regression(
        self,
        x: list[float],
        y: list[float]
    ) -> tuple[float, float]:
        """
        Simple linear regression to find slope and intercept.

        Args:
            x: Independent variable values.
            y: Dependent variable values.

        Returns:
            Tuple of (slope, intercept).
        """
        n = len(x)
        if n < 2:
            return 0.0, y[0] if y else 0.0

        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(xi * yi for xi, yi in zip(x, y))
        sum_x2 = sum(xi ** 2 for xi in x)

        denominator = n * sum_x2 - sum_x ** 2
        if abs(denominator) < 1e-10:
            return 0.0, sum_y / n

        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n

        return slope, intercept

    def _detect_seasonality(
        self,
        time_series: list[tuple[datetime, float]],
    ) -> tuple[bool, Optional[int]]:
        """
        Detect seasonality in the time series.

        Uses autocorrelation to detect periodic patterns.

        Args:
            time_series: List of (timestamp, value) tuples.

        Returns:
            Tuple of (seasonality_detected, period_hours).
        """
        if len(time_series) < 48:  # Need at least 2 days of data
            return False, None

        # Simple approach: check for daily pattern (24h) or weekly (168h)
        values = [v for _, v in time_series]

        # Check 24-hour autocorrelation
        daily_corr = self._autocorrelation(values, 24)

        if daily_corr > 0.5:  # Strong daily pattern
            return True, 24

        # Check 168-hour (weekly) autocorrelation
        if len(values) > 168:
            weekly_corr = self._autocorrelation(values, 168)
            if weekly_corr > 0.5:
                return True, 168

        return False, None

    def _autocorrelation(self, values: list[float], lag: int) -> float:
        """Compute autocorrelation at a given lag."""
        if len(values) <= lag:
            return 0.0

        n = len(values) - lag
        mean = statistics.mean(values)
        var = statistics.variance(values) if len(values) > 1 else 1.0

        if var == 0:
            return 0.0

        numerator = sum(
            (values[i] - mean) * (values[i + lag] - mean)
            for i in range(n)
        ) / n

        return numerator / var

    def _calculate_confidence(
        self,
        data_points: int,
        cpu_trend: Optional[TrendResult],
        memory_trend: Optional[TrendResult],
    ) -> float:
        """Calculate confidence score for the analysis."""
        if data_points < self.MIN_DATA_POINTS:
            return 0.0

        # Base confidence from data points
        base_confidence = min(1.0, data_points / self.HIGH_CONFIDENCE_POINTS)

        # Adjust for stability
        stability_factor = 1.0
        if cpu_trend and cpu_trend.direction == TrendDirection.VOLATILE:
            stability_factor *= 0.7
        if memory_trend and memory_trend.direction == TrendDirection.VOLATILE:
            stability_factor *= 0.7

        return round(base_confidence * stability_factor, 2)

    def _recommend_resources(
        self,
        trend: TrendResult,
        is_memory: bool = False,
    ) -> tuple[Optional[float], Optional[float]]:
        """
        Generate resource recommendations based on trend analysis.

        Args:
            trend: The trend analysis result.
            is_memory: Whether this is memory (affects rounding).

        Returns:
            Tuple of (recommended_request, recommended_limit).
        """
        # Request: P95 value with headroom
        request = trend.p95 * 1.1  # 10% headroom

        # Limit: Max value with headroom, or predicted 7d value (whichever is higher)
        limit = max(trend.max_val, trend.predicted_7d) * 1.2  # 20% headroom

        if is_memory:
            # Round memory to nearest MiB
            mib = 1024 * 1024
            request = round(request / mib) * mib
            limit = round(limit / mib) * mib

        return request, limit

    def get_latest_analysis(
        self,
        cluster_id: Optional[str],
        namespace: str,
        workload_name: str,
        container_name: str,
    ) -> Optional[TrendAnalysis]:
        """Get the most recent trend analysis for a workload."""
        query = TrendAnalysis.query.filter(
            TrendAnalysis.namespace == namespace,
            TrendAnalysis.workload_name == workload_name,
            TrendAnalysis.container_name == container_name,
        )

        if cluster_id:
            query = query.filter(TrendAnalysis.cluster_id == cluster_id)

        return query.order_by(TrendAnalysis.created_at.desc()).first()

    def list_analyses(
        self,
        cluster_id: Optional[str] = None,
        namespace: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[TrendAnalysis]:
        """List trend analyses with optional filters."""
        query = TrendAnalysis.query

        if cluster_id:
            query = query.filter(TrendAnalysis.cluster_id == cluster_id)
        if namespace:
            query = query.filter(TrendAnalysis.namespace == namespace)

        return query.order_by(TrendAnalysis.created_at.desc()).offset(offset).limit(limit).all()


# Module-level instances
_collector: Optional[HistoryCollector] = None
_analyzer: Optional[TrendAnalyzer] = None


def get_history_collector(prometheus_url: Optional[str] = None) -> HistoryCollector:
    """Get or create the history collector instance."""
    global _collector
    if _collector is None or prometheus_url:
        _collector = HistoryCollector(prometheus_url)
    return _collector


def get_trend_analyzer() -> TrendAnalyzer:
    """Get or create the trend analyzer instance."""
    global _analyzer
    if _analyzer is None:
        _analyzer = TrendAnalyzer()
    return _analyzer
