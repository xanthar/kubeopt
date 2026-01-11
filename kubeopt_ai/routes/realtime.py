"""
Real-time monitoring API endpoints for KubeOpt AI.

Provides REST API for real-time metrics, trend analysis, and
continuous anomaly monitoring.
"""

import logging
from flask import Blueprint, jsonify, request, current_app
from pydantic import BaseModel, Field, ValidationError
from typing import Optional
from enum import Enum

from kubeopt_ai.core.realtime_metrics import (
    TimeWindow,
    get_streaming_collector,
    get_anomaly_pipeline,
    get_background_monitor,
)

logger = logging.getLogger(__name__)

realtime_bp = Blueprint("realtime", __name__)


# Request/Response Schemas
class TimeWindowEnum(str, Enum):
    """Time window options for API requests."""

    FIVE_MINUTES = "5m"
    FIFTEEN_MINUTES = "15m"
    THIRTY_MINUTES = "30m"
    ONE_HOUR = "1h"
    SIX_HOURS = "6h"
    TWELVE_HOURS = "12h"
    TWENTY_FOUR_HOURS = "24h"


class WorkloadIdentifier(BaseModel):
    """Identifies a workload for monitoring."""

    namespace: str = Field(..., min_length=1)
    workload_name: str = Field(..., min_length=1)
    container_name: str = Field(..., min_length=1)


class TrendAnalysisRequest(BaseModel):
    """Request for trend analysis."""

    namespace: str = Field(..., min_length=1)
    workload_name: str = Field(..., min_length=1)
    container_name: str = Field(..., min_length=1)
    window: Optional[TimeWindowEnum] = TimeWindowEnum.FIFTEEN_MINUTES


class MonitoringConfigRequest(BaseModel):
    """Request to configure monitoring."""

    workloads: list[WorkloadIdentifier]
    check_interval: int = Field(60, ge=10, le=3600)


def _trend_to_dict(trend) -> dict:
    """Convert TrendAnalysis to dict."""
    return {
        "metric_name": trend.metric_name,
        "current_value": trend.current_value,
        "average_value": trend.average_value,
        "std_deviation": trend.std_deviation,
        "trend_direction": trend.trend_direction,
        "trend_rate": trend.trend_rate,
        "window": trend.window.value,
        "is_anomalous": trend.is_anomalous,
        "anomaly_score": trend.anomaly_score,
        "timestamp": trend.timestamp.isoformat(),
    }


def _alert_to_dict(alert) -> dict:
    """Convert AnomalyAlert to dict."""
    return {
        "anomaly_type": alert.anomaly_type.value,
        "severity": alert.severity.value,
        "workload_name": alert.workload_name,
        "namespace": alert.namespace,
        "container_name": alert.container_name,
        "resource_type": alert.resource_type,
        "description": alert.description,
        "current_value": alert.current_value,
        "threshold": alert.threshold,
        "score": alert.score,
        "detected_at": alert.detected_at.isoformat(),
        "recommendation": alert.recommendation,
    }


def _status_to_dict(status) -> dict:
    """Convert WorkloadStatus to dict."""
    return {
        "workload_name": status.workload_name,
        "namespace": status.namespace,
        "cpu_status": _trend_to_dict(status.cpu_status),
        "memory_status": _trend_to_dict(status.memory_status),
        "health_score": status.health_score,
        "active_alerts": [_alert_to_dict(a) for a in status.active_alerts],
        "last_updated": status.last_updated.isoformat(),
    }


def _get_time_window(window_str: Optional[str]) -> TimeWindow:
    """Convert string to TimeWindow enum."""
    mapping = {
        "5m": TimeWindow.FIVE_MINUTES,
        "15m": TimeWindow.FIFTEEN_MINUTES,
        "30m": TimeWindow.THIRTY_MINUTES,
        "1h": TimeWindow.ONE_HOUR,
        "6h": TimeWindow.SIX_HOURS,
        "12h": TimeWindow.TWELVE_HOURS,
        "24h": TimeWindow.TWENTY_FOUR_HOURS,
    }
    return mapping.get(window_str, TimeWindow.FIFTEEN_MINUTES)


@realtime_bp.route("/realtime/metrics", methods=["POST"])
def get_instant_metrics():
    """
    Get instant (current) metrics for a workload.

    Request JSON body:
        - namespace: Kubernetes namespace
        - workload_name: Name of the workload
        - container_name: Name of the container

    Returns:
        Current CPU and memory metrics.
    """
    data = request.get_json() or {}

    try:
        req = WorkloadIdentifier.model_validate(data)
    except ValidationError as e:
        return jsonify({
            "code": "VALIDATION_ERROR",
            "message": "Invalid request body",
            "details": e.errors(),
            "trace_id": None,
        }), 400

    prometheus_url = current_app.config.get("PROMETHEUS_BASE_URL")
    collector = get_streaming_collector(prometheus_url)

    try:
        metrics = collector.get_instant_metrics(
            namespace=req.namespace,
            workload_name=req.workload_name,
            container_name=req.container_name,
        )

        return jsonify({
            "namespace": req.namespace,
            "workload_name": req.workload_name,
            "container_name": req.container_name,
            "cpu_cores": metrics["cpu"],
            "memory_bytes": metrics["memory"],
            "timestamp": metrics["timestamp"].isoformat(),
        }), 200

    except Exception as e:
        logger.exception(f"Failed to get instant metrics: {e}")
        return jsonify({
            "code": "METRICS_ERROR",
            "message": f"Failed to get instant metrics: {e}",
            "details": None,
            "trace_id": None,
        }), 500


@realtime_bp.route("/realtime/trends", methods=["POST"])
def get_trend_analysis():
    """
    Get trend analysis for a workload's metrics.

    Request JSON body:
        - namespace: Kubernetes namespace
        - workload_name: Name of the workload
        - container_name: Name of the container
        - window: Time window for analysis (5m, 15m, 30m, 1h, 6h, 12h, 24h)

    Returns:
        Trend analysis for CPU and memory.
    """
    data = request.get_json() or {}

    try:
        req = TrendAnalysisRequest.model_validate(data)
    except ValidationError as e:
        return jsonify({
            "code": "VALIDATION_ERROR",
            "message": "Invalid request body",
            "details": e.errors(),
            "trace_id": None,
        }), 400

    prometheus_url = current_app.config.get("PROMETHEUS_BASE_URL")
    collector = get_streaming_collector(prometheus_url)
    window = _get_time_window(req.window.value if req.window else None)

    try:
        trends = collector.get_trend_analysis(
            namespace=req.namespace,
            workload_name=req.workload_name,
            container_name=req.container_name,
            window=window,
        )

        return jsonify({
            "namespace": req.namespace,
            "workload_name": req.workload_name,
            "container_name": req.container_name,
            "window": window.value,
            "cpu": _trend_to_dict(trends["cpu"]),
            "memory": _trend_to_dict(trends["memory"]),
        }), 200

    except Exception as e:
        logger.exception(f"Failed to get trend analysis: {e}")
        return jsonify({
            "code": "ANALYSIS_ERROR",
            "message": f"Failed to get trend analysis: {e}",
            "details": None,
            "trace_id": None,
        }), 500


@realtime_bp.route("/realtime/status", methods=["POST"])
def get_workload_status():
    """
    Get comprehensive real-time status for a workload.

    Request JSON body:
        - namespace: Kubernetes namespace
        - workload_name: Name of the workload
        - container_name: Name of the container
        - window: Optional time window for analysis

    Returns:
        Complete workload status with health score and alerts.
    """
    data = request.get_json() or {}

    try:
        req = TrendAnalysisRequest.model_validate(data)
    except ValidationError as e:
        return jsonify({
            "code": "VALIDATION_ERROR",
            "message": "Invalid request body",
            "details": e.errors(),
            "trace_id": None,
        }), 400

    prometheus_url = current_app.config.get("PROMETHEUS_BASE_URL")
    collector = get_streaming_collector(prometheus_url)
    window = _get_time_window(req.window.value if req.window else None)

    try:
        status = collector.get_workload_status(
            namespace=req.namespace,
            workload_name=req.workload_name,
            container_name=req.container_name,
            window=window,
        )

        return jsonify(_status_to_dict(status)), 200

    except Exception as e:
        logger.exception(f"Failed to get workload status: {e}")
        return jsonify({
            "code": "STATUS_ERROR",
            "message": f"Failed to get workload status: {e}",
            "details": None,
            "trace_id": None,
        }), 500


@realtime_bp.route("/realtime/monitor/start", methods=["POST"])
def start_monitoring():
    """
    Start background monitoring for workloads.

    Request JSON body:
        - workloads: List of workload identifiers to monitor
        - check_interval: Seconds between checks (10-3600)

    Returns:
        Monitoring status.
    """
    data = request.get_json() or {}

    try:
        req = MonitoringConfigRequest.model_validate(data)
    except ValidationError as e:
        return jsonify({
            "code": "VALIDATION_ERROR",
            "message": "Invalid request body",
            "details": e.errors(),
            "trace_id": None,
        }), 400

    prometheus_url = current_app.config.get("PROMETHEUS_BASE_URL")
    pipeline = get_anomaly_pipeline(prometheus_url)

    # Add workloads to monitoring
    for workload in req.workloads:
        pipeline.add_workload(
            namespace=workload.namespace,
            workload_name=workload.workload_name,
            container_name=workload.container_name,
        )

    # Start background monitor
    monitor = get_background_monitor(pipeline, req.check_interval)
    if not monitor.is_running:
        monitor.start()

    return jsonify({
        "status": "started",
        "workloads_monitored": len(req.workloads),
        "check_interval": req.check_interval,
        "is_running": monitor.is_running,
    }), 200


@realtime_bp.route("/realtime/monitor/stop", methods=["POST"])
def stop_monitoring():
    """
    Stop background monitoring.

    Returns:
        Monitoring status.
    """
    monitor = get_background_monitor()
    if monitor.is_running:
        monitor.stop()

    return jsonify({
        "status": "stopped",
        "is_running": monitor.is_running,
        "total_checks": monitor.check_count,
        "last_check": monitor.last_check.isoformat() if monitor.last_check else None,
    }), 200


@realtime_bp.route("/realtime/monitor/status", methods=["GET"])
def get_monitoring_status():
    """
    Get current monitoring status.

    Returns:
        Monitoring status and active alerts.
    """
    monitor = get_background_monitor()
    pipeline = get_anomaly_pipeline()

    active_alerts = pipeline.get_all_active_alerts()

    return jsonify({
        "is_running": monitor.is_running,
        "check_count": monitor.check_count,
        "last_check": monitor.last_check.isoformat() if monitor.last_check else None,
        "active_alerts_count": len(active_alerts),
        "active_alerts": [_alert_to_dict(a) for a in active_alerts],
    }), 200


@realtime_bp.route("/realtime/alerts", methods=["GET"])
def get_active_alerts():
    """
    Get all active alerts from the monitoring pipeline.

    Query parameters:
        - severity: Filter by severity (low, medium, high, critical)
        - limit: Maximum number of alerts to return

    Returns:
        List of active alerts.
    """
    severity_filter = request.args.get("severity")
    limit = request.args.get("limit", type=int, default=100)

    pipeline = get_anomaly_pipeline()
    alerts = pipeline.get_all_active_alerts()

    # Apply severity filter
    if severity_filter:
        alerts = [a for a in alerts if a.severity.value == severity_filter]

    # Apply limit
    alerts = alerts[:limit]

    return jsonify({
        "total_alerts": len(alerts),
        "alerts": [_alert_to_dict(a) for a in alerts],
    }), 200


@realtime_bp.route("/realtime/workload/<namespace>/<workload>/<container>", methods=["GET"])
def get_workload_realtime(namespace: str, workload: str, container: str):
    """
    Get real-time status for a specific workload (GET variant).

    Path parameters:
        - namespace: Kubernetes namespace
        - workload: Workload name
        - container: Container name

    Query parameters:
        - window: Time window (5m, 15m, 30m, 1h, 6h, 12h, 24h)

    Returns:
        Complete workload status.
    """
    window_str = request.args.get("window", "15m")
    window = _get_time_window(window_str)

    prometheus_url = current_app.config.get("PROMETHEUS_BASE_URL")
    collector = get_streaming_collector(prometheus_url)

    try:
        status = collector.get_workload_status(
            namespace=namespace,
            workload_name=workload,
            container_name=container,
            window=window,
        )

        return jsonify(_status_to_dict(status)), 200

    except Exception as e:
        logger.exception(f"Failed to get workload status: {e}")
        return jsonify({
            "code": "STATUS_ERROR",
            "message": f"Failed to get workload status: {e}",
            "details": None,
            "trace_id": None,
        }), 500
