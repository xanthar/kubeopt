"""
Unit tests for Workload Anomaly Detection.

Tests the statistical analysis, anomaly detection algorithms,
and alert generation functionality.
"""

import pytest
from statistics import mean, stdev

from kubeopt_ai.core.anomaly_detection import (
    AnomalyType,
    AlertSeverity,
    AnomalyAlert,
    StatisticalAnalyzer,
    AnomalyDetector,
    analyze_optimization_run_anomalies,
)


class TestStatisticalAnalyzer:
    """Tests for statistical analysis methods."""

    def test_z_score_normal(self):
        """Z-score calculation for normal distribution."""
        data = [10, 12, 11, 13, 10, 11, 12, 10, 11, 12]
        data_mean = mean(data)
        data_std = stdev(data)

        # Value at mean should have Z-score of 0
        z = StatisticalAnalyzer.z_score(data_mean, data)
        assert abs(z) < 0.01

        # Value one std above mean should have Z-score ~1
        z = StatisticalAnalyzer.z_score(data_mean + data_std, data)
        assert abs(z - 1.0) < 0.01

    def test_z_score_outlier(self):
        """Z-score detects outliers."""
        # Data with some variance
        data = [10, 11, 10, 9, 10, 11, 10, 9, 10, 11]

        # Value far from mean should have high Z-score
        z = StatisticalAnalyzer.z_score(50, data)
        assert z > 3  # Extreme outlier

    def test_z_score_insufficient_data(self):
        """Z-score returns 0 for insufficient data."""
        assert StatisticalAnalyzer.z_score(10, []) == 0.0
        assert StatisticalAnalyzer.z_score(10, [10]) == 0.0

    def test_z_score_zero_variance(self):
        """Z-score returns 0 for zero variance data."""
        data = [10, 10, 10, 10, 10]
        assert StatisticalAnalyzer.z_score(10, data) == 0.0

    def test_iqr_outlier_bounds(self):
        """IQR bounds calculation."""
        data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
        lower, upper = StatisticalAnalyzer.iqr_outlier_bounds(data)

        # Values within bounds shouldn't be outliers
        assert lower < 1
        assert upper > 12

    def test_iqr_outlier_bounds_insufficient_data(self):
        """IQR bounds with insufficient data."""
        data = [5, 10]
        lower, upper = StatisticalAnalyzer.iqr_outlier_bounds(data)
        assert lower == 5
        assert upper == 10

    def test_linear_trend_increasing(self):
        """Detect increasing linear trend."""
        data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        slope, intercept = StatisticalAnalyzer.linear_trend(data)

        assert slope > 0  # Increasing trend
        assert abs(slope - 1.0) < 0.01  # Slope should be ~1

    def test_linear_trend_decreasing(self):
        """Detect decreasing linear trend."""
        data = [10, 9, 8, 7, 6, 5, 4, 3, 2, 1]
        slope, _ = StatisticalAnalyzer.linear_trend(data)

        assert slope < 0  # Decreasing trend

    def test_linear_trend_flat(self):
        """Detect flat trend."""
        data = [5, 5, 5, 5, 5, 5, 5, 5, 5, 5]
        slope, _ = StatisticalAnalyzer.linear_trend(data)

        assert abs(slope) < 0.01  # Nearly flat

    def test_linear_trend_insufficient_data(self):
        """Linear trend with insufficient data."""
        assert StatisticalAnalyzer.linear_trend([]) == (0.0, 0.0)
        assert StatisticalAnalyzer.linear_trend([5]) == (0.0, 0.0)

    def test_rolling_mean(self):
        """Rolling mean calculation."""
        data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        rolling = StatisticalAnalyzer.rolling_mean(data, window=3)

        assert len(rolling) == 8  # len(data) - window + 1
        assert rolling[0] == mean([1, 2, 3])  # First window
        assert rolling[-1] == mean([8, 9, 10])  # Last window

    def test_rolling_mean_insufficient_data(self):
        """Rolling mean with insufficient data."""
        data = [1, 2]
        rolling = StatisticalAnalyzer.rolling_mean(data, window=5)
        assert rolling == [mean(data)]

    def test_coefficient_of_variation_low(self):
        """CV for low variability data."""
        data = [100, 101, 100, 99, 100, 101, 100, 99]
        cv = StatisticalAnalyzer.coefficient_of_variation(data)
        assert cv < 0.1  # Low variability

    def test_coefficient_of_variation_high(self):
        """CV for high variability data."""
        data = [1, 10, 2, 15, 3, 20, 5, 25]
        cv = StatisticalAnalyzer.coefficient_of_variation(data)
        assert cv > 0.5  # High variability

    def test_coefficient_of_variation_edge_cases(self):
        """CV edge cases."""
        assert StatisticalAnalyzer.coefficient_of_variation([]) == 0.0
        assert StatisticalAnalyzer.coefficient_of_variation([5]) == 0.0
        assert StatisticalAnalyzer.coefficient_of_variation([0, 0, 0]) == 0.0


class TestAnomalyDetector:
    """Tests for anomaly detection algorithms."""

    @pytest.fixture
    def detector(self):
        """Create an anomaly detector."""
        return AnomalyDetector()

    def test_detect_memory_leak_positive(self, detector):
        """Detect a memory leak pattern."""
        # Steadily increasing memory over 20 points
        data = [100 + i * 5 for i in range(20)]  # 100 -> 195 (95% increase)

        alert = detector.detect_memory_leak(
            data_points=data,
            workload_name="leaky-app",
            namespace="default",
            container_name="main",
        )

        assert alert is not None
        assert alert.anomaly_type == AnomalyType.MEMORY_LEAK
        assert alert.workload_name == "leaky-app"
        assert "memory leak" in alert.description.lower()
        assert alert.recommendation is not None

    def test_detect_memory_leak_negative(self, detector):
        """No alert for stable memory usage."""
        # Stable memory with small variations
        data = [100 + (i % 3) for i in range(20)]

        alert = detector.detect_memory_leak(
            data_points=data,
            workload_name="stable-app",
            namespace="default",
            container_name="main",
        )

        assert alert is None

    def test_detect_memory_leak_insufficient_data(self, detector):
        """No alert with insufficient data points."""
        alert = detector.detect_memory_leak(
            data_points=[100, 110, 120],
            workload_name="app",
            namespace="default",
            container_name="main",
        )
        assert alert is None

    def test_detect_spike_positive(self, detector):
        """Detect a resource spike."""
        # Baseline data with some variance followed by spike
        baseline = [10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10]
        spike = [50, 55, 60]  # 5-6x increase
        data = baseline + spike

        alert = detector.detect_spike(
            data_points=data,
            workload_name="spikey-app",
            namespace="default",
            container_name="main",
            resource_type="cpu",
        )

        assert alert is not None
        assert alert.anomaly_type == AnomalyType.CPU_SPIKE
        assert "spike" in alert.description.lower()

    def test_detect_spike_negative(self, detector):
        """No alert for stable resource usage."""
        data = [10, 11, 10, 12, 10, 11, 10, 12, 10, 11]

        alert = detector.detect_spike(
            data_points=data,
            workload_name="stable-app",
            namespace="default",
            container_name="main",
            resource_type="cpu",
        )

        assert alert is None

    def test_detect_spike_memory(self, detector):
        """Detect memory spike."""
        # Baseline with variance followed by spike
        baseline = [1000, 1050, 980, 1020, 990, 1010, 1000, 1030, 970, 1000,
                    1020, 990, 1010, 1000, 1040]
        spike = [5000, 5500, 6000]
        data = baseline + spike

        alert = detector.detect_spike(
            data_points=data,
            workload_name="app",
            namespace="default",
            container_name="main",
            resource_type="memory",
        )

        assert alert is not None
        assert alert.anomaly_type == AnomalyType.MEMORY_SPIKE

    def test_detect_underutilization_positive(self, detector):
        """Detect resource underutilization."""
        alert = detector.detect_underutilization(
            usage_value=0.05,  # 5% usage
            request_value=1.0,  # 1 core requested
            workload_name="wasteful-app",
            namespace="default",
            container_name="main",
            resource_type="cpu",
        )

        assert alert is not None
        assert alert.anomaly_type == AnomalyType.RESOURCE_UNDERUTILIZATION
        assert "underutilization" in alert.description.lower()
        assert alert.severity in [AlertSeverity.MEDIUM, AlertSeverity.HIGH]

    def test_detect_underutilization_negative(self, detector):
        """No alert for well-utilized resources."""
        alert = detector.detect_underutilization(
            usage_value=0.5,  # 50% usage
            request_value=1.0,
            workload_name="efficient-app",
            namespace="default",
            container_name="main",
            resource_type="cpu",
        )

        assert alert is None

    def test_detect_underutilization_no_request(self, detector):
        """No alert when no resources requested."""
        alert = detector.detect_underutilization(
            usage_value=0.5,
            request_value=0,
            workload_name="app",
            namespace="default",
            container_name="main",
            resource_type="cpu",
        )

        assert alert is None

    def test_detect_saturation_positive(self, detector):
        """Detect resource saturation."""
        alert = detector.detect_saturation(
            usage_value=0.95,  # 95% of limit
            limit_value=1.0,
            workload_name="saturated-app",
            namespace="default",
            container_name="main",
            resource_type="cpu",
        )

        assert alert is not None
        assert alert.anomaly_type == AnomalyType.RESOURCE_SATURATION
        assert "saturation" in alert.description.lower()

    def test_detect_saturation_critical(self, detector):
        """Critical saturation at 99%+."""
        alert = detector.detect_saturation(
            usage_value=0.99,
            limit_value=1.0,
            workload_name="critical-app",
            namespace="default",
            container_name="main",
            resource_type="memory",
        )

        assert alert is not None
        assert alert.severity == AlertSeverity.CRITICAL

    def test_detect_saturation_negative(self, detector):
        """No alert when under saturation threshold."""
        alert = detector.detect_saturation(
            usage_value=0.5,  # 50% of limit
            limit_value=1.0,
            workload_name="app",
            namespace="default",
            container_name="main",
            resource_type="cpu",
        )

        assert alert is None

    def test_analyze_workload_comprehensive(self, detector):
        """Comprehensive workload analysis."""
        container_metrics = [
            {
                "container_name": "main",
                "avg_cpu_usage": 0.05,  # Very low -> underutilization
                "p95_cpu_usage": 0.08,
                "max_cpu_usage": 0.1,
                "avg_memory_usage": 900_000_000,  # 900MB
                "p95_memory_usage": 950_000_000,
                "max_memory_usage": 1_000_000_000,
            }
        ]
        container_configs = [
            {
                "name": "main",
                "resources": {
                    "requests": {"cpu": "1", "memory": "2Gi"},  # 2GB
                    "limits": {"cpu": "2", "memory": "2Gi"},
                },
            }
        ]

        analysis = detector.analyze_workload(
            workload_name="test-app",
            namespace="default",
            container_metrics=container_metrics,
            container_configs=container_configs,
        )

        assert analysis.workload_name == "test-app"
        assert analysis.namespace == "default"
        # Should detect CPU underutilization (using 5% of 1 core request)
        assert len(analysis.alerts) > 0
        assert any(
            a.anomaly_type == AnomalyType.RESOURCE_UNDERUTILIZATION
            for a in analysis.alerts
        )
        assert analysis.health_score < 100  # Some issues detected

    def test_analyze_workload_healthy(self, detector):
        """Analyze a healthy workload."""
        container_metrics = [
            {
                "container_name": "main",
                "avg_cpu_usage": 0.5,  # 50% of request
                "p95_cpu_usage": 0.7,
                "max_cpu_usage": 0.8,
                "avg_memory_usage": 500_000_000,  # 500MB
                "p95_memory_usage": 700_000_000,
                "max_memory_usage": 800_000_000,
            }
        ]
        container_configs = [
            {
                "name": "main",
                "resources": {
                    "requests": {"cpu": "1", "memory": "1Gi"},
                    "limits": {"cpu": "2", "memory": "2Gi"},
                },
            }
        ]

        analysis = detector.analyze_workload(
            workload_name="healthy-app",
            namespace="default",
            container_metrics=container_metrics,
            container_configs=container_configs,
        )

        assert analysis.health_score == 100.0
        assert len(analysis.alerts) == 0

    def test_health_score_calculation(self, detector):
        """Health score decreases with alerts."""
        # No alerts -> 100
        assert detector._calculate_health_score([]) == 100.0

        # Low severity alerts
        low_alerts = [
            AnomalyAlert(
                anomaly_type=AnomalyType.RESOURCE_UNDERUTILIZATION,
                severity=AlertSeverity.LOW,
                workload_name="app",
                namespace="default",
                container_name="main",
                resource_type="cpu",
                description="test",
                current_value=0.1,
                threshold=0.2,
                score=0.5,
            )
        ]
        assert detector._calculate_health_score(low_alerts) == 95.0

        # Critical alert
        critical_alerts = [
            AnomalyAlert(
                anomaly_type=AnomalyType.RESOURCE_SATURATION,
                severity=AlertSeverity.CRITICAL,
                workload_name="app",
                namespace="default",
                container_name="main",
                resource_type="memory",
                description="test",
                current_value=0.99,
                threshold=0.9,
                score=0.99,
            )
        ]
        assert detector._calculate_health_score(critical_alerts) == 70.0


class TestAnalyzeOptimizationRunAnomalies:
    """Tests for the high-level anomaly analysis function."""

    @pytest.fixture
    def optimization_run_details(self):
        """Sample optimization run details with metrics."""
        return {
            "workloads": [
                {
                    "id": "snapshot-1",
                    "name": "web-app",
                    "namespace": "production",
                    "current_config": {
                        "replicas": 3,
                        "containers": [
                            {
                                "name": "main",
                                "resources": {
                                    "requests": {"cpu": "1", "memory": "2Gi"},
                                    "limits": {"cpu": "2", "memory": "4Gi"},
                                },
                            }
                        ],
                    },
                    "metrics_summary": {
                        "container_metrics": [
                            {
                                "container_name": "main",
                                "avg_cpu_usage": 0.1,  # 10% of request
                                "p95_cpu_usage": 0.15,
                                "max_cpu_usage": 0.2,
                                "avg_memory_usage": 500_000_000,  # 500MB
                                "p95_memory_usage": 700_000_000,
                                "max_memory_usage": 900_000_000,
                            }
                        ],
                    },
                }
            ],
            "suggestions": [],
        }

    def test_analyze_run_anomalies(self, optimization_run_details):
        """Analyze anomalies for an optimization run."""
        analyses = analyze_optimization_run_anomalies(
            optimization_run_details=optimization_run_details,
        )

        assert len(analyses) == 1
        analysis = analyses[0]
        assert analysis.workload_name == "web-app"
        assert analysis.namespace == "production"
        # Should detect underutilization (10% CPU usage of 1 core request)
        assert len(analysis.alerts) > 0

    def test_analyze_run_empty_workloads(self):
        """Analyze run with no workloads."""
        analyses = analyze_optimization_run_anomalies(
            optimization_run_details={"workloads": [], "suggestions": []},
        )

        assert analyses == []

    def test_analyze_run_missing_metrics(self):
        """Analyze run with missing metrics."""
        details = {
            "workloads": [
                {
                    "name": "app",
                    "namespace": "default",
                    "current_config": {
                        "containers": [{"name": "main", "resources": {}}]
                    },
                    "metrics_summary": {},  # No metrics
                }
            ],
            "suggestions": [],
        }

        analyses = analyze_optimization_run_anomalies(
            optimization_run_details=details,
        )

        assert len(analyses) == 1
        # No alerts without metrics data
        assert analyses[0].health_score == 100.0


class TestAnomalyAlertSeverity:
    """Tests for alert severity assignment."""

    def test_underutilization_severity_levels(self):
        """Test severity levels for underutilization."""
        detector = AnomalyDetector()

        # Very low utilization -> HIGH
        alert = detector.detect_underutilization(
            usage_value=0.03,  # 3%
            request_value=1.0,
            workload_name="app",
            namespace="default",
            container_name="main",
            resource_type="cpu",
        )
        assert alert.severity == AlertSeverity.HIGH

        # Low utilization -> MEDIUM
        alert = detector.detect_underutilization(
            usage_value=0.08,  # 8%
            request_value=1.0,
            workload_name="app",
            namespace="default",
            container_name="main",
            resource_type="cpu",
        )
        assert alert.severity == AlertSeverity.MEDIUM

    def test_saturation_severity_levels(self):
        """Test severity levels for saturation."""
        detector = AnomalyDetector()

        # 99%+ -> CRITICAL
        alert = detector.detect_saturation(
            usage_value=0.995,
            limit_value=1.0,
            workload_name="app",
            namespace="default",
            container_name="main",
            resource_type="memory",
        )
        assert alert.severity == AlertSeverity.CRITICAL

        # 95-99% -> HIGH
        alert = detector.detect_saturation(
            usage_value=0.96,
            limit_value=1.0,
            workload_name="app",
            namespace="default",
            container_name="main",
            resource_type="memory",
        )
        assert alert.severity == AlertSeverity.HIGH

        # 90-95% -> MEDIUM
        alert = detector.detect_saturation(
            usage_value=0.92,
            limit_value=1.0,
            workload_name="app",
            namespace="default",
            container_name="main",
            resource_type="memory",
        )
        assert alert.severity == AlertSeverity.MEDIUM
