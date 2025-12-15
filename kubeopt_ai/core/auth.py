"""
Authentication service for KubeOpt AI.

Provides user authentication, JWT token management, and authorization utilities.
"""

import hashlib
import logging
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

import bcrypt
from flask import current_app, request
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    get_jwt,
    get_jwt_identity,
)

from kubeopt_ai.core.models import (
    User,
    Team,
    Role,
    Permission,
    TeamMembership,
    RefreshToken,
    UserStatus,
    TeamStatus,
)
from kubeopt_ai.extensions import db

logger = logging.getLogger(__name__)


class AuthError(Exception):
    """Base exception for authentication errors."""

    def __init__(self, message: str, code: str = "AUTH_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class InvalidCredentialsError(AuthError):
    """Raised when login credentials are invalid."""

    def __init__(self, message: str = "Invalid email or password"):
        super().__init__(message, "INVALID_CREDENTIALS")


class UserNotFoundError(AuthError):
    """Raised when user is not found."""

    def __init__(self, message: str = "User not found"):
        super().__init__(message, "USER_NOT_FOUND")


class UserInactiveError(AuthError):
    """Raised when user account is not active."""

    def __init__(self, message: str = "User account is not active"):
        super().__init__(message, "USER_INACTIVE")


class TokenError(AuthError):
    """Raised when token operations fail."""

    def __init__(self, message: str = "Token operation failed"):
        super().__init__(message, "TOKEN_ERROR")


class PermissionDeniedError(AuthError):
    """Raised when user lacks required permission."""

    def __init__(self, message: str = "Permission denied"):
        super().__init__(message, "PERMISSION_DENIED")


class AuthService:
    """
    Service for handling authentication operations.

    Provides methods for user login, logout, token refresh, and password management.
    """

    def __init__(self):
        """Initialize the auth service."""
        pass

    def hash_password(self, password: str) -> str:
        """
        Hash a password using bcrypt.

        Args:
            password: Plain text password

        Returns:
            Hashed password string
        """
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

    def verify_password(self, password: str, password_hash: str) -> bool:
        """
        Verify a password against its hash.

        Args:
            password: Plain text password
            password_hash: Stored password hash

        Returns:
            True if password matches, False otherwise
        """
        try:
            return bcrypt.checkpw(
                password.encode("utf-8"),
                password_hash.encode("utf-8")
            )
        except Exception:
            return False

    def login(
        self,
        email: str,
        password: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Tuple[str, str, User]:
        """
        Authenticate user and generate tokens.

        Args:
            email: User email
            password: User password
            ip_address: Client IP address (optional)
            user_agent: Client user agent (optional)

        Returns:
            Tuple of (access_token, refresh_token, user)

        Raises:
            InvalidCredentialsError: If credentials are invalid
            UserInactiveError: If user account is not active
        """
        # Find user by email
        user = User.query.filter_by(email=email.lower()).first()

        if not user:
            logger.warning(f"Login attempt for non-existent user: {email}")
            raise InvalidCredentialsError()

        # Verify password
        if not self.verify_password(password, user.password_hash):
            logger.warning(f"Invalid password for user: {email}")
            raise InvalidCredentialsError()

        # Check user status
        if user.status != UserStatus.ACTIVE:
            logger.warning(f"Login attempt for inactive user: {email}")
            raise UserInactiveError(f"User account is {user.status.value}")

        # Generate tokens
        access_token = create_access_token(
            identity=user,
            additional_claims={
                "email": user.email,
                "is_superuser": user.is_superuser,
            }
        )

        refresh_token = self._create_refresh_token(
            user,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # Update last login timestamp
        user.last_login_at = datetime.now(timezone.utc)
        db.session.commit()

        logger.info(f"User logged in: {email}")
        return access_token, refresh_token, user

    def _create_refresh_token(
        self,
        user: User,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> str:
        """
        Create and store a refresh token for a user.

        Args:
            user: User to create token for
            ip_address: Client IP address
            user_agent: Client user agent

        Returns:
            Refresh token string
        """
        # Generate unique token identifier
        jti = secrets.token_urlsafe(32)

        # Create JWT refresh token
        refresh_token = create_refresh_token(
            identity=user,
            additional_claims={"jti": jti}
        )

        # Calculate expiration
        expires_delta = current_app.config.get(
            "JWT_REFRESH_TOKEN_EXPIRES",
            timedelta(days=7)
        )
        expires_at = datetime.now(timezone.utc) + expires_delta

        # Store token hash in database
        token_hash = hashlib.sha256(jti.encode()).hexdigest()
        token_record = RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.session.add(token_record)
        db.session.commit()

        return refresh_token

    def refresh_tokens(
        self,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Refresh access and refresh tokens.

        Must be called within a request context with a valid refresh token.

        Args:
            ip_address: Client IP address
            user_agent: Client user agent

        Returns:
            Tuple of (new_access_token, new_refresh_token)

        Raises:
            TokenError: If refresh fails
        """
        # Get current user from refresh token
        user_id = get_jwt_identity()
        user = db.session.get(User, user_id)

        if not user:
            raise TokenError("User not found")

        if user.status != UserStatus.ACTIVE:
            raise UserInactiveError()

        # Revoke old refresh token
        jwt_data = get_jwt()
        old_jti = jwt_data.get("jti")
        if old_jti:
            old_token_hash = hashlib.sha256(old_jti.encode()).hexdigest()
            old_token = RefreshToken.query.filter_by(token_hash=old_token_hash).first()
            if old_token:
                old_token.revoked = True
                old_token.revoked_at = datetime.now(timezone.utc)

        # Generate new tokens
        access_token = create_access_token(
            identity=user,
            additional_claims={
                "email": user.email,
                "is_superuser": user.is_superuser,
            }
        )

        refresh_token = self._create_refresh_token(
            user,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        db.session.commit()
        logger.info(f"Tokens refreshed for user: {user.email}")
        return access_token, refresh_token

    def logout(self, revoke_all: bool = False) -> None:
        """
        Logout user by revoking tokens.

        Must be called within a request context with a valid token.

        Args:
            revoke_all: If True, revoke all refresh tokens for the user
        """
        user_id = get_jwt_identity()

        if revoke_all:
            # Revoke all refresh tokens for the user
            RefreshToken.query.filter_by(user_id=user_id, revoked=False).update({
                "revoked": True,
                "revoked_at": datetime.now(timezone.utc)
            })
        else:
            # Revoke only the current refresh token
            jwt_data = get_jwt()
            jti = jwt_data.get("jti")
            if jti:
                token_hash = hashlib.sha256(jti.encode()).hexdigest()
                token = RefreshToken.query.filter_by(token_hash=token_hash).first()
                if token:
                    token.revoked = True
                    token.revoked_at = datetime.now(timezone.utc)

        db.session.commit()
        logger.info(f"User logged out: {user_id} (revoke_all={revoke_all})")

    def create_user(
        self,
        email: str,
        password: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        is_superuser: bool = False,
        status: UserStatus = UserStatus.ACTIVE,
    ) -> User:
        """
        Create a new user.

        Args:
            email: User email address
            password: User password
            first_name: User first name
            last_name: User last name
            is_superuser: Whether user is a superuser
            status: Initial user status

        Returns:
            Created User object

        Raises:
            ValueError: If email already exists or password is invalid
        """
        # Validate email uniqueness
        if User.query.filter_by(email=email.lower()).first():
            raise ValueError(f"User with email '{email}' already exists")

        # Validate password length
        min_length = current_app.config.get("AUTH_PASSWORD_MIN_LENGTH", 8)
        if len(password) < min_length:
            raise ValueError(f"Password must be at least {min_length} characters")

        # Create user
        user = User(
            email=email.lower(),
            password_hash=self.hash_password(password),
            first_name=first_name,
            last_name=last_name,
            is_superuser=is_superuser,
            status=status,
        )
        db.session.add(user)
        db.session.commit()

        logger.info(f"Created user: {email}")
        return user

    def update_password(self, user: User, new_password: str) -> None:
        """
        Update a user's password.

        Args:
            user: User to update
            new_password: New password

        Raises:
            ValueError: If password is invalid
        """
        min_length = current_app.config.get("AUTH_PASSWORD_MIN_LENGTH", 8)
        if len(new_password) < min_length:
            raise ValueError(f"Password must be at least {min_length} characters")

        user.password_hash = self.hash_password(new_password)
        user.updated_at = datetime.now(timezone.utc)
        db.session.commit()

        logger.info(f"Password updated for user: {user.email}")

    def get_user_by_id(self, user_id: str) -> Optional[User]:
        """Get user by ID."""
        return db.session.get(User, user_id)

    def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        return User.query.filter_by(email=email.lower()).first()


class TeamService:
    """
    Service for managing teams and memberships.
    """

    def create_team(
        self,
        name: str,
        slug: str,
        description: Optional[str] = None,
        settings: Optional[dict] = None,
    ) -> Team:
        """
        Create a new team.

        Args:
            name: Team display name
            slug: URL-safe team identifier
            description: Team description
            settings: Team settings

        Returns:
            Created Team object

        Raises:
            ValueError: If slug already exists
        """
        if Team.query.filter_by(slug=slug).first():
            raise ValueError(f"Team with slug '{slug}' already exists")

        team = Team(
            name=name,
            slug=slug,
            description=description,
            settings=settings or {},
        )
        db.session.add(team)
        db.session.commit()

        logger.info(f"Created team: {name} ({slug})")
        return team

    def add_member(
        self,
        team: Team,
        user: User,
        role: Role,
    ) -> TeamMembership:
        """
        Add a user to a team with a role.

        Args:
            team: Team to add user to
            user: User to add
            role: Role to assign

        Returns:
            Created TeamMembership object

        Raises:
            ValueError: If user is already a member
        """
        existing = TeamMembership.query.filter_by(
            team_id=team.id,
            user_id=user.id
        ).first()

        if existing:
            raise ValueError(f"User '{user.email}' is already a member of team '{team.name}'")

        membership = TeamMembership(
            team_id=team.id,
            user_id=user.id,
            role_id=role.id,
        )
        db.session.add(membership)
        db.session.commit()

        logger.info(f"Added {user.email} to team {team.name} with role {role.name}")
        return membership

    def remove_member(self, team: Team, user: User) -> None:
        """
        Remove a user from a team.

        Args:
            team: Team to remove user from
            user: User to remove
        """
        membership = TeamMembership.query.filter_by(
            team_id=team.id,
            user_id=user.id
        ).first()

        if membership:
            db.session.delete(membership)
            db.session.commit()
            logger.info(f"Removed {user.email} from team {team.name}")

    def update_member_role(self, team: Team, user: User, new_role: Role) -> TeamMembership:
        """
        Update a member's role in a team.

        Args:
            team: Team
            user: User
            new_role: New role to assign

        Returns:
            Updated TeamMembership

        Raises:
            ValueError: If user is not a member
        """
        membership = TeamMembership.query.filter_by(
            team_id=team.id,
            user_id=user.id
        ).first()

        if not membership:
            raise ValueError(f"User '{user.email}' is not a member of team '{team.name}'")

        membership.role_id = new_role.id
        db.session.commit()

        logger.info(f"Updated role for {user.email} in {team.name} to {new_role.name}")
        return membership

    def get_team_by_id(self, team_id: str) -> Optional[Team]:
        """Get team by ID."""
        return db.session.get(Team, team_id)

    def get_team_by_slug(self, slug: str) -> Optional[Team]:
        """Get team by slug."""
        return Team.query.filter_by(slug=slug).first()


class RoleService:
    """
    Service for managing roles and permissions.
    """

    def get_role_by_id(self, role_id: str) -> Optional[Role]:
        """Get role by ID."""
        return db.session.get(Role, role_id)

    def get_role_by_name(self, name: str) -> Optional[Role]:
        """Get role by name."""
        return Role.query.filter_by(name=name).first()

    def get_default_roles(self) -> list[Role]:
        """Get all system roles."""
        return Role.query.filter_by(is_system_role=True).all()

    def create_role(
        self,
        name: str,
        description: Optional[str] = None,
        permissions: Optional[list[Permission]] = None,
        is_system_role: bool = False,
    ) -> Role:
        """
        Create a new role.

        Args:
            name: Role name
            description: Role description
            permissions: List of permissions to assign
            is_system_role: Whether this is a system role

        Returns:
            Created Role object
        """
        if Role.query.filter_by(name=name).first():
            raise ValueError(f"Role '{name}' already exists")

        role = Role(
            name=name,
            description=description,
            is_system_role=is_system_role,
        )

        if permissions:
            role.permissions = permissions

        db.session.add(role)
        db.session.commit()

        logger.info(f"Created role: {name}")
        return role

    def get_permission_by_name(self, name: str) -> Optional[Permission]:
        """Get permission by name."""
        return Permission.query.filter_by(name=name).first()

    def get_permission(self, resource: str, action: str) -> Optional[Permission]:
        """Get permission by resource and action."""
        return Permission.query.filter_by(resource=resource, action=action).first()


# Service singletons
_auth_service: Optional[AuthService] = None
_team_service: Optional[TeamService] = None
_role_service: Optional[RoleService] = None


def get_auth_service() -> AuthService:
    """Get or create the AuthService singleton."""
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service


def get_team_service() -> TeamService:
    """Get or create the TeamService singleton."""
    global _team_service
    if _team_service is None:
        _team_service = TeamService()
    return _team_service


def get_role_service() -> RoleService:
    """Get or create the RoleService singleton."""
    global _role_service
    if _role_service is None:
        _role_service = RoleService()
    return _role_service
