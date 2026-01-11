"""
Unit tests for Cost Projection Engine.

Tests the cost calculation, resource parsing, and savings projection
functionality.
"""

import pytest
from decimal import Decimal

from kubeopt_ai.core.cost_engine import (
    CloudProvider,
    ResourcePricing,
    ResourceParser,
    CostBreakdown,
    WorkloadCost,
    CostCalculator,
    calculate_optimization_savings,
    get_default_region,
    CLOUD_PRICING,
)


class TestResourceParser:
    """Tests for Kubernetes resource string parsing."""

    def test_parse_cpu_millicores(self):
        """Parse CPU values in millicores."""
        assert ResourceParser.parse_cpu("100m") == Decimal("0.1")
        assert ResourceParser.parse_cpu("500m") == Decimal("0.5")
        assert ResourceParser.parse_cpu("1000m") == Decimal("1")
        assert ResourceParser.parse_cpu("2500m") == Decimal("2.5")

    def test_parse_cpu_cores(self):
        """Parse CPU values in cores."""
        assert ResourceParser.parse_cpu("1") == Decimal("1")
        assert ResourceParser.parse_cpu("0.5") == Decimal("0.5")
        assert ResourceParser.parse_cpu("2") == Decimal("2")
        assert ResourceParser.parse_cpu("0.25") == Decimal("0.25")

    def test_parse_cpu_empty(self):
        """Parse empty or None CPU values."""
        assert ResourceParser.parse_cpu(None) == Decimal("0")
        assert ResourceParser.parse_cpu("") == Decimal("0")

    def test_parse_cpu_invalid(self):
        """Parse invalid CPU values returns 0."""
        assert ResourceParser.parse_cpu("invalid") == Decimal("0")
        assert ResourceParser.parse_cpu("100Mi") == Decimal("0")

    def test_parse_memory_mibibytes(self):
        """Parse memory in MiB."""
        result = ResourceParser.parse_memory("128Mi")
        assert result == Decimal("128") / Decimal("1024")  # 0.125 GiB

    def test_parse_memory_gibibytes(self):
        """Parse memory in GiB."""
        result = ResourceParser.parse_memory("1Gi")
        assert result == Decimal("1")

        result = ResourceParser.parse_memory("2Gi")
        assert result == Decimal("2")

    def test_parse_memory_decimal_units(self):
        """Parse memory with decimal units (M, G)."""
        # 1G = 1000^3 bytes, 1Gi = 1024^3 bytes
        result_decimal = ResourceParser.parse_memory("1G")
        result_binary = ResourceParser.parse_memory("1Gi")
        assert result_decimal < result_binary

    def test_parse_memory_kibibytes(self):
        """Parse memory in KiB."""
        result = ResourceParser.parse_memory("1048576Ki")
        assert result == Decimal("1")  # 1 GiB

    def test_parse_memory_empty(self):
        """Parse empty or None memory values."""
        assert ResourceParser.parse_memory(None) == Decimal("0")
        assert ResourceParser.parse_memory("") == Decimal("0")

    def test_parse_memory_bytes(self):
        """Parse memory in raw bytes."""
        result = ResourceParser.parse_memory("1073741824")  # 1 GiB in bytes
        assert result == Decimal("1")

    def test_parse_resources(self):
        """Parse combined CPU and memory."""
        result = ResourceParser.parse_resources("500m", "1Gi")
        assert result.cpu_cores == Decimal("0.5")
        assert result.memory_gib == Decimal("1")


class TestCostCalculator:
    """Tests for cost calculation logic."""

    @pytest.fixture
    def calculator(self):
        """Create a calculator with default AWS pricing."""
        return CostCalculator(
            provider=CloudProvider.AWS,
            region="us-east-1",
        )

    @pytest.fixture
    def custom_calculator(self):
        """Create a calculator with custom pricing."""
        custom_pricing = ResourcePricing(
            cpu_per_core_hour=Decimal("0.05"),
            memory_per_gib_hour=Decimal("0.005"),
            region="custom",
        )
        return CostCalculator(
            provider=CloudProvider.AWS,
            custom_pricing=custom_pricing,
        )

    def test_get_pricing_default(self, calculator):
        """Get default pricing for AWS us-east-1."""
        pricing = calculator.get_pricing()
        assert pricing.region == "us-east-1"
        assert pricing.cpu_per_core_hour > 0
        assert pricing.memory_per_gib_hour > 0

    def test_get_pricing_custom(self, custom_calculator):
        """Custom pricing overrides provider pricing."""
        pricing = custom_calculator.get_pricing()
        assert pricing.cpu_per_core_hour == Decimal("0.05")
        assert pricing.memory_per_gib_hour == Decimal("0.005")

    def test_calculate_hourly_cost(self, calculator):
        """Calculate hourly cost for resources."""
        cost = calculator.calculate_hourly_cost(
            cpu_cores=Decimal("1"),
            memory_gib=Decimal("2"),
        )

        assert cost.cpu_cores == Decimal("1")
        assert cost.memory_gib == Decimal("2")
        assert cost.total_cost == cost.cpu_cost + cost.memory_cost
        assert cost.total_cost > 0

    def test_calculate_monthly_cost(self, calculator):
        """Calculate monthly cost for resources."""
        cost = calculator.calculate_monthly_cost(
            cpu_cores=Decimal("1"),
            memory_gib=Decimal("2"),
            replicas=3,
        )

        # Monthly should be ~730x hourly (hours per month)
        hourly = calculator.calculate_hourly_cost(
            cpu_cores=Decimal("1"),
            memory_gib=Decimal("2"),
        )
        expected = hourly.total_cost * Decimal("730") * Decimal("3")

        assert abs(cost.total_cost - expected) < Decimal("0.1")

    def test_calculate_workload_cost_current_only(self, calculator):
        """Calculate workload cost with current config only."""
        containers = [
            {
                "name": "main",
                "resources": {
                    "requests": {"cpu": "500m", "memory": "512Mi"},
                },
            }
        ]

        result = calculator.calculate_workload_cost(
            workload_name="test-app",
            namespace="default",
            containers_current=containers,
            replicas=2,
        )

        assert result.workload_name == "test-app"
        assert result.namespace == "default"
        assert result.replicas == 2
        assert result.current_cost.total_cost > 0
        assert result.projected_cost is None
        assert result.monthly_savings is None

    def test_calculate_workload_cost_with_savings(self, calculator):
        """Calculate workload cost with current and proposed configs."""
        containers_current = [
            {
                "name": "main",
                "resources": {
                    "requests": {"cpu": "1", "memory": "2Gi"},
                },
            }
        ]
        containers_proposed = [
            {
                "name": "main",
                "resources": {
                    "requests": {"cpu": "500m", "memory": "1Gi"},
                },
            }
        ]

        result = calculator.calculate_workload_cost(
            workload_name="test-app",
            namespace="default",
            containers_current=containers_current,
            containers_proposed=containers_proposed,
            replicas=2,
        )

        assert result.projected_cost is not None
        assert result.monthly_savings is not None
        assert result.savings_percent is not None
        # Proposed uses half the resources, should save ~50%
        assert result.monthly_savings > 0
        assert Decimal("40") <= result.savings_percent <= Decimal("60")

    def test_calculate_projection_multiple_workloads(self, calculator):
        """Calculate projection across multiple workloads."""
        workload1 = WorkloadCost(
            workload_name="app1",
            namespace="default",
            replicas=2,
            current_cost=CostBreakdown(
                cpu_cost=Decimal("100"),
                memory_cost=Decimal("50"),
                total_cost=Decimal("150"),
                cpu_cores=Decimal("2"),
                memory_gib=Decimal("4"),
            ),
            projected_cost=CostBreakdown(
                cpu_cost=Decimal("50"),
                memory_cost=Decimal("25"),
                total_cost=Decimal("75"),
                cpu_cores=Decimal("1"),
                memory_gib=Decimal("2"),
            ),
            monthly_savings=Decimal("75"),
            savings_percent=Decimal("50"),
        )
        workload2 = WorkloadCost(
            workload_name="app2",
            namespace="default",
            replicas=1,
            current_cost=CostBreakdown(
                cpu_cost=Decimal("200"),
                memory_cost=Decimal("100"),
                total_cost=Decimal("300"),
                cpu_cores=Decimal("4"),
                memory_gib=Decimal("8"),
            ),
            # No projected means no savings
        )

        projection = calculator.calculate_projection([workload1, workload2])

        assert projection.total_current_monthly == Decimal("450")
        # Workload2 has no projection, so projected = current
        assert projection.total_projected_monthly == Decimal("375")
        assert projection.total_monthly_savings == Decimal("75")
        assert projection.total_annual_savings == Decimal("900")


class TestCloudProviderPricing:
    """Tests for cloud provider pricing data."""

    def test_all_providers_have_pricing(self):
        """All cloud providers should have pricing data."""
        for provider in CloudProvider:
            assert provider in CLOUD_PRICING
            assert len(CLOUD_PRICING[provider]) > 0

    def test_default_regions_exist(self):
        """Default regions should exist in pricing data."""
        for provider in CloudProvider:
            default_region = get_default_region(provider)
            assert default_region in CLOUD_PRICING[provider]

    def test_pricing_values_positive(self):
        """All pricing values should be positive."""
        for provider, regions in CLOUD_PRICING.items():
            for region, pricing in regions.items():
                assert pricing.cpu_per_core_hour > 0
                assert pricing.memory_per_gib_hour > 0


class TestCalculateOptimizationSavings:
    """Tests for the high-level savings calculation function."""

    @pytest.fixture
    def optimization_run_details(self):
        """Sample optimization run details."""
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
                }
            ],
            "suggestions": [
                {
                    "workload_snapshot_id": "snapshot-1",
                    "container_name": "main",
                    "suggestion_type": "resources",
                    "proposed_config": {
                        "requests": {"cpu": "500m", "memory": "1Gi"},
                        "limits": {"cpu": "1", "memory": "2Gi"},
                    },
                }
            ],
        }

    def test_calculate_savings_aws(self, optimization_run_details):
        """Calculate savings with AWS pricing."""
        projection = calculate_optimization_savings(
            optimization_run_details=optimization_run_details,
            provider=CloudProvider.AWS,
            region="us-east-1",
        )

        assert projection.provider == CloudProvider.AWS
        assert projection.region == "us-east-1"
        assert projection.currency == "USD"
        assert len(projection.workload_costs) == 1
        assert projection.total_monthly_savings > 0

    def test_calculate_savings_gcp(self, optimization_run_details):
        """Calculate savings with GCP pricing."""
        projection = calculate_optimization_savings(
            optimization_run_details=optimization_run_details,
            provider=CloudProvider.GCP,
            region="us-central1",
        )

        assert projection.provider == CloudProvider.GCP
        assert projection.region == "us-central1"

    def test_calculate_savings_no_suggestions(self):
        """Calculate savings when no suggestions exist."""
        details = {
            "workloads": [
                {
                    "id": "snapshot-1",
                    "name": "web-app",
                    "namespace": "production",
                    "current_config": {
                        "replicas": 2,
                        "containers": [
                            {
                                "name": "main",
                                "resources": {
                                    "requests": {"cpu": "500m", "memory": "1Gi"},
                                },
                            }
                        ],
                    },
                }
            ],
            "suggestions": [],
        }

        projection = calculate_optimization_savings(
            optimization_run_details=details,
            provider=CloudProvider.AWS,
        )

        assert projection.total_monthly_savings == Decimal("0")
        assert projection.savings_percent == Decimal("0")

    def test_calculate_savings_empty_workloads(self):
        """Calculate savings with empty workloads."""
        projection = calculate_optimization_savings(
            optimization_run_details={"workloads": [], "suggestions": []},
            provider=CloudProvider.AWS,
        )

        assert projection.total_current_monthly == Decimal("0")
        assert projection.total_projected_monthly == Decimal("0")
