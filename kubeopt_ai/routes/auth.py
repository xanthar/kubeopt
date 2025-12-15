"""
Authentication API endpoints for KubeOpt AI.

Provides endpoints for user authentication, token management,
and basic user/team management.
"""

import logging
from typing import Optional

from flask import Blueprint, jsonify, request, g
from flask_jwt_extended import jwt_required
from pydantic import BaseModel, Field, EmailStr, field_validator, ValidationError

from kubeopt_ai.core.auth import (
    get_auth_service,
    get_team_service,
    get_role_service,
    AuthError,
    InvalidCredentialsError,
    UserInactiveError,
    TokenError,
)
from kubeopt_ai.core.decorators import (
    auth_required,
    require_permission,
    require_superuser,
    require_team_membership,
    get_current_user,
)
from kubeopt_ai.core.models import User, Team, Role, UserStatus, TeamStatus
from kubeopt_ai.extensions import db

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)


# Request/Response Schemas

class LoginRequest(BaseModel):
    """Login request schema."""
    email: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class RefreshRequest(BaseModel):
    """Token refresh request schema."""
    pass  # No body needed, uses refresh token from header


class RegisterRequest(BaseModel):
    """User registration request schema."""
    email: str = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)

    @field_validator('email')
    @classmethod
    def validate_email(cls, v):
        if '@' not in v:
            raise ValueError('Invalid email format')
        return v.lower()


class UpdateUserRequest(BaseModel):
    """Update user request schema."""
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    status: Optional[str] = Field(None)


class ChangePasswordRequest(BaseModel):
    """Change password request schema."""
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=128)


class CreateTeamRequest(BaseModel):
    """Create team request schema."""
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r'^[a-z0-9-]+$')
    description: Optional[str] = Field(None, max_length=1000)


class AddTeamMemberRequest(BaseModel):
    """Add team member request schema."""
    user_id: str = Field(..., min_length=1)
    role_id: str = Field(..., min_length=1)


class UpdateMemberRoleRequest(BaseModel):
    """Update member role request schema."""
    role_id: str = Field(..., min_length=1)


# Authentication Endpoints

@auth_bp.route("/api/v1/auth/login", methods=["POST"])
def login():
    """
    Authenticate user and return JWT tokens.

    Request Body:
        email: User email
        password: User password

    Returns:
        access_token: JWT access token
        refresh_token: JWT refresh token
        user: User information
    """
    try:
        data = LoginRequest.model_validate(request.json)
    except ValidationError as e:
        return jsonify({
            "code": "VALIDATION_ERROR",
            "message": "Invalid request data",
            "details": e.errors(),
        }), 400

    auth_service = get_auth_service()

    try:
        access_token, refresh_token, user = auth_service.login(
            email=data.email,
            password=data.password,
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string if request.user_agent else None,
        )
    except InvalidCredentialsError as e:
        return jsonify({
            "code": e.code,
            "message": e.message,
        }), 401
    except UserInactiveError as e:
        return jsonify({
            "code": e.code,
            "message": e.message,
        }), 403
    except AuthError as e:
        return jsonify({
            "code": e.code,
            "message": e.message,
        }), 400

    return jsonify({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "user": user.to_dict(),
    }), 200


@auth_bp.route("/api/v1/auth/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    """
    Refresh access token using refresh token.

    Headers:
        Authorization: Bearer <refresh_token>

    Returns:
        access_token: New JWT access token
        refresh_token: New JWT refresh token
    """
    auth_service = get_auth_service()

    try:
        access_token, refresh_token = auth_service.refresh_tokens(
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string if request.user_agent else None,
        )
    except (TokenError, UserInactiveError) as e:
        return jsonify({
            "code": e.code,
            "message": e.message,
        }), 401

    return jsonify({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
    }), 200


@auth_bp.route("/api/v1/auth/logout", methods=["POST"])
@auth_required()
def logout():
    """
    Logout user and revoke current token.

    Query Parameters:
        all: If "true", revoke all refresh tokens for the user

    Returns:
        Success message
    """
    revoke_all = request.args.get("all", "").lower() == "true"

    auth_service = get_auth_service()
    auth_service.logout(revoke_all=revoke_all)

    return jsonify({
        "message": "Logged out successfully",
    }), 200


@auth_bp.route("/api/v1/auth/me", methods=["GET"])
@auth_required()
def get_current_user_info():
    """
    Get current authenticated user information.

    Returns:
        User information with team memberships
    """
    user = get_current_user()
    return jsonify(user.to_dict(include_teams=True)), 200


@auth_bp.route("/api/v1/auth/me/password", methods=["PUT"])
@auth_required()
def change_password():
    """
    Change current user's password.

    Request Body:
        current_password: Current password
        new_password: New password

    Returns:
        Success message
    """
    try:
        data = ChangePasswordRequest.model_validate(request.json)
    except ValidationError as e:
        return jsonify({
            "code": "VALIDATION_ERROR",
            "message": "Invalid request data",
            "details": e.errors(),
        }), 400

    user = get_current_user()
    auth_service = get_auth_service()

    # Verify current password
    if not auth_service.verify_password(data.current_password, user.password_hash):
        return jsonify({
            "code": "INVALID_PASSWORD",
            "message": "Current password is incorrect",
        }), 400

    try:
        auth_service.update_password(user, data.new_password)
    except ValueError as e:
        return jsonify({
            "code": "VALIDATION_ERROR",
            "message": str(e),
        }), 400

    return jsonify({
        "message": "Password changed successfully",
    }), 200


# User Management Endpoints (Admin)

@auth_bp.route("/api/v1/users", methods=["GET"])
@auth_required()
@require_superuser()
def list_users():
    """
    List all users (superuser only).

    Query Parameters:
        status: Filter by status
        limit: Maximum results (default 50)
        offset: Pagination offset

    Returns:
        List of users with pagination
    """
    status = request.args.get("status")
    limit = min(int(request.args.get("limit", 50)), 100)
    offset = int(request.args.get("offset", 0))

    query = User.query

    if status:
        try:
            query = query.filter_by(status=UserStatus(status))
        except ValueError:
            return jsonify({
                "code": "INVALID_STATUS",
                "message": f"Invalid status: {status}",
            }), 400

    total = query.count()
    users = query.offset(offset).limit(limit).all()

    return jsonify({
        "users": [u.to_dict() for u in users],
        "pagination": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": (offset + len(users)) < total,
        },
    }), 200


@auth_bp.route("/api/v1/users", methods=["POST"])
@auth_required()
@require_superuser()
def create_user():
    """
    Create a new user (superuser only).

    Request Body:
        email: User email
        password: User password
        first_name: First name (optional)
        last_name: Last name (optional)

    Returns:
        Created user information
    """
    try:
        data = RegisterRequest.model_validate(request.json)
    except ValidationError as e:
        return jsonify({
            "code": "VALIDATION_ERROR",
            "message": "Invalid request data",
            "details": e.errors(),
        }), 400

    auth_service = get_auth_service()

    try:
        user = auth_service.create_user(
            email=data.email,
            password=data.password,
            first_name=data.first_name,
            last_name=data.last_name,
        )
    except ValueError as e:
        return jsonify({
            "code": "VALIDATION_ERROR",
            "message": str(e),
        }), 400

    return jsonify(user.to_dict()), 201


@auth_bp.route("/api/v1/users/<user_id>", methods=["GET"])
@auth_required()
@require_superuser()
def get_user(user_id: str):
    """
    Get user by ID (superuser only).

    Returns:
        User information with team memberships
    """
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"User '{user_id}' not found",
        }), 404

    return jsonify(user.to_dict(include_teams=True)), 200


@auth_bp.route("/api/v1/users/<user_id>", methods=["PATCH"])
@auth_required()
@require_superuser()
def update_user(user_id: str):
    """
    Update user (superuser only).

    Request Body:
        first_name: First name (optional)
        last_name: Last name (optional)
        status: User status (optional)

    Returns:
        Updated user information
    """
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"User '{user_id}' not found",
        }), 404

    try:
        data = UpdateUserRequest.model_validate(request.json)
    except ValidationError as e:
        return jsonify({
            "code": "VALIDATION_ERROR",
            "message": "Invalid request data",
            "details": e.errors(),
        }), 400

    if data.first_name is not None:
        user.first_name = data.first_name
    if data.last_name is not None:
        user.last_name = data.last_name
    if data.status is not None:
        try:
            user.status = UserStatus(data.status)
        except ValueError:
            return jsonify({
                "code": "INVALID_STATUS",
                "message": f"Invalid status: {data.status}",
            }), 400

    db.session.commit()
    return jsonify(user.to_dict()), 200


# Team Management Endpoints

@auth_bp.route("/api/v1/teams", methods=["GET"])
@auth_required()
def list_teams():
    """
    List teams the current user belongs to.

    Superusers can see all teams.

    Returns:
        List of teams
    """
    user = get_current_user()

    if user.is_superuser:
        teams = Team.query.filter_by(status=TeamStatus.ACTIVE).all()
    else:
        teams = user.get_teams()

    return jsonify({
        "teams": [t.to_dict() for t in teams],
    }), 200


@auth_bp.route("/api/v1/teams", methods=["POST"])
@auth_required()
@require_superuser()
def create_team():
    """
    Create a new team (superuser only).

    Request Body:
        name: Team name
        slug: URL-safe identifier
        description: Description (optional)

    Returns:
        Created team information
    """
    try:
        data = CreateTeamRequest.model_validate(request.json)
    except ValidationError as e:
        return jsonify({
            "code": "VALIDATION_ERROR",
            "message": "Invalid request data",
            "details": e.errors(),
        }), 400

    team_service = get_team_service()

    try:
        team = team_service.create_team(
            name=data.name,
            slug=data.slug,
            description=data.description,
        )
    except ValueError as e:
        return jsonify({
            "code": "VALIDATION_ERROR",
            "message": str(e),
        }), 400

    return jsonify(team.to_dict()), 201


@auth_bp.route("/api/v1/teams/<team_id>", methods=["GET"])
@auth_required()
@require_team_membership(team_param="team_id")
def get_team(team_id: str):
    """
    Get team by ID.

    Requires team membership or superuser status.

    Returns:
        Team information with members
    """
    team = g.current_team
    return jsonify(team.to_dict(include_members=True)), 200


@auth_bp.route("/api/v1/teams/<team_id>/members", methods=["GET"])
@auth_required()
@require_team_membership(team_param="team_id")
def list_team_members(team_id: str):
    """
    List members of a team.

    Returns:
        List of team members with roles
    """
    team = g.current_team
    members = [m.to_dict() for m in team.memberships]

    # Add user details
    for member in members:
        user = db.session.get(User, member["user_id"])
        if user:
            member["user_email"] = user.email
            member["user_name"] = user.full_name

    return jsonify({
        "members": members,
    }), 200


@auth_bp.route("/api/v1/teams/<team_id>/members", methods=["POST"])
@auth_required()
@require_permission("team", "manage_members", team_param="team_id")
def add_team_member(team_id: str):
    """
    Add a member to a team.

    Requires team management permission.

    Request Body:
        user_id: User ID to add
        role_id: Role ID to assign

    Returns:
        Created membership information
    """
    try:
        data = AddTeamMemberRequest.model_validate(request.json)
    except ValidationError as e:
        return jsonify({
            "code": "VALIDATION_ERROR",
            "message": "Invalid request data",
            "details": e.errors(),
        }), 400

    team = g.current_team
    user = db.session.get(User, data.user_id)
    role = db.session.get(Role, data.role_id)

    if not user:
        return jsonify({
            "code": "USER_NOT_FOUND",
            "message": f"User '{data.user_id}' not found",
        }), 404

    if not role:
        return jsonify({
            "code": "ROLE_NOT_FOUND",
            "message": f"Role '{data.role_id}' not found",
        }), 404

    team_service = get_team_service()

    try:
        membership = team_service.add_member(team, user, role)
    except ValueError as e:
        return jsonify({
            "code": "VALIDATION_ERROR",
            "message": str(e),
        }), 400

    return jsonify(membership.to_dict()), 201


@auth_bp.route("/api/v1/teams/<team_id>/members/<user_id>", methods=["DELETE"])
@auth_required()
@require_permission("team", "manage_members", team_param="team_id")
def remove_team_member(team_id: str, user_id: str):
    """
    Remove a member from a team.

    Requires team management permission.

    Returns:
        Success message
    """
    team = g.current_team
    user = db.session.get(User, user_id)

    if not user:
        return jsonify({
            "code": "USER_NOT_FOUND",
            "message": f"User '{user_id}' not found",
        }), 404

    team_service = get_team_service()
    team_service.remove_member(team, user)

    return jsonify({
        "message": "Member removed successfully",
    }), 200


@auth_bp.route("/api/v1/teams/<team_id>/members/<user_id>/role", methods=["PUT"])
@auth_required()
@require_permission("team", "manage_members", team_param="team_id")
def update_member_role(team_id: str, user_id: str):
    """
    Update a member's role in a team.

    Requires team management permission.

    Request Body:
        role_id: New role ID

    Returns:
        Updated membership information
    """
    try:
        data = UpdateMemberRoleRequest.model_validate(request.json)
    except ValidationError as e:
        return jsonify({
            "code": "VALIDATION_ERROR",
            "message": "Invalid request data",
            "details": e.errors(),
        }), 400

    team = g.current_team
    user = db.session.get(User, user_id)
    role = db.session.get(Role, data.role_id)

    if not user:
        return jsonify({
            "code": "USER_NOT_FOUND",
            "message": f"User '{user_id}' not found",
        }), 404

    if not role:
        return jsonify({
            "code": "ROLE_NOT_FOUND",
            "message": f"Role '{data.role_id}' not found",
        }), 404

    team_service = get_team_service()

    try:
        membership = team_service.update_member_role(team, user, role)
    except ValueError as e:
        return jsonify({
            "code": "VALIDATION_ERROR",
            "message": str(e),
        }), 400

    return jsonify(membership.to_dict()), 200


# Role Management Endpoints

@auth_bp.route("/api/v1/roles", methods=["GET"])
@auth_required()
def list_roles():
    """
    List available roles.

    Returns:
        List of roles with permissions
    """
    roles = Role.query.all()
    return jsonify({
        "roles": [r.to_dict(include_permissions=True) for r in roles],
    }), 200


@auth_bp.route("/api/v1/roles/<role_id>", methods=["GET"])
@auth_required()
def get_role(role_id: str):
    """
    Get role by ID.

    Returns:
        Role information with permissions
    """
    role = db.session.get(Role, role_id)
    if not role:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Role '{role_id}' not found",
        }), 404

    return jsonify(role.to_dict(include_permissions=True)), 200
