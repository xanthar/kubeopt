"""
Cluster management API routes for KubeOpt AI.

Provides REST endpoints for managing Kubernetes clusters in a multi-cluster
environment.
"""

import logging
from flask import Blueprint, request, jsonify

from kubeopt_ai.core.cluster_manager import (
    get_cluster_manager,
    ClusterManagerError,
    ClusterNotFoundError,
)

logger = logging.getLogger(__name__)

clusters_bp = Blueprint("clusters", __name__, url_prefix="/api/v1/clusters")


@clusters_bp.route("", methods=["POST"])
def create_cluster():
    """
    Register a new Kubernetes cluster.

    Request Body:
        name (str): Unique cluster name (required)
        provider (str): Cloud provider (aws, gcp, azure, on_prem, other)
        region (str): Cluster region/zone
        display_name (str): Human-readable name
        description (str): Cluster description
        api_server_url (str): Kubernetes API server URL
        kubeconfig (str): Kubeconfig content
        kubeconfig_context (str): Context name
        prometheus_url (str): Prometheus server URL
        prometheus_auth (dict): Prometheus auth config
        labels (dict): Custom labels
        settings (dict): Additional settings
        team_id (str): Owning team ID

    Returns:
        201: Created cluster object
        400: Invalid request
        500: Server error
    """
    data = request.get_json()

    if not data:
        return jsonify({
            "code": "BAD_REQUEST",
            "message": "Request body is required",
        }), 400

    name = data.get("name")
    if not name:
        return jsonify({
            "code": "BAD_REQUEST",
            "message": "Cluster name is required",
        }), 400

    try:
        manager = get_cluster_manager()
        cluster = manager.register(
            name=name,
            provider=data.get("provider", "other"),
            region=data.get("region"),
            display_name=data.get("display_name"),
            description=data.get("description"),
            api_server_url=data.get("api_server_url"),
            kubeconfig=data.get("kubeconfig"),
            kubeconfig_context=data.get("kubeconfig_context"),
            prometheus_url=data.get("prometheus_url"),
            prometheus_auth=data.get("prometheus_auth"),
            labels=data.get("labels"),
            settings=data.get("settings"),
            team_id=data.get("team_id"),
        )

        return jsonify(cluster.to_dict()), 201

    except ClusterManagerError as e:
        logger.error(f"Failed to create cluster: {e}")
        return jsonify({
            "code": "CREATE_FAILED",
            "message": str(e),
        }), 400


@clusters_bp.route("", methods=["GET"])
def list_clusters():
    """
    List registered clusters.

    Query Parameters:
        team_id (str): Filter by team
        status (str): Filter by status
        provider (str): Filter by provider
        limit (int): Max results (default 100)
        offset (int): Skip results

    Returns:
        200: List of cluster objects
    """
    team_id = request.args.get("team_id")
    status = request.args.get("status")
    provider = request.args.get("provider")
    limit = request.args.get("limit", 100, type=int)
    offset = request.args.get("offset", 0, type=int)

    manager = get_cluster_manager()
    clusters = manager.list(
        team_id=team_id,
        status=status,
        provider=provider,
        limit=limit,
        offset=offset,
    )

    return jsonify({
        "clusters": [c.to_dict() for c in clusters],
        "count": len(clusters),
        "limit": limit,
        "offset": offset,
    })


@clusters_bp.route("/<cluster_id>", methods=["GET"])
def get_cluster(cluster_id: str):
    """
    Get a cluster by ID.

    Path Parameters:
        cluster_id: Cluster UUID

    Returns:
        200: Cluster object
        404: Cluster not found
    """
    try:
        manager = get_cluster_manager()
        cluster = manager.get(cluster_id)
        return jsonify(cluster.to_dict())

    except ClusterNotFoundError:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Cluster not found: {cluster_id}",
        }), 404


@clusters_bp.route("/<cluster_id>", methods=["PUT"])
def update_cluster(cluster_id: str):
    """
    Update a cluster's configuration.

    Path Parameters:
        cluster_id: Cluster UUID

    Request Body:
        Any cluster fields to update

    Returns:
        200: Updated cluster object
        404: Cluster not found
        400: Update failed
    """
    data = request.get_json()

    if not data:
        return jsonify({
            "code": "BAD_REQUEST",
            "message": "Request body is required",
        }), 400

    try:
        manager = get_cluster_manager()
        cluster = manager.update(cluster_id, **data)
        return jsonify(cluster.to_dict())

    except ClusterNotFoundError:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Cluster not found: {cluster_id}",
        }), 404

    except ClusterManagerError as e:
        return jsonify({
            "code": "UPDATE_FAILED",
            "message": str(e),
        }), 400


@clusters_bp.route("/<cluster_id>", methods=["DELETE"])
def delete_cluster(cluster_id: str):
    """
    Delete a cluster.

    Path Parameters:
        cluster_id: Cluster UUID

    Returns:
        204: Successfully deleted
        404: Cluster not found
        400: Deletion failed
    """
    try:
        manager = get_cluster_manager()
        manager.delete(cluster_id)
        return "", 204

    except ClusterNotFoundError:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Cluster not found: {cluster_id}",
        }), 404

    except ClusterManagerError as e:
        return jsonify({
            "code": "DELETE_FAILED",
            "message": str(e),
        }), 400


@clusters_bp.route("/<cluster_id>/test", methods=["POST"])
def test_cluster_connection(cluster_id: str):
    """
    Test connection to a cluster.

    Path Parameters:
        cluster_id: Cluster UUID

    Returns:
        200: Connection test results
        404: Cluster not found
    """
    try:
        manager = get_cluster_manager()
        result = manager.test_connection(cluster_id)

        return jsonify({
            "success": result.success,
            "message": result.message,
            "kubernetes_version": result.kubernetes_version,
            "prometheus_reachable": result.prometheus_reachable,
            "latency_ms": result.latency_ms,
        })

    except ClusterNotFoundError:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Cluster not found: {cluster_id}",
        }), 404


@clusters_bp.route("/<cluster_id>/status", methods=["PUT"])
def set_cluster_status(cluster_id: str):
    """
    Set a cluster's status.

    Path Parameters:
        cluster_id: Cluster UUID

    Request Body:
        status (str): New status value
        error (str): Optional error message

    Returns:
        200: Updated cluster object
        404: Cluster not found
        400: Invalid status
    """
    data = request.get_json()

    if not data or "status" not in data:
        return jsonify({
            "code": "BAD_REQUEST",
            "message": "Status is required",
        }), 400

    try:
        manager = get_cluster_manager()
        cluster = manager.set_status(
            cluster_id,
            status=data["status"],
            error=data.get("error"),
        )
        return jsonify(cluster.to_dict())

    except ClusterNotFoundError:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Cluster not found: {cluster_id}",
        }), 404

    except ClusterManagerError as e:
        return jsonify({
            "code": "INVALID_STATUS",
            "message": str(e),
        }), 400
