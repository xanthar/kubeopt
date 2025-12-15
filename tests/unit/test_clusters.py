"""
Unit tests for cluster management (F019).
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from kubeopt_ai.core.models import Cluster, ClusterStatus, ClusterProvider
from kubeopt_ai.core.cluster_manager import (
    ClusterManager,
    ClusterManagerError,
    ClusterNotFoundError,
    ClusterConnectionResult,
)


class TestClusterManager:
    """Tests for ClusterManager service."""

    def test_register_cluster_success(self, app, db_session):
        """Test successful cluster registration."""
        manager = ClusterManager()

        cluster = manager.register(
            name="test-cluster",
            provider="aws",
            region="us-east-1",
            display_name="Test Cluster",
            description="A test cluster",
            api_server_url="https://api.test.example.com",
            prometheus_url="http://prometheus.test.example.com:9090",
        )

        assert cluster.id is not None
        assert cluster.name == "test-cluster"
        assert cluster.provider == ClusterProvider.AWS
        assert cluster.region == "us-east-1"
        assert cluster.status == ClusterStatus.PENDING
        assert cluster.prometheus_url == "http://prometheus.test.example.com:9090"

    def test_register_cluster_with_labels(self, app, db_session):
        """Test cluster registration with custom labels."""
        manager = ClusterManager()

        labels = {"environment": "production", "team": "platform"}
        cluster = manager.register(
            name="labeled-cluster",
            labels=labels,
        )

        assert cluster.labels == labels

    def test_register_cluster_unknown_provider(self, app, db_session):
        """Test that unknown providers default to 'other'."""
        manager = ClusterManager()

        cluster = manager.register(
            name="unknown-provider",
            provider="unknown",
        )

        assert cluster.provider == ClusterProvider.OTHER

    def test_get_cluster_success(self, app, db_session):
        """Test getting a cluster by ID."""
        manager = ClusterManager()

        created = manager.register(name="get-test")
        retrieved = manager.get(created.id)

        assert retrieved.id == created.id
        assert retrieved.name == "get-test"

    def test_get_cluster_not_found(self, app, db_session):
        """Test getting a non-existent cluster."""
        manager = ClusterManager()

        with pytest.raises(ClusterNotFoundError):
            manager.get("non-existent-id")

    def test_get_cluster_by_name(self, app, db_session):
        """Test getting a cluster by name."""
        manager = ClusterManager()

        manager.register(name="named-cluster")
        cluster = manager.get_by_name("named-cluster")

        assert cluster is not None
        assert cluster.name == "named-cluster"

    def test_get_cluster_by_name_not_found(self, app, db_session):
        """Test getting a non-existent cluster by name."""
        manager = ClusterManager()

        cluster = manager.get_by_name("non-existent")
        assert cluster is None

    def test_list_clusters(self, app, db_session):
        """Test listing clusters."""
        manager = ClusterManager()

        manager.register(name="cluster-1")
        manager.register(name="cluster-2")
        manager.register(name="cluster-3")

        clusters = manager.list()

        assert len(clusters) >= 3
        names = [c.name for c in clusters]
        assert "cluster-1" in names
        assert "cluster-2" in names
        assert "cluster-3" in names

    def test_list_clusters_with_status_filter(self, app, db_session):
        """Test listing clusters filtered by status."""
        manager = ClusterManager()

        cluster = manager.register(name="pending-cluster")
        assert cluster.status == ClusterStatus.PENDING

        clusters = manager.list(status="pending")
        assert any(c.name == "pending-cluster" for c in clusters)

    def test_list_clusters_with_provider_filter(self, app, db_session):
        """Test listing clusters filtered by provider."""
        manager = ClusterManager()

        manager.register(name="aws-cluster", provider="aws")
        manager.register(name="gcp-cluster", provider="gcp")

        aws_clusters = manager.list(provider="aws")
        assert any(c.name == "aws-cluster" for c in aws_clusters)
        assert not any(c.name == "gcp-cluster" for c in aws_clusters)

    def test_list_clusters_with_pagination(self, app, db_session):
        """Test listing clusters with pagination."""
        manager = ClusterManager()

        for i in range(5):
            manager.register(name=f"paginated-{i}")

        page1 = manager.list(limit=2, offset=0)
        page2 = manager.list(limit=2, offset=2)

        assert len(page1) <= 2
        assert len(page2) <= 2

    def test_update_cluster_success(self, app, db_session):
        """Test updating a cluster."""
        manager = ClusterManager()

        cluster = manager.register(name="update-test")
        updated = manager.update(
            cluster.id,
            display_name="Updated Display Name",
            description="Updated description",
        )

        assert updated.display_name == "Updated Display Name"
        assert updated.description == "Updated description"

    def test_update_cluster_provider(self, app, db_session):
        """Test updating cluster provider."""
        manager = ClusterManager()

        cluster = manager.register(name="provider-update", provider="aws")
        updated = manager.update(cluster.id, provider="gcp")

        assert updated.provider == ClusterProvider.GCP

    def test_update_cluster_not_found(self, app, db_session):
        """Test updating a non-existent cluster."""
        manager = ClusterManager()

        with pytest.raises(ClusterNotFoundError):
            manager.update("non-existent-id", display_name="Test")

    def test_delete_cluster_success(self, app, db_session):
        """Test deleting a cluster."""
        manager = ClusterManager()

        cluster = manager.register(name="delete-test")
        cluster_id = cluster.id

        result = manager.delete(cluster_id)
        assert result is True

        with pytest.raises(ClusterNotFoundError):
            manager.get(cluster_id)

    def test_delete_cluster_not_found(self, app, db_session):
        """Test deleting a non-existent cluster."""
        manager = ClusterManager()

        with pytest.raises(ClusterNotFoundError):
            manager.delete("non-existent-id")

    @patch('kubeopt_ai.core.cluster_manager.requests.get')
    def test_test_connection_success(self, mock_get, app, db_session):
        """Test successful connection test."""
        manager = ClusterManager()

        cluster = manager.register(
            name="connection-test",
            api_server_url="https://api.test.example.com",
            prometheus_url="http://prometheus.test.example.com:9090",
        )

        # Mock K8s API response
        k8s_response = MagicMock()
        k8s_response.status_code = 200
        k8s_response.json.return_value = {"gitVersion": "v1.28.0"}

        # Mock Prometheus response
        prom_response = MagicMock()
        prom_response.status_code = 200

        mock_get.side_effect = [k8s_response, prom_response]

        result = manager.test_connection(cluster.id)

        assert result.success is True
        assert result.kubernetes_version == "v1.28.0"
        assert result.prometheus_reachable is True
        assert result.latency_ms is not None

    @patch('kubeopt_ai.core.cluster_manager.requests.get')
    def test_test_connection_k8s_unreachable(self, mock_get, app, db_session):
        """Test connection when K8s API is unreachable."""
        from requests.exceptions import ConnectionError

        manager = ClusterManager()

        cluster = manager.register(
            name="unreachable-test",
            api_server_url="https://api.unreachable.example.com",
        )

        mock_get.side_effect = ConnectionError("Connection refused")

        result = manager.test_connection(cluster.id)

        assert result.success is False
        assert "unreachable" in result.message.lower()

    def test_set_status_success(self, app, db_session):
        """Test setting cluster status."""
        manager = ClusterManager()

        cluster = manager.register(name="status-test")
        updated = manager.set_status(cluster.id, "active")

        assert updated.status == ClusterStatus.ACTIVE

    def test_set_status_with_error(self, app, db_session):
        """Test setting cluster status with error message."""
        manager = ClusterManager()

        cluster = manager.register(name="error-status-test")
        updated = manager.set_status(
            cluster.id,
            "unreachable",
            error="Connection timeout"
        )

        assert updated.status == ClusterStatus.UNREACHABLE
        assert updated.last_error == "Connection timeout"

    def test_set_status_invalid(self, app, db_session):
        """Test setting invalid status."""
        manager = ClusterManager()

        cluster = manager.register(name="invalid-status-test")

        with pytest.raises(ClusterManagerError):
            manager.set_status(cluster.id, "invalid-status")

    def test_get_prometheus_url(self, app, db_session):
        """Test getting Prometheus URL for a cluster."""
        manager = ClusterManager()

        cluster = manager.register(
            name="prometheus-url-test",
            prometheus_url="http://prometheus.test:9090",
        )

        url = manager.get_prometheus_url(cluster.id)
        assert url == "http://prometheus.test:9090"

    def test_cluster_to_dict(self, app, db_session):
        """Test cluster serialization."""
        manager = ClusterManager()

        cluster = manager.register(
            name="serialize-test",
            provider="aws",
            region="us-west-2",
            prometheus_url="http://prometheus.test:9090",
        )

        data = cluster.to_dict()

        assert data["name"] == "serialize-test"
        assert data["provider"] == "aws"
        assert data["region"] == "us-west-2"
        assert data["prometheus_url"] == "http://prometheus.test:9090"
        assert "kubeconfig" not in data  # Sensitive data excluded

    def test_cluster_to_dict_include_sensitive(self, app, db_session):
        """Test cluster serialization with sensitive data."""
        manager = ClusterManager()

        cluster = manager.register(
            name="sensitive-test",
            kubeconfig="secret-config",
        )

        data = cluster.to_dict(include_sensitive=True)

        assert data["kubeconfig"] == "secret-config"


class TestClusterRoutes:
    """Tests for cluster API routes."""

    def test_create_cluster_endpoint(self, client, db_session):
        """Test POST /api/v1/clusters."""
        response = client.post("/api/v1/clusters", json={
            "name": "api-test-cluster",
            "provider": "gcp",
            "region": "us-central1",
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data["name"] == "api-test-cluster"
        assert data["provider"] == "gcp"

    def test_create_cluster_missing_name(self, client, db_session):
        """Test POST /api/v1/clusters without name."""
        response = client.post("/api/v1/clusters", json={
            "provider": "aws",
        })

        assert response.status_code == 400
        data = response.get_json()
        assert "name" in data["message"].lower()

    def test_list_clusters_endpoint(self, client, db_session):
        """Test GET /api/v1/clusters."""
        # Create some clusters
        client.post("/api/v1/clusters", json={"name": "list-test-1"})
        client.post("/api/v1/clusters", json={"name": "list-test-2"})

        response = client.get("/api/v1/clusters")

        assert response.status_code == 200
        data = response.get_json()
        assert "clusters" in data
        assert "count" in data

    def test_get_cluster_endpoint(self, client, db_session):
        """Test GET /api/v1/clusters/<id>."""
        create_response = client.post("/api/v1/clusters", json={
            "name": "get-endpoint-test",
        })
        cluster_id = create_response.get_json()["id"]

        response = client.get(f"/api/v1/clusters/{cluster_id}")

        assert response.status_code == 200
        data = response.get_json()
        assert data["name"] == "get-endpoint-test"

    def test_get_cluster_not_found_endpoint(self, client, db_session):
        """Test GET /api/v1/clusters/<id> with invalid ID."""
        response = client.get("/api/v1/clusters/non-existent-id")

        assert response.status_code == 404

    def test_update_cluster_endpoint(self, client, db_session):
        """Test PUT /api/v1/clusters/<id>."""
        create_response = client.post("/api/v1/clusters", json={
            "name": "update-endpoint-test",
        })
        cluster_id = create_response.get_json()["id"]

        response = client.put(f"/api/v1/clusters/{cluster_id}", json={
            "display_name": "Updated Name",
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data["display_name"] == "Updated Name"

    def test_delete_cluster_endpoint(self, client, db_session):
        """Test DELETE /api/v1/clusters/<id>."""
        create_response = client.post("/api/v1/clusters", json={
            "name": "delete-endpoint-test",
        })
        cluster_id = create_response.get_json()["id"]

        response = client.delete(f"/api/v1/clusters/{cluster_id}")

        assert response.status_code == 204

        # Verify deletion
        get_response = client.get(f"/api/v1/clusters/{cluster_id}")
        assert get_response.status_code == 404

    def test_test_connection_endpoint(self, client, db_session):
        """Test POST /api/v1/clusters/<id>/test."""
        create_response = client.post("/api/v1/clusters", json={
            "name": "test-connection-endpoint",
            "api_server_url": "https://invalid.example.com",
        })
        cluster_id = create_response.get_json()["id"]

        with patch('kubeopt_ai.core.cluster_manager.requests.get') as mock_get:
            from requests.exceptions import ConnectionError
            mock_get.side_effect = ConnectionError("Connection refused")

            response = client.post(f"/api/v1/clusters/{cluster_id}/test")

        assert response.status_code == 200
        data = response.get_json()
        assert "success" in data

    def test_set_status_endpoint(self, client, db_session):
        """Test PUT /api/v1/clusters/<id>/status."""
        create_response = client.post("/api/v1/clusters", json={
            "name": "status-endpoint-test",
        })
        cluster_id = create_response.get_json()["id"]

        response = client.put(f"/api/v1/clusters/{cluster_id}/status", json={
            "status": "active",
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "active"
