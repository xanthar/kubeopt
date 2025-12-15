"""
Optimization API endpoints for KubeOpt AI.

Provides REST API for triggering and retrieving optimization runs.
"""

import logging
from flask import Blueprint, jsonify, request, current_app
from pydantic import ValidationError

from kubeopt_ai.core.schemas import OptimizationRunRequest
from kubeopt_ai.core.optimizer_service import (
    OptimizerService,
    OptimizationError,
    create_optimizer_service,
)
from kubeopt_ai.core.models import OptimizationRun

logger = logging.getLogger(__name__)

optimize_bp = Blueprint("optimize", __name__)


def get_optimizer_service() -> OptimizerService:
    """Get or create the optimizer service."""
    return create_optimizer_service(
        app_config=current_app.config,
        use_mock_llm=current_app.config.get("TESTING", False),
    )


@optimize_bp.route("/optimize/run", methods=["POST"])
def create_optimization_run():
    """
    Create and execute a new optimization run.

    Request JSON body:
        - manifest_path: string (filesystem path to manifests)
        - lookback_days: optional int (default 7)

    Returns:
        - run_id: UUID of the created run
        - status: current status of the run
        - summary: workload and suggestion counts
    """
    data = request.get_json() or {}

    # Validate request
    try:
        req = OptimizationRunRequest.model_validate(data)
    except ValidationError as e:
        return jsonify({
            "code": "VALIDATION_ERROR",
            "message": "Invalid request body",
            "details": e.errors(),
            "trace_id": None
        }), 400

    logger.info(f"Received optimization request for path: {req.manifest_path}")

    try:
        service = get_optimizer_service()

        # Run optimization (skip metrics in testing mode)
        skip_metrics = current_app.config.get("TESTING", False)
        run = service.run_optimization(
            manifest_path=req.manifest_path,
            lookback_days=req.lookback_days,
            skip_metrics=skip_metrics,
        )

        # Get full details
        details = service.get_run_details(run.id)

        return jsonify({
            "run_id": run.id,
            "status": run.status.value,
            "manifest_path": run.manifest_source_path,
            "lookback_days": run.lookback_days,
            "summary": details.get("summary", {}) if details else {},
        }), 202

    except OptimizationError as e:
        logger.error(f"Optimization failed: {e}")
        return jsonify({
            "code": "OPTIMIZATION_ERROR",
            "message": str(e),
            "details": None,
            "trace_id": None
        }), 500


@optimize_bp.route("/optimize/run/<run_id>", methods=["GET"])
def get_optimization_run(run_id: str):
    """
    Retrieve details of an optimization run.

    Args:
        run_id: UUID of the optimization run

    Returns:
        - Run metadata (status, created_at, lookback_days)
        - Workload snapshots
        - Suggestions and diff-text
    """
    logger.info(f"Retrieving optimization run: {run_id}")

    from kubeopt_ai.extensions import db
    run = db.session.get(OptimizationRun, run_id)
    if not run:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Optimization run {run_id} not found",
            "details": None,
            "trace_id": None
        }), 404

    service = get_optimizer_service()
    details = service.get_run_details(run_id)

    if not details:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Optimization run {run_id} not found",
            "details": None,
            "trace_id": None
        }), 404

    return jsonify(details), 200


@optimize_bp.route("/optimize/runs", methods=["GET"])
def list_optimization_runs():
    """
    List all optimization runs with optional filtering.

    Query parameters:
        - status: Filter by status (pending, running, completed, failed)
        - limit: Maximum number of runs to return (default 20)
        - offset: Pagination offset (default 0)

    Returns:
        - List of optimization runs
        - Total count
    """
    status = request.args.get("status")
    limit = min(int(request.args.get("limit", 20)), 100)
    offset = int(request.args.get("offset", 0))

    query = OptimizationRun.query

    if status:
        query = query.filter_by(status=status)

    total = query.count()
    runs = (
        query
        .order_by(OptimizationRun.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return jsonify({
        "runs": [run.to_dict() for run in runs],
        "total": total,
        "limit": limit,
        "offset": offset,
    }), 200
