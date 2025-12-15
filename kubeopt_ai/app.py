"""
Flask application factory for KubeOpt AI.

This module provides the application factory pattern for creating Flask instances
with proper configuration, extensions, and route registration.
"""

import logging
import sys
from typing import Optional

from flask import Flask

from kubeopt_ai.config import get_config, BaseConfig
from kubeopt_ai.extensions import init_extensions


def setup_logging(app: Flask) -> None:
    """
    Configure application logging.

    Args:
        app: Flask application instance
    """
    log_level = getattr(logging, app.config.get("LOG_LEVEL", "INFO").upper())
    log_format = app.config.get("LOG_FORMAT", "json")

    if log_format == "json":
        formatter = logging.Formatter(
            '{"timestamp": "%(asctime)s", "level": "%(levelname)s", '
            '"logger": "%(name)s", "message": "%(message)s"}'
        )
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Add stream handler
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(log_level)
    root_logger.addHandler(stream_handler)

    # Set Flask app logger
    app.logger.setLevel(log_level)


def register_blueprints(app: Flask) -> None:
    """
    Register all Flask blueprints.

    Args:
        app: Flask application instance
    """
    from kubeopt_ai.routes.health import health_bp
    from kubeopt_ai.routes.optimize import optimize_bp
    from kubeopt_ai.routes.insights import insights_bp
    from kubeopt_ai.routes.realtime import realtime_bp
    from kubeopt_ai.routes.webhooks import webhooks_bp
    from kubeopt_ai.routes.audit import audit_bp
    from kubeopt_ai.routes.auth import auth_bp
    from kubeopt_ai.routes.clusters import clusters_bp
    from kubeopt_ai.routes.history import history_bp
    from kubeopt_ai.routes.docs import docs_bp
    from kubeopt_ai.routes.schedules import schedules_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(optimize_bp, url_prefix="/api/v1")
    app.register_blueprint(insights_bp, url_prefix="/api/v1")
    app.register_blueprint(realtime_bp, url_prefix="/api/v1")
    app.register_blueprint(webhooks_bp, url_prefix="/api/v1")
    app.register_blueprint(audit_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(clusters_bp)  # F019: Multi-cluster support
    app.register_blueprint(history_bp)   # F020: Historical trends
    app.register_blueprint(docs_bp)      # F029: OpenAPI documentation
    app.register_blueprint(schedules_bp) # F021: Scheduled optimization runs


def register_error_handlers(app: Flask) -> None:
    """
    Register application-wide error handlers.

    Args:
        app: Flask application instance
    """
    from flask import jsonify

    @app.errorhandler(400)
    def bad_request(error):
        return jsonify({
            "code": "BAD_REQUEST",
            "message": str(error.description) if hasattr(error, 'description') else "Bad request",
            "details": None,
            "trace_id": None
        }), 400

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({
            "code": "NOT_FOUND",
            "message": "Resource not found",
            "details": None,
            "trace_id": None
        }), 404

    @app.errorhandler(429)
    def rate_limit_exceeded(error):
        app.logger.warning(f"Rate limit exceeded: {error}")
        return jsonify({
            "code": "RATE_LIMIT_EXCEEDED",
            "message": "Too many requests. Please slow down.",
            "details": str(error.description) if hasattr(error, 'description') else None,
            "trace_id": None
        }), 429

    @app.errorhandler(500)
    def internal_error(error):
        app.logger.exception("Internal server error")
        return jsonify({
            "code": "INTERNAL_ERROR",
            "message": "An internal error occurred",
            "details": None,
            "trace_id": None
        }), 500


def create_app(config: Optional[BaseConfig] = None) -> Flask:
    """
    Create and configure the Flask application.

    Args:
        config: Optional configuration object. If not provided, configuration
                is determined from FLASK_ENV environment variable.

    Returns:
        Configured Flask application instance
    """
    app = Flask(__name__)

    # Load configuration
    if config is None:
        config = get_config()

    app.config.from_object(config)

    # Setup logging
    setup_logging(app)

    # Initialize extensions
    init_extensions(app)

    # Register blueprints
    register_blueprints(app)

    # Register error handlers
    register_error_handlers(app)

    app.logger.info("KubeOpt AI application initialized")

    return app
