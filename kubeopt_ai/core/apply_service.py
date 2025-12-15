"""
Apply service for KubeOpt AI.

Orchestrates the recommendation apply workflow, including approval,
guardrails, execution, rollback, and audit logging.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from kubeopt_ai.extensions import db
from kubeopt_ai.core.models import (
    ApplyBatch,
    ApplyMode,
    ApplyPolicy,
    ApplyRequest,
    ApplyRequestStatus,
    AuditAction,
    Cluster,
    Suggestion,
)
from kubeopt_ai.core.k8s_apply import K8sApplyService, K8sApplyError
from kubeopt_ai.core.guardrails import GuardrailService
from kubeopt_ai.core.audit import AuditService

logger = logging.getLogger(__name__)


class ApplyServiceError(Exception):
    """Exception raised for apply service errors."""
    pass


class ApplyRequestNotFoundError(ApplyServiceError):
    """Exception raised when an apply request is not found."""
    pass


class ApplyPolicyNotFoundError(ApplyServiceError):
    """Exception raised when an apply policy is not found."""
    pass


class InvalidApplyStateError(ApplyServiceError):
    """Exception raised when operation is invalid for current state."""
    pass


class ApplyService:
    """
    Orchestrates the recommendation apply workflow.

    Handles approval workflows, guardrail validation, execution,
    rollback, and audit logging integration.
    """

    def __init__(
        self,
        guardrail_service: Optional[GuardrailService] = None,
        audit_service: Optional[AuditService] = None,
    ):
        """
        Initialize the apply service.

        Args:
            guardrail_service: Service for guardrail validation.
            audit_service: Service for audit logging.
        """
        self.guardrail_service = guardrail_service or GuardrailService()
        self.audit_service = audit_service

    def create_apply_request(
        self,
        suggestion_id: str,
        cluster_id: str,
        mode: ApplyMode = ApplyMode.DRY_RUN,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> ApplyRequest:
        """
        Create a new apply request.

        Runs guardrail checks and determines if approval is needed.

        Args:
            suggestion_id: ID of the suggestion to apply.
            cluster_id: ID of the target cluster.
            mode: Apply mode (dry_run or apply).
            user_id: ID of the user creating the request.
            team_id: ID of the team.

        Returns:
            The created ApplyRequest.

        Raises:
            ApplyServiceError: If creation fails.
        """
        # Get suggestion
        suggestion = db.session.get(Suggestion, suggestion_id)
        if not suggestion:
            raise ApplyServiceError(f"Suggestion not found: {suggestion_id}")

        # Get cluster
        cluster = db.session.get(Cluster, cluster_id)
        if not cluster:
            raise ApplyServiceError(f"Cluster not found: {cluster_id}")

        # Get effective policy
        policy = self._get_effective_policy(cluster_id, team_id, suggestion.workload_snapshot.namespace)

        # Run guardrail checks
        guardrail_results = {}
        requires_approval = True

        if policy:
            results = self.guardrail_service.check_all(suggestion, policy, cluster)
            guardrail_results = self.guardrail_service.results_to_dict(results)

            # Check if auto-approval is possible
            if not self.guardrail_service.has_any_failure(results):
                requires_approval = policy.require_approval
                if self.guardrail_service.should_auto_approve(suggestion, policy):
                    requires_approval = False

        # Determine initial status
        if mode == ApplyMode.DRY_RUN:
            # Dry-run doesn't need approval
            initial_status = ApplyRequestStatus.APPROVED
            requires_approval = False
        elif not requires_approval:
            initial_status = ApplyRequestStatus.APPROVED
        else:
            initial_status = ApplyRequestStatus.PENDING_APPROVAL

        # Create the request
        apply_request = ApplyRequest(
            suggestion_id=suggestion_id,
            cluster_id=cluster_id,
            team_id=team_id,
            mode=mode,
            status=initial_status,
            requires_approval=requires_approval,
            apply_policy_id=policy.id if policy else None,
            proposed_config=suggestion.proposed_config,
            guardrail_results=guardrail_results,
            created_by_id=user_id,
        )

        # If auto-approved, set approval timestamp
        if initial_status == ApplyRequestStatus.APPROVED and not requires_approval:
            apply_request.approved_at = datetime.now(timezone.utc)

        db.session.add(apply_request)
        db.session.commit()

        # Log audit
        if self.audit_service:
            self.audit_service.log(
                action=AuditAction.CREATE,
                resource_type="apply_request",
                resource_id=apply_request.id,
                details={
                    "suggestion_id": suggestion_id,
                    "cluster_id": cluster_id,
                    "mode": mode.value,
                    "requires_approval": requires_approval,
                }
            )

        logger.info(f"Created apply request {apply_request.id} for suggestion {suggestion_id}")
        return apply_request

    def approve_request(
        self,
        request_id: str,
        approver_id: str,
    ) -> ApplyRequest:
        """
        Approve a pending apply request.

        Args:
            request_id: ID of the apply request.
            approver_id: ID of the user approving.

        Returns:
            The updated ApplyRequest.

        Raises:
            ApplyRequestNotFoundError: If request is not found.
            InvalidApplyStateError: If request is not pending approval.
        """
        apply_request = self._get_request(request_id)

        if apply_request.status != ApplyRequestStatus.PENDING_APPROVAL:
            raise InvalidApplyStateError(
                f"Cannot approve request in {apply_request.status.value} status"
            )

        apply_request.status = ApplyRequestStatus.APPROVED
        apply_request.approved_by_id = approver_id
        apply_request.approved_at = datetime.now(timezone.utc)

        db.session.commit()

        # Log audit
        if self.audit_service:
            self.audit_service.log(
                action=AuditAction.UPDATE,
                resource_type="apply_request",
                resource_id=request_id,
                details={"action": "approve", "approver_id": approver_id}
            )

        logger.info(f"Approved apply request {request_id}")
        return apply_request

    def reject_request(
        self,
        request_id: str,
        rejector_id: str,
        reason: str,
    ) -> ApplyRequest:
        """
        Reject an apply request.

        Args:
            request_id: ID of the apply request.
            rejector_id: ID of the user rejecting.
            reason: Reason for rejection.

        Returns:
            The updated ApplyRequest.

        Raises:
            ApplyRequestNotFoundError: If request is not found.
            InvalidApplyStateError: If request is not pending approval.
        """
        apply_request = self._get_request(request_id)

        if apply_request.status != ApplyRequestStatus.PENDING_APPROVAL:
            raise InvalidApplyStateError(
                f"Cannot reject request in {apply_request.status.value} status"
            )

        apply_request.status = ApplyRequestStatus.REJECTED
        apply_request.rejection_reason = reason

        db.session.commit()

        # Log audit
        if self.audit_service:
            self.audit_service.log(
                action=AuditAction.UPDATE,
                resource_type="apply_request",
                resource_id=request_id,
                details={"action": "reject", "rejector_id": rejector_id, "reason": reason}
            )

        logger.info(f"Rejected apply request {request_id}: {reason}")
        return apply_request

    def execute_request(
        self,
        request_id: str,
        executor_id: Optional[str] = None,
    ) -> ApplyRequest:
        """
        Execute an approved apply request.

        Captures pre-apply state, applies the change, and logs the result.

        Args:
            request_id: ID of the apply request.
            executor_id: ID of the user executing (optional).

        Returns:
            The updated ApplyRequest.

        Raises:
            ApplyRequestNotFoundError: If request is not found.
            InvalidApplyStateError: If request is not approved.
            ApplyServiceError: If execution fails.
        """
        apply_request = self._get_request(request_id)

        if apply_request.status != ApplyRequestStatus.APPROVED:
            raise InvalidApplyStateError(
                f"Cannot execute request in {apply_request.status.value} status"
            )

        # Update status to in-progress
        apply_request.status = ApplyRequestStatus.IN_PROGRESS
        apply_request.started_at = datetime.now(timezone.utc)
        db.session.commit()

        try:
            # Get suggestion and cluster
            suggestion = apply_request.suggestion
            cluster = apply_request.cluster

            # Create K8s apply service
            k8s_service = K8sApplyService(cluster)

            try:
                # Build patch from suggestion
                resource_patch = k8s_service.build_patch_from_suggestion(suggestion)

                # Apply based on suggestion type
                dry_run = apply_request.mode == ApplyMode.DRY_RUN

                if suggestion.suggestion_type == "hpa":
                    result = k8s_service.apply_hpa(
                        namespace=resource_patch.namespace,
                        name=resource_patch.name,
                        hpa_spec=resource_patch.patch,
                        dry_run=dry_run
                    )
                else:
                    result = k8s_service.apply_patch(
                        namespace=resource_patch.namespace,
                        kind=resource_patch.kind,
                        name=resource_patch.name,
                        patch=resource_patch.patch,
                        dry_run=dry_run
                    )

                # Update request with results
                apply_request.completed_at = datetime.now(timezone.utc)
                apply_request.duration_ms = result.duration_ms
                apply_request.kubectl_output = result.output

                if result.success:
                    apply_request.status = ApplyRequestStatus.COMPLETED
                    if result.previous_config:
                        apply_request.previous_config = result.previous_config
                else:
                    apply_request.status = ApplyRequestStatus.FAILED
                    apply_request.error_message = result.message

            finally:
                k8s_service.close()

        except Exception as e:
            apply_request.status = ApplyRequestStatus.FAILED
            apply_request.completed_at = datetime.now(timezone.utc)
            apply_request.error_message = str(e)
            logger.error(f"Apply request {request_id} failed: {e}")

        db.session.commit()

        # Log audit
        if self.audit_service:
            self.audit_service.log(
                action=AuditAction.APPLY,
                resource_type="apply_request",
                resource_id=request_id,
                details={
                    "status": apply_request.status.value,
                    "mode": apply_request.mode.value,
                    "executor_id": executor_id,
                    "duration_ms": apply_request.duration_ms,
                }
            )

        logger.info(f"Executed apply request {request_id}: {apply_request.status.value}")
        return apply_request

    def rollback_request(
        self,
        request_id: str,
        reason: str,
        user_id: Optional[str] = None,
    ) -> ApplyRequest:
        """
        Roll back a completed apply to previous state.

        Args:
            request_id: ID of the apply request.
            reason: Reason for rollback.
            user_id: ID of the user initiating rollback.

        Returns:
            The updated ApplyRequest.

        Raises:
            ApplyRequestNotFoundError: If request is not found.
            InvalidApplyStateError: If request cannot be rolled back.
            ApplyServiceError: If rollback fails.
        """
        apply_request = self._get_request(request_id)

        if apply_request.status != ApplyRequestStatus.COMPLETED:
            raise InvalidApplyStateError(
                f"Cannot rollback request in {apply_request.status.value} status"
            )

        if apply_request.rolled_back:
            raise InvalidApplyStateError("Request has already been rolled back")

        if not apply_request.previous_config:
            raise InvalidApplyStateError("No previous configuration stored for rollback")

        # Get suggestion and cluster
        suggestion = apply_request.suggestion
        cluster = apply_request.cluster
        workload = suggestion.workload_snapshot

        # Create K8s apply service
        k8s_service = K8sApplyService(cluster)

        try:
            result = k8s_service.rollback(
                namespace=workload.namespace,
                kind=workload.kind.value if hasattr(workload.kind, 'value') else workload.kind,
                name=workload.name,
                previous_config=apply_request.previous_config
            )

            if result.success:
                apply_request.rolled_back = True
                apply_request.rolled_back_at = datetime.now(timezone.utc)
                apply_request.rolled_back_by_id = user_id
                apply_request.rollback_reason = reason
                apply_request.status = ApplyRequestStatus.ROLLED_BACK
            else:
                raise ApplyServiceError(f"Rollback failed: {result.message}")

        finally:
            k8s_service.close()

        db.session.commit()

        # Log audit
        if self.audit_service:
            self.audit_service.log(
                action=AuditAction.REVERT,
                resource_type="apply_request",
                resource_id=request_id,
                details={"reason": reason, "user_id": user_id}
            )

        logger.info(f"Rolled back apply request {request_id}: {reason}")
        return apply_request

    def create_batch(
        self,
        suggestion_ids: list[str],
        cluster_id: str,
        mode: ApplyMode = ApplyMode.DRY_RUN,
        stop_on_failure: bool = True,
        name: Optional[str] = None,
        description: Optional[str] = None,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> ApplyBatch:
        """
        Create a batch of apply requests.

        Args:
            suggestion_ids: List of suggestion IDs to include.
            cluster_id: ID of the target cluster.
            mode: Apply mode for all requests.
            stop_on_failure: Whether to stop on first failure.
            name: Optional batch name.
            description: Optional batch description.
            user_id: ID of the user creating the batch.
            team_id: ID of the team.

        Returns:
            The created ApplyBatch.
        """
        # Verify cluster exists
        cluster = db.session.get(Cluster, cluster_id)
        if not cluster:
            raise ApplyServiceError(f"Cluster not found: {cluster_id}")

        # Create batch
        batch = ApplyBatch(
            name=name,
            description=description,
            cluster_id=cluster_id,
            team_id=team_id,
            mode=mode,
            stop_on_failure=stop_on_failure,
            total_requests=len(suggestion_ids),
            created_by_id=user_id,
        )

        db.session.add(batch)
        db.session.flush()  # Get batch ID

        # Create individual apply requests
        for suggestion_id in suggestion_ids:
            try:
                apply_request = self.create_apply_request(
                    suggestion_id=suggestion_id,
                    cluster_id=cluster_id,
                    mode=mode,
                    user_id=user_id,
                    team_id=team_id,
                )
                apply_request.batch_id = batch.id
            except Exception as e:
                logger.warning(f"Failed to create apply request for {suggestion_id}: {e}")
                batch.total_requests -= 1

        # Determine batch approval status
        pending_count = ApplyRequest.query.filter_by(
            batch_id=batch.id,
            status=ApplyRequestStatus.PENDING_APPROVAL
        ).count()

        if pending_count > 0:
            batch.requires_approval = True
            batch.status = ApplyRequestStatus.PENDING_APPROVAL
        else:
            batch.requires_approval = False
            batch.status = ApplyRequestStatus.APPROVED

        db.session.commit()

        logger.info(f"Created apply batch {batch.id} with {batch.total_requests} requests")
        return batch

    def execute_batch(
        self,
        batch_id: str,
        executor_id: Optional[str] = None,
    ) -> ApplyBatch:
        """
        Execute all approved requests in a batch.

        Args:
            batch_id: ID of the apply batch.
            executor_id: ID of the user executing.

        Returns:
            The updated ApplyBatch.
        """
        batch = db.session.get(ApplyBatch, batch_id)
        if not batch:
            raise ApplyServiceError(f"Batch not found: {batch_id}")

        if batch.status != ApplyRequestStatus.APPROVED:
            raise InvalidApplyStateError(
                f"Cannot execute batch in {batch.status.value} status"
            )

        batch.status = ApplyRequestStatus.IN_PROGRESS
        batch.started_at = datetime.now(timezone.utc)
        db.session.commit()

        # Get approved requests in batch
        requests = ApplyRequest.query.filter_by(
            batch_id=batch_id,
            status=ApplyRequestStatus.APPROVED
        ).all()

        for apply_request in requests:
            try:
                self.execute_request(apply_request.id, executor_id)
                batch.completed_requests += 1

                if apply_request.status == ApplyRequestStatus.FAILED:
                    batch.failed_requests += 1
                    if batch.stop_on_failure:
                        batch.status = ApplyRequestStatus.FAILED
                        break

            except Exception as e:
                logger.error(f"Failed to execute request {apply_request.id}: {e}")
                batch.failed_requests += 1
                if batch.stop_on_failure:
                    batch.status = ApplyRequestStatus.FAILED
                    break

        # Update batch status
        if batch.status == ApplyRequestStatus.IN_PROGRESS:
            if batch.failed_requests > 0:
                batch.status = ApplyRequestStatus.FAILED
            else:
                batch.status = ApplyRequestStatus.COMPLETED

        batch.completed_at = datetime.now(timezone.utc)
        db.session.commit()

        logger.info(f"Executed batch {batch_id}: {batch.completed_requests}/{batch.total_requests} completed")
        return batch

    def get_request(self, request_id: str) -> ApplyRequest:
        """Get an apply request by ID."""
        return self._get_request(request_id)

    def get_policy(self, policy_id: str) -> ApplyPolicy:
        """Get an apply policy by ID."""
        policy = db.session.get(ApplyPolicy, policy_id)
        if not policy:
            raise ApplyPolicyNotFoundError(f"Policy not found: {policy_id}")
        return policy

    def list_requests(
        self,
        team_id: Optional[str] = None,
        cluster_id: Optional[str] = None,
        status: Optional[ApplyRequestStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ApplyRequest]:
        """List apply requests with optional filters."""
        query = ApplyRequest.query

        if team_id:
            query = query.filter_by(team_id=team_id)
        if cluster_id:
            query = query.filter_by(cluster_id=cluster_id)
        if status:
            query = query.filter_by(status=status)

        query = query.order_by(ApplyRequest.created_at.desc())
        return query.offset(offset).limit(limit).all()

    def _get_request(self, request_id: str) -> ApplyRequest:
        """Get an apply request by ID."""
        apply_request = db.session.get(ApplyRequest, request_id)
        if not apply_request:
            raise ApplyRequestNotFoundError(f"Apply request not found: {request_id}")
        return apply_request

    def _get_effective_policy(
        self,
        cluster_id: str,
        team_id: Optional[str],
        namespace: str
    ) -> Optional[ApplyPolicy]:
        """
        Get the highest-priority applicable policy.

        Priority order:
        1. Cluster-specific + team-specific
        2. Cluster-specific
        3. Team-specific
        4. Global (no cluster, no team)
        """
        query = ApplyPolicy.query.filter_by(enabled=True)

        # Build candidates with priority
        candidates = []

        # Cluster + team specific
        if team_id:
            policy = query.filter_by(
                cluster_id=cluster_id,
                team_id=team_id
            ).order_by(ApplyPolicy.priority.desc()).first()
            if policy:
                candidates.append((4, policy))

        # Cluster specific
        policy = query.filter_by(
            cluster_id=cluster_id,
            team_id=None
        ).order_by(ApplyPolicy.priority.desc()).first()
        if policy:
            candidates.append((3, policy))

        # Team specific
        if team_id:
            policy = query.filter_by(
                cluster_id=None,
                team_id=team_id
            ).order_by(ApplyPolicy.priority.desc()).first()
            if policy:
                candidates.append((2, policy))

        # Global
        policy = query.filter_by(
            cluster_id=None,
            team_id=None
        ).order_by(ApplyPolicy.priority.desc()).first()
        if policy:
            candidates.append((1, policy))

        # Return highest priority
        if candidates:
            candidates.sort(key=lambda x: (x[0], x[1].priority), reverse=True)
            return candidates[0][1]

        return None


# Module-level instance
_service: Optional[ApplyService] = None


def get_apply_service(
    guardrail_service: Optional[GuardrailService] = None,
    audit_service: Optional[AuditService] = None,
) -> ApplyService:
    """Get or create the apply service instance."""
    global _service
    if _service is None:
        _service = ApplyService(guardrail_service, audit_service)
    return _service
