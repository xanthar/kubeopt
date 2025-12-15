"""Add recommendation auto-apply tables.

Revision ID: 20251215_005
Revises: 20251215_004
Create Date: 2025-12-15

Features:
- F022: Recommendation Auto-Apply (apply_policies, apply_batches, apply_requests tables)
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251215_005'
down_revision = '20251215_004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ==========================================================================
    # F022: Recommendation Auto-Apply
    # ==========================================================================

    # Create apply_policies table
    op.create_table(
        'apply_policies',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        # Scope
        sa.Column('team_id', sa.String(36), sa.ForeignKey('teams.id', ondelete='CASCADE'), nullable=True),
        sa.Column('cluster_id', sa.String(36), sa.ForeignKey('clusters.id', ondelete='CASCADE'), nullable=True),
        # Approval settings
        sa.Column('require_approval', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('auto_approve_below_threshold', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('approval_threshold_cpu_percent', sa.Float(), nullable=False, server_default='20.0'),
        sa.Column('approval_threshold_memory_percent', sa.Float(), nullable=False, server_default='20.0'),
        # Guardrails - resource change limits
        sa.Column('max_cpu_increase_percent', sa.Float(), nullable=False, server_default='200.0'),
        sa.Column('max_cpu_decrease_percent', sa.Float(), nullable=False, server_default='50.0'),
        sa.Column('max_memory_increase_percent', sa.Float(), nullable=False, server_default='200.0'),
        sa.Column('max_memory_decrease_percent', sa.Float(), nullable=False, server_default='50.0'),
        # Guardrails - minimum resources
        sa.Column('min_cpu_request', sa.String(50), nullable=True, server_default='10m'),
        sa.Column('min_memory_request', sa.String(50), nullable=True, server_default='32Mi'),
        # Blackout windows and exclusions (JSON)
        sa.Column('blackout_windows', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('excluded_namespaces', sa.JSON(), nullable=False, server_default='["kube-system", "kube-public"]'),
        sa.Column('excluded_workload_patterns', sa.JSON(), nullable=False, server_default='[]'),
        # Status and priority
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='0'),
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('created_by_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
    )

    # Create indexes for apply_policies
    op.create_index('ix_apply_policies_name', 'apply_policies', ['name'])
    op.create_index('ix_apply_policies_team_id', 'apply_policies', ['team_id'])
    op.create_index('ix_apply_policies_cluster_id', 'apply_policies', ['cluster_id'])
    op.create_index('ix_apply_policies_enabled', 'apply_policies', ['enabled'])
    op.create_index('ix_apply_policies_priority', 'apply_policies', ['priority'])

    # Create apply_batches table (must be before apply_requests due to FK)
    op.create_table(
        'apply_batches',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('cluster_id', sa.String(36), sa.ForeignKey('clusters.id', ondelete='CASCADE'), nullable=False),
        sa.Column('team_id', sa.String(36), sa.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True),
        sa.Column('optimization_run_id', sa.String(36), sa.ForeignKey('optimization_runs.id', ondelete='SET NULL'), nullable=True),
        # Batch configuration
        sa.Column('status', sa.String(30), nullable=False, server_default='pending_approval'),
        sa.Column('mode', sa.String(20), nullable=False, server_default='dry_run'),
        # Approval
        sa.Column('requires_approval', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('approved_by_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        # Progress tracking
        sa.Column('total_requests', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('completed_requests', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failed_requests', sa.Integer(), nullable=False, server_default='0'),
        # Execution control
        sa.Column('stop_on_failure', sa.Boolean(), nullable=False, server_default='true'),
        # Execution timestamps
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('created_by_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
    )

    # Create indexes for apply_batches
    op.create_index('ix_apply_batches_cluster_id', 'apply_batches', ['cluster_id'])
    op.create_index('ix_apply_batches_team_id', 'apply_batches', ['team_id'])
    op.create_index('ix_apply_batches_status', 'apply_batches', ['status'])
    op.create_index('ix_apply_batches_created_at', 'apply_batches', ['created_at'])

    # Create apply_requests table
    op.create_table(
        'apply_requests',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('suggestion_id', sa.String(36), sa.ForeignKey('suggestions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('cluster_id', sa.String(36), sa.ForeignKey('clusters.id', ondelete='CASCADE'), nullable=False),
        sa.Column('team_id', sa.String(36), sa.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True),
        sa.Column('batch_id', sa.String(36), sa.ForeignKey('apply_batches.id', ondelete='SET NULL'), nullable=True),
        # Request configuration
        sa.Column('status', sa.String(30), nullable=False, server_default='pending_approval'),
        sa.Column('mode', sa.String(20), nullable=False, server_default='dry_run'),
        # Approval workflow
        sa.Column('requires_approval', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('approved_by_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        # Policy used
        sa.Column('apply_policy_id', sa.String(36), sa.ForeignKey('apply_policies.id', ondelete='SET NULL'), nullable=True),
        # Pre-apply state (for rollback)
        sa.Column('previous_config', sa.JSON(), nullable=True),
        sa.Column('proposed_config', sa.JSON(), nullable=False, server_default='{}'),
        # Execution details
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        # Results
        sa.Column('kubectl_output', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        # Guardrail check results
        sa.Column('guardrail_results', sa.JSON(), nullable=True),
        # Rollback tracking
        sa.Column('rolled_back', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('rolled_back_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rolled_back_by_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('rollback_reason', sa.Text(), nullable=True),
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('created_by_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
    )

    # Create indexes for apply_requests
    op.create_index('ix_apply_requests_suggestion_id', 'apply_requests', ['suggestion_id'])
    op.create_index('ix_apply_requests_cluster_id', 'apply_requests', ['cluster_id'])
    op.create_index('ix_apply_requests_team_id', 'apply_requests', ['team_id'])
    op.create_index('ix_apply_requests_batch_id', 'apply_requests', ['batch_id'])
    op.create_index('ix_apply_requests_status', 'apply_requests', ['status'])
    op.create_index('ix_apply_requests_created_at', 'apply_requests', ['created_at'])


def downgrade() -> None:
    # Drop apply_requests table and indexes
    op.drop_index('ix_apply_requests_created_at', table_name='apply_requests')
    op.drop_index('ix_apply_requests_status', table_name='apply_requests')
    op.drop_index('ix_apply_requests_batch_id', table_name='apply_requests')
    op.drop_index('ix_apply_requests_team_id', table_name='apply_requests')
    op.drop_index('ix_apply_requests_cluster_id', table_name='apply_requests')
    op.drop_index('ix_apply_requests_suggestion_id', table_name='apply_requests')
    op.drop_table('apply_requests')

    # Drop apply_batches table and indexes
    op.drop_index('ix_apply_batches_created_at', table_name='apply_batches')
    op.drop_index('ix_apply_batches_status', table_name='apply_batches')
    op.drop_index('ix_apply_batches_team_id', table_name='apply_batches')
    op.drop_index('ix_apply_batches_cluster_id', table_name='apply_batches')
    op.drop_table('apply_batches')

    # Drop apply_policies table and indexes
    op.drop_index('ix_apply_policies_priority', table_name='apply_policies')
    op.drop_index('ix_apply_policies_enabled', table_name='apply_policies')
    op.drop_index('ix_apply_policies_cluster_id', table_name='apply_policies')
    op.drop_index('ix_apply_policies_team_id', table_name='apply_policies')
    op.drop_index('ix_apply_policies_name', table_name='apply_policies')
    op.drop_table('apply_policies')
