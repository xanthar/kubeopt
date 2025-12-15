"""
Rate limiting utilities for KubeOpt AI.

Provides rate limiting decorators and configuration for API endpoints.
"""

import logging
from functools import wraps
from typing import Callable, Optional, Any

from flask import jsonify, current_app, g, request

from kubeopt_ai.extensions import limiter

logger = logging.getLogger(__name__)


# Predefined rate limits for different endpoint types
class RateLimits:
    """Standard rate limit configurations."""

    # General API endpoints
    DEFAULT = "100/hour"

    # Resource-intensive operations
    OPTIMIZE = "10/minute"

    # Read operations (higher limits)
    READ = "300/hour"

    # Export operations (lower limits due to resource intensity)
    EXPORT = "20/hour"

    # Write operations
    WRITE = "60/hour"

    # Health checks (high limit for monitoring)
    HEALTH = "600/hour"

    # Webhook operations
    WEBHOOK = "30/minute"


def rate_limit(limit: str = RateLimits.DEFAULT):
    """
    Apply rate limiting to an endpoint.

    Args:
        limit: Rate limit string (e.g., "100/hour", "10/minute")

    Returns:
        Decorator function.

    Example:
        @rate_limit("10/minute")
        def expensive_endpoint():
            ...
    """
    return limiter.limit(limit)


def exempt_from_rate_limit():
    """
    Exempt an endpoint from rate limiting.

    Returns:
        Decorator function.

    Example:
        @exempt_from_rate_limit()
        def internal_endpoint():
            ...
    """
    return limiter.exempt


def get_rate_limit_key() -> str:
    """
    Get the rate limit key for the current request.

    By default, uses the remote IP address. Can be extended
    to use user ID for authenticated requests.

    Returns:
        Key string for rate limiting.
    """
    # If user is authenticated, use user_id as part of the key
    user_id = getattr(g, "user_id", None)
    if user_id:
        return f"user:{user_id}"

    # Fall back to IP address
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()

    return request.remote_addr or "unknown"


def rate_limit_by_user(limit: str = RateLimits.DEFAULT):
    """
    Apply rate limiting by user (if authenticated) or IP.

    Args:
        limit: Rate limit string.

    Returns:
        Decorator function.
    """
    return limiter.limit(limit, key_func=get_rate_limit_key)


def handle_rate_limit_exceeded(e):
    """
    Error handler for rate limit exceeded.

    Args:
        e: The rate limit exception.

    Returns:
        JSON error response with 429 status.
    """
    logger.warning(
        f"Rate limit exceeded: {request.remote_addr} - {request.path}"
    )

    # Get the retry-after header if available
    retry_after = getattr(e, "retry_after", None)

    response = {
        "code": "RATE_LIMIT_EXCEEDED",
        "message": "Too many requests. Please slow down.",
        "details": {
            "limit": str(e.description) if hasattr(e, "description") else None,
            "retry_after": retry_after,
        },
        "trace_id": None,
    }

    resp = jsonify(response)
    resp.status_code = 429

    # Add rate limit headers
    if retry_after:
        resp.headers["Retry-After"] = str(retry_after)

    return resp


def add_rate_limit_headers(response):
    """
    Add rate limit headers to response.

    This is typically called as an after_request handler.

    Args:
        response: Flask response object.

    Returns:
        Response with added headers.
    """
    # Get current rate limit info from limiter
    try:
        limit_info = getattr(g, "_rate_limiting_complete", None)
        if limit_info:
            response.headers["X-RateLimit-Limit"] = str(limit_info.get("limit", ""))
            response.headers["X-RateLimit-Remaining"] = str(limit_info.get("remaining", ""))
            response.headers["X-RateLimit-Reset"] = str(limit_info.get("reset", ""))
    except Exception:
        pass  # Don't fail if we can't add headers

    return response


def check_rate_limit_bypass() -> bool:
    """
    Check if the current request should bypass rate limiting.

    Useful for internal/admin requests or during testing.

    Returns:
        True if rate limiting should be bypassed.
    """
    # Check for bypass header (for internal services)
    bypass_key = current_app.config.get("RATE_LIMIT_BYPASS_KEY")
    if bypass_key:
        request_key = request.headers.get("X-RateLimit-Bypass")
        if request_key == bypass_key:
            return True

    # Check if rate limiting is disabled
    if not current_app.config.get("RATE_LIMIT_ENABLED", True):
        return True

    return False


def conditional_rate_limit(limit: str = RateLimits.DEFAULT):
    """
    Apply rate limiting only if not bypassed.

    Args:
        limit: Rate limit string.

    Returns:
        Decorator function.

    Example:
        @conditional_rate_limit("10/minute")
        def endpoint():
            ...
    """
    def decorator(f: Callable) -> Callable:
        # Apply the limiter decorator
        limited_f = limiter.limit(limit)(f)

        @wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if check_rate_limit_bypass():
                return f(*args, **kwargs)
            return limited_f(*args, **kwargs)

        return wrapper

    return decorator


# Export commonly used items
__all__ = [
    "RateLimits",
    "rate_limit",
    "rate_limit_by_user",
    "exempt_from_rate_limit",
    "conditional_rate_limit",
    "handle_rate_limit_exceeded",
    "add_rate_limit_headers",
    "get_rate_limit_key",
    "check_rate_limit_bypass",
    "limiter",
]
