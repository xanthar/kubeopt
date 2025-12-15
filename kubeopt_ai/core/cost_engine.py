"""
Cost Projection Engine for KubeOpt AI.

This module provides cloud provider pricing models and cost calculation
for Kubernetes workloads. It estimates current costs and projected savings
from optimization recommendations.

Supported providers:
- AWS (EKS)
- GCP (GKE)
- Azure (AKS)
"""

import logging
import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class CloudProvider(str, Enum):
    """Supported cloud providers."""
    AWS = "aws"
    GCP = "gcp"
    AZURE = "azure"
    ON_PREM = "on_prem"  # Custom pricing for on-prem


@dataclass(frozen=True)
class ResourcePricing:
    """Pricing per resource unit per hour."""
    cpu_per_core_hour: Decimal  # USD per vCPU hour
    memory_per_gib_hour: Decimal  # USD per GiB hour
    region: str
    instance_type: str = "general"


# Cloud provider pricing (approximate on-demand rates as of 2024)
# These are simplified averages - real pricing varies by instance type/region
CLOUD_PRICING: dict[CloudProvider, dict[str, ResourcePricing]] = {
    CloudProvider.AWS: {
        "us-east-1": ResourcePricing(
            cpu_per_core_hour=Decimal("0.0416"),
            memory_per_gib_hour=Decimal("0.0046"),
            region="us-east-1",
        ),
        "us-west-2": ResourcePricing(
            cpu_per_core_hour=Decimal("0.0416"),
            memory_per_gib_hour=Decimal("0.0046"),
            region="us-west-2",
        ),
        "eu-west-1": ResourcePricing(
            cpu_per_core_hour=Decimal("0.0464"),
            memory_per_gib_hour=Decimal("0.0051"),
            region="eu-west-1",
        ),
        "ap-northeast-1": ResourcePricing(
            cpu_per_core_hour=Decimal("0.0528"),
            memory_per_gib_hour=Decimal("0.0058"),
            region="ap-northeast-1",
        ),
    },
    CloudProvider.GCP: {
        "us-central1": ResourcePricing(
            cpu_per_core_hour=Decimal("0.0335"),
            memory_per_gib_hour=Decimal("0.0045"),
            region="us-central1",
        ),
        "us-east1": ResourcePricing(
            cpu_per_core_hour=Decimal("0.0335"),
            memory_per_gib_hour=Decimal("0.0045"),
            region="us-east1",
        ),
        "europe-west1": ResourcePricing(
            cpu_per_core_hour=Decimal("0.0369"),
            memory_per_gib_hour=Decimal("0.0049"),
            region="europe-west1",
        ),
    },
    CloudProvider.AZURE: {
        "eastus": ResourcePricing(
            cpu_per_core_hour=Decimal("0.0400"),
            memory_per_gib_hour=Decimal("0.0044"),
            region="eastus",
        ),
        "westus2": ResourcePricing(
            cpu_per_core_hour=Decimal("0.0400"),
            memory_per_gib_hour=Decimal("0.0044"),
            region="westus2",
        ),
        "westeurope": ResourcePricing(
            cpu_per_core_hour=Decimal("0.0440"),
            memory_per_gib_hour=Decimal("0.0048"),
            region="westeurope",
        ),
    },
    CloudProvider.ON_PREM: {
        "default": ResourcePricing(
            cpu_per_core_hour=Decimal("0.030"),  # Conservative estimate
            memory_per_gib_hour=Decimal("0.004"),
            region="default",
        ),
    },
}


def get_default_region(provider: CloudProvider) -> str:
    """Get the default region for a cloud provider."""
    defaults = {
        CloudProvider.AWS: "us-east-1",
        CloudProvider.GCP: "us-central1",
        CloudProvider.AZURE: "eastus",
        CloudProvider.ON_PREM: "default",
    }
    return defaults.get(provider, "default")


@dataclass
class ResourceValues:
    """Parsed resource values in standard units."""
    cpu_cores: Decimal  # In full cores (1 = 1 vCPU)
    memory_gib: Decimal  # In GiB


class ResourceParser:
    """Parse Kubernetes resource strings into numeric values."""

    # CPU patterns: "100m", "0.5", "1", "2000m"
    CPU_MILLI_PATTERN = re.compile(r"^(\d+)m$")
    CPU_CORE_PATTERN = re.compile(r"^(\d+\.?\d*)$")

    # Memory patterns: "128Mi", "1Gi", "256M", "1G", "1073741824"
    MEMORY_PATTERN = re.compile(
        r"^(\d+\.?\d*)(Ki|Mi|Gi|Ti|K|M|G|T|k|m|g)?$"
    )

    # Multipliers for memory units (to bytes)
    MEMORY_MULTIPLIERS = {
        None: 1,
        "": 1,
        "Ki": 1024,
        "Mi": 1024**2,
        "Gi": 1024**3,
        "Ti": 1024**4,
        "K": 1000,
        "M": 1000**2,
        "G": 1000**3,
        "T": 1000**4,
        "k": 1000,
        "m": 1000**2,
        "g": 1000**3,
    }

    @classmethod
    def parse_cpu(cls, cpu_str: Optional[str]) -> Decimal:
        """
        Parse a Kubernetes CPU string to cores.

        Args:
            cpu_str: CPU string like "100m", "0.5", "1"

        Returns:
            CPU value in cores as Decimal
        """
        if not cpu_str:
            return Decimal("0")

        cpu_str = str(cpu_str).strip()

        # Check for millicores
        milli_match = cls.CPU_MILLI_PATTERN.match(cpu_str)
        if milli_match:
            millicores = Decimal(milli_match.group(1))
            return millicores / Decimal("1000")

        # Check for cores (decimal)
        core_match = cls.CPU_CORE_PATTERN.match(cpu_str)
        if core_match:
            return Decimal(core_match.group(1))

        logger.warning(f"Could not parse CPU value: {cpu_str}")
        return Decimal("0")

    @classmethod
    def parse_memory(cls, mem_str: Optional[str]) -> Decimal:
        """
        Parse a Kubernetes memory string to GiB.

        Args:
            mem_str: Memory string like "128Mi", "1Gi", "256M"

        Returns:
            Memory value in GiB as Decimal
        """
        if not mem_str:
            return Decimal("0")

        mem_str = str(mem_str).strip()

        match = cls.MEMORY_PATTERN.match(mem_str)
        if not match:
            logger.warning(f"Could not parse memory value: {mem_str}")
            return Decimal("0")

        value = Decimal(match.group(1))
        unit = match.group(2)

        multiplier = cls.MEMORY_MULTIPLIERS.get(unit, 1)
        bytes_value = value * Decimal(str(multiplier))

        # Convert to GiB
        gib = bytes_value / Decimal(str(1024**3))
        return gib

    @classmethod
    def parse_resources(
        cls,
        cpu: Optional[str],
        memory: Optional[str]
    ) -> ResourceValues:
        """Parse both CPU and memory into ResourceValues."""
        return ResourceValues(
            cpu_cores=cls.parse_cpu(cpu),
            memory_gib=cls.parse_memory(memory),
        )


@dataclass
class CostBreakdown:
    """Breakdown of costs by resource type."""
    cpu_cost: Decimal
    memory_cost: Decimal
    total_cost: Decimal
    cpu_cores: Decimal
    memory_gib: Decimal


@dataclass
class WorkloadCost:
    """Cost analysis for a single workload."""
    workload_name: str
    namespace: str
    replicas: int
    current_cost: CostBreakdown
    projected_cost: Optional[CostBreakdown] = None
    monthly_savings: Optional[Decimal] = None
    savings_percent: Optional[Decimal] = None


@dataclass
class CostProjection:
    """Complete cost projection for an optimization run."""
    provider: CloudProvider
    region: str
    currency: str
    workload_costs: list[WorkloadCost]
    total_current_monthly: Decimal
    total_projected_monthly: Decimal
    total_monthly_savings: Decimal
    total_annual_savings: Decimal
    savings_percent: Decimal


class CostCalculator:
    """
    Calculate resource costs and projected savings.

    Uses cloud provider pricing to estimate the cost of current
    resource allocations and the potential savings from applying
    optimization recommendations.
    """

    HOURS_PER_MONTH = Decimal("730")  # Average hours per month
    HOURS_PER_YEAR = Decimal("8760")

    def __init__(
        self,
        provider: CloudProvider = CloudProvider.AWS,
        region: Optional[str] = None,
        custom_pricing: Optional[ResourcePricing] = None,
    ):
        """
        Initialize the cost calculator.

        Args:
            provider: Cloud provider for pricing.
            region: Region for pricing lookup.
            custom_pricing: Optional custom pricing to override defaults.
        """
        self.provider = provider
        self.region = region or get_default_region(provider)
        self.custom_pricing = custom_pricing

    def get_pricing(self) -> ResourcePricing:
        """Get the effective pricing for calculations."""
        if self.custom_pricing:
            return self.custom_pricing

        provider_pricing = CLOUD_PRICING.get(self.provider, {})
        pricing = provider_pricing.get(self.region)

        if not pricing:
            # Fall back to first available region
            if provider_pricing:
                pricing = next(iter(provider_pricing.values()))
            else:
                # Ultimate fallback to on-prem
                pricing = CLOUD_PRICING[CloudProvider.ON_PREM]["default"]

        return pricing

    def calculate_hourly_cost(
        self,
        cpu_cores: Decimal,
        memory_gib: Decimal,
    ) -> CostBreakdown:
        """
        Calculate hourly cost for given resources.

        Args:
            cpu_cores: CPU in cores.
            memory_gib: Memory in GiB.

        Returns:
            CostBreakdown with hourly costs.
        """
        pricing = self.get_pricing()

        cpu_cost = cpu_cores * pricing.cpu_per_core_hour
        memory_cost = memory_gib * pricing.memory_per_gib_hour
        total = cpu_cost + memory_cost

        return CostBreakdown(
            cpu_cost=cpu_cost.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            memory_cost=memory_cost.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            total_cost=total.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            cpu_cores=cpu_cores,
            memory_gib=memory_gib,
        )

    def calculate_monthly_cost(
        self,
        cpu_cores: Decimal,
        memory_gib: Decimal,
        replicas: int = 1,
    ) -> CostBreakdown:
        """
        Calculate monthly cost for given resources.

        Args:
            cpu_cores: CPU in cores (per replica).
            memory_gib: Memory in GiB (per replica).
            replicas: Number of replicas.

        Returns:
            CostBreakdown with monthly costs.
        """
        hourly = self.calculate_hourly_cost(cpu_cores, memory_gib)

        # Scale by replicas and hours per month
        scale = self.HOURS_PER_MONTH * Decimal(str(replicas))

        return CostBreakdown(
            cpu_cost=(hourly.cpu_cost * scale).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            ),
            memory_cost=(hourly.memory_cost * scale).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            ),
            total_cost=(hourly.total_cost * scale).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            ),
            cpu_cores=cpu_cores * Decimal(str(replicas)),
            memory_gib=memory_gib * Decimal(str(replicas)),
        )

    def calculate_workload_cost(
        self,
        workload_name: str,
        namespace: str,
        containers_current: list[dict],
        containers_proposed: Optional[list[dict]] = None,
        replicas: int = 1,
    ) -> WorkloadCost:
        """
        Calculate cost analysis for a workload.

        Args:
            workload_name: Name of the workload.
            namespace: Kubernetes namespace.
            containers_current: List of current container configs with resources.
            containers_proposed: Optional list of proposed container configs.
            replicas: Number of replicas.

        Returns:
            WorkloadCost with current and projected costs.
        """
        # Sum up current resources across containers
        total_cpu_current = Decimal("0")
        total_mem_current = Decimal("0")

        for container in containers_current:
            resources = container.get("resources", {})
            requests = resources.get("requests", {})

            # Use requests for cost calculation (that's what's reserved)
            cpu = ResourceParser.parse_cpu(requests.get("cpu"))
            mem = ResourceParser.parse_memory(requests.get("memory"))

            total_cpu_current += cpu
            total_mem_current += mem

        current_cost = self.calculate_monthly_cost(
            total_cpu_current, total_mem_current, replicas
        )

        # Calculate proposed if provided
        projected_cost = None
        monthly_savings = None
        savings_percent = None

        if containers_proposed:
            total_cpu_proposed = Decimal("0")
            total_mem_proposed = Decimal("0")

            for container in containers_proposed:
                resources = container.get("resources", {})
                requests = resources.get("requests", {})

                cpu = ResourceParser.parse_cpu(requests.get("cpu"))
                mem = ResourceParser.parse_memory(requests.get("memory"))

                total_cpu_proposed += cpu
                total_mem_proposed += mem

            projected_cost = self.calculate_monthly_cost(
                total_cpu_proposed, total_mem_proposed, replicas
            )

            monthly_savings = current_cost.total_cost - projected_cost.total_cost
            if current_cost.total_cost > 0:
                savings_percent = (
                    (monthly_savings / current_cost.total_cost) * Decimal("100")
                ).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)

        return WorkloadCost(
            workload_name=workload_name,
            namespace=namespace,
            replicas=replicas,
            current_cost=current_cost,
            projected_cost=projected_cost,
            monthly_savings=monthly_savings,
            savings_percent=savings_percent,
        )

    def calculate_projection(
        self,
        workload_analyses: list[WorkloadCost],
    ) -> CostProjection:
        """
        Calculate total cost projection across multiple workloads.

        Args:
            workload_analyses: List of individual workload cost analyses.

        Returns:
            CostProjection with totals and savings.
        """
        total_current = Decimal("0")
        total_projected = Decimal("0")

        for wc in workload_analyses:
            total_current += wc.current_cost.total_cost
            if wc.projected_cost:
                total_projected += wc.projected_cost.total_cost
            else:
                total_projected += wc.current_cost.total_cost

        total_savings = total_current - total_projected
        annual_savings = total_savings * Decimal("12")

        savings_percent = Decimal("0")
        if total_current > 0:
            savings_percent = (
                (total_savings / total_current) * Decimal("100")
            ).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)

        return CostProjection(
            provider=self.provider,
            region=self.region,
            currency="USD",
            workload_costs=workload_analyses,
            total_current_monthly=total_current.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            ),
            total_projected_monthly=total_projected.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            ),
            total_monthly_savings=total_savings.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            ),
            total_annual_savings=annual_savings.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            ),
            savings_percent=savings_percent,
        )


def calculate_optimization_savings(
    optimization_run_details: dict,
    provider: CloudProvider = CloudProvider.AWS,
    region: Optional[str] = None,
) -> CostProjection:
    """
    Calculate cost savings from an optimization run.

    Args:
        optimization_run_details: Details dict from OptimizerService.get_run_details()
        provider: Cloud provider for pricing.
        region: Region for pricing lookup.

    Returns:
        CostProjection with detailed cost analysis.
    """
    calculator = CostCalculator(provider=provider, region=region)

    workload_analyses = []

    for workload in optimization_run_details.get("workloads", []):
        workload_name = workload.get("name", "unknown")
        namespace = workload.get("namespace", "default")
        current_config = workload.get("current_config", {})

        # Get containers from current config
        containers_current = current_config.get("containers", [])
        replicas = current_config.get("replicas", 1) or 1

        # Find matching suggestions
        suggestions = [
            s for s in optimization_run_details.get("suggestions", [])
            if s.get("workload_snapshot_id") == workload.get("id")
            and s.get("suggestion_type") == "resources"
        ]

        # Build proposed containers from suggestions
        containers_proposed = None
        if suggestions:
            containers_proposed = []
            for container in containers_current:
                container_name = container.get("name")
                matching_suggestion = next(
                    (s for s in suggestions if s.get("container_name") == container_name),
                    None
                )

                if matching_suggestion:
                    proposed_config = matching_suggestion.get("proposed_config", {})
                    containers_proposed.append({
                        "name": container_name,
                        "resources": proposed_config,
                    })
                else:
                    containers_proposed.append(container)

        workload_cost = calculator.calculate_workload_cost(
            workload_name=workload_name,
            namespace=namespace,
            containers_current=containers_current,
            containers_proposed=containers_proposed,
            replicas=replicas,
        )
        workload_analyses.append(workload_cost)

    return calculator.calculate_projection(workload_analyses)
