"""
Pydantic schemas for request/response validation and LLM response parsing.

This module defines the data structures used throughout KubeOpt AI for:
- API request/response validation
- LLM response schema validation
- Internal data transfer objects
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


# ============================================================================
# Enums
# ============================================================================

class RunStatus(str, Enum):
    """Status values for optimization runs."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class WorkloadKind(str, Enum):
    """Kubernetes workload types supported by the optimizer."""
    DEPLOYMENT = "Deployment"
    STATEFULSET = "StatefulSet"
    DAEMONSET = "DaemonSet"


# ============================================================================
# Resource Configuration Schemas
# ============================================================================

class ResourceRequirements(BaseModel):
    """CPU and memory resource requirements."""
    cpu: Optional[str] = None
    memory: Optional[str] = None


class ContainerResources(BaseModel):
    """Container resource requests and limits."""
    requests: ResourceRequirements = Field(default_factory=ResourceRequirements)
    limits: ResourceRequirements = Field(default_factory=ResourceRequirements)


class ContainerConfig(BaseModel):
    """Configuration for a single container."""
    name: str
    image: str
    resources: ContainerResources = Field(default_factory=ContainerResources)


# ============================================================================
# HPA Configuration Schemas
# ============================================================================

class HPAConfig(BaseModel):
    """HorizontalPodAutoscaler configuration."""
    min_replicas: Optional[int] = Field(default=None, ge=1)
    max_replicas: Optional[int] = Field(default=None, ge=1)
    target_cpu_percent: Optional[int] = Field(default=None, ge=1, le=100)
    target_memory_percent: Optional[int] = Field(default=None, ge=1, le=100)


# ============================================================================
# Workload Descriptor Schemas (for scanning)
# ============================================================================

class WorkloadDescriptor(BaseModel):
    """
    Normalized workload descriptor from K8s manifest scanning.

    Contains all relevant information about a workload for optimization.
    """
    model_config = ConfigDict(use_enum_values=True)

    kind: WorkloadKind
    name: str
    namespace: str = "default"
    replicas: Optional[int] = None
    containers: list[ContainerConfig] = Field(default_factory=list)
    hpa: Optional[HPAConfig] = None
    labels: dict[str, str] = Field(default_factory=dict)
    manifest_path: Optional[str] = None


# ============================================================================
# Metrics Schemas
# ============================================================================

class ContainerMetrics(BaseModel):
    """Metrics for a single container over a lookback period."""
    container_name: str
    avg_cpu_usage: Optional[float] = None  # in cores
    p95_cpu_usage: Optional[float] = None
    max_cpu_usage: Optional[float] = None
    avg_memory_usage: Optional[float] = None  # in bytes
    p95_memory_usage: Optional[float] = None
    max_memory_usage: Optional[float] = None


class WorkloadMetrics(BaseModel):
    """Aggregated metrics for a workload."""
    workload_name: str
    namespace: str
    lookback_days: int
    container_metrics: list[ContainerMetrics] = Field(default_factory=list)
    avg_replica_count: Optional[float] = None
    max_replica_count: Optional[int] = None


# ============================================================================
# LLM Response Schemas
# ============================================================================

class ContainerSuggestion(BaseModel):
    """LLM suggestion for a container's resources."""
    container: str
    current: ContainerResources
    proposed: ContainerResources
    reasoning: str


class HPASuggestion(BaseModel):
    """LLM suggestion for HPA configuration."""
    current: Optional[HPAConfig] = None
    proposed: Optional[HPAConfig] = None
    reasoning: str


class WorkloadSuggestion(BaseModel):
    """Complete LLM suggestion for a workload."""
    name: str
    namespace: str
    kind: str
    suggestions: list[ContainerSuggestion] = Field(default_factory=list)
    hpa: Optional[HPASuggestion] = None


class LLMOptimizationResponse(BaseModel):
    """
    Schema for validating LLM optimization responses.

    This is the expected JSON structure from the LLM.
    """
    workloads: list[WorkloadSuggestion]


# ============================================================================
# API Request/Response Schemas
# ============================================================================

class OptimizationRunRequest(BaseModel):
    """Request body for creating an optimization run."""
    manifest_path: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        description="Filesystem path to Kubernetes manifests"
    )
    lookback_days: int = Field(
        default=7,
        ge=1,
        le=90,
        description="Number of days to look back for metrics"
    )


class OptimizationRunResponse(BaseModel):
    """Response body for optimization run details."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime
    manifest_source_path: str
    lookback_days: int
    status: RunStatus
    error_message: Optional[str] = None


class WorkloadSnapshotResponse(BaseModel):
    """Response body for workload snapshot details."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    name: str
    namespace: str
    kind: str
    current_config: dict
    metrics_summary: Optional[dict] = None


class SuggestionResponse(BaseModel):
    """Response body for suggestion details."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    workload_snapshot_id: str
    container_name: str
    suggestion_type: str
    current_config: dict
    proposed_config: dict
    reasoning: Optional[str] = None
    diff_text: Optional[str] = None


class OptimizationRunDetailResponse(BaseModel):
    """Detailed response including workloads and suggestions."""
    run: OptimizationRunResponse
    workloads: list[WorkloadSnapshotResponse] = Field(default_factory=list)
    suggestions: list[SuggestionResponse] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Standard error response format."""
    code: str
    message: str
    details: Optional[dict] = None
    trace_id: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    service: str
    version: str = "1.0.0"
    checks: Optional[dict] = None


# ============================================================================
# Cost Projection Schemas
# ============================================================================

class CloudProvider(str, Enum):
    """Supported cloud providers for cost calculation."""
    AWS = "aws"
    GCP = "gcp"
    AZURE = "azure"
    ON_PREM = "on_prem"


class CostBreakdownResponse(BaseModel):
    """Breakdown of costs by resource type."""
    cpu_cost: float
    memory_cost: float
    total_cost: float
    cpu_cores: float
    memory_gib: float


class WorkloadCostResponse(BaseModel):
    """Cost analysis for a single workload."""
    workload_name: str
    namespace: str
    replicas: int
    current_cost: CostBreakdownResponse
    projected_cost: Optional[CostBreakdownResponse] = None
    monthly_savings: Optional[float] = None
    savings_percent: Optional[float] = None


class CostProjectionResponse(BaseModel):
    """Complete cost projection response."""
    provider: str
    region: str
    currency: str
    workload_costs: list[WorkloadCostResponse] = Field(default_factory=list)
    total_current_monthly: float
    total_projected_monthly: float
    total_monthly_savings: float
    total_annual_savings: float
    savings_percent: float


class CostProjectionRequest(BaseModel):
    """Request for cost projection calculation."""
    run_id: str = Field(..., description="Optimization run ID to analyze")
    provider: CloudProvider = Field(
        default=CloudProvider.AWS,
        description="Cloud provider for pricing"
    )
    region: Optional[str] = Field(
        default=None,
        description="Cloud region (uses provider default if not specified)"
    )


# ============================================================================
# Anomaly Detection Schemas
# ============================================================================

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


class AnomalyAlertResponse(BaseModel):
    """An anomaly detection alert."""
    anomaly_type: AnomalyType
    severity: AlertSeverity
    workload_name: str
    namespace: str
    container_name: str
    resource_type: str
    description: str
    current_value: float
    threshold: float
    score: float
    detected_at: datetime
    recommendation: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class AnomalyAnalysisResponse(BaseModel):
    """Complete anomaly analysis for a workload."""
    workload_name: str
    namespace: str
    analysis_period_hours: int
    alerts: list[AnomalyAlertResponse] = Field(default_factory=list)
    health_score: float
    analyzed_at: datetime


class AnomalyAnalysisRequest(BaseModel):
    """Request for anomaly analysis."""
    run_id: str = Field(..., description="Optimization run ID to analyze")
    hours: int = Field(
        default=24,
        ge=1,
        le=168,
        description="Analysis period in hours (max 7 days)"
    )


class AnomalySummaryResponse(BaseModel):
    """Summary of anomaly analysis across workloads."""
    run_id: str
    total_workloads: int
    total_alerts: int
    alerts_by_severity: dict[str, int]
    alerts_by_type: dict[str, int]
    average_health_score: float
    workload_analyses: list[AnomalyAnalysisResponse] = Field(default_factory=list)
