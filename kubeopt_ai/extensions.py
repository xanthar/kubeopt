"""
Flask extensions initialization.

This module initializes Flask extensions that are shared across the application.
Extensions are initialized without the app context and bound later in the app factory.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

# Database extension
db = SQLAlchemy()

# Migration extension
migrate = Migrate()


def init_extensions(app) -> None:
    """
    Initialize all Flask extensions with the application instance.

    Args:
        app: Flask application instance
    """
    db.init_app(app)
    migrate.init_app(app, db)
