"""Initial schema for KubeOpt AI

Revision ID: 001_initial_schema
Revises:
Create Date: 2024-12-14

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001_initial_schema'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create initial database schema."""
    # Create optimization_runs table
    op.create_table(
        'optimization_runs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('manifest_source_path', sa.String(length=1024), nullable=False),
        sa.Column('lookback_days', sa.Integer(), nullable=False, server_default='7'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_optimization_runs_status', 'optimization_runs', ['status'])
    op.create_index('ix_optimization_runs_created_at', 'optimization_runs', ['created_at'])

    # Create workload_snapshots table
    op.create_table(
        'workload_snapshots',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('run_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=253), nullable=False),
        sa.Column('namespace', sa.String(length=253), nullable=False, server_default='default'),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('current_config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('metrics_summary', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(['run_id'], ['optimization_runs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_workload_snapshots_run_id', 'workload_snapshots', ['run_id'])
    op.create_index('ix_workload_snapshots_name_namespace', 'workload_snapshots', ['name', 'namespace'])

    # Create suggestions table
    op.create_table(
        'suggestions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('workload_snapshot_id', sa.String(length=36), nullable=False),
        sa.Column('container_name', sa.String(length=253), nullable=False),
        sa.Column('suggestion_type', sa.String(length=50), nullable=False, server_default='resources'),
        sa.Column('current_config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('proposed_config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('reasoning', sa.Text(), nullable=True),
        sa.Column('diff_text', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['workload_snapshot_id'], ['workload_snapshots.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_suggestions_workload_snapshot_id', 'suggestions', ['workload_snapshot_id'])
    op.create_index('ix_suggestions_container_name', 'suggestions', ['container_name'])


def downgrade() -> None:
    """Drop all tables."""
    op.drop_index('ix_suggestions_container_name', table_name='suggestions')
    op.drop_index('ix_suggestions_workload_snapshot_id', table_name='suggestions')
    op.drop_table('suggestions')

    op.drop_index('ix_workload_snapshots_name_namespace', table_name='workload_snapshots')
    op.drop_index('ix_workload_snapshots_run_id', table_name='workload_snapshots')
    op.drop_table('workload_snapshots')

    op.drop_index('ix_optimization_runs_created_at', table_name='optimization_runs')
    op.drop_index('ix_optimization_runs_status', table_name='optimization_runs')
    op.drop_table('optimization_runs')
