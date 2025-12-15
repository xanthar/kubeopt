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


# ============================================================================
# Apply Feature Schemas (F022)
# ============================================================================

class ApplyMode(str, Enum):
    """How the apply should be executed."""
    DRY_RUN = "dry_run"
    APPLY = "apply"


class ApplyRequestStatus(str, Enum):
    """Status values for apply requests."""
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class GuardrailCheckStatus(str, Enum):
    """Result of guardrail check."""
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"


class BlackoutWindowSchema(BaseModel):
    """Blackout window configuration."""
    day_of_week: Optional[int] = Field(
        default=None,
        ge=0,
        le=6,
        description="Day of week (0=Monday, 6=Sunday), None for every day"
    )
    start_time: str = Field(
        ...,
        pattern=r"^\d{2}:\d{2}$",
        description="Start time in HH:MM format"
    )
    end_time: str = Field(
        ...,
        pattern=r"^\d{2}:\d{2}$",
        description="End time in HH:MM format"
    )
    timezone: str = Field(default="UTC", description="Timezone for the window")


class CreateApplyPolicyRequest(BaseModel):
    """Request to create an apply policy."""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    team_id: Optional[str] = None
    cluster_id: Optional[str] = None
    require_approval: bool = Field(default=True)
    auto_approve_below_threshold: bool = Field(default=False)
    approval_threshold_cpu_percent: float = Field(default=20.0, ge=0, le=100)
    approval_threshold_memory_percent: float = Field(default=20.0, ge=0, le=100)
    max_cpu_increase_percent: float = Field(default=200.0, ge=0)
    max_cpu_decrease_percent: float = Field(default=50.0, ge=0, le=100)
    max_memory_increase_percent: float = Field(default=200.0, ge=0)
    max_memory_decrease_percent: float = Field(default=50.0, ge=0, le=100)
    min_cpu_request: Optional[str] = Field(default="10m")
    min_memory_request: Optional[str] = Field(default="32Mi")
    blackout_windows: list[BlackoutWindowSchema] = Field(default_factory=list)
    excluded_namespaces: list[str] = Field(
        default_factory=lambda: ["kube-system", "kube-public"]
    )
    excluded_workload_patterns: list[str] = Field(default_factory=list)
    priority: int = Field(default=0)


class UpdateApplyPolicyRequest(BaseModel):
    """Request to update an apply policy."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    require_approval: Optional[bool] = None
    auto_approve_below_threshold: Optional[bool] = None
    approval_threshold_cpu_percent: Optional[float] = Field(default=None, ge=0, le=100)
    approval_threshold_memory_percent: Optional[float] = Field(default=None, ge=0, le=100)
    max_cpu_increase_percent: Optional[float] = Field(default=None, ge=0)
    max_cpu_decrease_percent: Optional[float] = Field(default=None, ge=0, le=100)
    max_memory_increase_percent: Optional[float] = Field(default=None, ge=0)
    max_memory_decrease_percent: Optional[float] = Field(default=None, ge=0, le=100)
    min_cpu_request: Optional[str] = None
    min_memory_request: Optional[str] = None
    blackout_windows: Optional[list[BlackoutWindowSchema]] = None
    excluded_namespaces: Optional[list[str]] = None
    excluded_workload_patterns: Optional[list[str]] = None
    enabled: Optional[bool] = None
    priority: Optional[int] = None


class ApplyPolicyResponse(BaseModel):
    """Response for apply policy."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: Optional[str] = None
    team_id: Optional[str] = None
    cluster_id: Optional[str] = None
    require_approval: bool
    auto_approve_below_threshold: bool
    approval_threshold_cpu_percent: float
    approval_threshold_memory_percent: float
    max_cpu_increase_percent: float
    max_cpu_decrease_percent: float
    max_memory_increase_percent: float
    max_memory_decrease_percent: float
    min_cpu_request: Optional[str] = None
    min_memory_request: Optional[str] = None
    blackout_windows: list = Field(default_factory=list)
    excluded_namespaces: list = Field(default_factory=list)
    excluded_workload_patterns: list = Field(default_factory=list)
    enabled: bool
    priority: int
    created_at: datetime
    updated_at: datetime


class CreateApplyRequest(BaseModel):
    """Request to create an apply request."""
    suggestion_id: str = Field(..., description="ID of the suggestion to apply")
    cluster_id: str = Field(..., description="ID of the target cluster")
    mode: ApplyMode = Field(default=ApplyMode.DRY_RUN)


class CreateBatchApplyRequest(BaseModel):
    """Request to create a batch of apply requests."""
    suggestion_ids: list[str] = Field(..., min_length=1)
    cluster_id: str = Field(..., description="ID of the target cluster")
    mode: ApplyMode = Field(default=ApplyMode.DRY_RUN)
    stop_on_failure: bool = Field(default=True)
    name: Optional[str] = None
    description: Optional[str] = None


class ApproveRequestBody(BaseModel):
    """Body for approving an apply request."""
    comment: Optional[str] = None


class RejectRequestBody(BaseModel):
    """Body for rejecting an apply request."""
    reason: str = Field(..., min_length=1)


class RollbackRequestBody(BaseModel):
    """Body for rolling back an apply request."""
    reason: str = Field(..., min_length=1)


class GuardrailCheckResponse(BaseModel):
    """Response for a guardrail check result."""
    name: str
    status: GuardrailCheckStatus
    message: str
    current_value: Optional[float] = None
    proposed_value: Optional[float] = None
    threshold: Optional[float] = None


class ApplyRequestResponse(BaseModel):
    """Response for an apply request."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    suggestion_id: str
    cluster_id: str
    team_id: Optional[str] = None
    batch_id: Optional[str] = None
    status: ApplyRequestStatus
    mode: ApplyMode
    requires_approval: bool
    approved_by_id: Optional[str] = None
    approved_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    apply_policy_id: Optional[str] = None
    previous_config: Optional[dict] = None
    proposed_config: dict
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    kubectl_output: Optional[str] = None
    error_message: Optional[str] = None
    guardrail_results: Optional[dict] = None
    rolled_back: bool
    rolled_back_at: Optional[datetime] = None
    rollback_reason: Optional[str] = None
    created_at: datetime


class ApplyBatchResponse(BaseModel):
    """Response for an apply batch."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: Optional[str] = None
    description: Optional[str] = None
    cluster_id: str
    team_id: Optional[str] = None
    optimization_run_id: Optional[str] = None
    status: ApplyRequestStatus
    mode: ApplyMode
    requires_approval: bool
    approved_by_id: Optional[str] = None
    approved_at: Optional[datetime] = None
    total_requests: int
    completed_requests: int
    failed_requests: int
    stop_on_failure: bool
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime


class ApplyHistoryResponse(BaseModel):
    """Response for apply history listing."""
    requests: list[ApplyRequestResponse]
    total: int
    page: int
    per_page: int
