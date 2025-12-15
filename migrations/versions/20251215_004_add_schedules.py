"""Add scheduled optimization tables.

Revision ID: 20251215_004
Revises: 20251215_003_add_clusters_and_trends
Create Date: 2025-12-15

Features:
- F021: Scheduled Optimization Runs (schedules, schedule_runs tables)
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251215_004'
down_revision = '20251215_003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ==========================================================================
    # F021: Scheduled Optimization Runs
    # ==========================================================================

    # Create schedules table
    op.create_table(
        'schedules',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('cron_expression', sa.String(100), nullable=False),
        sa.Column('timezone', sa.String(50), nullable=False, server_default='UTC'),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        # Optimization run configuration
        sa.Column('manifest_source_path', sa.String(1024), nullable=False),
        sa.Column('lookback_days', sa.Integer(), nullable=False, server_default='7'),
        # Multi-cluster support
        sa.Column('cluster_id', sa.String(36), sa.ForeignKey('clusters.id', ondelete='SET NULL'), nullable=True),
        # Multi-tenancy
        sa.Column('team_id', sa.String(36), sa.ForeignKey('teams.id', ondelete='CASCADE'), nullable=True),
        sa.Column('created_by_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        # Additional settings
        sa.Column('settings', sa.JSON(), nullable=True),
        # Run tracking
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('run_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failure_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('consecutive_failures', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_consecutive_failures', sa.Integer(), nullable=False, server_default='3'),
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Create indexes for schedules
    op.create_index('ix_schedules_name', 'schedules', ['name'])
    op.create_index('ix_schedules_status', 'schedules', ['status'])
    op.create_index('ix_schedules_team_id', 'schedules', ['team_id'])
    op.create_index('ix_schedules_cluster_id', 'schedules', ['cluster_id'])
    op.create_index('ix_schedules_next_run_at', 'schedules', ['next_run_at'])

    # Create unique constraint for schedule name per team
    op.create_unique_constraint('uq_schedule_name_team', 'schedules', ['name', 'team_id'])

    # Create schedule_runs table
    op.create_table(
        'schedule_runs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('schedule_id', sa.String(36), sa.ForeignKey('schedules.id', ondelete='CASCADE'), nullable=False),
        sa.Column('optimization_run_id', sa.String(36), sa.ForeignKey('optimization_runs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('trigger_type', sa.String(20), nullable=False, server_default='scheduled'),
        sa.Column('triggered_by_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('scheduled_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('result_summary', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Create indexes for schedule_runs
    op.create_index('ix_schedule_runs_schedule_id', 'schedule_runs', ['schedule_id'])
    op.create_index('ix_schedule_runs_status', 'schedule_runs', ['status'])
    op.create_index('ix_schedule_runs_scheduled_time', 'schedule_runs', ['scheduled_time'])
    op.create_index('ix_schedule_runs_started_at', 'schedule_runs', ['started_at'])


def downgrade() -> None:
    # Drop schedule_runs table and indexes
    op.drop_index('ix_schedule_runs_started_at', table_name='schedule_runs')
    op.drop_index('ix_schedule_runs_scheduled_time', table_name='schedule_runs')
    op.drop_index('ix_schedule_runs_status', table_name='schedule_runs')
    op.drop_index('ix_schedule_runs_schedule_id', table_name='schedule_runs')
    op.drop_table('schedule_runs')

    # Drop schedules table and indexes
    op.drop_constraint('uq_schedule_name_team', 'schedules', type_='unique')
    op.drop_index('ix_schedules_next_run_at', table_name='schedules')
    op.drop_index('ix_schedules_cluster_id', table_name='schedules')
    op.drop_index('ix_schedules_team_id', table_name='schedules')
    op.drop_index('ix_schedules_status', table_name='schedules')
    op.drop_index('ix_schedules_name', table_name='schedules')
    op.drop_table('schedules')
