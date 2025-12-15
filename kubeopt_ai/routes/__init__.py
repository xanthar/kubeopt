"""
Routes package for KubeOpt AI.

Contains Flask blueprints for API endpoints.
"""

from kubeopt_ai.routes.health import health_bp
from kubeopt_ai.routes.optimize import optimize_bp
from kubeopt_ai.routes.insights import insights_bp
from kubeopt_ai.routes.realtime import realtime_bp
from kubeopt_ai.routes.webhooks import webhooks_bp

__all__ = ["health_bp", "optimize_bp", "insights_bp", "realtime_bp", "webhooks_bp"]
