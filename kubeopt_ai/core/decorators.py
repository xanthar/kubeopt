"""
Authentication and authorization decorators for KubeOpt AI.

Provides decorators for protecting API endpoints with JWT authentication
and permission-based access control.
"""

import functools
import logging
from typing import Callable, Optional

from flask import current_app, g, request, jsonify
from flask_jwt_extended import (
    get_jwt_identity,
    verify_jwt_in_request,
)

from kubeopt_ai.core.models import User, Team, UserStatus
from kubeopt_ai.extensions import db

logger = logging.getLogger(__name__)


def auth_required(
    optional: bool = False,
    fresh: bool = False,
    refresh: bool = False,
):
    """
    Decorator to require JWT authentication on an endpoint.

    This wraps flask-jwt-extended's jwt_required with additional features:
    - Sets g.current_user for easy access to the authenticated user
    - Respects AUTH_ENABLED config setting
    - Provides consistent error handling

    Args:
        optional: If True, authentication is optional (user may be None)
        fresh: If True, requires a fresh token (recently issued)
        refresh: If True, requires a refresh token instead of access token

    Usage:
        @app.route('/protected')
        @auth_required()
        def protected_route():
            user = g.current_user
            return jsonify({"user": user.email})

        @app.route('/optional-auth')
        @auth_required(optional=True)
        def optional_auth_route():
            if g.current_user:
                return jsonify({"user": g.current_user.email})
            return jsonify({"user": None})
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            # Check if auth is enabled
            if not current_app.config.get("AUTH_ENABLED", True):
                g.current_user = None
                return fn(*args, **kwargs)

            # Verify JWT
            try:
                verify_jwt_in_request(optional=optional, fresh=fresh, refresh=refresh)
            except Exception:
                if optional:
                    g.current_user = None
                    return fn(*args, **kwargs)
                raise

            # Load user
            user_id = get_jwt_identity()
            if user_id:
                user = db.session.get(User, user_id)
                if user and user.status == UserStatus.ACTIVE:
                    g.current_user = user
                elif user:
                    return jsonify({
                        "code": "USER_INACTIVE",
                        "message": f"User account is {user.status.value}",
                    }), 403
                else:
                    g.current_user = None
                    if not optional:
                        return jsonify({
                            "code": "USER_NOT_FOUND",
                            "message": "User not found",
                        }), 401
            else:
                g.current_user = None

            return fn(*args, **kwargs)
        return wrapper
    return decorator


def require_permission(
    resource: str,
    action: str,
    team_param: Optional[str] = None,
    team_header: Optional[str] = "X-Team-ID",
):
    """
    Decorator to require a specific permission on an endpoint.

    Checks if the current user has the required permission within the
    specified team context. Superusers bypass permission checks.

    Args:
        resource: Resource type (e.g., "optimization", "webhook", "team")
        action: Action type (e.g., "create", "read", "update", "delete")
        team_param: Name of URL parameter containing team ID (optional)
        team_header: Name of request header containing team ID (optional)

    Usage:
        @app.route('/optimization', methods=['POST'])
        @auth_required()
        @require_permission('optimization', 'create')
        def create_optimization():
            # User has permission to create optimizations in the team
            pass

        @app.route('/teams/<team_id>/settings', methods=['PUT'])
        @auth_required()
        @require_permission('team', 'update', team_param='team_id')
        def update_team_settings(team_id):
            # User has permission to update team settings
            pass
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            # Check if auth is enabled
            if not current_app.config.get("AUTH_ENABLED", True):
                return fn(*args, **kwargs)

            user = getattr(g, 'current_user', None)

            if not user:
                return jsonify({
                    "code": "UNAUTHORIZED",
                    "message": "Authentication required",
                }), 401

            # Superusers bypass permission checks
            if user.is_superuser:
                return fn(*args, **kwargs)

            # Determine team context
            team_id = None

            if team_param and team_param in kwargs:
                team_id = kwargs[team_param]
            elif team_header:
                team_id = request.headers.get(team_header)

            if not team_id:
                # Try to get team from query params or JSON body
                team_id = request.args.get("team_id")
                if not team_id and request.is_json:
                    team_id = request.json.get("team_id") if request.json else None

            if not team_id:
                return jsonify({
                    "code": "TEAM_REQUIRED",
                    "message": "Team context is required for this operation",
                }), 400

            # Store team context in g for use by the route
            team = db.session.get(Team, team_id)
            if not team:
                return jsonify({
                    "code": "TEAM_NOT_FOUND",
                    "message": f"Team '{team_id}' not found",
                }), 404

            g.current_team = team

            # Check permission
            if not user.has_permission_in_team(team_id, resource, action):
                logger.warning(
                    f"Permission denied: user={user.email} team={team_id} "
                    f"resource={resource} action={action}"
                )
                return jsonify({
                    "code": "PERMISSION_DENIED",
                    "message": f"You don't have permission to {action} {resource}",
                }), 403

            return fn(*args, **kwargs)
        return wrapper
    return decorator


def require_superuser():
    """
    Decorator to require superuser status.

    Usage:
        @app.route('/admin/users')
        @auth_required()
        @require_superuser()
        def admin_users():
            # Only superusers can access
            pass
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            # Check if auth is enabled
            if not current_app.config.get("AUTH_ENABLED", True):
                return fn(*args, **kwargs)

            user = getattr(g, 'current_user', None)

            if not user:
                return jsonify({
                    "code": "UNAUTHORIZED",
                    "message": "Authentication required",
                }), 401

            if not user.is_superuser:
                return jsonify({
                    "code": "SUPERUSER_REQUIRED",
                    "message": "Superuser access required",
                }), 403

            return fn(*args, **kwargs)
        return wrapper
    return decorator


def require_team_membership(team_param: str = "team_id"):
    """
    Decorator to require membership in a team.

    Ensures the user is a member of the specified team before allowing access.
    Superusers bypass this check.

    Args:
        team_param: Name of URL parameter or header containing team ID

    Usage:
        @app.route('/teams/<team_id>/data')
        @auth_required()
        @require_team_membership()
        def get_team_data(team_id):
            # User is a member of the team
            pass
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            # Check if auth is enabled
            if not current_app.config.get("AUTH_ENABLED", True):
                return fn(*args, **kwargs)

            user = getattr(g, 'current_user', None)

            if not user:
                return jsonify({
                    "code": "UNAUTHORIZED",
                    "message": "Authentication required",
                }), 401

            # Superusers can access any team
            if user.is_superuser:
                return fn(*args, **kwargs)

            # Get team ID from kwargs, headers, or query params
            team_id = kwargs.get(team_param)
            if not team_id:
                team_id = request.headers.get("X-Team-ID")
            if not team_id:
                team_id = request.args.get("team_id")

            if not team_id:
                return jsonify({
                    "code": "TEAM_REQUIRED",
                    "message": "Team ID is required",
                }), 400

            # Check membership
            membership = user.team_memberships.filter_by(team_id=team_id).first()
            if not membership:
                return jsonify({
                    "code": "NOT_TEAM_MEMBER",
                    "message": "You are not a member of this team",
                }), 403

            # Store team and role in g
            g.current_team = membership.team
            g.current_role = membership.role

            return fn(*args, **kwargs)
        return wrapper
    return decorator


def get_current_user() -> Optional[User]:
    """
    Get the current authenticated user.

    Returns:
        User object or None if not authenticated
    """
    return getattr(g, 'current_user', None)


def get_current_team() -> Optional[Team]:
    """
    Get the current team context.

    Returns:
        Team object or None if no team context
    """
    return getattr(g, 'current_team', None)
