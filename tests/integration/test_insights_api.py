"""
Integration tests for Insights API endpoints.

Tests the cost projection and anomaly detection API endpoints with
real database transactions and end-to-end request flows.
"""

import pytest
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "manifests"


class TestCostProjectionEndpoints:
    """Integration tests for cost projection API endpoints."""

    def test_post_cost_projection_aws(self, client, optimization_run):
        """Test POST cost projection with AWS provider."""
        response = client.post(
            "/api/v1/insights/cost",
            json={
                "run_id": optimization_run,
                "provider": "aws",
                "region": "us-east-1",
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["run_id"] == optimization_run
        assert data["provider"] == "aws"
        assert data["region"] == "us-east-1"
        assert data["currency"] == "USD"
        assert "workload_costs" in data
        assert isinstance(data["workload_costs"], list)
        assert "total_current_monthly" in data
        assert "total_projected_monthly" in data
        assert "total_monthly_savings" in data
        assert "total_annual_savings" in data
        assert "savings_percent" in data

    def test_post_cost_projection_gcp(self, client, optimization_run):
        """Test POST cost projection with GCP provider."""
        response = client.post(
            "/api/v1/insights/cost",
            json={
                "run_id": optimization_run,
                "provider": "gcp",
                "region": "us-central1",
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["provider"] == "gcp"
        assert data["region"] == "us-central1"

    def test_post_cost_projection_azure(self, client, optimization_run):
        """Test POST cost projection with Azure provider."""
        response = client.post(
            "/api/v1/insights/cost",
            json={
                "run_id": optimization_run,
                "provider": "azure",
                "region": "eastus",
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["provider"] == "azure"
        assert data["region"] == "eastus"

    def test_post_cost_projection_on_prem(self, client, optimization_run):
        """Test POST cost projection with on-prem provider."""
        response = client.post(
            "/api/v1/insights/cost",
            json={
                "run_id": optimization_run,
                "provider": "on_prem",
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["provider"] == "on_prem"

    def test_post_cost_projection_missing_run_id(self, client):
        """Test POST cost projection without run_id."""
        response = client.post(
            "/api/v1/insights/cost",
            json={
                "provider": "aws",
            },
        )

        assert response.status_code == 400
        data = response.get_json()
        assert data["code"] == "VALIDATION_ERROR"

    def test_post_cost_projection_invalid_run_id(self, client):
        """Test POST cost projection with non-existent run_id."""
        response = client.post(
            "/api/v1/insights/cost",
            json={
                "run_id": "nonexistent-run-id",
                "provider": "aws",
            },
        )

        assert response.status_code == 404
        data = response.get_json()
        assert data["code"] == "NOT_FOUND"

    def test_post_cost_projection_invalid_provider(self, client, optimization_run):
        """Test POST cost projection with invalid provider."""
        response = client.post(
            "/api/v1/insights/cost",
            json={
                "run_id": optimization_run,
                "provider": "invalid_provider",
            },
        )

        assert response.status_code == 400
        data = response.get_json()
        assert data["code"] == "VALIDATION_ERROR"

    def test_get_cost_projection_default(self, client, optimization_run):
        """Test GET cost projection with default parameters."""
        response = client.get(f"/api/v1/insights/cost/{optimization_run}")

        assert response.status_code == 200
        data = response.get_json()
        assert data["run_id"] == optimization_run
        assert data["provider"] == "aws"  # Default provider
        assert "workload_costs" in data

    def test_get_cost_projection_with_provider(self, client, optimization_run):
        """Test GET cost projection with provider query param."""
        response = client.get(
            f"/api/v1/insights/cost/{optimization_run}?provider=gcp"
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["provider"] == "gcp"

    def test_get_cost_projection_with_region(self, client, optimization_run):
        """Test GET cost projection with region query param."""
        response = client.get(
            f"/api/v1/insights/cost/{optimization_run}?provider=aws&region=eu-west-1"
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["region"] == "eu-west-1"

    def test_get_cost_projection_not_found(self, client):
        """Test GET cost projection for non-existent run."""
        response = client.get("/api/v1/insights/cost/nonexistent-id")

        assert response.status_code == 404
        data = response.get_json()
        assert data["code"] == "NOT_FOUND"

    def test_cost_projection_has_workload_details(self, client, optimization_run):
        """Test that cost projection includes workload details."""
        response = client.get(f"/api/v1/insights/cost/{optimization_run}")

        assert response.status_code == 200
        data = response.get_json()

        # Should have workload costs with proper structure
        assert len(data["workload_costs"]) > 0
        workload = data["workload_costs"][0]
        assert "workload_name" in workload
        assert "namespace" in workload
        assert "replicas" in workload
        assert "current_cost" in workload
        assert "cpu_cost" in workload["current_cost"]
        assert "memory_cost" in workload["current_cost"]
        assert "total_cost" in workload["current_cost"]

    def test_cost_projection_totals_are_positive(self, client, optimization_run):
        """Test that cost projection totals are non-negative."""
        response = client.get(f"/api/v1/insights/cost/{optimization_run}")

        assert response.status_code == 200
        data = response.get_json()

        assert data["total_current_monthly"] >= 0
        assert data["total_projected_monthly"] >= 0
        # Savings can be negative if recommendations increase cost
        assert isinstance(data["total_monthly_savings"], (int, float))
        assert isinstance(data["total_annual_savings"], (int, float))


class TestAnomalyAnalysisEndpoints:
    """Integration tests for anomaly analysis API endpoints."""

    def test_post_anomaly_analysis_default_hours(self, client, optimization_run):
        """Test POST anomaly analysis with default hours."""
        response = client.post(
            "/api/v1/insights/anomalies",
            json={
                "run_id": optimization_run,
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["run_id"] == optimization_run
        assert "total_workloads" in data
        assert "total_alerts" in data
        assert "alerts_by_severity" in data
        assert "alerts_by_type" in data
        assert "average_health_score" in data
        assert "workload_analyses" in data

    def test_post_anomaly_analysis_custom_hours(self, client, optimization_run):
        """Test POST anomaly analysis with custom hours."""
        response = client.post(
            "/api/v1/insights/anomalies",
            json={
                "run_id": optimization_run,
                "hours": 48,
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["run_id"] == optimization_run

    def test_post_anomaly_analysis_min_hours(self, client, optimization_run):
        """Test POST anomaly analysis with minimum hours (1)."""
        response = client.post(
            "/api/v1/insights/anomalies",
            json={
                "run_id": optimization_run,
                "hours": 1,
            },
        )

        assert response.status_code == 200

    def test_post_anomaly_analysis_max_hours(self, client, optimization_run):
        """Test POST anomaly analysis with maximum hours (168)."""
        response = client.post(
            "/api/v1/insights/anomalies",
            json={
                "run_id": optimization_run,
                "hours": 168,
            },
        )

        assert response.status_code == 200

    def test_post_anomaly_analysis_invalid_hours_too_low(self, client, optimization_run):
        """Test POST anomaly analysis with hours below minimum."""
        response = client.post(
            "/api/v1/insights/anomalies",
            json={
                "run_id": optimization_run,
                "hours": 0,
            },
        )

        assert response.status_code == 400
        data = response.get_json()
        assert data["code"] == "VALIDATION_ERROR"

    def test_post_anomaly_analysis_invalid_hours_too_high(self, client, optimization_run):
        """Test POST anomaly analysis with hours above maximum."""
        response = client.post(
            "/api/v1/insights/anomalies",
            json={
                "run_id": optimization_run,
                "hours": 200,
            },
        )

        assert response.status_code == 400
        data = response.get_json()
        assert data["code"] == "VALIDATION_ERROR"

    def test_post_anomaly_analysis_missing_run_id(self, client):
        """Test POST anomaly analysis without run_id."""
        response = client.post(
            "/api/v1/insights/anomalies",
            json={},
        )

        assert response.status_code == 400
        data = response.get_json()
        assert data["code"] == "VALIDATION_ERROR"

    def test_post_anomaly_analysis_invalid_run_id(self, client):
        """Test POST anomaly analysis with non-existent run_id."""
        response = client.post(
            "/api/v1/insights/anomalies",
            json={
                "run_id": "nonexistent-run-id",
            },
        )

        assert response.status_code == 404
        data = response.get_json()
        assert data["code"] == "NOT_FOUND"

    def test_get_anomaly_analysis_default(self, client, optimization_run):
        """Test GET anomaly analysis with default parameters."""
        response = client.get(f"/api/v1/insights/anomalies/{optimization_run}")

        assert response.status_code == 200
        data = response.get_json()
        assert data["run_id"] == optimization_run
        assert "total_workloads" in data
        assert "workload_analyses" in data

    def test_get_anomaly_analysis_with_severity_filter(self, client, optimization_run):
        """Test GET anomaly analysis with severity filter."""
        response = client.get(
            f"/api/v1/insights/anomalies/{optimization_run}?severity=high"
        )

        assert response.status_code == 200
        data = response.get_json()
        # All alerts should be high severity (or none)
        for workload in data["workload_analyses"]:
            for alert in workload["alerts"]:
                assert alert["severity"] == "high"

    def test_get_anomaly_analysis_not_found(self, client):
        """Test GET anomaly analysis for non-existent run."""
        response = client.get("/api/v1/insights/anomalies/nonexistent-id")

        assert response.status_code == 404
        data = response.get_json()
        assert data["code"] == "NOT_FOUND"

    def test_anomaly_analysis_health_score_range(self, client, optimization_run):
        """Test that health scores are within valid range."""
        response = client.get(f"/api/v1/insights/anomalies/{optimization_run}")

        assert response.status_code == 200
        data = response.get_json()

        # Average health score should be between 0 and 100
        assert 0 <= data["average_health_score"] <= 100

        # Individual workload health scores should also be valid
        for workload in data["workload_analyses"]:
            assert 0 <= workload["health_score"] <= 100

    def test_anomaly_analysis_alert_structure(self, client, optimization_run):
        """Test that alerts have proper structure when present."""
        response = client.get(f"/api/v1/insights/anomalies/{optimization_run}")

        assert response.status_code == 200
        data = response.get_json()

        for workload in data["workload_analyses"]:
            assert "workload_name" in workload
            assert "namespace" in workload
            assert "analysis_period_hours" in workload
            assert "alerts" in workload
            assert "health_score" in workload
            assert "analyzed_at" in workload

            for alert in workload["alerts"]:
                assert "anomaly_type" in alert
                assert "severity" in alert
                assert "workload_name" in alert
                assert "description" in alert
                assert "recommendation" in alert


class TestInsightsSummaryEndpoint:
    """Integration tests for insights summary endpoint."""

    def test_get_insights_summary_default(self, client, optimization_run):
        """Test GET insights summary with default parameters."""
        response = client.get(f"/api/v1/insights/summary/{optimization_run}")

        assert response.status_code == 200
        data = response.get_json()
        assert data["run_id"] == optimization_run

        # Cost summary
        assert "cost_summary" in data
        cost = data["cost_summary"]
        assert "provider" in cost
        assert "currency" in cost
        assert "current_monthly" in cost
        assert "projected_monthly" in cost
        assert "monthly_savings" in cost
        assert "annual_savings" in cost
        assert "savings_percent" in cost

        # Health summary
        assert "health_summary" in data
        health = data["health_summary"]
        assert "average_health_score" in health
        assert "total_alerts" in health
        assert "critical_alerts" in health
        assert "high_alerts" in health

        # Recommendations
        assert "top_recommendations" in data
        assert "workload_count" in data
        assert "suggestion_count" in data

    def test_get_insights_summary_with_provider(self, client, optimization_run):
        """Test GET insights summary with provider query param."""
        response = client.get(
            f"/api/v1/insights/summary/{optimization_run}?provider=gcp"
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["cost_summary"]["provider"] == "gcp"

    def test_get_insights_summary_with_region(self, client, optimization_run):
        """Test GET insights summary with region query param."""
        response = client.get(
            f"/api/v1/insights/summary/{optimization_run}?provider=aws&region=eu-west-1"
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["cost_summary"]["region"] == "eu-west-1"

    def test_get_insights_summary_not_found(self, client):
        """Test GET insights summary for non-existent run."""
        response = client.get("/api/v1/insights/summary/nonexistent-id")

        assert response.status_code == 404
        data = response.get_json()
        assert data["code"] == "NOT_FOUND"

    def test_insights_summary_recommendations_limit(self, client, optimization_run):
        """Test that recommendations are limited to top 5."""
        response = client.get(f"/api/v1/insights/summary/{optimization_run}")

        assert response.status_code == 200
        data = response.get_json()

        # Should have at most 5 recommendations
        assert len(data["top_recommendations"]) <= 5

    def test_insights_summary_recommendation_structure(self, client, optimization_run):
        """Test recommendation structure when present."""
        response = client.get(f"/api/v1/insights/summary/{optimization_run}")

        assert response.status_code == 200
        data = response.get_json()

        for rec in data["top_recommendations"]:
            assert "type" in rec
            assert "severity" in rec
            assert "workload" in rec
            assert "recommendation" in rec

    def test_insights_summary_health_score_range(self, client, optimization_run):
        """Test that health score is within valid range."""
        response = client.get(f"/api/v1/insights/summary/{optimization_run}")

        assert response.status_code == 200
        data = response.get_json()

        health_score = data["health_summary"]["average_health_score"]
        assert 0 <= health_score <= 100

    def test_insights_summary_counts_non_negative(self, client, optimization_run):
        """Test that all counts are non-negative."""
        response = client.get(f"/api/v1/insights/summary/{optimization_run}")

        assert response.status_code == 200
        data = response.get_json()

        assert data["workload_count"] >= 0
        assert data["suggestion_count"] >= 0
        assert data["health_summary"]["total_alerts"] >= 0
        assert data["health_summary"]["critical_alerts"] >= 0
        assert data["health_summary"]["high_alerts"] >= 0


class TestErrorHandling:
    """Integration tests for error handling in insights endpoints."""

    def test_insights_404_for_invalid_path(self, client):
        """Test 404 for invalid insights path."""
        response = client.get("/api/v1/insights/invalid")

        assert response.status_code == 404

    def test_cost_endpoint_bad_json(self, client):
        """Test cost endpoint with malformed JSON."""
        response = client.post(
            "/api/v1/insights/cost",
            data="not valid json",
            content_type="application/json",
        )

        # Should handle gracefully
        assert response.status_code == 400

    def test_anomaly_endpoint_bad_json(self, client):
        """Test anomaly endpoint with malformed JSON."""
        response = client.post(
            "/api/v1/insights/anomalies",
            data="not valid json",
            content_type="application/json",
        )

        # Should handle gracefully
        assert response.status_code == 400

    def test_cost_endpoint_empty_body(self, client):
        """Test cost endpoint with empty body."""
        response = client.post(
            "/api/v1/insights/cost",
            json={},
        )

        assert response.status_code == 400
        data = response.get_json()
        assert data["code"] == "VALIDATION_ERROR"

    def test_anomaly_endpoint_empty_body(self, client):
        """Test anomaly endpoint with empty body."""
        response = client.post(
            "/api/v1/insights/anomalies",
            json={},
        )

        assert response.status_code == 400
        data = response.get_json()
        assert data["code"] == "VALIDATION_ERROR"


class TestDatabaseTransactions:
    """Integration tests for database transaction handling."""

    def test_multiple_cost_projections_same_run(self, client, optimization_run):
        """Test multiple cost projections for the same run."""
        # Request cost projection multiple times
        for provider in ["aws", "gcp", "azure"]:
            response = client.post(
                "/api/v1/insights/cost",
                json={
                    "run_id": optimization_run,
                    "provider": provider,
                },
            )
            assert response.status_code == 200

    def test_multiple_anomaly_analyses_same_run(self, client, optimization_run):
        """Test multiple anomaly analyses for the same run."""
        # Request anomaly analysis multiple times
        for hours in [1, 24, 48, 168]:
            response = client.post(
                "/api/v1/insights/anomalies",
                json={
                    "run_id": optimization_run,
                    "hours": hours,
                },
            )
            assert response.status_code == 200

    def test_concurrent_insights_requests(self, client, optimization_run):
        """Test that insights can be requested concurrently for same run."""
        # Get cost and anomaly in sequence (simulating concurrent access)
        cost_response = client.get(f"/api/v1/insights/cost/{optimization_run}")
        anomaly_response = client.get(f"/api/v1/insights/anomalies/{optimization_run}")
        summary_response = client.get(f"/api/v1/insights/summary/{optimization_run}")

        assert cost_response.status_code == 200
        assert anomaly_response.status_code == 200
        assert summary_response.status_code == 200

    def test_optimization_run_persists_for_insights(self, client):
        """Test that optimization run data persists for insights queries."""
        # Create optimization run
        create_response = client.post(
            "/api/v1/optimize/run",
            json={"manifest_path": str(FIXTURES_DIR)},
        )
        run_id = create_response.get_json()["run_id"]

        # Verify run exists
        run_response = client.get(f"/api/v1/optimize/run/{run_id}")
        assert run_response.status_code == 200

        # Query insights
        cost_response = client.get(f"/api/v1/insights/cost/{run_id}")
        assert cost_response.status_code == 200

        anomaly_response = client.get(f"/api/v1/insights/anomalies/{run_id}")
        assert anomaly_response.status_code == 200

        summary_response = client.get(f"/api/v1/insights/summary/{run_id}")
        assert summary_response.status_code == 200


class TestCloudProviderPricing:
    """Integration tests for cloud provider-specific pricing."""

    def test_aws_pricing_structure(self, client, optimization_run):
        """Test AWS pricing has expected structure."""
        response = client.post(
            "/api/v1/insights/cost",
            json={
                "run_id": optimization_run,
                "provider": "aws",
                "region": "us-east-1",
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["currency"] == "USD"

    def test_gcp_pricing_structure(self, client, optimization_run):
        """Test GCP pricing has expected structure."""
        response = client.post(
            "/api/v1/insights/cost",
            json={
                "run_id": optimization_run,
                "provider": "gcp",
                "region": "us-central1",
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["currency"] == "USD"

    def test_azure_pricing_structure(self, client, optimization_run):
        """Test Azure pricing has expected structure."""
        response = client.post(
            "/api/v1/insights/cost",
            json={
                "run_id": optimization_run,
                "provider": "azure",
                "region": "eastus",
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["currency"] == "USD"

    def test_on_prem_pricing_structure(self, client, optimization_run):
        """Test on-prem pricing has expected structure."""
        response = client.post(
            "/api/v1/insights/cost",
            json={
                "run_id": optimization_run,
                "provider": "on_prem",
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["currency"] == "USD"

    def test_different_providers_different_costs(self, client, optimization_run):
        """Test that different providers may have different costs."""
        costs = {}
        for provider in ["aws", "gcp", "azure", "on_prem"]:
            response = client.post(
                "/api/v1/insights/cost",
                json={
                    "run_id": optimization_run,
                    "provider": provider,
                },
            )
            assert response.status_code == 200
            data = response.get_json()
            costs[provider] = data["total_current_monthly"]

        # All should have calculated costs (may differ)
        for provider, cost in costs.items():
            assert cost >= 0, f"{provider} should have non-negative cost"
