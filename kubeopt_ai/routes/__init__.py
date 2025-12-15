"""
Routes package for KubeOpt AI.

Contains Flask blueprints for API endpoints.
"""

from kubeopt_ai.routes.health import health_bp
from kubeopt_ai.routes.optimize import optimize_bp
from kubeopt_ai.routes.insights import insights_bp
from kubeopt_ai.routes.realtime import realtime_bp
from kubeopt_ai.routes.webhooks import webhooks_bp
from kubeopt_ai.routes.auth import auth_bp
from kubeopt_ai.routes.clusters import clusters_bp
from kubeopt_ai.routes.history import history_bp
from kubeopt_ai.routes.docs import docs_bp
from kubeopt_ai.routes.schedules import schedules_bp
from kubeopt_ai.routes.apply import apply_bp

__all__ = [
    "health_bp",
    "optimize_bp",
    "insights_bp",
    "realtime_bp",
    "webhooks_bp",
    "auth_bp",
    "clusters_bp",
    "history_bp",
    "docs_bp",
    "schedules_bp",
    "apply_bp",
]
