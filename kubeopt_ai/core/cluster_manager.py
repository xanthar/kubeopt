"""
Cluster management service for KubeOpt AI.

Provides functionality for managing multiple Kubernetes clusters,
including registration, connection testing, and cluster operations.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass

import requests
from requests.exceptions import RequestException

from kubeopt_ai.extensions import db
from kubeopt_ai.core.models import (
    Cluster,
    ClusterStatus,
    ClusterProvider,
)

logger = logging.getLogger(__name__)


class ClusterManagerError(Exception):
    """Exception raised for cluster management errors."""
    pass


class ClusterNotFoundError(ClusterManagerError):
    """Exception raised when a cluster is not found."""
    pass


class ClusterConnectionError(ClusterManagerError):
    """Exception raised when cluster connection fails."""
    pass


@dataclass
class ClusterConnectionResult:
    """Result of a cluster connection test."""
    success: bool
    message: str
    kubernetes_version: Optional[str] = None
    prometheus_reachable: bool = False
    latency_ms: Optional[float] = None


class ClusterManager:
    """
    Service for managing Kubernetes clusters.

    Provides CRUD operations, connection testing, and cluster health monitoring.
    """

    def __init__(self, timeout: int = 10):
        """
        Initialize the cluster manager.

        Args:
            timeout: Default timeout for connection tests in seconds.
        """
        self.timeout = timeout

    def register(
        self,
        name: str,
        provider: str = "other",
        region: Optional[str] = None,
        display_name: Optional[str] = None,
        description: Optional[str] = None,
        api_server_url: Optional[str] = None,
        kubeconfig: Optional[str] = None,
        kubeconfig_context: Optional[str] = None,
        prometheus_url: Optional[str] = None,
        prometheus_auth: Optional[dict] = None,
        labels: Optional[dict] = None,
        settings: Optional[dict] = None,
        team_id: Optional[str] = None,
    ) -> Cluster:
        """
        Register a new Kubernetes cluster.

        Args:
            name: Unique cluster name.
            provider: Cloud provider (aws, gcp, azure, on_prem, other).
            region: Cluster region/zone.
            display_name: Human-readable display name.
            description: Cluster description.
            api_server_url: Kubernetes API server URL.
            kubeconfig: Kubeconfig content (should be encrypted in production).
            kubeconfig_context: Context name within kubeconfig.
            prometheus_url: Prometheus server URL for this cluster.
            prometheus_auth: Prometheus authentication config.
            labels: Custom labels for the cluster.
            settings: Additional cluster settings.
            team_id: Team that owns this cluster.

        Returns:
            The created Cluster object.

        Raises:
            ClusterManagerError: If registration fails.
        """
        try:
            # Validate provider
            try:
                provider_enum = ClusterProvider(provider.lower())
            except ValueError:
                provider_enum = ClusterProvider.OTHER

            cluster = Cluster(
                name=name,
                display_name=display_name or name,
                description=description,
                provider=provider_enum,
                region=region,
                status=ClusterStatus.PENDING,
                api_server_url=api_server_url,
                kubeconfig=kubeconfig,
                kubeconfig_context=kubeconfig_context,
                prometheus_url=prometheus_url,
                prometheus_auth=prometheus_auth or {},
                labels=labels or {},
                settings=settings or {},
                team_id=team_id,
            )

            db.session.add(cluster)
            db.session.commit()

            logger.info(f"Registered cluster: {name} (id={cluster.id})")
            return cluster

        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to register cluster {name}: {e}")
            raise ClusterManagerError(f"Failed to register cluster: {e}")

    def get(self, cluster_id: str) -> Cluster:
        """
        Get a cluster by ID.

        Args:
            cluster_id: The cluster ID.

        Returns:
            The Cluster object.

        Raises:
            ClusterNotFoundError: If cluster is not found.
        """
        cluster = db.session.get(Cluster, cluster_id)
        if not cluster:
            raise ClusterNotFoundError(f"Cluster not found: {cluster_id}")
        return cluster

    def get_by_name(self, name: str, team_id: Optional[str] = None) -> Optional[Cluster]:
        """
        Get a cluster by name, optionally filtered by team.

        Args:
            name: The cluster name.
            team_id: Optional team ID filter.

        Returns:
            The Cluster object or None if not found.
        """
        query = Cluster.query.filter_by(name=name)
        if team_id:
            query = query.filter_by(team_id=team_id)
        return query.first()

    def list(
        self,
        team_id: Optional[str] = None,
        status: Optional[str] = None,
        provider: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Cluster]:
        """
        List clusters with optional filters.

        Args:
            team_id: Filter by team ID.
            status: Filter by status.
            provider: Filter by provider.
            limit: Maximum number of results.
            offset: Number of results to skip.

        Returns:
            List of Cluster objects.
        """
        query = Cluster.query

        if team_id:
            query = query.filter_by(team_id=team_id)
        if status:
            try:
                status_enum = ClusterStatus(status.lower())
                query = query.filter_by(status=status_enum)
            except ValueError:
                pass
        if provider:
            try:
                provider_enum = ClusterProvider(provider.lower())
                query = query.filter_by(provider=provider_enum)
            except ValueError:
                pass

        query = query.order_by(Cluster.name)
        return query.offset(offset).limit(limit).all()

    def update(
        self,
        cluster_id: str,
        **kwargs
    ) -> Cluster:
        """
        Update a cluster's configuration.

        Args:
            cluster_id: The cluster ID.
            **kwargs: Fields to update.

        Returns:
            The updated Cluster object.

        Raises:
            ClusterNotFoundError: If cluster is not found.
            ClusterManagerError: If update fails.
        """
        cluster = self.get(cluster_id)

        try:
            # Handle provider conversion
            if 'provider' in kwargs:
                try:
                    kwargs['provider'] = ClusterProvider(kwargs['provider'].lower())
                except ValueError:
                    kwargs['provider'] = ClusterProvider.OTHER

            # Handle status conversion
            if 'status' in kwargs:
                try:
                    kwargs['status'] = ClusterStatus(kwargs['status'].lower())
                except ValueError:
                    del kwargs['status']

            # Update allowed fields
            allowed_fields = {
                'name', 'display_name', 'description', 'provider', 'region',
                'status', 'api_server_url', 'kubeconfig', 'kubeconfig_context',
                'prometheus_url', 'prometheus_auth', 'labels', 'settings'
            }

            for key, value in kwargs.items():
                if key in allowed_fields:
                    setattr(cluster, key, value)

            db.session.commit()
            logger.info(f"Updated cluster: {cluster.name} (id={cluster_id})")
            return cluster

        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to update cluster {cluster_id}: {e}")
            raise ClusterManagerError(f"Failed to update cluster: {e}")

    def delete(self, cluster_id: str) -> bool:
        """
        Delete a cluster.

        Args:
            cluster_id: The cluster ID.

        Returns:
            True if deleted successfully.

        Raises:
            ClusterNotFoundError: If cluster is not found.
            ClusterManagerError: If deletion fails.
        """
        cluster = self.get(cluster_id)

        try:
            db.session.delete(cluster)
            db.session.commit()
            logger.info(f"Deleted cluster: {cluster.name} (id={cluster_id})")
            return True

        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to delete cluster {cluster_id}: {e}")
            raise ClusterManagerError(f"Failed to delete cluster: {e}")

    def test_connection(self, cluster_id: str) -> ClusterConnectionResult:
        """
        Test connection to a cluster.

        Tests both Kubernetes API and Prometheus connectivity.

        Args:
            cluster_id: The cluster ID.

        Returns:
            ClusterConnectionResult with connection status.

        Raises:
            ClusterNotFoundError: If cluster is not found.
        """
        cluster = self.get(cluster_id)
        k8s_version = None
        prometheus_ok = False
        latency_ms = None

        # Test Kubernetes API connection
        # SSL verification can be configured per-cluster via settings.verify_ssl
        # Defaults to True for security - only disable for self-signed certs
        verify_ssl = cluster.settings.get("verify_ssl", True) if cluster.settings else True

        if cluster.api_server_url:
            try:
                import time
                start = time.time()
                response = requests.get(
                    f"{cluster.api_server_url}/version",
                    timeout=self.timeout,
                    verify=verify_ssl,
                )
                latency_ms = (time.time() - start) * 1000

                if response.status_code == 200:
                    data = response.json()
                    k8s_version = data.get('gitVersion', 'unknown')
                elif response.status_code == 401:
                    # Auth required but endpoint is reachable
                    k8s_version = "auth_required"

            except RequestException as e:
                logger.warning(f"K8s API connection failed for {cluster.name}: {e}")
                self._update_cluster_status(cluster, ClusterStatus.UNREACHABLE, str(e))
                return ClusterConnectionResult(
                    success=False,
                    message=f"Kubernetes API unreachable: {e}",
                    latency_ms=latency_ms,
                )

        # Test Prometheus connection
        if cluster.prometheus_url:
            try:
                response = requests.get(
                    f"{cluster.prometheus_url}/api/v1/status/config",
                    timeout=self.timeout,
                    verify=verify_ssl,
                )
                prometheus_ok = response.status_code == 200

            except RequestException as e:
                logger.warning(f"Prometheus connection failed for {cluster.name}: {e}")

        # Update cluster status
        self._update_cluster_status(
            cluster,
            ClusterStatus.ACTIVE if k8s_version else ClusterStatus.UNREACHABLE,
            None if k8s_version else "Connection test failed"
        )

        return ClusterConnectionResult(
            success=bool(k8s_version),
            message="Connection successful" if k8s_version else "Connection failed",
            kubernetes_version=k8s_version,
            prometheus_reachable=prometheus_ok,
            latency_ms=latency_ms,
        )

    def _update_cluster_status(
        self,
        cluster: Cluster,
        status: ClusterStatus,
        error: Optional[str]
    ) -> None:
        """Update cluster status and connection info."""
        try:
            cluster.status = status
            cluster.last_error = error
            if status == ClusterStatus.ACTIVE:
                cluster.last_connected_at = datetime.now(timezone.utc)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to update cluster status: {e}")

    def get_prometheus_url(self, cluster_id: str) -> Optional[str]:
        """
        Get the Prometheus URL for a cluster.

        Args:
            cluster_id: The cluster ID.

        Returns:
            The Prometheus URL or None.

        Raises:
            ClusterNotFoundError: If cluster is not found.
        """
        cluster = self.get(cluster_id)
        return cluster.prometheus_url

    def set_status(self, cluster_id: str, status: str, error: Optional[str] = None) -> Cluster:
        """
        Set a cluster's status.

        Args:
            cluster_id: The cluster ID.
            status: New status value.
            error: Optional error message.

        Returns:
            The updated Cluster object.
        """
        cluster = self.get(cluster_id)

        try:
            status_enum = ClusterStatus(status.lower())
        except ValueError:
            raise ClusterManagerError(f"Invalid status: {status}")

        self._update_cluster_status(cluster, status_enum, error)
        return cluster


# Module-level instance
_manager: Optional[ClusterManager] = None


def get_cluster_manager(timeout: int = 10) -> ClusterManager:
    """Get or create the cluster manager instance."""
    global _manager
    if _manager is None:
        _manager = ClusterManager(timeout)
    return _manager
