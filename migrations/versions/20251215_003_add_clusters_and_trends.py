"""Add clusters and trend analysis tables.

Revision ID: 20251215_003
Revises: 20251215_002_add_rbac_tables
Create Date: 2025-12-15

Features:
- F019: Multi-Cluster Support (clusters table, cluster_id FKs)
- F020: Historical Trend Analysis (metrics_history, trend_analyses tables)
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251215_003'
down_revision = '20251215_002_add_rbac_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ==========================================================================
    # F019: Multi-Cluster Support
    # ==========================================================================

    # Create clusters table
    op.create_table(
        'clusters',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('display_name', sa.String(255), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('provider', sa.String(20), nullable=False, server_default='other'),
        sa.Column('region', sa.String(100), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('kubeconfig', sa.Text(), nullable=True),
        sa.Column('kubeconfig_context', sa.String(255), nullable=True),
        sa.Column('api_server_url', sa.String(1024), nullable=True),
        sa.Column('prometheus_url', sa.String(1024), nullable=True),
        sa.Column('prometheus_auth', sa.JSON(), nullable=True),
        sa.Column('labels', sa.JSON(), nullable=True),
        sa.Column('settings', sa.JSON(), nullable=True),
        sa.Column('last_connected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('team_id', sa.String(36), sa.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Create indexes for clusters
    op.create_index('ix_clusters_name', 'clusters', ['name'])
    op.create_index('ix_clusters_status', 'clusters', ['status'])
    op.create_index('ix_clusters_provider', 'clusters', ['provider'])
    op.create_index('ix_clusters_team_id', 'clusters', ['team_id'])

    # Create unique constraint for cluster name per team
    op.create_unique_constraint('uq_cluster_name_team', 'clusters', ['name', 'team_id'])

    # Add cluster_id to optimization_runs
    op.add_column('optimization_runs',
        sa.Column('cluster_id', sa.String(36), sa.ForeignKey('clusters.id', ondelete='SET NULL'), nullable=True)
    )
    op.create_index('ix_optimization_runs_cluster_id', 'optimization_runs', ['cluster_id'])

    # Add cluster_id to workload_snapshots
    op.add_column('workload_snapshots',
        sa.Column('cluster_id', sa.String(36), sa.ForeignKey('clusters.id', ondelete='SET NULL'), nullable=True)
    )
    op.create_index('ix_workload_snapshots_cluster_id', 'workload_snapshots', ['cluster_id'])

    # ==========================================================================
    # F020: Historical Trend Analysis
    # ==========================================================================

    # Create metrics_history table
    op.create_table(
        'metrics_history',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('cluster_id', sa.String(36), sa.ForeignKey('clusters.id', ondelete='CASCADE'), nullable=True),
        sa.Column('namespace', sa.String(253), nullable=False),
        sa.Column('workload_name', sa.String(253), nullable=False),
        sa.Column('workload_kind', sa.String(50), nullable=False),
        sa.Column('container_name', sa.String(253), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('cpu_usage', sa.Float(), nullable=True),
        sa.Column('cpu_request', sa.Float(), nullable=True),
        sa.Column('cpu_limit', sa.Float(), nullable=True),
        sa.Column('memory_usage', sa.Float(), nullable=True),
        sa.Column('memory_request', sa.Float(), nullable=True),
        sa.Column('memory_limit', sa.Float(), nullable=True),
        sa.Column('replica_count', sa.Integer(), nullable=True),
        sa.Column('extra_metrics', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Create indexes for metrics_history (optimized for time-series queries)
    op.create_index('ix_metrics_history_cluster_id', 'metrics_history', ['cluster_id'])
    op.create_index('ix_metrics_history_timestamp', 'metrics_history', ['timestamp'])
    op.create_index('ix_metrics_history_namespace', 'metrics_history', ['namespace'])
    op.create_index('ix_metrics_history_workload', 'metrics_history', ['namespace', 'workload_name'])
    op.create_index('ix_metrics_history_container', 'metrics_history', ['namespace', 'workload_name', 'container_name'])
    op.create_index('ix_metrics_history_time_range', 'metrics_history', ['cluster_id', 'namespace', 'workload_name', 'timestamp'])

    # Create trend_analyses table
    op.create_table(
        'trend_analyses',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('cluster_id', sa.String(36), sa.ForeignKey('clusters.id', ondelete='CASCADE'), nullable=True),
        sa.Column('namespace', sa.String(253), nullable=False),
        sa.Column('workload_name', sa.String(253), nullable=False),
        sa.Column('container_name', sa.String(253), nullable=False),
        sa.Column('analysis_period_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('analysis_period_end', sa.DateTime(timezone=True), nullable=False),
        # CPU trend fields
        sa.Column('cpu_trend_direction', sa.String(20), nullable=False, server_default='stable'),
        sa.Column('cpu_trend_slope', sa.Float(), nullable=True),
        sa.Column('cpu_avg', sa.Float(), nullable=True),
        sa.Column('cpu_p95', sa.Float(), nullable=True),
        sa.Column('cpu_max', sa.Float(), nullable=True),
        sa.Column('cpu_predicted_7d', sa.Float(), nullable=True),
        sa.Column('cpu_predicted_30d', sa.Float(), nullable=True),
        # Memory trend fields
        sa.Column('memory_trend_direction', sa.String(20), nullable=False, server_default='stable'),
        sa.Column('memory_trend_slope', sa.Float(), nullable=True),
        sa.Column('memory_avg', sa.Float(), nullable=True),
        sa.Column('memory_p95', sa.Float(), nullable=True),
        sa.Column('memory_max', sa.Float(), nullable=True),
        sa.Column('memory_predicted_7d', sa.Float(), nullable=True),
        sa.Column('memory_predicted_30d', sa.Float(), nullable=True),
        # Statistical metrics
        sa.Column('cpu_std_dev', sa.Float(), nullable=True),
        sa.Column('memory_std_dev', sa.Float(), nullable=True),
        sa.Column('seasonality_detected', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('seasonality_period_hours', sa.Integer(), nullable=True),
        # Recommendations
        sa.Column('recommended_cpu_request', sa.Float(), nullable=True),
        sa.Column('recommended_cpu_limit', sa.Float(), nullable=True),
        sa.Column('recommended_memory_request', sa.Float(), nullable=True),
        sa.Column('recommended_memory_limit', sa.Float(), nullable=True),
        sa.Column('confidence_score', sa.Float(), nullable=True),
        # Metadata
        sa.Column('data_points_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('analysis_metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Create indexes for trend_analyses
    op.create_index('ix_trend_analyses_cluster_id', 'trend_analyses', ['cluster_id'])
    op.create_index('ix_trend_analyses_namespace', 'trend_analyses', ['namespace'])
    op.create_index('ix_trend_analyses_workload', 'trend_analyses', ['namespace', 'workload_name'])
    op.create_index('ix_trend_analyses_created_at', 'trend_analyses', ['created_at'])


def downgrade() -> None:
    # Drop trend_analyses table and indexes
    op.drop_index('ix_trend_analyses_created_at', table_name='trend_analyses')
    op.drop_index('ix_trend_analyses_workload', table_name='trend_analyses')
    op.drop_index('ix_trend_analyses_namespace', table_name='trend_analyses')
    op.drop_index('ix_trend_analyses_cluster_id', table_name='trend_analyses')
    op.drop_table('trend_analyses')

    # Drop metrics_history table and indexes
    op.drop_index('ix_metrics_history_time_range', table_name='metrics_history')
    op.drop_index('ix_metrics_history_container', table_name='metrics_history')
    op.drop_index('ix_metrics_history_workload', table_name='metrics_history')
    op.drop_index('ix_metrics_history_namespace', table_name='metrics_history')
    op.drop_index('ix_metrics_history_timestamp', table_name='metrics_history')
    op.drop_index('ix_metrics_history_cluster_id', table_name='metrics_history')
    op.drop_table('metrics_history')

    # Remove cluster_id from workload_snapshots
    op.drop_index('ix_workload_snapshots_cluster_id', table_name='workload_snapshots')
    op.drop_column('workload_snapshots', 'cluster_id')

    # Remove cluster_id from optimization_runs
    op.drop_index('ix_optimization_runs_cluster_id', table_name='optimization_runs')
    op.drop_column('optimization_runs', 'cluster_id')

    # Drop clusters table
    op.drop_constraint('uq_cluster_name_team', 'clusters', type_='unique')
    op.drop_index('ix_clusters_team_id', table_name='clusters')
    op.drop_index('ix_clusters_provider', table_name='clusters')
    op.drop_index('ix_clusters_status', table_name='clusters')
    op.drop_index('ix_clusters_name', table_name='clusters')
    op.drop_table('clusters')
