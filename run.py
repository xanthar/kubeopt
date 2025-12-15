#!/usr/bin/env python
"""
KubeOpt AI application entrypoint.

This module provides the main entry point for running the Flask application.
Use this for development or invoke via gunicorn for production.

Usage:
    Development: python run.py
    Production: gunicorn -w 4 -b 0.0.0.0:5000 'run:app'
"""

import os
from kubeopt_ai.app import create_app

# Create the application instance
app = create_app()

if __name__ == "__main__":
    # Get configuration from environment
    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    port = int(os.environ.get("FLASK_PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "true").lower() == "true"

    app.run(host=host, port=port, debug=debug)
