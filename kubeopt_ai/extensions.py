"""
Flask extensions initialization.

This module initializes Flask extensions that are shared across the application.
Extensions are initialized without the app context and bound later in the app factory.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_jwt_extended import JWTManager

# Database extension
db = SQLAlchemy()

# Migration extension
migrate = Migrate()

# Rate limiter extension
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],  # No default limit, applied per-endpoint
    storage_uri="memory://",  # Default to in-memory, can be overridden
)

# JWT extension
jwt = JWTManager()


def init_extensions(app) -> None:
    """
    Initialize all Flask extensions with the application instance.

    Args:
        app: Flask application instance
    """
    db.init_app(app)
    migrate.init_app(app, db)

    # Configure rate limiter from app config
    storage_uri = app.config.get("RATE_LIMIT_STORAGE_URL", "memory://")
    limiter._storage_uri = storage_uri

    # Set default limits from config
    default_limits = app.config.get("RATE_LIMIT_DEFAULT", "")
    if default_limits:
        limiter._default_limits = [default_limits]

    # Check if rate limiting is enabled
    if app.config.get("RATE_LIMIT_ENABLED", True):
        limiter.init_app(app)

    # Initialize JWT extension
    jwt.init_app(app)

    # Register JWT callbacks for token validation
    _register_jwt_callbacks(app)


def _register_jwt_callbacks(app) -> None:
    """Register JWT callbacks for token validation and user loading."""
    from kubeopt_ai.core.models import User, RefreshToken
    from datetime import datetime, timezone
    import hashlib

    @jwt.user_identity_loader
    def user_identity_lookup(user):
        """Return user ID for JWT identity."""
        if isinstance(user, User):
            return user.id
        return user

    @jwt.user_lookup_loader
    def user_lookup_callback(_jwt_header, jwt_data):
        """Load user from JWT identity."""
        identity = jwt_data["sub"]
        return db.session.get(User, identity)

    @jwt.token_in_blocklist_loader
    def check_if_token_revoked(jwt_header, jwt_payload):
        """Check if a token has been revoked."""
        jti = jwt_payload.get("jti")
        token_type = jwt_payload.get("type")

        # Only check refresh tokens for revocation
        if token_type == "refresh":
            token_hash = hashlib.sha256(jti.encode()).hexdigest()
            token = RefreshToken.query.filter_by(token_hash=token_hash).first()
            if token:
                return token.revoked or token.expires_at < datetime.now(timezone.utc)
        return False

    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        """Handle expired token errors."""
        return {
            "code": "TOKEN_EXPIRED",
            "message": "The token has expired",
        }, 401

    @jwt.invalid_token_loader
    def invalid_token_callback(error):
        """Handle invalid token errors."""
        return {
            "code": "INVALID_TOKEN",
            "message": "Token verification failed",
            "details": str(error),
        }, 401

    @jwt.unauthorized_loader
    def missing_token_callback(error):
        """Handle missing token errors."""
        return {
            "code": "MISSING_TOKEN",
            "message": "Authorization token is required",
        }, 401

    @jwt.revoked_token_loader
    def revoked_token_callback(jwt_header, jwt_payload):
        """Handle revoked token errors."""
        return {
            "code": "TOKEN_REVOKED",
            "message": "The token has been revoked",
        }, 401
