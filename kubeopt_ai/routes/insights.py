"""
Insights API endpoints for KubeOpt AI.

Provides REST API for cost projections and anomaly detection analysis.
"""

import logging
from collections import Counter
from flask import Blueprint, jsonify, request, current_app
from pydantic import ValidationError

from kubeopt_ai.core.schemas import CostProjectionRequest, AnomalyAnalysisRequest
from kubeopt_ai.core.optimizer_service import create_optimizer_service
from kubeopt_ai.core.models import OptimizationRun
from kubeopt_ai.core.cost_engine import (
    calculate_optimization_savings,
    CloudProvider as CostCloudProvider,
    CostBreakdown,
    WorkloadCost,
    CostProjection,
)
from kubeopt_ai.core.anomaly_detection import (
    analyze_optimization_run_anomalies,
    AnomalyAnalysis,
    AnomalyAlert,
)

logger = logging.getLogger(__name__)

insights_bp = Blueprint("insights", __name__)


def _cost_breakdown_to_dict(breakdown: CostBreakdown) -> dict:
    """Convert CostBreakdown to JSON-serializable dict."""
    return {
        "cpu_cost": float(breakdown.cpu_cost),
        "memory_cost": float(breakdown.memory_cost),
        "total_cost": float(breakdown.total_cost),
        "cpu_cores": float(breakdown.cpu_cores),
        "memory_gib": float(breakdown.memory_gib),
    }


def _workload_cost_to_dict(wc: WorkloadCost) -> dict:
    """Convert WorkloadCost to JSON-serializable dict."""
    result = {
        "workload_name": wc.workload_name,
        "namespace": wc.namespace,
        "replicas": wc.replicas,
        "current_cost": _cost_breakdown_to_dict(wc.current_cost),
    }

    if wc.projected_cost:
        result["projected_cost"] = _cost_breakdown_to_dict(wc.projected_cost)

    if wc.monthly_savings is not None:
        result["monthly_savings"] = float(wc.monthly_savings)

    if wc.savings_percent is not None:
        result["savings_percent"] = float(wc.savings_percent)

    return result


def _cost_projection_to_dict(projection: CostProjection) -> dict:
    """Convert CostProjection to JSON-serializable dict."""
    return {
        "provider": projection.provider.value,
        "region": projection.region,
        "currency": projection.currency,
        "workload_costs": [
            _workload_cost_to_dict(wc) for wc in projection.workload_costs
        ],
        "total_current_monthly": float(projection.total_current_monthly),
        "total_projected_monthly": float(projection.total_projected_monthly),
        "total_monthly_savings": float(projection.total_monthly_savings),
        "total_annual_savings": float(projection.total_annual_savings),
        "savings_percent": float(projection.savings_percent),
    }


def _alert_to_dict(alert: AnomalyAlert) -> dict:
    """Convert AnomalyAlert to JSON-serializable dict."""
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
        "metadata": alert.metadata,
    }


def _analysis_to_dict(analysis: AnomalyAnalysis) -> dict:
    """Convert AnomalyAnalysis to JSON-serializable dict."""
    return {
        "workload_name": analysis.workload_name,
        "namespace": analysis.namespace,
        "analysis_period_hours": analysis.analysis_period_hours,
        "alerts": [_alert_to_dict(a) for a in analysis.alerts],
        "health_score": analysis.health_score,
        "analyzed_at": analysis.analyzed_at.isoformat(),
    }


@insights_bp.route("/insights/cost", methods=["POST"])
def calculate_cost_projection():
    """
    Calculate cost projection for an optimization run.

    Shows current resource costs and projected savings if recommendations
    are applied. Supports multiple cloud providers and regions.

    Request JSON body:
        - run_id: UUID of the optimization run
        - provider: Cloud provider (aws, gcp, azure, on_prem)
        - region: Optional region override

    Returns:
        - Cost breakdown per workload
        - Total current and projected monthly costs
        - Estimated savings (monthly and annual)
    """
    data = request.get_json() or {}

    # Validate request
    try:
        req = CostProjectionRequest.model_validate(data)
    except ValidationError as e:
        return jsonify({
            "code": "VALIDATION_ERROR",
            "message": "Invalid request body",
            "details": e.errors(),
            "trace_id": None
        }), 400

    logger.info(f"Calculating cost projection for run: {req.run_id}")

    # Get optimization run details
    from kubeopt_ai.extensions import db
    run = db.session.get(OptimizationRun, req.run_id)
    if not run:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Optimization run {req.run_id} not found",
            "details": None,
            "trace_id": None
        }), 404

    service = create_optimizer_service(
        app_config=current_app.config,
        use_mock_llm=current_app.config.get("TESTING", False),
    )
    run_details = service.get_run_details(req.run_id)

    if not run_details:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Optimization run {req.run_id} not found",
            "details": None,
            "trace_id": None
        }), 404

    try:
        # Map schema provider to cost engine provider
        provider_map = {
            "aws": CostCloudProvider.AWS,
            "gcp": CostCloudProvider.GCP,
            "azure": CostCloudProvider.AZURE,
            "on_prem": CostCloudProvider.ON_PREM,
        }
        provider = provider_map.get(req.provider.value, CostCloudProvider.AWS)

        projection = calculate_optimization_savings(
            optimization_run_details=run_details,
            provider=provider,
            region=req.region,
        )

        response = _cost_projection_to_dict(projection)
        response["run_id"] = req.run_id

        return jsonify(response), 200

    except Exception as e:
        logger.exception(f"Cost projection failed: {e}")
        return jsonify({
            "code": "CALCULATION_ERROR",
            "message": f"Failed to calculate cost projection: {e}",
            "details": None,
            "trace_id": None
        }), 500


@insights_bp.route("/insights/cost/<run_id>", methods=["GET"])
def get_cost_projection(run_id: str):
    """
    Get cost projection for an optimization run (GET variant).

    Uses AWS us-east-1 pricing by default. Use POST endpoint
    to specify provider and region.

    Args:
        run_id: UUID of the optimization run

    Returns:
        - Cost breakdown per workload
        - Total current and projected monthly costs
        - Estimated savings (monthly and annual)
    """
    provider_str = request.args.get("provider", "aws")
    region = request.args.get("region")

    logger.info(f"Getting cost projection for run: {run_id}")

    # Get optimization run details
    from kubeopt_ai.extensions import db
    run = db.session.get(OptimizationRun, run_id)
    if not run:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Optimization run {run_id} not found",
            "details": None,
            "trace_id": None
        }), 404

    service = create_optimizer_service(
        app_config=current_app.config,
        use_mock_llm=current_app.config.get("TESTING", False),
    )
    run_details = service.get_run_details(run_id)

    if not run_details:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Optimization run {run_id} not found",
            "details": None,
            "trace_id": None
        }), 404

    try:
        provider_map = {
            "aws": CostCloudProvider.AWS,
            "gcp": CostCloudProvider.GCP,
            "azure": CostCloudProvider.AZURE,
            "on_prem": CostCloudProvider.ON_PREM,
        }
        provider = provider_map.get(provider_str, CostCloudProvider.AWS)

        projection = calculate_optimization_savings(
            optimization_run_details=run_details,
            provider=provider,
            region=region,
        )

        response = _cost_projection_to_dict(projection)
        response["run_id"] = run_id

        return jsonify(response), 200

    except Exception as e:
        logger.exception(f"Cost projection failed: {e}")
        return jsonify({
            "code": "CALCULATION_ERROR",
            "message": f"Failed to calculate cost projection: {e}",
            "details": None,
            "trace_id": None
        }), 500


@insights_bp.route("/insights/anomalies", methods=["POST"])
def analyze_anomalies():
    """
    Analyze workloads for resource usage anomalies.

    Detects patterns like memory leaks, CPU spikes, underutilization,
    and resource saturation.

    Request JSON body:
        - run_id: UUID of the optimization run
        - hours: Analysis period in hours (1-168, default 24)

    Returns:
        - Anomaly alerts per workload
        - Health scores
        - Recommendations
    """
    data = request.get_json() or {}

    # Validate request
    try:
        req = AnomalyAnalysisRequest.model_validate(data)
    except ValidationError as e:
        return jsonify({
            "code": "VALIDATION_ERROR",
            "message": "Invalid request body",
            "details": e.errors(),
            "trace_id": None
        }), 400

    logger.info(f"Analyzing anomalies for run: {req.run_id}")

    # Get optimization run details
    from kubeopt_ai.extensions import db
    run = db.session.get(OptimizationRun, req.run_id)
    if not run:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Optimization run {req.run_id} not found",
            "details": None,
            "trace_id": None
        }), 404

    service = create_optimizer_service(
        app_config=current_app.config,
        use_mock_llm=current_app.config.get("TESTING", False),
    )
    run_details = service.get_run_details(req.run_id)

    if not run_details:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Optimization run {req.run_id} not found",
            "details": None,
            "trace_id": None
        }), 404

    try:
        prometheus_url = current_app.config.get("PROMETHEUS_BASE_URL")

        analyses = analyze_optimization_run_anomalies(
            optimization_run_details=run_details,
            prometheus_url=prometheus_url,
        )

        # Build summary
        all_alerts = []
        health_scores = []
        for analysis in analyses:
            all_alerts.extend(analysis.alerts)
            health_scores.append(analysis.health_score)

        severity_counts = Counter(a.severity.value for a in all_alerts)
        type_counts = Counter(a.anomaly_type.value for a in all_alerts)

        response = {
            "run_id": req.run_id,
            "total_workloads": len(analyses),
            "total_alerts": len(all_alerts),
            "alerts_by_severity": dict(severity_counts),
            "alerts_by_type": dict(type_counts),
            "average_health_score": (
                sum(health_scores) / len(health_scores) if health_scores else 100.0
            ),
            "workload_analyses": [_analysis_to_dict(a) for a in analyses],
        }

        return jsonify(response), 200

    except Exception as e:
        logger.exception(f"Anomaly analysis failed: {e}")
        return jsonify({
            "code": "ANALYSIS_ERROR",
            "message": f"Failed to analyze anomalies: {e}",
            "details": None,
            "trace_id": None
        }), 500


@insights_bp.route("/insights/anomalies/<run_id>", methods=["GET"])
def get_anomaly_analysis(run_id: str):
    """
    Get anomaly analysis for an optimization run (GET variant).

    Args:
        run_id: UUID of the optimization run

    Query parameters:
        - hours: Analysis period (default 24)
        - severity: Filter by severity (low, medium, high, critical)

    Returns:
        - Anomaly alerts per workload
        - Health scores
        - Recommendations
    """
    severity_filter = request.args.get("severity")

    logger.info(f"Getting anomaly analysis for run: {run_id}")

    # Get optimization run details
    from kubeopt_ai.extensions import db
    run = db.session.get(OptimizationRun, run_id)
    if not run:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Optimization run {run_id} not found",
            "details": None,
            "trace_id": None
        }), 404

    service = create_optimizer_service(
        app_config=current_app.config,
        use_mock_llm=current_app.config.get("TESTING", False),
    )
    run_details = service.get_run_details(run_id)

    if not run_details:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Optimization run {run_id} not found",
            "details": None,
            "trace_id": None
        }), 404

    try:
        prometheus_url = current_app.config.get("PROMETHEUS_BASE_URL")

        analyses = analyze_optimization_run_anomalies(
            optimization_run_details=run_details,
            prometheus_url=prometheus_url,
        )

        # Apply severity filter if specified
        if severity_filter:
            for analysis in analyses:
                analysis.alerts = [
                    a for a in analysis.alerts
                    if a.severity.value == severity_filter
                ]

        # Build summary
        all_alerts = []
        health_scores = []
        for analysis in analyses:
            all_alerts.extend(analysis.alerts)
            health_scores.append(analysis.health_score)

        severity_counts = Counter(a.severity.value for a in all_alerts)
        type_counts = Counter(a.anomaly_type.value for a in all_alerts)

        response = {
            "run_id": run_id,
            "total_workloads": len(analyses),
            "total_alerts": len(all_alerts),
            "alerts_by_severity": dict(severity_counts),
            "alerts_by_type": dict(type_counts),
            "average_health_score": (
                sum(health_scores) / len(health_scores) if health_scores else 100.0
            ),
            "workload_analyses": [_analysis_to_dict(a) for a in analyses],
        }

        return jsonify(response), 200

    except Exception as e:
        logger.exception(f"Anomaly analysis failed: {e}")
        return jsonify({
            "code": "ANALYSIS_ERROR",
            "message": f"Failed to analyze anomalies: {e}",
            "details": None,
            "trace_id": None
        }), 500


@insights_bp.route("/insights/summary/<run_id>", methods=["GET"])
def get_insights_summary(run_id: str):
    """
    Get a combined insights summary for an optimization run.

    Combines cost projection and anomaly analysis into a single
    executive summary view.

    Args:
        run_id: UUID of the optimization run

    Returns:
        - Cost summary with savings
        - Anomaly summary with health score
        - Top recommendations
    """
    provider_str = request.args.get("provider", "aws")
    region = request.args.get("region")

    logger.info(f"Getting insights summary for run: {run_id}")

    # Get optimization run details
    from kubeopt_ai.extensions import db
    run = db.session.get(OptimizationRun, run_id)
    if not run:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Optimization run {run_id} not found",
            "details": None,
            "trace_id": None
        }), 404

    service = create_optimizer_service(
        app_config=current_app.config,
        use_mock_llm=current_app.config.get("TESTING", False),
    )
    run_details = service.get_run_details(run_id)

    if not run_details:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Optimization run {run_id} not found",
            "details": None,
            "trace_id": None
        }), 404

    try:
        # Cost projection
        provider_map = {
            "aws": CostCloudProvider.AWS,
            "gcp": CostCloudProvider.GCP,
            "azure": CostCloudProvider.AZURE,
            "on_prem": CostCloudProvider.ON_PREM,
        }
        provider = provider_map.get(provider_str, CostCloudProvider.AWS)

        cost_projection = calculate_optimization_savings(
            optimization_run_details=run_details,
            provider=provider,
            region=region,
        )

        # Anomaly analysis
        prometheus_url = current_app.config.get("PROMETHEUS_BASE_URL")
        anomaly_analyses = analyze_optimization_run_anomalies(
            optimization_run_details=run_details,
            prometheus_url=prometheus_url,
        )

        # Collect all alerts and calculate health
        all_alerts = []
        health_scores = []
        for analysis in anomaly_analyses:
            all_alerts.extend(analysis.alerts)
            health_scores.append(analysis.health_score)

        # Get top recommendations (high/critical alerts)
        top_recommendations = [
            {
                "type": a.anomaly_type.value,
                "severity": a.severity.value,
                "workload": f"{a.namespace}/{a.workload_name}",
                "recommendation": a.recommendation,
            }
            for a in sorted(
                all_alerts,
                key=lambda x: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(
                    x.severity.value, 4
                ),
            )[:5]  # Top 5 recommendations
        ]

        response = {
            "run_id": run_id,
            "cost_summary": {
                "provider": cost_projection.provider.value,
                "region": cost_projection.region,
                "currency": cost_projection.currency,
                "current_monthly": float(cost_projection.total_current_monthly),
                "projected_monthly": float(cost_projection.total_projected_monthly),
                "monthly_savings": float(cost_projection.total_monthly_savings),
                "annual_savings": float(cost_projection.total_annual_savings),
                "savings_percent": float(cost_projection.savings_percent),
            },
            "health_summary": {
                "average_health_score": (
                    sum(health_scores) / len(health_scores) if health_scores else 100.0
                ),
                "total_alerts": len(all_alerts),
                "critical_alerts": sum(
                    1 for a in all_alerts if a.severity.value == "critical"
                ),
                "high_alerts": sum(
                    1 for a in all_alerts if a.severity.value == "high"
                ),
            },
            "top_recommendations": top_recommendations,
            "workload_count": len(run_details.get("workloads", [])),
            "suggestion_count": len(run_details.get("suggestions", [])),
        }

        return jsonify(response), 200

    except Exception as e:
        logger.exception(f"Insights summary failed: {e}")
        return jsonify({
            "code": "SUMMARY_ERROR",
            "message": f"Failed to generate insights summary: {e}",
            "details": None,
            "trace_id": None
        }), 500
