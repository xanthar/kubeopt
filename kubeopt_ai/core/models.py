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


def generate_uuid() -> str:
    """Generate a new UUID string."""
    return str(uuid.uuid4())


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

    # Relationships
    workload_snapshots: Mapped[list["WorkloadSnapshot"]] = relationship(
        "WorkloadSnapshot",
        back_populates="optimization_run",
        cascade="all, delete-orphan",
        lazy="dynamic"
    )

    # Indexes
    __table_args__ = (
        Index("ix_optimization_runs_status", "status"),
        Index("ix_optimization_runs_created_at", "created_at"),
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
    )

    def __repr__(self) -> str:
        return f"<WorkloadSnapshot {self.namespace}/{self.name} kind={self.kind}>"

    def to_dict(self) -> dict:
        """Convert model to dictionary representation."""
        return {
            "id": self.id,
            "run_id": self.run_id,
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
