"""
Unit tests for historical trend analysis (F020).
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta, timezone

from kubeopt_ai.core.models import MetricsHistory, TrendAnalysis, TrendDirection
from kubeopt_ai.core.trend_analyzer import (
    HistoryCollector,
    TrendAnalyzer,
    TrendAnalyzerError,
    TrendResult,
)


class TestHistoryCollector:
    """Tests for HistoryCollector service."""

    def test_get_history_empty(self, app, db_session):
        """Test getting history when no data exists."""
        collector = HistoryCollector()

        history = collector.get_history(
            cluster_id=None,
            namespace="default",
            workload_name="test-workload",
            container_name="main",
            start_time=datetime.now(timezone.utc) - timedelta(days=7),
        )

        assert history == []

    def test_get_history_with_data(self, app, db_session):
        """Test getting history with existing data."""
        # Create test data
        now = datetime.now(timezone.utc)
        for i in range(5):
            record = MetricsHistory(
                namespace="default",
                workload_name="test-workload",
                workload_kind="Deployment",
                container_name="main",
                timestamp=now - timedelta(hours=i),
                cpu_usage=0.5 + i * 0.1,
                memory_usage=1024 * 1024 * (100 + i * 10),
            )
            db_session.add(record)
        db_session.commit()

        collector = HistoryCollector()
        history = collector.get_history(
            cluster_id=None,
            namespace="default",
            workload_name="test-workload",
            container_name="main",
            start_time=now - timedelta(days=1),
        )

        assert len(history) == 5

    def test_get_history_time_filter(self, app, db_session):
        """Test history filtering by time range."""
        now = datetime.now(timezone.utc)

        # Create data at different times
        for days_ago in [1, 3, 7, 14]:
            record = MetricsHistory(
                namespace="default",
                workload_name="time-filter-test",
                workload_kind="Deployment",
                container_name="main",
                timestamp=now - timedelta(days=days_ago),
                cpu_usage=0.5,
            )
            db_session.add(record)
        db_session.commit()

        collector = HistoryCollector()

        # Get last 5 days
        history = collector.get_history(
            cluster_id=None,
            namespace="default",
            workload_name="time-filter-test",
            container_name="main",
            start_time=now - timedelta(days=5),
        )

        assert len(history) == 2  # Only 1 and 3 days ago

    def test_get_history_cluster_filter(self, app, db_session):
        """Test history filtering by cluster."""
        now = datetime.now(timezone.utc)

        # Create data for different clusters
        for cluster_id in ["cluster-1", "cluster-2"]:
            record = MetricsHistory(
                cluster_id=cluster_id,
                namespace="default",
                workload_name="cluster-filter-test",
                workload_kind="Deployment",
                container_name="main",
                timestamp=now,
                cpu_usage=0.5,
            )
            db_session.add(record)
        db_session.commit()

        collector = HistoryCollector()

        history = collector.get_history(
            cluster_id="cluster-1",
            namespace="default",
            workload_name="cluster-filter-test",
            container_name="main",
            start_time=now - timedelta(hours=1),
        )

        assert len(history) == 1
        assert history[0].cluster_id == "cluster-1"


class TestTrendAnalyzer:
    """Tests for TrendAnalyzer service."""

    def test_analyze_empty_history(self, app, db_session):
        """Test analysis with no data raises error."""
        analyzer = TrendAnalyzer()

        with pytest.raises(TrendAnalyzerError, match="No historical data"):
            analyzer.analyze(
                cluster_id=None,
                namespace="default",
                workload_name="test",
                container_name="main",
                history=[],
            )

    def test_analyze_insufficient_data(self, app, db_session):
        """Test analysis with insufficient data raises error."""
        analyzer = TrendAnalyzer()
        now = datetime.now(timezone.utc)

        history = [
            MetricsHistory(
                namespace="default",
                workload_name="test",
                workload_kind="Deployment",
                container_name="main",
                timestamp=now,
                cpu_usage=0.5,
            ),
        ]

        with pytest.raises(TrendAnalyzerError, match="Insufficient data"):
            analyzer.analyze(
                cluster_id=None,
                namespace="default",
                workload_name="test",
                container_name="main",
                history=history,
            )

    def test_analyze_stable_trend(self, app, db_session):
        """Test analysis detects stable trend."""
        analyzer = TrendAnalyzer()
        now = datetime.now(timezone.utc)

        # Create stable data (constant values)
        history = []
        for i in range(20):
            history.append(MetricsHistory(
                namespace="default",
                workload_name="stable-test",
                workload_kind="Deployment",
                container_name="main",
                timestamp=now - timedelta(hours=i),
                cpu_usage=0.5,  # Constant
                memory_usage=1024 * 1024 * 100,  # Constant
            ))

        analysis = analyzer.analyze(
            cluster_id=None,
            namespace="default",
            workload_name="stable-test",
            container_name="main",
            history=history,
        )

        assert analysis.cpu_trend_direction == TrendDirection.STABLE
        assert analysis.memory_trend_direction == TrendDirection.STABLE

    def test_analyze_increasing_trend(self, app, db_session):
        """Test analysis detects increasing trend."""
        analyzer = TrendAnalyzer()
        now = datetime.now(timezone.utc)

        # Create increasing data with moderate slope to avoid volatility detection
        history = []
        base_cpu = 1.0  # Higher base value
        for i in range(20):
            history.append(MetricsHistory(
                namespace="default",
                workload_name="increasing-test",
                workload_kind="Deployment",
                container_name="main",
                timestamp=now - timedelta(hours=19-i),  # Oldest first
                cpu_usage=base_cpu + i * 0.02,  # Small increases on larger base
                memory_usage=1024 * 1024 * (500 + i * 10),  # Increasing
            ))

        analysis = analyzer.analyze(
            cluster_id=None,
            namespace="default",
            workload_name="increasing-test",
            container_name="main",
            history=history,
        )

        assert analysis.cpu_trend_direction == TrendDirection.INCREASING
        assert analysis.cpu_trend_slope > 0

    def test_analyze_decreasing_trend(self, app, db_session):
        """Test analysis detects decreasing trend."""
        analyzer = TrendAnalyzer()
        now = datetime.now(timezone.utc)

        # Create decreasing data with moderate slope to avoid volatility detection
        history = []
        base_cpu = 2.0  # Higher base value
        for i in range(20):
            history.append(MetricsHistory(
                namespace="default",
                workload_name="decreasing-test",
                workload_kind="Deployment",
                container_name="main",
                timestamp=now - timedelta(hours=19-i),
                cpu_usage=base_cpu - i * 0.02,  # Small decreases on larger base
                memory_usage=1024 * 1024 * (1000 - i * 10),  # Decreasing
            ))

        analysis = analyzer.analyze(
            cluster_id=None,
            namespace="default",
            workload_name="decreasing-test",
            container_name="main",
            history=history,
        )

        assert analysis.cpu_trend_direction == TrendDirection.DECREASING
        assert analysis.cpu_trend_slope < 0

    def test_analyze_statistics(self, app, db_session):
        """Test analysis computes correct statistics."""
        analyzer = TrendAnalyzer()
        now = datetime.now(timezone.utc)

        values = [0.2, 0.4, 0.6, 0.8, 1.0]
        history = []
        for i, val in enumerate(values):
            history.append(MetricsHistory(
                namespace="default",
                workload_name="stats-test",
                workload_kind="Deployment",
                container_name="main",
                timestamp=now - timedelta(hours=len(values)-1-i),
                cpu_usage=val,
            ))

        analysis = analyzer.analyze(
            cluster_id=None,
            namespace="default",
            workload_name="stats-test",
            container_name="main",
            history=history,
        )

        assert analysis.cpu_avg == pytest.approx(0.6, rel=0.01)
        assert analysis.cpu_max == pytest.approx(1.0, rel=0.01)
        assert analysis.data_points_count == 5

    def test_analyze_generates_recommendations(self, app, db_session):
        """Test analysis generates resource recommendations."""
        analyzer = TrendAnalyzer()
        now = datetime.now(timezone.utc)

        history = []
        for i in range(20):
            history.append(MetricsHistory(
                namespace="default",
                workload_name="recommendations-test",
                workload_kind="Deployment",
                container_name="main",
                timestamp=now - timedelta(hours=i),
                cpu_usage=0.5 + (i % 5) * 0.1,
                memory_usage=1024 * 1024 * (100 + (i % 5) * 10),
            ))

        analysis = analyzer.analyze(
            cluster_id=None,
            namespace="default",
            workload_name="recommendations-test",
            container_name="main",
            history=history,
        )

        assert analysis.recommended_cpu_request is not None
        assert analysis.recommended_cpu_limit is not None
        assert analysis.recommended_memory_request is not None
        assert analysis.recommended_memory_limit is not None
        assert analysis.confidence_score is not None

    def test_analyze_stores_result(self, app, db_session):
        """Test analysis stores result in database."""
        analyzer = TrendAnalyzer()
        now = datetime.now(timezone.utc)

        history = []
        for i in range(10):
            history.append(MetricsHistory(
                namespace="default",
                workload_name="storage-test",
                workload_kind="Deployment",
                container_name="main",
                timestamp=now - timedelta(hours=i),
                cpu_usage=0.5,
            ))

        analysis = analyzer.analyze(
            cluster_id=None,
            namespace="default",
            workload_name="storage-test",
            container_name="main",
            history=history,
        )

        # Verify stored in database
        stored = db_session.get(TrendAnalysis, analysis.id)
        assert stored is not None
        assert stored.workload_name == "storage-test"

    def test_get_latest_analysis(self, app, db_session):
        """Test retrieving the latest analysis."""
        analyzer = TrendAnalyzer()
        now = datetime.now(timezone.utc)

        # Create multiple analyses
        for i in range(3):
            history = []
            for j in range(10):
                history.append(MetricsHistory(
                    namespace="default",
                    workload_name="latest-test",
                    workload_kind="Deployment",
                    container_name="main",
                    timestamp=now - timedelta(hours=j + i*10),
                    cpu_usage=0.5,
                ))

            analyzer.analyze(
                cluster_id=None,
                namespace="default",
                workload_name="latest-test",
                container_name="main",
                history=history,
            )

        latest = analyzer.get_latest_analysis(
            cluster_id=None,
            namespace="default",
            workload_name="latest-test",
            container_name="main",
        )

        assert latest is not None

    def test_list_analyses(self, app, db_session):
        """Test listing analyses."""
        analyzer = TrendAnalyzer()
        now = datetime.now(timezone.utc)

        # Create some analyses
        for name in ["list-test-1", "list-test-2"]:
            history = []
            for i in range(10):
                history.append(MetricsHistory(
                    namespace="default",
                    workload_name=name,
                    workload_kind="Deployment",
                    container_name="main",
                    timestamp=now - timedelta(hours=i),
                    cpu_usage=0.5,
                ))
            analyzer.analyze(
                cluster_id=None,
                namespace="default",
                workload_name=name,
                container_name="main",
                history=history,
            )

        analyses = analyzer.list_analyses(namespace="default")
        assert len(analyses) >= 2


class TestLinearRegression:
    """Tests for linear regression helper."""

    def test_linear_regression_positive_slope(self, app, db_session):
        """Test linear regression with positive slope."""
        analyzer = TrendAnalyzer()

        x = [0, 1, 2, 3, 4]
        y = [1, 2, 3, 4, 5]

        slope, intercept = analyzer._linear_regression(x, y)

        assert slope == pytest.approx(1.0, rel=0.01)
        assert intercept == pytest.approx(1.0, rel=0.01)

    def test_linear_regression_negative_slope(self, app, db_session):
        """Test linear regression with negative slope."""
        analyzer = TrendAnalyzer()

        x = [0, 1, 2, 3, 4]
        y = [5, 4, 3, 2, 1]

        slope, intercept = analyzer._linear_regression(x, y)

        assert slope == pytest.approx(-1.0, rel=0.01)
        assert intercept == pytest.approx(5.0, rel=0.01)

    def test_linear_regression_zero_slope(self, app, db_session):
        """Test linear regression with zero slope."""
        analyzer = TrendAnalyzer()

        x = [0, 1, 2, 3, 4]
        y = [3, 3, 3, 3, 3]

        slope, intercept = analyzer._linear_regression(x, y)

        assert slope == pytest.approx(0.0, abs=0.001)
        assert intercept == pytest.approx(3.0, rel=0.01)


class TestHistoryRoutes:
    """Tests for history API routes."""

    def test_get_metrics_history_missing_params(self, client, db_session):
        """Test GET /api/v1/history/metrics without required params."""
        response = client.get("/api/v1/history/metrics")

        assert response.status_code == 400
        data = response.get_json()
        assert "required" in data["message"].lower()

    def test_get_metrics_history_empty(self, client, db_session):
        """Test GET /api/v1/history/metrics with no data."""
        response = client.get(
            "/api/v1/history/metrics",
            query_string={
                "namespace": "default",
                "workload_name": "test",
                "container_name": "main",
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["metrics"] == []
        assert data["count"] == 0

    def test_list_trends_endpoint(self, client, db_session):
        """Test GET /api/v1/history/trends."""
        response = client.get("/api/v1/history/trends")

        assert response.status_code == 200
        data = response.get_json()
        assert "analyses" in data
        assert "count" in data

    def test_analyze_endpoint_missing_params(self, client, db_session):
        """Test POST /api/v1/history/trends/analyze without required params."""
        response = client.post("/api/v1/history/trends/analyze", json={
            "namespace": "default",
            # Missing workload_name and container_name
        })

        assert response.status_code == 400

    def test_analyze_endpoint_insufficient_data(self, client, db_session):
        """Test POST /api/v1/history/trends/analyze with no historical data."""
        response = client.post("/api/v1/history/trends/analyze", json={
            "namespace": "default",
            "workload_name": "no-data-test",
            "container_name": "main",
        })

        assert response.status_code == 400
        data = response.get_json()
        assert "insufficient" in data["message"].lower() or "not enough" in data["message"].lower()

    def test_get_history_summary_endpoint(self, client, db_session):
        """Test GET /api/v1/history/summary."""
        response = client.get("/api/v1/history/summary")

        assert response.status_code == 200
        data = response.get_json()
        assert "total_records" in data
        assert "unique_workloads" in data
        assert "analysis_count" in data

    def test_get_latest_trend_missing_params(self, client, db_session):
        """Test GET /api/v1/history/trends/latest without params."""
        response = client.get("/api/v1/history/trends/latest")

        assert response.status_code == 400

    def test_get_latest_trend_not_found(self, client, db_session):
        """Test GET /api/v1/history/trends/latest when none exists."""
        response = client.get(
            "/api/v1/history/trends/latest",
            query_string={
                "namespace": "default",
                "workload_name": "nonexistent",
                "container_name": "main",
            },
        )

        assert response.status_code == 404
