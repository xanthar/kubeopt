"""Add RBAC and multi-tenancy tables

Revision ID: 002_add_rbac_tables
Revises: 001_add_audit_logs
Create Date: 2025-12-15

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '002_add_rbac_tables'
down_revision = '001_add_audit_logs'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create RBAC and multi-tenancy tables."""

    # Create permissions table
    op.create_table(
        'permissions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('resource', sa.String(length=100), nullable=False),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
        sa.UniqueConstraint('resource', 'action', name='uq_permission_resource_action')
    )
    op.create_index('ix_permissions_resource', 'permissions', ['resource'])
    op.create_index('ix_permissions_action', 'permissions', ['action'])

    # Create roles table
    op.create_table(
        'roles',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('is_system_role', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_index('ix_roles_is_system_role', 'roles', ['is_system_role'])

    # Create role_permissions association table
    op.create_table(
        'role_permissions',
        sa.Column('role_id', sa.String(length=36), nullable=False),
        sa.Column('permission_id', sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['permission_id'], ['permissions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('role_id', 'permission_id')
    )

    # Create teams table
    op.create_table(
        'teams',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('slug', sa.String(length=100), nullable=False),
        sa.Column('description', sa.String(length=1000), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='active'),
        sa.Column('settings', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug')
    )
    op.create_index('ix_teams_status', 'teams', ['status'])
    op.create_index('ix_teams_slug', 'teams', ['slug'])

    # Create users table
    op.create_table(
        'users',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('first_name', sa.String(length=100), nullable=True),
        sa.Column('last_name', sa.String(length=100), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='active'),
        sa.Column('is_superuser', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
    )
    op.create_index('ix_users_email', 'users', ['email'])
    op.create_index('ix_users_status', 'users', ['status'])

    # Create team_memberships table
    op.create_table(
        'team_memberships',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('team_id', sa.String(length=36), nullable=False),
        sa.Column('role_id', sa.String(length=36), nullable=False),
        sa.Column('joined_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'team_id', name='uq_user_team')
    )
    op.create_index('ix_team_memberships_user_id', 'team_memberships', ['user_id'])
    op.create_index('ix_team_memberships_team_id', 'team_memberships', ['team_id'])

    # Create refresh_tokens table
    op.create_table(
        'refresh_tokens',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('token_hash', sa.String(length=255), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.String(length=512), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash')
    )
    op.create_index('ix_refresh_tokens_user_id', 'refresh_tokens', ['user_id'])
    op.create_index('ix_refresh_tokens_token_hash', 'refresh_tokens', ['token_hash'])
    op.create_index('ix_refresh_tokens_expires_at', 'refresh_tokens', ['expires_at'])

    # Add team_id and created_by_id to optimization_runs
    op.add_column('optimization_runs', sa.Column('team_id', sa.String(length=36), nullable=True))
    op.add_column('optimization_runs', sa.Column('created_by_id', sa.String(length=36), nullable=True))
    op.create_foreign_key(
        'fk_optimization_runs_team_id',
        'optimization_runs', 'teams',
        ['team_id'], ['id'],
        ondelete='SET NULL'
    )
    op.create_foreign_key(
        'fk_optimization_runs_created_by_id',
        'optimization_runs', 'users',
        ['created_by_id'], ['id'],
        ondelete='SET NULL'
    )
    op.create_index('ix_optimization_runs_team_id', 'optimization_runs', ['team_id'])

    # Insert default permissions
    op.execute("""
        INSERT INTO permissions (id, name, description, resource, action, created_at) VALUES
        -- Optimization permissions
        ('perm-opt-create', 'Create Optimization Run', 'Create new optimization runs', 'optimization', 'create', NOW()),
        ('perm-opt-read', 'Read Optimization Run', 'View optimization runs and results', 'optimization', 'read', NOW()),
        ('perm-opt-delete', 'Delete Optimization Run', 'Delete optimization runs', 'optimization', 'delete', NOW()),
        -- Webhook permissions
        ('perm-webhook-create', 'Create Webhook', 'Create webhook configurations', 'webhook', 'create', NOW()),
        ('perm-webhook-read', 'Read Webhook', 'View webhook configurations', 'webhook', 'read', NOW()),
        ('perm-webhook-update', 'Update Webhook', 'Update webhook configurations', 'webhook', 'update', NOW()),
        ('perm-webhook-delete', 'Delete Webhook', 'Delete webhook configurations', 'webhook', 'delete', NOW()),
        -- Team management permissions
        ('perm-team-read', 'Read Team', 'View team information', 'team', 'read', NOW()),
        ('perm-team-update', 'Update Team', 'Update team settings', 'team', 'update', NOW()),
        ('perm-team-manage-members', 'Manage Team Members', 'Add/remove team members', 'team', 'manage_members', NOW()),
        -- User permissions
        ('perm-user-read', 'Read Users', 'View user information', 'user', 'read', NOW()),
        ('perm-user-update', 'Update Users', 'Update user information', 'user', 'update', NOW()),
        -- Audit permissions
        ('perm-audit-read', 'Read Audit Logs', 'View audit logs', 'audit', 'read', NOW()),
        ('perm-audit-export', 'Export Audit Logs', 'Export audit logs', 'audit', 'export', NOW()),
        -- Admin permission (wildcard)
        ('perm-admin-all', 'Full Admin Access', 'Full administrative access to all resources', '*', '*', NOW())
    """)

    # Insert default roles
    op.execute("""
        INSERT INTO roles (id, name, description, is_system_role, created_at, updated_at) VALUES
        ('role-admin', 'Admin', 'Full administrative access to team resources', true, NOW(), NOW()),
        ('role-operator', 'Operator', 'Can create and manage optimization runs and webhooks', true, NOW(), NOW()),
        ('role-viewer', 'Viewer', 'Read-only access to team resources', true, NOW(), NOW())
    """)

    # Assign permissions to roles
    op.execute("""
        INSERT INTO role_permissions (role_id, permission_id) VALUES
        -- Admin gets everything
        ('role-admin', 'perm-admin-all'),
        -- Operator permissions
        ('role-operator', 'perm-opt-create'),
        ('role-operator', 'perm-opt-read'),
        ('role-operator', 'perm-opt-delete'),
        ('role-operator', 'perm-webhook-create'),
        ('role-operator', 'perm-webhook-read'),
        ('role-operator', 'perm-webhook-update'),
        ('role-operator', 'perm-webhook-delete'),
        ('role-operator', 'perm-team-read'),
        ('role-operator', 'perm-audit-read'),
        -- Viewer permissions
        ('role-viewer', 'perm-opt-read'),
        ('role-viewer', 'perm-webhook-read'),
        ('role-viewer', 'perm-team-read'),
        ('role-viewer', 'perm-audit-read')
    """)


def downgrade() -> None:
    """Drop RBAC and multi-tenancy tables."""
    # Remove foreign keys from optimization_runs
    op.drop_index('ix_optimization_runs_team_id', table_name='optimization_runs')
    op.drop_constraint('fk_optimization_runs_created_by_id', 'optimization_runs', type_='foreignkey')
    op.drop_constraint('fk_optimization_runs_team_id', 'optimization_runs', type_='foreignkey')
    op.drop_column('optimization_runs', 'created_by_id')
    op.drop_column('optimization_runs', 'team_id')

    # Drop tables in reverse order
    op.drop_index('ix_refresh_tokens_expires_at', table_name='refresh_tokens')
    op.drop_index('ix_refresh_tokens_token_hash', table_name='refresh_tokens')
    op.drop_index('ix_refresh_tokens_user_id', table_name='refresh_tokens')
    op.drop_table('refresh_tokens')

    op.drop_index('ix_team_memberships_team_id', table_name='team_memberships')
    op.drop_index('ix_team_memberships_user_id', table_name='team_memberships')
    op.drop_table('team_memberships')

    op.drop_index('ix_users_status', table_name='users')
    op.drop_index('ix_users_email', table_name='users')
    op.drop_table('users')

    op.drop_index('ix_teams_slug', table_name='teams')
    op.drop_index('ix_teams_status', table_name='teams')
    op.drop_table('teams')

    op.drop_table('role_permissions')

    op.drop_index('ix_roles_is_system_role', table_name='roles')
    op.drop_table('roles')

    op.drop_index('ix_permissions_action', table_name='permissions')
    op.drop_index('ix_permissions_resource', table_name='permissions')
    op.drop_table('permissions')
