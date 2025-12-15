"""
SQLAlchemy database models for KubeOpt AI.

Defines the persistence layer for optimization runs, workload snapshots,
and optimization suggestions.
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Column,
    String,
    Integer,
    DateTime,
    Text,
    ForeignKey,
    Enum as SQLEnum,
    Index,
    Table,
    Boolean,
    UniqueConstraint,
    Float,
)
from sqlalchemy import JSON
from sqlalchemy.orm import relationship, Mapped, mapped_column

from kubeopt_ai.extensions import db


class RunStatus(str, Enum):
    """Status values for optimization runs."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class WebhookType(str, Enum):
    """Types of webhooks supported."""
    SLACK = "slack"
    GENERIC = "generic"
    TEAMS = "teams"
    DISCORD = "discord"


class WebhookStatus(str, Enum):
    """Status of webhook delivery."""
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    RETRYING = "retrying"


class WorkloadKind(str, Enum):
    """Kubernetes workload types supported by the optimizer."""
    DEPLOYMENT = "Deployment"
    STATEFULSET = "StatefulSet"
    DAEMONSET = "DaemonSet"


class AuditAction(str, Enum):
    """Types of auditable actions in the system."""
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    READ = "read"
    APPLY = "apply"
    REVERT = "revert"
    LOGIN = "login"
    LOGOUT = "logout"
    EXPORT = "export"


class UserStatus(str, Enum):
    """Status values for users."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    PENDING = "pending"


class ClusterStatus(str, Enum):
    """Status values for Kubernetes clusters."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    UNREACHABLE = "unreachable"
    PENDING = "pending"


class ClusterProvider(str, Enum):
    """Cloud provider types for clusters."""
    AWS = "aws"
    GCP = "gcp"
    AZURE = "azure"
    ON_PREM = "on_prem"
    OTHER = "other"


class TrendDirection(str, Enum):
    """Direction of a metric trend."""
    INCREASING = "increasing"
    DECREASING = "decreasing"
    STABLE = "stable"
    VOLATILE = "volatile"


class TeamStatus(str, Enum):
    """Status values for teams."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"


def generate_uuid() -> str:
    """Generate a new UUID string."""
    return str(uuid.uuid4())


class Cluster(db.Model):
    """
    Kubernetes cluster configuration for multi-cluster support.

    Stores connection details, Prometheus URL, and metadata for each
    managed Kubernetes cluster.
    """
    __tablename__ = "clusters"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )
    display_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )
    provider: Mapped[ClusterProvider] = mapped_column(
        SQLEnum(ClusterProvider, native_enum=False),
        default=ClusterProvider.OTHER,
        nullable=False
    )
    region: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True
    )
    status: Mapped[ClusterStatus] = mapped_column(
        SQLEnum(ClusterStatus, native_enum=False),
        default=ClusterStatus.PENDING,
        nullable=False
    )
    # Connection configuration
    kubeconfig: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True  # Can be stored encrypted or reference external secret
    )
    kubeconfig_context: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True
    )
    api_server_url: Mapped[Optional[str]] = mapped_column(
        String(1024),
        nullable=True
    )
    # Prometheus configuration
    prometheus_url: Mapped[Optional[str]] = mapped_column(
        String(1024),
        nullable=True
    )
    prometheus_auth: Mapped[dict] = mapped_column(
        JSON,
        nullable=True,
        default=dict
    )
    # Metadata and settings
    labels: Mapped[dict] = mapped_column(
        JSON,
        nullable=True,
        default=dict
    )
    settings: Mapped[dict] = mapped_column(
        JSON,
        nullable=True,
        default=dict
    )
    last_connected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    last_error: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )
    # Multi-tenancy: team ownership
    team_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("teams.id", ondelete="SET NULL"),
        nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    optimization_runs: Mapped[list["OptimizationRun"]] = relationship(
        "OptimizationRun",
        back_populates="cluster",
        lazy="dynamic"
    )
    workload_snapshots: Mapped[list["WorkloadSnapshot"]] = relationship(
        "WorkloadSnapshot",
        back_populates="cluster",
        lazy="dynamic"
    )
    metrics_history: Mapped[list["MetricsHistory"]] = relationship(
        "MetricsHistory",
        back_populates="cluster",
        cascade="all, delete-orphan",
        lazy="dynamic"
    )
    team: Mapped[Optional["Team"]] = relationship(
        "Team",
        foreign_keys=[team_id]
    )

    # Indexes
    __table_args__ = (
        Index("ix_clusters_name", "name"),
        Index("ix_clusters_status", "status"),
        Index("ix_clusters_provider", "provider"),
        Index("ix_clusters_team_id", "team_id"),
        UniqueConstraint("name", "team_id", name="uq_cluster_name_team"),
    )

    def __repr__(self) -> str:
        return f"<Cluster {self.name} provider={self.provider} status={self.status}>"

    def to_dict(self, include_sensitive: bool = False) -> dict:
        """Convert model to dictionary representation."""
        result = {
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "provider": self.provider.value if self.provider else None,
            "region": self.region,
            "status": self.status.value if self.status else None,
            "api_server_url": self.api_server_url,
            "prometheus_url": self.prometheus_url,
            "labels": self.labels,
            "settings": self.settings,
            "last_connected_at": self.last_connected_at.isoformat() if self.last_connected_at else None,
            "last_error": self.last_error,
            "team_id": self.team_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_sensitive:
            result["kubeconfig"] = self.kubeconfig
            result["kubeconfig_context"] = self.kubeconfig_context
            result["prometheus_auth"] = self.prometheus_auth
        return result


class OptimizationRun(db.Model):
    """
    Represents a single optimization run.

    An optimization run scans a set of Kubernetes manifests, collects metrics,
    and generates AI-powered resource optimization suggestions.
    """
    __tablename__ = "optimization_runs"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    manifest_source_path: Mapped[str] = mapped_column(
        String(1024),
        nullable=False
    )
    lookback_days: Mapped[int] = mapped_column(
        Integer,
        default=7,
        nullable=False
    )
    status: Mapped[RunStatus] = mapped_column(
        SQLEnum(RunStatus, native_enum=False),
        default=RunStatus.PENDING,
        nullable=False
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )
    # Multi-cluster support
    cluster_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("clusters.id", ondelete="SET NULL"),
        nullable=True  # Nullable for backward compatibility
    )
    # Multi-tenancy: team ownership
    team_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("teams.id", ondelete="SET NULL"),
        nullable=True  # Nullable for backward compatibility
    )
    created_by_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True  # Nullable for backward compatibility
    )

    # Relationships
    workload_snapshots: Mapped[list["WorkloadSnapshot"]] = relationship(
        "WorkloadSnapshot",
        back_populates="optimization_run",
        cascade="all, delete-orphan",
        lazy="dynamic"
    )
    cluster: Mapped[Optional["Cluster"]] = relationship(
        "Cluster",
        back_populates="optimization_runs"
    )
    team: Mapped[Optional["Team"]] = relationship(
        "Team",
        back_populates="optimization_runs"
    )

    # Indexes
    __table_args__ = (
        Index("ix_optimization_runs_status", "status"),
        Index("ix_optimization_runs_created_at", "created_at"),
        Index("ix_optimization_runs_team_id", "team_id"),
        Index("ix_optimization_runs_cluster_id", "cluster_id"),
    )

    def __repr__(self) -> str:
        return f"<OptimizationRun {self.id} status={self.status}>"

    def to_dict(self) -> dict:
        """Convert model to dictionary representation."""
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "manifest_source_path": self.manifest_source_path,
            "lookback_days": self.lookback_days,
            "status": self.status.value if self.status else None,
            "error_message": self.error_message,
            "cluster_id": self.cluster_id,
            "team_id": self.team_id,
            "created_by_id": self.created_by_id,
        }


class WorkloadSnapshot(db.Model):
    """
    Snapshot of a Kubernetes workload at the time of optimization.

    Captures the workload's configuration and metrics at the point when
    the optimization run was executed.
    """
    __tablename__ = "workload_snapshots"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid
    )
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("optimization_runs.id", ondelete="CASCADE"),
        nullable=False
    )
    # Multi-cluster support
    cluster_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("clusters.id", ondelete="SET NULL"),
        nullable=True  # Nullable for backward compatibility
    )
    name: Mapped[str] = mapped_column(
        String(253),  # K8s name max length
        nullable=False
    )
    namespace: Mapped[str] = mapped_column(
        String(253),
        nullable=False,
        default="default"
    )
    kind: Mapped[WorkloadKind] = mapped_column(
        SQLEnum(WorkloadKind, native_enum=False),
        nullable=False
    )
    current_config: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict
    )
    metrics_summary: Mapped[dict] = mapped_column(
        JSON,
        nullable=True,
        default=dict
    )

    # Relationships
    optimization_run: Mapped["OptimizationRun"] = relationship(
        "OptimizationRun",
        back_populates="workload_snapshots"
    )
    cluster: Mapped[Optional["Cluster"]] = relationship(
        "Cluster",
        back_populates="workload_snapshots"
    )
    suggestions: Mapped[list["Suggestion"]] = relationship(
        "Suggestion",
        back_populates="workload_snapshot",
        cascade="all, delete-orphan",
        lazy="dynamic"
    )

    # Indexes
    __table_args__ = (
        Index("ix_workload_snapshots_run_id", "run_id"),
        Index("ix_workload_snapshots_name_namespace", "name", "namespace"),
        Index("ix_workload_snapshots_cluster_id", "cluster_id"),
    )

    def __repr__(self) -> str:
        return f"<WorkloadSnapshot {self.namespace}/{self.name} kind={self.kind}>"

    def to_dict(self) -> dict:
        """Convert model to dictionary representation."""
        return {
            "id": self.id,
            "run_id": self.run_id,
            "cluster_id": self.cluster_id,
            "name": self.name,
            "namespace": self.namespace,
            "kind": self.kind.value if self.kind else None,
            "current_config": self.current_config,
            "metrics_summary": self.metrics_summary,
        }


class Suggestion(db.Model):
    """
    AI-generated optimization suggestion for a container in a workload.

    Contains proposed resource changes and the reasoning behind them.
    """
    __tablename__ = "suggestions"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid
    )
    workload_snapshot_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("workload_snapshots.id", ondelete="CASCADE"),
        nullable=False
    )
    container_name: Mapped[str] = mapped_column(
        String(253),  # K8s container name max length
        nullable=False
    )
    suggestion_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="resources"  # 'resources' or 'hpa'
    )
    current_config: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict
    )
    proposed_config: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict
    )
    reasoning: Mapped[str] = mapped_column(
        Text,
        nullable=True
    )
    diff_text: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )

    # Relationships
    workload_snapshot: Mapped["WorkloadSnapshot"] = relationship(
        "WorkloadSnapshot",
        back_populates="suggestions"
    )

    # Indexes
    __table_args__ = (
        Index("ix_suggestions_workload_snapshot_id", "workload_snapshot_id"),
        Index("ix_suggestions_container_name", "container_name"),
    )

    def __repr__(self) -> str:
        return f"<Suggestion {self.id} container={self.container_name}>"

    def to_dict(self) -> dict:
        """Convert model to dictionary representation."""
        return {
            "id": self.id,
            "workload_snapshot_id": self.workload_snapshot_id,
            "container_name": self.container_name,
            "suggestion_type": self.suggestion_type,
            "current_config": self.current_config,
            "proposed_config": self.proposed_config,
            "reasoning": self.reasoning,
            "diff_text": self.diff_text,
        }


class WebhookConfig(db.Model):
    """
    Configuration for a webhook endpoint.

    Stores webhook URL, type, and customization options for
    anomaly alert notifications.
    """
    __tablename__ = "webhook_configs"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )
    webhook_type: Mapped[WebhookType] = mapped_column(
        SQLEnum(WebhookType, native_enum=False),
        default=WebhookType.GENERIC,
        nullable=False
    )
    url: Mapped[str] = mapped_column(
        String(2048),
        nullable=False
    )
    secret: Mapped[Optional[str]] = mapped_column(
        String(256),
        nullable=True
    )
    enabled: Mapped[bool] = mapped_column(
        default=True,
        nullable=False
    )
    severity_filter: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True
    )
    custom_headers: Mapped[dict] = mapped_column(
        JSON,
        nullable=True,
        default=dict
    )
    template: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    delivery_logs: Mapped[list["WebhookDeliveryLog"]] = relationship(
        "WebhookDeliveryLog",
        back_populates="webhook_config",
        cascade="all, delete-orphan",
        lazy="dynamic"
    )

    # Indexes
    __table_args__ = (
        Index("ix_webhook_configs_enabled", "enabled"),
        Index("ix_webhook_configs_webhook_type", "webhook_type"),
    )

    def __repr__(self) -> str:
        return f"<WebhookConfig {self.name} type={self.webhook_type}>"

    def to_dict(self) -> dict:
        """Convert model to dictionary representation."""
        return {
            "id": self.id,
            "name": self.name,
            "webhook_type": self.webhook_type.value if self.webhook_type else None,
            "url": self.url,
            "enabled": self.enabled,
            "severity_filter": self.severity_filter,
            "custom_headers": self.custom_headers,
            "template": self.template,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class WebhookDeliveryLog(db.Model):
    """
    Log of webhook delivery attempts.

    Tracks delivery status, retries, and responses for webhook notifications.
    """
    __tablename__ = "webhook_delivery_logs"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid
    )
    webhook_config_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("webhook_configs.id", ondelete="CASCADE"),
        nullable=False
    )
    alert_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False
    )
    status: Mapped[WebhookStatus] = mapped_column(
        SQLEnum(WebhookStatus, native_enum=False),
        default=WebhookStatus.PENDING,
        nullable=False
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        default=3,
        nullable=False
    )
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    response_status_code: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True
    )
    response_body: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )
    payload: Mapped[dict] = mapped_column(
        JSON,
        nullable=True,
        default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    webhook_config: Mapped["WebhookConfig"] = relationship(
        "WebhookConfig",
        back_populates="delivery_logs"
    )

    # Indexes
    __table_args__ = (
        Index("ix_webhook_delivery_logs_webhook_config_id", "webhook_config_id"),
        Index("ix_webhook_delivery_logs_status", "status"),
        Index("ix_webhook_delivery_logs_next_retry_at", "next_retry_at"),
    )

    def __repr__(self) -> str:
        return f"<WebhookDeliveryLog {self.id} status={self.status}>"

    def to_dict(self) -> dict:
        """Convert model to dictionary representation."""
        return {
            "id": self.id,
            "webhook_config_id": self.webhook_config_id,
            "alert_id": self.alert_id,
            "status": self.status.value if self.status else None,
            "attempt_count": self.attempt_count,
            "max_attempts": self.max_attempts,
            "last_attempt_at": self.last_attempt_at.isoformat() if self.last_attempt_at else None,
            "next_retry_at": self.next_retry_at.isoformat() if self.next_retry_at else None,
            "response_status_code": self.response_status_code,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AuditLog(db.Model):
    """
    Audit log entry for tracking user actions and system events.

    Provides a comprehensive audit trail for security, compliance,
    and debugging purposes.
    """
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        nullable=True  # Nullable until RBAC is implemented
    )
    user_email: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True
    )
    action: Mapped[AuditAction] = mapped_column(
        SQLEnum(AuditAction, native_enum=False),
        nullable=False
    )
    resource_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )
    resource_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        nullable=True
    )
    details: Mapped[dict] = mapped_column(
        JSON,
        nullable=True,
        default=dict
    )
    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45),  # IPv6 max length
        nullable=True
    )
    user_agent: Mapped[Optional[str]] = mapped_column(
        String(512),
        nullable=True
    )
    request_method: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True
    )
    request_path: Mapped[Optional[str]] = mapped_column(
        String(2048),
        nullable=True
    )
    response_status: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True
    )
    duration_ms: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True
    )

    # Indexes for efficient querying
    __table_args__ = (
        Index("ix_audit_logs_timestamp", "timestamp"),
        Index("ix_audit_logs_user_id", "user_id"),
        Index("ix_audit_logs_action", "action"),
        Index("ix_audit_logs_resource_type", "resource_type"),
        Index("ix_audit_logs_resource_id", "resource_id"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog {self.id} action={self.action} resource={self.resource_type}>"

    def to_dict(self) -> dict:
        """Convert model to dictionary representation."""
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "user_id": self.user_id,
            "user_email": self.user_email,
            "action": self.action.value if self.action else None,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "details": self.details,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "request_method": self.request_method,
            "request_path": self.request_path,
            "response_status": self.response_status,
            "duration_ms": self.duration_ms,
        }


# Association table for Role-Permission many-to-many relationship
role_permissions = Table(
    "role_permissions",
    db.Model.metadata,
    Column("role_id", String(36), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", String(36), ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class Permission(db.Model):
    """
    Granular permission for a specific action or resource.

    Permissions define what actions can be performed on which resources.
    They are assigned to roles, which are then assigned to users within teams.
    """
    __tablename__ = "permissions"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid
    )
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True
    )
    description: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True
    )
    resource: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )
    action: Mapped[str] = mapped_column(
        String(50),
        nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    roles: Mapped[list["Role"]] = relationship(
        "Role",
        secondary=role_permissions,
        back_populates="permissions"
    )

    # Indexes
    __table_args__ = (
        Index("ix_permissions_resource", "resource"),
        Index("ix_permissions_action", "action"),
        UniqueConstraint("resource", "action", name="uq_permission_resource_action"),
    )

    def __repr__(self) -> str:
        return f"<Permission {self.name} ({self.resource}:{self.action})>"

    def to_dict(self) -> dict:
        """Convert model to dictionary representation."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "resource": self.resource,
            "action": self.action,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Role(db.Model):
    """
    Role that groups permissions together.

    Roles define a set of permissions that can be assigned to users within teams.
    Common roles include admin, operator, viewer, etc.
    """
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid
    )
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True
    )
    description: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True
    )
    is_system_role: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    permissions: Mapped[list["Permission"]] = relationship(
        "Permission",
        secondary=role_permissions,
        back_populates="roles"
    )
    team_memberships: Mapped[list["TeamMembership"]] = relationship(
        "TeamMembership",
        back_populates="role",
        lazy="dynamic"
    )

    # Indexes
    __table_args__ = (
        Index("ix_roles_is_system_role", "is_system_role"),
    )

    def __repr__(self) -> str:
        return f"<Role {self.name}>"

    def to_dict(self, include_permissions: bool = False) -> dict:
        """Convert model to dictionary representation."""
        result = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "is_system_role": self.is_system_role,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_permissions:
            result["permissions"] = [p.to_dict() for p in self.permissions]
        return result

    def has_permission(self, resource: str, action: str) -> bool:
        """Check if this role has a specific permission."""
        for perm in self.permissions:
            if perm.resource == resource and perm.action == action:
                return True
            # Wildcard support
            if perm.resource == "*" or (perm.resource == resource and perm.action == "*"):
                return True
        return False


class Team(db.Model):
    """
    Team/organization that groups users together.

    Teams provide multi-tenancy support, allowing resource isolation
    between different groups of users.
    """
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )
    slug: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True
    )
    description: Mapped[Optional[str]] = mapped_column(
        String(1000),
        nullable=True
    )
    status: Mapped[TeamStatus] = mapped_column(
        SQLEnum(TeamStatus, native_enum=False),
        default=TeamStatus.ACTIVE,
        nullable=False
    )
    settings: Mapped[dict] = mapped_column(
        JSON,
        nullable=True,
        default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    memberships: Mapped[list["TeamMembership"]] = relationship(
        "TeamMembership",
        back_populates="team",
        cascade="all, delete-orphan",
        lazy="dynamic"
    )
    optimization_runs: Mapped[list["OptimizationRun"]] = relationship(
        "OptimizationRun",
        back_populates="team",
        lazy="dynamic"
    )

    # Indexes
    __table_args__ = (
        Index("ix_teams_status", "status"),
        Index("ix_teams_slug", "slug"),
    )

    def __repr__(self) -> str:
        return f"<Team {self.name} ({self.slug})>"

    def to_dict(self, include_members: bool = False) -> dict:
        """Convert model to dictionary representation."""
        result = {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "status": self.status.value if self.status else None,
            "settings": self.settings,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_members:
            result["members"] = [m.to_dict() for m in self.memberships]
        return result


class User(db.Model):
    """
    User account in the system.

    Users can belong to multiple teams with different roles in each team.
    Authentication is handled via JWT tokens.
    """
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid
    )
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True
    )
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )
    first_name: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True
    )
    last_name: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True
    )
    status: Mapped[UserStatus] = mapped_column(
        SQLEnum(UserStatus, native_enum=False),
        default=UserStatus.ACTIVE,
        nullable=False
    )
    is_superuser: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    team_memberships: Mapped[list["TeamMembership"]] = relationship(
        "TeamMembership",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="dynamic"
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        "RefreshToken",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="dynamic"
    )

    # Indexes
    __table_args__ = (
        Index("ix_users_email", "email"),
        Index("ix_users_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<User {self.email}>"

    @property
    def full_name(self) -> str:
        """Get the user's full name."""
        parts = [self.first_name, self.last_name]
        return " ".join(p for p in parts if p) or self.email

    def to_dict(self, include_teams: bool = False) -> dict:
        """Convert model to dictionary representation."""
        result = {
            "id": self.id,
            "email": self.email,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "full_name": self.full_name,
            "status": self.status.value if self.status else None,
            "is_superuser": self.is_superuser,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_teams:
            result["teams"] = [m.to_dict() for m in self.team_memberships]
        return result

    def get_teams(self) -> list["Team"]:
        """Get all teams the user belongs to."""
        return [m.team for m in self.team_memberships]

    def get_role_in_team(self, team_id: str) -> Optional["Role"]:
        """Get the user's role in a specific team."""
        membership = self.team_memberships.filter_by(team_id=team_id).first()
        return membership.role if membership else None

    def has_permission_in_team(self, team_id: str, resource: str, action: str) -> bool:
        """Check if user has a specific permission in a team."""
        if self.is_superuser:
            return True
        role = self.get_role_in_team(team_id)
        return role.has_permission(resource, action) if role else False


class TeamMembership(db.Model):
    """
    Association between users and teams with roles.

    Represents a user's membership in a team and their role within that team.
    """
    __tablename__ = "team_memberships"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )
    team_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False
    )
    role_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("roles.id", ondelete="RESTRICT"),
        nullable=False
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="team_memberships"
    )
    team: Mapped["Team"] = relationship(
        "Team",
        back_populates="memberships"
    )
    role: Mapped["Role"] = relationship(
        "Role",
        back_populates="team_memberships"
    )

    # Indexes and constraints
    __table_args__ = (
        Index("ix_team_memberships_user_id", "user_id"),
        Index("ix_team_memberships_team_id", "team_id"),
        UniqueConstraint("user_id", "team_id", name="uq_user_team"),
    )

    def __repr__(self) -> str:
        return f"<TeamMembership user={self.user_id} team={self.team_id} role={self.role_id}>"

    def to_dict(self) -> dict:
        """Convert model to dictionary representation."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "team_id": self.team_id,
            "role_id": self.role_id,
            "role_name": self.role.name if self.role else None,
            "team_name": self.team.name if self.team else None,
            "joined_at": self.joined_at.isoformat() if self.joined_at else None,
        }


class RefreshToken(db.Model):
    """
    JWT refresh token for maintaining user sessions.

    Stores refresh tokens for token renewal and revocation tracking.
    """
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )
    token_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False
    )
    revoked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45),
        nullable=True
    )
    user_agent: Mapped[Optional[str]] = mapped_column(
        String(512),
        nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="refresh_tokens"
    )

    # Indexes
    __table_args__ = (
        Index("ix_refresh_tokens_user_id", "user_id"),
        Index("ix_refresh_tokens_token_hash", "token_hash"),
        Index("ix_refresh_tokens_expires_at", "expires_at"),
    )

    def __repr__(self) -> str:
        return f"<RefreshToken {self.id} user={self.user_id}>"

    @property
    def is_valid(self) -> bool:
        """Check if the token is valid (not expired and not revoked)."""
        return not self.revoked and self.expires_at > datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        """Convert model to dictionary representation."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "revoked": self.revoked,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "ip_address": self.ip_address,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# =============================================================================
# Historical Trend Analysis Models (F020)
# =============================================================================


class MetricsHistory(db.Model):
    """
    Time-series storage for historical metrics data.

    Stores CPU and memory metrics collected over time for trend analysis
    and capacity planning.
    """
    __tablename__ = "metrics_history"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid
    )
    cluster_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("clusters.id", ondelete="CASCADE"),
        nullable=True
    )
    namespace: Mapped[str] = mapped_column(
        String(253),
        nullable=False
    )
    workload_name: Mapped[str] = mapped_column(
        String(253),
        nullable=False
    )
    workload_kind: Mapped[str] = mapped_column(
        String(50),
        nullable=False
    )
    container_name: Mapped[str] = mapped_column(
        String(253),
        nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False
    )
    # CPU metrics (in cores)
    cpu_usage: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True
    )
    cpu_request: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True
    )
    cpu_limit: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True
    )
    # Memory metrics (in bytes)
    memory_usage: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True
    )
    memory_request: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True
    )
    memory_limit: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True
    )
    # Replica count
    replica_count: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True
    )
    # Additional metrics
    extra_metrics: Mapped[dict] = mapped_column(
        JSON,
        nullable=True,
        default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    cluster: Mapped[Optional["Cluster"]] = relationship(
        "Cluster",
        back_populates="metrics_history"
    )

    # Indexes for efficient time-series queries
    __table_args__ = (
        Index("ix_metrics_history_cluster_id", "cluster_id"),
        Index("ix_metrics_history_timestamp", "timestamp"),
        Index("ix_metrics_history_namespace", "namespace"),
        Index("ix_metrics_history_workload", "namespace", "workload_name"),
        Index("ix_metrics_history_container", "namespace", "workload_name", "container_name"),
        Index("ix_metrics_history_time_range", "cluster_id", "namespace", "workload_name", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<MetricsHistory {self.namespace}/{self.workload_name}/{self.container_name} @ {self.timestamp}>"

    def to_dict(self) -> dict:
        """Convert model to dictionary representation."""
        return {
            "id": self.id,
            "cluster_id": self.cluster_id,
            "namespace": self.namespace,
            "workload_name": self.workload_name,
            "workload_kind": self.workload_kind,
            "container_name": self.container_name,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "cpu_usage": self.cpu_usage,
            "cpu_request": self.cpu_request,
            "cpu_limit": self.cpu_limit,
            "memory_usage": self.memory_usage,
            "memory_request": self.memory_request,
            "memory_limit": self.memory_limit,
            "replica_count": self.replica_count,
            "extra_metrics": self.extra_metrics,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class TrendAnalysis(db.Model):
    """
    Results of trend analysis for a workload.

    Stores computed trends, predictions, and recommendations based on
    historical metrics data.
    """
    __tablename__ = "trend_analyses"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid
    )
    cluster_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("clusters.id", ondelete="CASCADE"),
        nullable=True
    )
    namespace: Mapped[str] = mapped_column(
        String(253),
        nullable=False
    )
    workload_name: Mapped[str] = mapped_column(
        String(253),
        nullable=False
    )
    container_name: Mapped[str] = mapped_column(
        String(253),
        nullable=False
    )
    analysis_period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False
    )
    analysis_period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False
    )
    # CPU trend analysis
    cpu_trend_direction: Mapped[TrendDirection] = mapped_column(
        SQLEnum(TrendDirection, native_enum=False),
        default=TrendDirection.STABLE,
        nullable=False
    )
    cpu_trend_slope: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True
    )
    cpu_avg: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True
    )
    cpu_p95: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True
    )
    cpu_max: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True
    )
    cpu_predicted_7d: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True
    )
    cpu_predicted_30d: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True
    )
    # Memory trend analysis
    memory_trend_direction: Mapped[TrendDirection] = mapped_column(
        SQLEnum(TrendDirection, native_enum=False),
        default=TrendDirection.STABLE,
        nullable=False
    )
    memory_trend_slope: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True
    )
    memory_avg: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True
    )
    memory_p95: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True
    )
    memory_max: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True
    )
    memory_predicted_7d: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True
    )
    memory_predicted_30d: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True
    )
    # Statistical metrics
    cpu_std_dev: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True
    )
    memory_std_dev: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True
    )
    seasonality_detected: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False
    )
    seasonality_period_hours: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True
    )
    # Recommendations
    recommended_cpu_request: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True
    )
    recommended_cpu_limit: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True
    )
    recommended_memory_request: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True
    )
    recommended_memory_limit: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True
    )
    confidence_score: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True
    )
    # Metadata
    data_points_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False
    )
    analysis_metadata: Mapped[dict] = mapped_column(
        JSON,
        nullable=True,
        default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Indexes
    __table_args__ = (
        Index("ix_trend_analyses_cluster_id", "cluster_id"),
        Index("ix_trend_analyses_namespace", "namespace"),
        Index("ix_trend_analyses_workload", "namespace", "workload_name"),
        Index("ix_trend_analyses_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<TrendAnalysis {self.namespace}/{self.workload_name}/{self.container_name}>"

    def to_dict(self) -> dict:
        """Convert model to dictionary representation."""
        return {
            "id": self.id,
            "cluster_id": self.cluster_id,
            "namespace": self.namespace,
            "workload_name": self.workload_name,
            "container_name": self.container_name,
            "analysis_period_start": self.analysis_period_start.isoformat() if self.analysis_period_start else None,
            "analysis_period_end": self.analysis_period_end.isoformat() if self.analysis_period_end else None,
            "cpu_trend_direction": self.cpu_trend_direction.value if self.cpu_trend_direction else None,
            "cpu_trend_slope": self.cpu_trend_slope,
            "cpu_avg": self.cpu_avg,
            "cpu_p95": self.cpu_p95,
            "cpu_max": self.cpu_max,
            "cpu_predicted_7d": self.cpu_predicted_7d,
            "cpu_predicted_30d": self.cpu_predicted_30d,
            "memory_trend_direction": self.memory_trend_direction.value if self.memory_trend_direction else None,
            "memory_trend_slope": self.memory_trend_slope,
            "memory_avg": self.memory_avg,
            "memory_p95": self.memory_p95,
            "memory_max": self.memory_max,
            "memory_predicted_7d": self.memory_predicted_7d,
            "memory_predicted_30d": self.memory_predicted_30d,
            "cpu_std_dev": self.cpu_std_dev,
            "memory_std_dev": self.memory_std_dev,
            "seasonality_detected": self.seasonality_detected,
            "seasonality_period_hours": self.seasonality_period_hours,
            "recommended_cpu_request": self.recommended_cpu_request,
            "recommended_cpu_limit": self.recommended_cpu_limit,
            "recommended_memory_request": self.recommended_memory_request,
            "recommended_memory_limit": self.recommended_memory_limit,
            "confidence_score": self.confidence_score,
            "data_points_count": self.data_points_count,
            "analysis_metadata": self.analysis_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
