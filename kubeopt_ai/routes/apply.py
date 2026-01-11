"""
Apply management API routes for KubeOpt AI.

Provides REST endpoints for applying optimization recommendations
with approval workflows and safety guardrails.
"""

import logging
from flask import Blueprint, request, jsonify

from kubeopt_ai.extensions import db
from kubeopt_ai.core.apply_service import (
    get_apply_service,
    ApplyServiceError,
    ApplyRequestNotFoundError,
    InvalidApplyStateError,
)
from kubeopt_ai.core.models import (
    ApplyPolicy,
    ApplyRequest,
    ApplyBatch,
    ApplyMode,
    ApplyRequestStatus,
)
from kubeopt_ai.core.schemas import (
    CreateApplyPolicyRequest,
    UpdateApplyPolicyRequest,
    CreateApplyRequest,
    CreateBatchApplyRequest,
    RejectRequestBody,
    RollbackRequestBody,
)

logger = logging.getLogger(__name__)

apply_bp = Blueprint("apply", __name__, url_prefix="/api/v1")


# =============================================================================
# Apply Policy Endpoints
# =============================================================================

@apply_bp.route("/apply-policies", methods=["POST"])
def create_policy():
    """
    Create a new apply policy.

    Request Body:
        name (str): Policy name (required)
        description (str): Policy description
        team_id (str): Team scope
        cluster_id (str): Cluster scope
        require_approval (bool): Require manual approval
        auto_approve_below_threshold (bool): Auto-approve small changes
        approval_threshold_cpu_percent (float): CPU change threshold
        approval_threshold_memory_percent (float): Memory change threshold
        max_cpu_increase_percent (float): Max CPU increase allowed
        max_cpu_decrease_percent (float): Max CPU decrease allowed
        max_memory_increase_percent (float): Max memory increase allowed
        max_memory_decrease_percent (float): Max memory decrease allowed
        min_cpu_request (str): Minimum CPU request
        min_memory_request (str): Minimum memory request
        blackout_windows (list): List of blackout windows
        excluded_namespaces (list): Namespaces to exclude
        excluded_workload_patterns (list): Workload patterns to exclude
        priority (int): Policy priority

    Returns:
        201: Created policy object
        400: Invalid request
        500: Server error
    """
    data = request.get_json()
    if not data:
        return jsonify({
            "code": "BAD_REQUEST",
            "message": "Request body is required",
        }), 400

    try:
        # Validate with Pydantic
        req = CreateApplyPolicyRequest(**data)

        policy = ApplyPolicy(
            name=req.name,
            description=req.description,
            team_id=req.team_id,
            cluster_id=req.cluster_id,
            require_approval=req.require_approval,
            auto_approve_below_threshold=req.auto_approve_below_threshold,
            approval_threshold_cpu_percent=req.approval_threshold_cpu_percent,
            approval_threshold_memory_percent=req.approval_threshold_memory_percent,
            max_cpu_increase_percent=req.max_cpu_increase_percent,
            max_cpu_decrease_percent=req.max_cpu_decrease_percent,
            max_memory_increase_percent=req.max_memory_increase_percent,
            max_memory_decrease_percent=req.max_memory_decrease_percent,
            min_cpu_request=req.min_cpu_request,
            min_memory_request=req.min_memory_request,
            blackout_windows=[w.model_dump() for w in req.blackout_windows],
            excluded_namespaces=req.excluded_namespaces,
            excluded_workload_patterns=req.excluded_workload_patterns,
            priority=req.priority,
        )

        db.session.add(policy)
        db.session.commit()

        return jsonify(policy.to_dict()), 201

    except ValueError as e:
        return jsonify({
            "code": "VALIDATION_ERROR",
            "message": str(e),
        }), 400
    except Exception as e:
        logger.error(f"Failed to create policy: {e}")
        db.session.rollback()
        return jsonify({
            "code": "SERVER_ERROR",
            "message": "Failed to create policy",
        }), 500


@apply_bp.route("/apply-policies", methods=["GET"])
def list_policies():
    """
    List apply policies.

    Query Parameters:
        team_id (str): Filter by team
        cluster_id (str): Filter by cluster
        enabled (bool): Filter by enabled status
        limit (int): Max results (default: 100)
        offset (int): Results offset (default: 0)

    Returns:
        200: List of policies
    """
    team_id = request.args.get("team_id")
    cluster_id = request.args.get("cluster_id")
    enabled = request.args.get("enabled")
    limit = int(request.args.get("limit", 100))
    offset = int(request.args.get("offset", 0))

    query = ApplyPolicy.query

    if team_id:
        query = query.filter_by(team_id=team_id)
    if cluster_id:
        query = query.filter_by(cluster_id=cluster_id)
    if enabled is not None:
        query = query.filter_by(enabled=enabled.lower() == "true")

    query = query.order_by(ApplyPolicy.priority.desc(), ApplyPolicy.name)
    policies = query.offset(offset).limit(limit).all()

    return jsonify({
        "policies": [p.to_dict() for p in policies],
        "total": query.count(),
        "limit": limit,
        "offset": offset,
    }), 200


@apply_bp.route("/apply-policies/<policy_id>", methods=["GET"])
def get_policy(policy_id: str):
    """Get apply policy by ID."""
    policy = db.session.get(ApplyPolicy, policy_id)
    if not policy:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Policy not found: {policy_id}",
        }), 404

    return jsonify(policy.to_dict()), 200


@apply_bp.route("/apply-policies/<policy_id>", methods=["PUT"])
def update_policy(policy_id: str):
    """Update an apply policy."""
    policy = db.session.get(ApplyPolicy, policy_id)
    if not policy:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Policy not found: {policy_id}",
        }), 404

    data = request.get_json()
    if not data:
        return jsonify({
            "code": "BAD_REQUEST",
            "message": "Request body is required",
        }), 400

    try:
        req = UpdateApplyPolicyRequest(**data)

        # Update only provided fields
        if req.name is not None:
            policy.name = req.name
        if req.description is not None:
            policy.description = req.description
        if req.require_approval is not None:
            policy.require_approval = req.require_approval
        if req.auto_approve_below_threshold is not None:
            policy.auto_approve_below_threshold = req.auto_approve_below_threshold
        if req.approval_threshold_cpu_percent is not None:
            policy.approval_threshold_cpu_percent = req.approval_threshold_cpu_percent
        if req.approval_threshold_memory_percent is not None:
            policy.approval_threshold_memory_percent = req.approval_threshold_memory_percent
        if req.max_cpu_increase_percent is not None:
            policy.max_cpu_increase_percent = req.max_cpu_increase_percent
        if req.max_cpu_decrease_percent is not None:
            policy.max_cpu_decrease_percent = req.max_cpu_decrease_percent
        if req.max_memory_increase_percent is not None:
            policy.max_memory_increase_percent = req.max_memory_increase_percent
        if req.max_memory_decrease_percent is not None:
            policy.max_memory_decrease_percent = req.max_memory_decrease_percent
        if req.min_cpu_request is not None:
            policy.min_cpu_request = req.min_cpu_request
        if req.min_memory_request is not None:
            policy.min_memory_request = req.min_memory_request
        if req.blackout_windows is not None:
            policy.blackout_windows = [w.model_dump() for w in req.blackout_windows]
        if req.excluded_namespaces is not None:
            policy.excluded_namespaces = req.excluded_namespaces
        if req.excluded_workload_patterns is not None:
            policy.excluded_workload_patterns = req.excluded_workload_patterns
        if req.enabled is not None:
            policy.enabled = req.enabled
        if req.priority is not None:
            policy.priority = req.priority

        db.session.commit()
        return jsonify(policy.to_dict()), 200

    except ValueError as e:
        return jsonify({
            "code": "VALIDATION_ERROR",
            "message": str(e),
        }), 400
    except Exception as e:
        logger.error(f"Failed to update policy: {e}")
        db.session.rollback()
        return jsonify({
            "code": "SERVER_ERROR",
            "message": "Failed to update policy",
        }), 500


@apply_bp.route("/apply-policies/<policy_id>", methods=["DELETE"])
def delete_policy(policy_id: str):
    """Delete an apply policy."""
    policy = db.session.get(ApplyPolicy, policy_id)
    if not policy:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Policy not found: {policy_id}",
        }), 404

    try:
        db.session.delete(policy)
        db.session.commit()
        return "", 204
    except Exception as e:
        logger.error(f"Failed to delete policy: {e}")
        db.session.rollback()
        return jsonify({
            "code": "SERVER_ERROR",
            "message": "Failed to delete policy",
        }), 500


# =============================================================================
# Apply Request Endpoints
# =============================================================================

@apply_bp.route("/apply", methods=["POST"])
def create_apply_request():
    """
    Create a new apply request.

    Request Body:
        suggestion_id (str): ID of suggestion to apply (required)
        cluster_id (str): ID of target cluster (required)
        mode (str): "dry_run" or "apply" (default: dry_run)

    Returns:
        201: Created apply request
        400: Invalid request
        404: Suggestion or cluster not found
        500: Server error
    """
    data = request.get_json()
    if not data:
        return jsonify({
            "code": "BAD_REQUEST",
            "message": "Request body is required",
        }), 400

    try:
        req = CreateApplyRequest(**data)
        service = get_apply_service()

        # Convert mode string to enum
        mode = ApplyMode(req.mode.value if hasattr(req.mode, 'value') else req.mode)

        apply_request = service.create_apply_request(
            suggestion_id=req.suggestion_id,
            cluster_id=req.cluster_id,
            mode=mode,
            user_id=data.get("user_id"),
            team_id=data.get("team_id"),
        )

        return jsonify(apply_request.to_dict()), 201

    except ApplyServiceError as e:
        return jsonify({
            "code": "BAD_REQUEST",
            "message": str(e),
        }), 400
    except ValueError as e:
        return jsonify({
            "code": "VALIDATION_ERROR",
            "message": str(e),
        }), 400
    except Exception as e:
        logger.error(f"Failed to create apply request: {e}")
        return jsonify({
            "code": "SERVER_ERROR",
            "message": "Failed to create apply request",
        }), 500


@apply_bp.route("/apply/batch", methods=["POST"])
def create_batch_apply():
    """
    Create a batch of apply requests.

    Request Body:
        suggestion_ids (list): List of suggestion IDs (required)
        cluster_id (str): ID of target cluster (required)
        mode (str): "dry_run" or "apply" (default: dry_run)
        stop_on_failure (bool): Stop on first failure (default: true)
        name (str): Batch name
        description (str): Batch description

    Returns:
        201: Created batch
        400: Invalid request
        500: Server error
    """
    data = request.get_json()
    if not data:
        return jsonify({
            "code": "BAD_REQUEST",
            "message": "Request body is required",
        }), 400

    try:
        req = CreateBatchApplyRequest(**data)
        service = get_apply_service()

        mode = ApplyMode(req.mode.value if hasattr(req.mode, 'value') else req.mode)

        batch = service.create_batch(
            suggestion_ids=req.suggestion_ids,
            cluster_id=req.cluster_id,
            mode=mode,
            stop_on_failure=req.stop_on_failure,
            name=req.name,
            description=req.description,
            user_id=data.get("user_id"),
            team_id=data.get("team_id"),
        )

        return jsonify(batch.to_dict()), 201

    except ApplyServiceError as e:
        return jsonify({
            "code": "BAD_REQUEST",
            "message": str(e),
        }), 400
    except ValueError as e:
        return jsonify({
            "code": "VALIDATION_ERROR",
            "message": str(e),
        }), 400
    except Exception as e:
        logger.error(f"Failed to create batch: {e}")
        return jsonify({
            "code": "SERVER_ERROR",
            "message": "Failed to create batch",
        }), 500


@apply_bp.route("/apply/requests", methods=["GET"])
def list_apply_requests():
    """
    List apply requests.

    Query Parameters:
        team_id (str): Filter by team
        cluster_id (str): Filter by cluster
        status (str): Filter by status
        limit (int): Max results (default: 100)
        offset (int): Results offset (default: 0)

    Returns:
        200: List of apply requests
    """
    team_id = request.args.get("team_id")
    cluster_id = request.args.get("cluster_id")
    status = request.args.get("status")
    limit = int(request.args.get("limit", 100))
    offset = int(request.args.get("offset", 0))

    service = get_apply_service()

    status_enum = None
    if status:
        try:
            status_enum = ApplyRequestStatus(status)
        except ValueError:
            pass

    requests_list = service.list_requests(
        team_id=team_id,
        cluster_id=cluster_id,
        status=status_enum,
        limit=limit,
        offset=offset,
    )

    return jsonify({
        "requests": [r.to_dict() for r in requests_list],
        "limit": limit,
        "offset": offset,
    }), 200


@apply_bp.route("/apply/requests/<request_id>", methods=["GET"])
def get_apply_request(request_id: str):
    """Get apply request by ID."""
    try:
        service = get_apply_service()
        apply_request = service.get_request(request_id)
        return jsonify(apply_request.to_dict()), 200
    except ApplyRequestNotFoundError:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Apply request not found: {request_id}",
        }), 404


@apply_bp.route("/apply/requests/<request_id>/approve", methods=["POST"])
def approve_apply_request(request_id: str):
    """Approve a pending apply request."""
    data = request.get_json() or {}

    try:
        service = get_apply_service()
        approver_id = data.get("user_id", "system")

        apply_request = service.approve_request(
            request_id=request_id,
            approver_id=approver_id,
        )

        return jsonify(apply_request.to_dict()), 200

    except ApplyRequestNotFoundError:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Apply request not found: {request_id}",
        }), 404
    except InvalidApplyStateError as e:
        return jsonify({
            "code": "INVALID_STATE",
            "message": str(e),
        }), 400


@apply_bp.route("/apply/requests/<request_id>/reject", methods=["POST"])
def reject_apply_request(request_id: str):
    """Reject a pending apply request."""
    data = request.get_json()
    if not data or not data.get("reason"):
        return jsonify({
            "code": "BAD_REQUEST",
            "message": "Rejection reason is required",
        }), 400

    try:
        req = RejectRequestBody(**data)
        service = get_apply_service()
        rejector_id = data.get("user_id", "system")

        apply_request = service.reject_request(
            request_id=request_id,
            rejector_id=rejector_id,
            reason=req.reason,
        )

        return jsonify(apply_request.to_dict()), 200

    except ApplyRequestNotFoundError:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Apply request not found: {request_id}",
        }), 404
    except InvalidApplyStateError as e:
        return jsonify({
            "code": "INVALID_STATE",
            "message": str(e),
        }), 400


@apply_bp.route("/apply/requests/<request_id>/execute", methods=["POST"])
def execute_apply_request(request_id: str):
    """Execute an approved apply request."""
    data = request.get_json() or {}

    try:
        service = get_apply_service()
        executor_id = data.get("user_id")

        apply_request = service.execute_request(
            request_id=request_id,
            executor_id=executor_id,
        )

        return jsonify(apply_request.to_dict()), 200

    except ApplyRequestNotFoundError:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Apply request not found: {request_id}",
        }), 404
    except InvalidApplyStateError as e:
        return jsonify({
            "code": "INVALID_STATE",
            "message": str(e),
        }), 400
    except ApplyServiceError as e:
        return jsonify({
            "code": "APPLY_ERROR",
            "message": str(e),
        }), 500


@apply_bp.route("/apply/requests/<request_id>/rollback", methods=["POST"])
def rollback_apply_request(request_id: str):
    """Rollback a completed apply request."""
    data = request.get_json()
    if not data or not data.get("reason"):
        return jsonify({
            "code": "BAD_REQUEST",
            "message": "Rollback reason is required",
        }), 400

    try:
        req = RollbackRequestBody(**data)
        service = get_apply_service()

        apply_request = service.rollback_request(
            request_id=request_id,
            reason=req.reason,
            user_id=data.get("user_id"),
        )

        return jsonify(apply_request.to_dict()), 200

    except ApplyRequestNotFoundError:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Apply request not found: {request_id}",
        }), 404
    except InvalidApplyStateError as e:
        return jsonify({
            "code": "INVALID_STATE",
            "message": str(e),
        }), 400
    except ApplyServiceError as e:
        return jsonify({
            "code": "ROLLBACK_ERROR",
            "message": str(e),
        }), 500


# =============================================================================
# Batch Endpoints
# =============================================================================

@apply_bp.route("/apply/batches", methods=["GET"])
def list_batches():
    """List apply batches."""
    team_id = request.args.get("team_id")
    cluster_id = request.args.get("cluster_id")
    status = request.args.get("status")
    limit = int(request.args.get("limit", 100))
    offset = int(request.args.get("offset", 0))

    query = ApplyBatch.query

    if team_id:
        query = query.filter_by(team_id=team_id)
    if cluster_id:
        query = query.filter_by(cluster_id=cluster_id)
    if status:
        try:
            status_enum = ApplyRequestStatus(status)
            query = query.filter_by(status=status_enum)
        except ValueError:
            pass

    query = query.order_by(ApplyBatch.created_at.desc())
    batches = query.offset(offset).limit(limit).all()

    return jsonify({
        "batches": [b.to_dict() for b in batches],
        "limit": limit,
        "offset": offset,
    }), 200


@apply_bp.route("/apply/batches/<batch_id>", methods=["GET"])
def get_batch(batch_id: str):
    """Get batch by ID with its requests."""
    batch = db.session.get(ApplyBatch, batch_id)
    if not batch:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Batch not found: {batch_id}",
        }), 404

    # Include requests in response
    requests_list = ApplyRequest.query.filter_by(batch_id=batch_id).all()

    result = batch.to_dict()
    result["requests"] = [r.to_dict() for r in requests_list]

    return jsonify(result), 200


@apply_bp.route("/apply/batches/<batch_id>/approve", methods=["POST"])
def approve_batch(batch_id: str):
    """Approve all pending requests in a batch."""
    data = request.get_json() or {}
    approver_id = data.get("user_id", "system")

    batch = db.session.get(ApplyBatch, batch_id)
    if not batch:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Batch not found: {batch_id}",
        }), 404

    if batch.status != ApplyRequestStatus.PENDING_APPROVAL:
        return jsonify({
            "code": "INVALID_STATE",
            "message": f"Cannot approve batch in {batch.status.value} status",
        }), 400

    service = get_apply_service()

    # Approve all pending requests in batch
    pending_requests = ApplyRequest.query.filter_by(
        batch_id=batch_id,
        status=ApplyRequestStatus.PENDING_APPROVAL
    ).all()

    for apply_request in pending_requests:
        try:
            service.approve_request(apply_request.id, approver_id)
        except Exception as e:
            logger.warning(f"Failed to approve request {apply_request.id}: {e}")

    # Update batch status
    from datetime import datetime, timezone
    batch.status = ApplyRequestStatus.APPROVED
    batch.approved_by_id = approver_id
    batch.approved_at = datetime.now(timezone.utc)
    db.session.commit()

    return jsonify(batch.to_dict()), 200


@apply_bp.route("/apply/batches/<batch_id>/execute", methods=["POST"])
def execute_batch(batch_id: str):
    """Execute all approved requests in a batch."""
    data = request.get_json() or {}

    try:
        service = get_apply_service()
        executor_id = data.get("user_id")

        batch = service.execute_batch(
            batch_id=batch_id,
            executor_id=executor_id,
        )

        return jsonify(batch.to_dict()), 200

    except ApplyServiceError as e:
        return jsonify({
            "code": "BAD_REQUEST",
            "message": str(e),
        }), 400
    except InvalidApplyStateError as e:
        return jsonify({
            "code": "INVALID_STATE",
            "message": str(e),
        }), 400


@apply_bp.route("/apply/batches/<batch_id>/cancel", methods=["POST"])
def cancel_batch(batch_id: str):
    """Cancel a pending batch."""
    batch = db.session.get(ApplyBatch, batch_id)
    if not batch:
        return jsonify({
            "code": "NOT_FOUND",
            "message": f"Batch not found: {batch_id}",
        }), 404

    if batch.status not in [ApplyRequestStatus.PENDING_APPROVAL, ApplyRequestStatus.APPROVED]:
        return jsonify({
            "code": "INVALID_STATE",
            "message": f"Cannot cancel batch in {batch.status.value} status",
        }), 400

    # Cancel all pending requests in batch
    ApplyRequest.query.filter_by(
        batch_id=batch_id
    ).filter(
        ApplyRequest.status.in_([
            ApplyRequestStatus.PENDING_APPROVAL,
            ApplyRequestStatus.APPROVED
        ])
    ).update({"status": ApplyRequestStatus.REJECTED})

    batch.status = ApplyRequestStatus.REJECTED
    db.session.commit()

    return jsonify(batch.to_dict()), 200


# =============================================================================
# Convenience Endpoints
# =============================================================================

@apply_bp.route("/suggestions/<suggestion_id>/apply", methods=["POST"])
def quick_apply_suggestion(suggestion_id: str):
    """Quick apply a single suggestion."""
    data = request.get_json() or {}

    cluster_id = data.get("cluster_id")
    if not cluster_id:
        return jsonify({
            "code": "BAD_REQUEST",
            "message": "cluster_id is required",
        }), 400

    try:
        service = get_apply_service()
        mode = ApplyMode(data.get("mode", "dry_run"))

        apply_request = service.create_apply_request(
            suggestion_id=suggestion_id,
            cluster_id=cluster_id,
            mode=mode,
            user_id=data.get("user_id"),
            team_id=data.get("team_id"),
        )

        # If auto-approved and mode is apply, execute immediately
        if apply_request.status == ApplyRequestStatus.APPROVED and not apply_request.requires_approval:
            apply_request = service.execute_request(
                apply_request.id,
                data.get("user_id")
            )

        return jsonify(apply_request.to_dict()), 201

    except ApplyServiceError as e:
        return jsonify({
            "code": "BAD_REQUEST",
            "message": str(e),
        }), 400


@apply_bp.route("/apply/history", methods=["GET"])
def get_apply_history():
    """Get apply request history with filters."""
    team_id = request.args.get("team_id")
    cluster_id = request.args.get("cluster_id")
    status = request.args.get("status")
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))

    query = ApplyRequest.query

    if team_id:
        query = query.filter_by(team_id=team_id)
    if cluster_id:
        query = query.filter_by(cluster_id=cluster_id)
    if status:
        try:
            status_enum = ApplyRequestStatus(status)
            query = query.filter_by(status=status_enum)
        except ValueError:
            pass

    query = query.order_by(ApplyRequest.created_at.desc())

    total = query.count()
    offset = (page - 1) * per_page
    requests_list = query.offset(offset).limit(per_page).all()

    return jsonify({
        "requests": [r.to_dict() for r in requests_list],
        "total": total,
        "page": page,
        "per_page": per_page,
    }), 200
