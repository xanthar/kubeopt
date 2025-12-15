"""
Historical trend analysis API routes for KubeOpt AI.

Provides REST endpoints for querying historical metrics and trend analyses.
"""

import logging
from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, jsonify

from kubeopt_ai.core.trend_analyzer import (
    get_history_collector,
    get_trend_analyzer,
    TrendAnalyzerError,
)
from kubeopt_ai.core.models import MetricsHistory, TrendAnalysis
from kubeopt_ai.extensions import db

logger = logging.getLogger(__name__)

history_bp = Blueprint("history", __name__, url_prefix="/api/v1/history")


@history_bp.route("/metrics", methods=["GET"])
def get_metrics_history():
    """
    Query historical metrics for a workload.

    Query Parameters:
        cluster_id (str): Filter by cluster
        namespace (str): Kubernetes namespace (required)
        workload_name (str): Workload name (required)
        container_name (str): Container name (required)
        start_time (str): ISO format start time
        end_time (str): ISO format end time
        days (int): Alternative to start_time - get last N days
        limit (int): Max results

    Returns:
        200: List of metrics records
        400: Missing required parameters
    """
    namespace = request.args.get("namespace")
    workload_name = request.args.get("workload_name")
    container_name = request.args.get("container_name")

    if not all([namespace, workload_name, container_name]):
        return jsonify({
            "code": "BAD_REQUEST",
            "message": "namespace, workload_name, and container_name are required",
        }), 400

    cluster_id = request.args.get("cluster_id")
    limit = request.args.get("limit", 1000, type=int)

    # Determine time range
    end_time = datetime.now(timezone.utc)
    start_time = None

    if request.args.get("start_time"):
        try:
            start_time = datetime.fromisoformat(request.args["start_time"].replace("Z", "+00:00"))
        except ValueError:
            return jsonify({
                "code": "BAD_REQUEST",
                "message": "Invalid start_time format. Use ISO 8601.",
            }), 400

    if request.args.get("end_time"):
        try:
            end_time = datetime.fromisoformat(request.args["end_time"].replace("Z", "+00:00"))
        except ValueError:
            return jsonify({
                "code": "BAD_REQUEST",
                "message": "Invalid end_time format. Use ISO 8601.",
            }), 400

    if not start_time:
        days = request.args.get("days", 7, type=int)
        start_time = end_time - timedelta(days=days)

    # Query metrics
    collector = get_history_collector()
    history = collector.get_history(
        cluster_id=cluster_id,
        namespace=namespace,
        workload_name=workload_name,
        container_name=container_name,
        start_time=start_time,
        end_time=end_time,
    )

    # Apply limit
    if len(history) > limit:
        history = history[:limit]

    return jsonify({
        "metrics": [h.to_dict() for h in history],
        "count": len(history),
        "time_range": {
            "start": start_time.isoformat(),
            "end": end_time.isoformat(),
        },
    })


@history_bp.route("/metrics/collect", methods=["POST"])
def collect_metrics_snapshot():
    """
    Collect a point-in-time metrics snapshot.

    Request Body:
        cluster_id (str): Optional cluster ID
        namespace (str): Kubernetes namespace (required)
        workload_name (str): Workload name (required)
        workload_kind (str): Workload kind (required)
        container_name (str): Container name (required)

    Returns:
        201: Created metrics record
        400: Missing required parameters
    """
    data = request.get_json()

    if not data:
        return jsonify({
            "code": "BAD_REQUEST",
            "message": "Request body is required",
        }), 400

    required = ["namespace", "workload_name", "workload_kind", "container_name"]
    missing = [f for f in required if not data.get(f)]

    if missing:
        return jsonify({
            "code": "BAD_REQUEST",
            "message": f"Missing required fields: {', '.join(missing)}",
        }), 400

    try:
        collector = get_history_collector()
        record = collector.collect_snapshot(
            cluster_id=data.get("cluster_id"),
            namespace=data["namespace"],
            workload_name=data["workload_name"],
            workload_kind=data["workload_kind"],
            container_name=data["container_name"],
        )

        return jsonify(record.to_dict()), 201

    except Exception as e:
        logger.error(f"Failed to collect metrics: {e}")
        return jsonify({
            "code": "COLLECTION_FAILED",
            "message": str(e),
        }), 500


@history_bp.route("/trends", methods=["GET"])
def list_trend_analyses():
    """
    List trend analyses.

    Query Parameters:
        cluster_id (str): Filter by cluster
        namespace (str): Filter by namespace
        limit (int): Max results (default 100)
        offset (int): Skip results

    Returns:
        200: List of trend analyses
    """
    cluster_id = request.args.get("cluster_id")
    namespace = request.args.get("namespace")
    limit = request.args.get("limit", 100, type=int)
    offset = request.args.get("offset", 0, type=int)

    analyzer = get_trend_analyzer()
    analyses = analyzer.list_analyses(
        cluster_id=cluster_id,
        namespace=namespace,
        limit=limit,
        offset=offset,
    )

    return jsonify({
        "analyses": [a.to_dict() for a in analyses],
        "count": len(analyses),
        "limit": limit,
        "offset": offset,
    })


@history_bp.route("/trends/<analysis_id>", methods=["GET"])
def get_trend_analysis(analysis_id: str):
    """
    Get a specific trend analysis by ID.

    Path Parameters:
        analysis_id: Analysis UUID

    Returns:
        200: Trend analysis object
        404: Analysis not found
    """
    analysis = db.session.get(TrendAnalysis, analysis_id)

    if not analysis:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Trend analysis not found: {analysis_id}",
        }), 404

    return jsonify(analysis.to_dict())


@history_bp.route("/trends/analyze", methods=["POST"])
def run_trend_analysis():
    """
    Run trend analysis on historical metrics.

    Request Body:
        cluster_id (str): Optional cluster ID
        namespace (str): Kubernetes namespace (required)
        workload_name (str): Workload name (required)
        container_name (str): Container name (required)
        days (int): Analysis period in days (default 30)

    Returns:
        201: Created trend analysis
        400: Missing required parameters or insufficient data
        500: Analysis failed
    """
    data = request.get_json()

    if not data:
        return jsonify({
            "code": "BAD_REQUEST",
            "message": "Request body is required",
        }), 400

    required = ["namespace", "workload_name", "container_name"]
    missing = [f for f in required if not data.get(f)]

    if missing:
        return jsonify({
            "code": "BAD_REQUEST",
            "message": f"Missing required fields: {', '.join(missing)}",
        }), 400

    cluster_id = data.get("cluster_id")
    namespace = data["namespace"]
    workload_name = data["workload_name"]
    container_name = data["container_name"]
    days = data.get("days", 30)

    # Get historical data
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=days)

    collector = get_history_collector()
    history = collector.get_history(
        cluster_id=cluster_id,
        namespace=namespace,
        workload_name=workload_name,
        container_name=container_name,
        start_time=start_time,
        end_time=end_time,
    )

    if len(history) < 2:
        return jsonify({
            "code": "INSUFFICIENT_DATA",
            "message": f"Not enough historical data for analysis. Found {len(history)} data points, need at least 2.",
        }), 400

    try:
        analyzer = get_trend_analyzer()
        analysis = analyzer.analyze(
            cluster_id=cluster_id,
            namespace=namespace,
            workload_name=workload_name,
            container_name=container_name,
            history=history,
        )

        return jsonify(analysis.to_dict()), 201

    except TrendAnalyzerError as e:
        return jsonify({
            "code": "ANALYSIS_FAILED",
            "message": str(e),
        }), 400

    except Exception as e:
        logger.error(f"Trend analysis failed: {e}")
        return jsonify({
            "code": "INTERNAL_ERROR",
            "message": str(e),
        }), 500


@history_bp.route("/trends/latest", methods=["GET"])
def get_latest_trend():
    """
    Get the most recent trend analysis for a workload.

    Query Parameters:
        cluster_id (str): Optional cluster filter
        namespace (str): Kubernetes namespace (required)
        workload_name (str): Workload name (required)
        container_name (str): Container name (required)

    Returns:
        200: Latest trend analysis
        400: Missing required parameters
        404: No analysis found
    """
    namespace = request.args.get("namespace")
    workload_name = request.args.get("workload_name")
    container_name = request.args.get("container_name")

    if not all([namespace, workload_name, container_name]):
        return jsonify({
            "code": "BAD_REQUEST",
            "message": "namespace, workload_name, and container_name are required",
        }), 400

    cluster_id = request.args.get("cluster_id")

    analyzer = get_trend_analyzer()
    analysis = analyzer.get_latest_analysis(
        cluster_id=cluster_id,
        namespace=namespace,
        workload_name=workload_name,
        container_name=container_name,
    )

    if not analysis:
        return jsonify({
            "code": "NOT_FOUND",
            "message": "No trend analysis found for this workload",
        }), 404

    return jsonify(analysis.to_dict())


@history_bp.route("/summary", methods=["GET"])
def get_history_summary():
    """
    Get a summary of historical data availability.

    Query Parameters:
        cluster_id (str): Optional cluster filter
        namespace (str): Optional namespace filter

    Returns:
        200: Summary statistics
    """
    cluster_id = request.args.get("cluster_id")
    namespace = request.args.get("namespace")

    query = MetricsHistory.query

    if cluster_id:
        query = query.filter(MetricsHistory.cluster_id == cluster_id)
    if namespace:
        query = query.filter(MetricsHistory.namespace == namespace)

    # Get counts
    total_records = query.count()

    # Get unique workloads
    workload_query = db.session.query(
        MetricsHistory.namespace,
        MetricsHistory.workload_name,
    ).distinct()

    if cluster_id:
        workload_query = workload_query.filter(MetricsHistory.cluster_id == cluster_id)
    if namespace:
        workload_query = workload_query.filter(MetricsHistory.namespace == namespace)

    unique_workloads = workload_query.count()

    # Get time range
    from sqlalchemy import func
    time_stats = db.session.query(
        func.min(MetricsHistory.timestamp),
        func.max(MetricsHistory.timestamp),
    )

    if cluster_id:
        time_stats = time_stats.filter(MetricsHistory.cluster_id == cluster_id)
    if namespace:
        time_stats = time_stats.filter(MetricsHistory.namespace == namespace)

    min_time, max_time = time_stats.first()

    # Count analyses
    analysis_query = TrendAnalysis.query
    if cluster_id:
        analysis_query = analysis_query.filter(TrendAnalysis.cluster_id == cluster_id)
    if namespace:
        analysis_query = analysis_query.filter(TrendAnalysis.namespace == namespace)

    analysis_count = analysis_query.count()

    return jsonify({
        "total_records": total_records,
        "unique_workloads": unique_workloads,
        "analysis_count": analysis_count,
        "time_range": {
            "oldest": min_time.isoformat() if min_time else None,
            "newest": max_time.isoformat() if max_time else None,
        },
    })
