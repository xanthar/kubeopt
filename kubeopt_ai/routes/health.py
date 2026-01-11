"""
Health check endpoints for KubeOpt AI.

Provides liveness and readiness probes for Kubernetes deployments.
"""

import logging
from flask import Blueprint, jsonify
from sqlalchemy import text

from kubeopt_ai.extensions import db

logger = logging.getLogger(__name__)

health_bp = Blueprint("health", __name__)


@health_bp.route("/api/v1/health", methods=["GET"])
def health():
    """
    Health check endpoint for liveness probe.

    Returns basic application health status.
    """
    return jsonify({
        "status": "healthy",
        "service": "kubeopt-ai",
        "version": "1.0.0"
    }), 200


@health_bp.route("/api/v1/health/ready", methods=["GET"])
def readiness():
    """
    Readiness check endpoint for Kubernetes readiness probe.

    Checks database connectivity and returns detailed status.
    """
    health_status = {
        "status": "ready",
        "service": "kubeopt-ai",
        "checks": {}
    }

    # Check database connectivity
    try:
        db.session.execute(text("SELECT 1"))
        health_status["checks"]["database"] = {
            "status": "healthy",
            "message": "Database connection successful"
        }
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        health_status["status"] = "not_ready"
        health_status["checks"]["database"] = {
            "status": "unhealthy",
            "message": "Database connection failed"
        }
        return jsonify(health_status), 503

    return jsonify(health_status), 200


@health_bp.route("/api/v1/health/live", methods=["GET"])
def liveness():
    """
    Liveness check endpoint for Kubernetes liveness probe.

    Returns simple alive status without dependency checks.
    """
    return jsonify({
        "status": "alive",
        "service": "kubeopt-ai"
    }), 200
