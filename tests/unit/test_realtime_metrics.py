"""
Unit tests for real-time metrics streaming.
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, MagicMock

from kubeopt_ai.core.realtime_metrics import (
    TimeWindow,
    MetricDataPoint,
    MetricStream,
    TrendAnalysis,
    WorkloadStatus,
    StreamingMetricsCollector,
    RealTimeAnomalyPipeline,
    BackgroundMonitor,
    RealTimePromQLQueries,
)
from kubeopt_ai.core.anomaly_detection import AnomalyAlert, AnomalyType, AlertSeverity


class TestTimeWindow:
    """Tests for TimeWindow enum."""

    def test_time_window_values(self):
        """Test all time window values."""
        assert TimeWindow.FIVE_MINUTES.value == "5m"
        assert TimeWindow.FIFTEEN_MINUTES.value == "15m"
        assert TimeWindow.THIRTY_MINUTES.value == "30m"
        assert TimeWindow.ONE_HOUR.value == "1h"
        assert TimeWindow.SIX_HOURS.value == "6h"
        assert TimeWindow.TWELVE_HOURS.value == "12h"
        assert TimeWindow.TWENTY_FOUR_HOURS.value == "24h"

    def test_time_window_seconds(self):
        """Test time window seconds conversion."""
        assert TimeWindow.FIVE_MINUTES.seconds == 300
        assert TimeWindow.FIFTEEN_MINUTES.seconds == 900
        assert TimeWindow.THIRTY_MINUTES.seconds == 1800
        assert TimeWindow.ONE_HOUR.seconds == 3600
        assert TimeWindow.SIX_HOURS.seconds == 21600
        assert TimeWindow.TWELVE_HOURS.seconds == 43200
        assert TimeWindow.TWENTY_FOUR_HOURS.seconds == 86400


class TestMetricDataPoint:
    """Tests for MetricDataPoint dataclass."""

    def test_create_data_point(self):
        """Test creating a metric data point."""
        now = datetime.now(timezone.utc)
        point = MetricDataPoint(timestamp=now, value=1.5)

        assert point.timestamp == now
        assert point.value == 1.5
        assert point.labels == {}

    def test_create_data_point_with_labels(self):
        """Test creating a data point with labels."""
        now = datetime.now(timezone.utc)
        labels = {"namespace": "default", "pod": "test-pod"}
        point = MetricDataPoint(timestamp=now, value=2.0, labels=labels)

        assert point.labels == labels


class TestMetricStream:
    """Tests for MetricStream dataclass."""

    def test_create_stream(self):
        """Test creating a metric stream."""
        stream = MetricStream(
            metric_name="cpu",
            namespace="default",
            workload_name="test-deploy",
            container_name="main",
        )

        assert stream.metric_name == "cpu"
        assert stream.namespace == "default"
        assert stream.workload_name == "test-deploy"
        assert stream.container_name == "main"
        assert stream.window_size == 100

    def test_add_data_point(self):
        """Test adding data points to stream."""
        stream = MetricStream(
            metric_name="cpu",
            namespace="default",
            workload_name="test-deploy",
            container_name="main",
        )

        now = datetime.now(timezone.utc)
        point = MetricDataPoint(timestamp=now, value=0.5)
        stream.add(point)

        assert len(stream.data) == 1
        assert stream.get_values() == [0.5]

    def test_get_latest(self):
        """Test getting latest data points."""
        stream = MetricStream(
            metric_name="cpu",
            namespace="default",
            workload_name="test-deploy",
            container_name="main",
        )

        now = datetime.now(timezone.utc)
        for i in range(5):
            point = MetricDataPoint(
                timestamp=now + timedelta(seconds=i),
                value=float(i),
            )
            stream.add(point)

        latest = stream.get_latest(3)
        assert len(latest) == 3
        assert [p.value for p in latest] == [2.0, 3.0, 4.0]

    def test_get_window(self):
        """Test getting data points within time window."""
        stream = MetricStream(
            metric_name="cpu",
            namespace="default",
            workload_name="test-deploy",
            container_name="main",
        )

        now = datetime.now(timezone.utc)
        # Add points from 10 minutes ago to now
        for i in range(11):
            point = MetricDataPoint(
                timestamp=now - timedelta(minutes=10 - i),
                value=float(i),
            )
            stream.add(point)

        # Get 5-minute window
        window_data = stream.get_window(TimeWindow.FIVE_MINUTES)
        assert len(window_data) >= 5  # Should have at least 5 points

    def test_window_size_limit(self):
        """Test that stream respects window size limit."""
        stream = MetricStream(
            metric_name="cpu",
            namespace="default",
            workload_name="test-deploy",
            container_name="main",
            window_size=5,
        )

        now = datetime.now(timezone.utc)
        for i in range(10):
            point = MetricDataPoint(timestamp=now, value=float(i))
            stream.add(point)

        assert len(stream.data) == 5
        # Should keep the latest values
        assert stream.get_values() == [5.0, 6.0, 7.0, 8.0, 9.0]

    def test_clear(self):
        """Test clearing the stream."""
        stream = MetricStream(
            metric_name="cpu",
            namespace="default",
            workload_name="test-deploy",
            container_name="main",
        )

        now = datetime.now(timezone.utc)
        stream.add(MetricDataPoint(timestamp=now, value=1.0))
        stream.add(MetricDataPoint(timestamp=now, value=2.0))

        stream.clear()
        assert len(stream.data) == 0


class TestTrendAnalysis:
    """Tests for TrendAnalysis dataclass."""

    def test_create_trend_analysis(self):
        """Test creating a trend analysis."""
        trend = TrendAnalysis(
            metric_name="cpu",
            current_value=0.5,
            average_value=0.4,
            std_deviation=0.1,
            trend_direction="increasing",
            trend_rate=0.02,
            window=TimeWindow.FIFTEEN_MINUTES,
            is_anomalous=False,
        )

        assert trend.metric_name == "cpu"
        assert trend.current_value == 0.5
        assert trend.average_value == 0.4
        assert trend.std_deviation == 0.1
        assert trend.trend_direction == "increasing"
        assert not trend.is_anomalous


class TestRealTimePromQLQueries:
    """Tests for PromQL query templates."""

    def test_instant_cpu_query(self):
        """Test instant CPU query template."""
        query = RealTimePromQLQueries.INSTANT_CPU.format(
            namespace="default",
            workload_name="test-deploy",
            container_name="main",
        )

        assert "container_cpu_usage_seconds_total" in query
        assert 'namespace="default"' in query
        assert 'pod=~"test-deploy-.*"' in query
        assert 'container="main"' in query

    def test_instant_memory_query(self):
        """Test instant memory query template."""
        query = RealTimePromQLQueries.INSTANT_MEMORY.format(
            namespace="default",
            workload_name="test-deploy",
            container_name="main",
        )

        assert "container_memory_working_set_bytes" in query
        assert 'namespace="default"' in query

    def test_cpu_trend_query(self):
        """Test CPU trend query template."""
        query = RealTimePromQLQueries.CPU_TREND.format(
            namespace="default",
            workload_name="test-deploy",
            container_name="main",
            window="15m",
        )

        assert "deriv" in query
        assert "[15m:1m]" in query

    def test_memory_trend_query(self):
        """Test memory trend query template."""
        query = RealTimePromQLQueries.MEMORY_TREND.format(
            namespace="default",
            workload_name="test-deploy",
            container_name="main",
            window="1h",
        )

        assert "deriv" in query
        assert "[1h:1m]" in query

    def test_stddev_queries(self):
        """Test standard deviation queries."""
        cpu_query = RealTimePromQLQueries.STDDEV_CPU_WINDOW.format(
            namespace="default",
            workload_name="test",
            container_name="main",
            window="15m",
        )
        assert "stddev_over_time" in cpu_query

        mem_query = RealTimePromQLQueries.STDDEV_MEMORY_WINDOW.format(
            namespace="default",
            workload_name="test",
            container_name="main",
            window="15m",
        )
        assert "stddev_over_time" in mem_query


class TestStreamingMetricsCollector:
    """Tests for StreamingMetricsCollector."""

    def test_create_collector(self):
        """Test creating a collector."""
        collector = StreamingMetricsCollector(
            prometheus_url="http://localhost:9090",
            timeout=10,
        )

        assert collector._default_window == TimeWindow.FIFTEEN_MINUTES

    def test_stream_key(self):
        """Test stream key generation."""
        collector = StreamingMetricsCollector()
        key = collector._stream_key("cpu", "default", "test-deploy", "main")

        assert key == "cpu:default/test-deploy/main"

    @patch.object(StreamingMetricsCollector, "_safe_query")
    def test_get_instant_metrics(self, mock_query):
        """Test getting instant metrics."""
        mock_query.side_effect = [0.5, 1024 * 1024 * 256]  # CPU, memory

        collector = StreamingMetricsCollector()
        metrics = collector.get_instant_metrics(
            namespace="default",
            workload_name="test-deploy",
            container_name="main",
        )

        assert metrics["cpu"] == 0.5
        assert metrics["memory"] == 1024 * 1024 * 256
        assert "timestamp" in metrics

    @patch.object(StreamingMetricsCollector, "_safe_query")
    def test_get_trend_analysis(self, mock_query):
        """Test getting trend analysis."""
        # Mock returns: current, avg, stddev, trend for CPU and memory
        mock_query.side_effect = [
            0.5,   # cpu current
            0.4,   # cpu avg
            0.1,   # cpu stddev
            0.01,  # cpu trend
            1024 * 1024 * 256,  # mem current
            1024 * 1024 * 200,  # mem avg
            1024 * 1024 * 50,   # mem stddev
            1000,  # mem trend
        ]

        collector = StreamingMetricsCollector()
        trends = collector.get_trend_analysis(
            namespace="default",
            workload_name="test-deploy",
            container_name="main",
        )

        assert "cpu" in trends
        assert "memory" in trends
        assert trends["cpu"].metric_name == "cpu"
        assert trends["memory"].metric_name == "memory"

    def test_build_trend_analysis_stable(self):
        """Test trend analysis with stable trend."""
        collector = StreamingMetricsCollector()
        trend = collector._build_trend_analysis(
            metric_name="cpu",
            current=0.5,
            average=0.5,
            stddev=0.1,
            trend_rate=0.001,  # Very small rate
            window=TimeWindow.FIFTEEN_MINUTES,
        )

        assert trend.trend_direction == "stable"
        assert not trend.is_anomalous

    def test_build_trend_analysis_increasing(self):
        """Test trend analysis with increasing trend."""
        collector = StreamingMetricsCollector()
        trend = collector._build_trend_analysis(
            metric_name="cpu",
            current=0.7,
            average=0.5,
            stddev=0.05,
            trend_rate=0.1,  # Positive rate
            window=TimeWindow.FIFTEEN_MINUTES,
        )

        assert trend.trend_direction == "increasing"

    def test_build_trend_analysis_anomalous(self):
        """Test trend analysis detects anomaly."""
        collector = StreamingMetricsCollector()
        trend = collector._build_trend_analysis(
            metric_name="cpu",
            current=1.0,  # Very high
            average=0.3,
            stddev=0.1,  # Current is >2 stddev from avg
            trend_rate=0.02,
            window=TimeWindow.FIFTEEN_MINUTES,
        )

        assert trend.is_anomalous
        assert trend.anomaly_score > 0

    @patch.object(StreamingMetricsCollector, "get_trend_analysis")
    def test_get_workload_status(self, mock_trends):
        """Test getting complete workload status."""
        mock_trends.return_value = {
            "cpu": TrendAnalysis(
                metric_name="cpu",
                current_value=0.5,
                average_value=0.4,
                std_deviation=0.1,
                trend_direction="stable",
                trend_rate=0.0,
                window=TimeWindow.FIFTEEN_MINUTES,
                is_anomalous=False,
                anomaly_score=0.2,
            ),
            "memory": TrendAnalysis(
                metric_name="memory",
                current_value=256 * 1024 * 1024,
                average_value=200 * 1024 * 1024,
                std_deviation=50 * 1024 * 1024,
                trend_direction="increasing",
                trend_rate=1000,
                window=TimeWindow.FIFTEEN_MINUTES,
                is_anomalous=False,
                anomaly_score=0.3,
            ),
        }

        collector = StreamingMetricsCollector()
        status = collector.get_workload_status(
            namespace="default",
            workload_name="test-deploy",
            container_name="main",
        )

        assert status.workload_name == "test-deploy"
        assert status.namespace == "default"
        assert 0 <= status.health_score <= 100
        assert len(status.active_alerts) == 0  # No anomalies

    def test_severity_from_score(self):
        """Test severity level calculation from score."""
        collector = StreamingMetricsCollector()

        assert collector._severity_from_score(0.95) == AlertSeverity.CRITICAL
        assert collector._severity_from_score(0.8) == AlertSeverity.HIGH
        assert collector._severity_from_score(0.6) == AlertSeverity.MEDIUM
        assert collector._severity_from_score(0.3) == AlertSeverity.LOW


class TestRealTimeAnomalyPipeline:
    """Tests for RealTimeAnomalyPipeline."""

    def test_create_pipeline(self):
        """Test creating an anomaly pipeline."""
        pipeline = RealTimeAnomalyPipeline()

        assert pipeline._monitored_workloads == {}
        assert pipeline._active_alerts == {}

    def test_add_workload(self):
        """Test adding a workload to monitoring."""
        pipeline = RealTimeAnomalyPipeline()
        pipeline.add_workload(
            namespace="default",
            workload_name="test-deploy",
            container_name="main",
        )

        key = "default/test-deploy/main"
        assert key in pipeline._monitored_workloads
        assert key in pipeline._active_alerts

    def test_remove_workload(self):
        """Test removing a workload from monitoring."""
        pipeline = RealTimeAnomalyPipeline()
        pipeline.add_workload(
            namespace="default",
            workload_name="test-deploy",
            container_name="main",
        )

        pipeline.remove_workload(
            namespace="default",
            workload_name="test-deploy",
            container_name="main",
        )

        key = "default/test-deploy/main"
        assert key not in pipeline._monitored_workloads
        assert key not in pipeline._active_alerts

    @patch.object(StreamingMetricsCollector, "get_workload_status")
    def test_check_workload(self, mock_status):
        """Test checking a workload for anomalies."""
        mock_status.return_value = WorkloadStatus(
            workload_name="test-deploy",
            namespace="default",
            cpu_status=TrendAnalysis(
                metric_name="cpu",
                current_value=0.5,
                average_value=0.4,
                std_deviation=0.1,
                trend_direction="stable",
                trend_rate=0.0,
                window=TimeWindow.FIFTEEN_MINUTES,
                is_anomalous=False,
            ),
            memory_status=TrendAnalysis(
                metric_name="memory",
                current_value=256 * 1024 * 1024,
                average_value=200 * 1024 * 1024,
                std_deviation=50 * 1024 * 1024,
                trend_direction="stable",
                trend_rate=0.0,
                window=TimeWindow.FIFTEEN_MINUTES,
                is_anomalous=False,
            ),
            health_score=95.0,
            active_alerts=[],
        )

        pipeline = RealTimeAnomalyPipeline()
        status = pipeline.check_workload(
            namespace="default",
            workload_name="test-deploy",
            container_name="main",
        )

        assert status.health_score == 95.0

    def test_alert_callback(self):
        """Test that alert callback is triggered."""
        alerts_received = []

        def callback(alert):
            alerts_received.append(alert)

        pipeline = RealTimeAnomalyPipeline(alert_callback=callback)

        # Create mock alert
        mock_alert = AnomalyAlert(
            anomaly_type=AnomalyType.CPU_SPIKE,
            severity=AlertSeverity.HIGH,
            workload_name="test",
            namespace="default",
            container_name="main",
            resource_type="cpu",
            description="Test alert",
            current_value=0.9,
            threshold=0.5,
            score=0.8,
            recommendation="Scale up",
        )

        # Manually trigger callback
        pipeline._alert_callback(mock_alert)

        assert len(alerts_received) == 1
        assert alerts_received[0].workload_name == "test"

    def test_get_all_active_alerts(self):
        """Test getting all active alerts."""
        pipeline = RealTimeAnomalyPipeline()

        # Add some alerts manually
        pipeline._active_alerts["workload1"] = [
            AnomalyAlert(
                anomaly_type=AnomalyType.CPU_SPIKE,
                severity=AlertSeverity.HIGH,
                workload_name="workload1",
                namespace="default",
                container_name="main",
                resource_type="cpu",
                description="Alert 1",
                current_value=0.9,
                threshold=0.5,
                score=0.8,
                recommendation="Fix it",
            )
        ]
        pipeline._active_alerts["workload2"] = [
            AnomalyAlert(
                anomaly_type=AnomalyType.MEMORY_LEAK,
                severity=AlertSeverity.CRITICAL,
                workload_name="workload2",
                namespace="default",
                container_name="main",
                resource_type="memory",
                description="Alert 2",
                current_value=0.95,
                threshold=0.8,
                score=0.9,
                recommendation="Fix it",
            )
        ]

        alerts = pipeline.get_all_active_alerts()
        assert len(alerts) == 2


class TestBackgroundMonitor:
    """Tests for BackgroundMonitor."""

    def test_create_monitor(self):
        """Test creating a background monitor."""
        pipeline = RealTimeAnomalyPipeline()
        monitor = BackgroundMonitor(pipeline, check_interval=60)

        assert monitor._check_interval == 60
        assert not monitor._running
        assert monitor._check_count == 0

    def test_start_stop(self):
        """Test starting and stopping the monitor."""
        pipeline = RealTimeAnomalyPipeline()
        monitor = BackgroundMonitor(pipeline, check_interval=60)

        monitor.start()
        assert monitor.is_running

        monitor.stop()
        assert not monitor.is_running

    def test_check_count(self):
        """Test check count tracking."""
        pipeline = RealTimeAnomalyPipeline()
        monitor = BackgroundMonitor(pipeline, check_interval=60)

        assert monitor.check_count == 0

        # Manually perform a check
        monitor._perform_check()
        assert monitor.check_count == 1
        assert monitor.last_check is not None

    def test_last_check_timestamp(self):
        """Test last check timestamp is set."""
        pipeline = RealTimeAnomalyPipeline()
        monitor = BackgroundMonitor(pipeline, check_interval=60)

        assert monitor.last_check is None

        monitor._perform_check()
        assert monitor.last_check is not None
        assert isinstance(monitor.last_check, datetime)


class TestWorkloadStatus:
    """Tests for WorkloadStatus dataclass."""

    def test_create_status(self):
        """Test creating a workload status."""
        cpu_trend = TrendAnalysis(
            metric_name="cpu",
            current_value=0.5,
            average_value=0.4,
            std_deviation=0.1,
            trend_direction="stable",
            trend_rate=0.0,
            window=TimeWindow.FIFTEEN_MINUTES,
            is_anomalous=False,
        )
        memory_trend = TrendAnalysis(
            metric_name="memory",
            current_value=256 * 1024 * 1024,
            average_value=200 * 1024 * 1024,
            std_deviation=50 * 1024 * 1024,
            trend_direction="stable",
            trend_rate=0.0,
            window=TimeWindow.FIFTEEN_MINUTES,
            is_anomalous=False,
        )

        status = WorkloadStatus(
            workload_name="test-deploy",
            namespace="default",
            cpu_status=cpu_trend,
            memory_status=memory_trend,
            health_score=95.0,
        )

        assert status.workload_name == "test-deploy"
        assert status.namespace == "default"
        assert status.health_score == 95.0
        assert status.active_alerts == []

    def test_status_with_alerts(self):
        """Test workload status with active alerts."""
        cpu_trend = TrendAnalysis(
            metric_name="cpu",
            current_value=0.9,
            average_value=0.4,
            std_deviation=0.1,
            trend_direction="increasing",
            trend_rate=0.1,
            window=TimeWindow.FIFTEEN_MINUTES,
            is_anomalous=True,
            anomaly_score=0.8,
        )
        memory_trend = TrendAnalysis(
            metric_name="memory",
            current_value=256 * 1024 * 1024,
            average_value=200 * 1024 * 1024,
            std_deviation=50 * 1024 * 1024,
            trend_direction="stable",
            trend_rate=0.0,
            window=TimeWindow.FIFTEEN_MINUTES,
            is_anomalous=False,
        )

        alert = AnomalyAlert(
            anomaly_type=AnomalyType.CPU_SPIKE,
            severity=AlertSeverity.HIGH,
            workload_name="test-deploy",
            namespace="default",
            container_name="main",
            resource_type="cpu",
            description="High CPU",
            current_value=0.9,
            threshold=0.5,
            score=0.8,
            recommendation="Scale up",
        )

        status = WorkloadStatus(
            workload_name="test-deploy",
            namespace="default",
            cpu_status=cpu_trend,
            memory_status=memory_trend,
            health_score=60.0,
            active_alerts=[alert],
        )

        assert len(status.active_alerts) == 1
        assert status.active_alerts[0].anomaly_type == AnomalyType.CPU_SPIKE
