"""
Optimizer service orchestration for KubeOpt AI.

This module provides the high-level orchestration logic that ties together
the K8s scanner, metrics collector, LLM client, and database operations
to perform end-to-end optimization runs.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from kubeopt_ai.extensions import db
from kubeopt_ai.core.models import (
    OptimizationRun,
    WorkloadSnapshot,
    Suggestion,
    RunStatus,
    WorkloadKind,
)
from kubeopt_ai.core.k8s_scanner import K8sScanner, scan_manifests, ManifestScanError
from kubeopt_ai.core.metrics_collector import (
    MetricsCollector,
    MetricsCollectionError,
)
from kubeopt_ai.core.yaml_diff import YAMLDiffGenerator, generate_diff_for_suggestion
from kubeopt_ai.core.schemas import WorkloadDescriptor, WorkloadMetrics
from kubeopt_ai.llm.client import (
    ClaudeLLMClient,
    MockLLMClient,
    LLMClientError,
    LLMResponseValidationError,
)

logger = logging.getLogger(__name__)


class OptimizationError(Exception):
    """Exception raised when optimization fails."""
    pass


class OptimizerService:
    """
    Service for orchestrating Kubernetes resource optimization.

    Coordinates the scanning of manifests, collection of metrics,
    LLM-based suggestion generation, and persistence of results.
    """

    def __init__(
        self,
        prometheus_url: Optional[str] = None,
        llm_api_key: Optional[str] = None,
        llm_model_name: str = "claude-sonnet-4-20250514",
        use_mock_llm: bool = False,
    ):
        """
        Initialize the optimizer service.

        Args:
            prometheus_url: URL for Prometheus server.
            llm_api_key: API key for Claude.
            llm_model_name: Claude model to use.
            use_mock_llm: If True, use mock LLM client for testing.
        """
        self._scanner = K8sScanner()
        self._metrics_collector = MetricsCollector(prometheus_url=prometheus_url)
        self._diff_generator = YAMLDiffGenerator()

        if use_mock_llm:
            self._llm_client = MockLLMClient()
        elif llm_api_key:
            self._llm_client = ClaudeLLMClient(
                api_key=llm_api_key,
                model_name=llm_model_name,
            )
        else:
            self._llm_client = None

    def run_optimization(
        self,
        manifest_path: str,
        lookback_days: int = 7,
        skip_metrics: bool = False,
    ) -> OptimizationRun:
        """
        Execute a complete optimization run.

        Args:
            manifest_path: Path to directory or file with K8s manifests.
            lookback_days: Number of days to look back for metrics.
            skip_metrics: If True, skip metrics collection (for testing).

        Returns:
            The completed OptimizationRun with results.

        Raises:
            OptimizationError: If the optimization fails.
        """
        # Create the run record
        run = OptimizationRun(
            manifest_source_path=manifest_path,
            lookback_days=lookback_days,
            status=RunStatus.RUNNING,
        )
        db.session.add(run)
        db.session.commit()

        logger.info(f"Starting optimization run {run.id} for path: {manifest_path}")

        try:
            # Step 1: Scan manifests
            workloads = self._scan_manifests(manifest_path)
            logger.info(f"Found {len(workloads)} workloads to optimize")

            if not workloads:
                run.status = RunStatus.COMPLETED
                run.error_message = "No workloads found in manifests"
                db.session.commit()
                return run

            # Step 2: Collect metrics for each workload
            metrics = []
            if not skip_metrics:
                metrics = self._collect_metrics(workloads, lookback_days)
            else:
                # Generate empty metrics for testing
                metrics = [
                    WorkloadMetrics(
                        workload_name=w.name,
                        namespace=w.namespace,
                        lookback_days=lookback_days,
                        container_metrics=[],
                    )
                    for w in workloads
                ]

            # Step 3: Create workload snapshots in database
            snapshots = self._create_snapshots(run, workloads, metrics)

            # Step 4: Generate suggestions via LLM
            if self._llm_client:
                suggestions_response = self._generate_suggestions(workloads, metrics)

                # Step 5: Store suggestions and generate diffs
                self._store_suggestions(run, snapshots, suggestions_response)

            # Mark run as completed
            run.status = RunStatus.COMPLETED
            run.updated_at = datetime.now(timezone.utc)
            db.session.commit()

            logger.info(f"Optimization run {run.id} completed successfully")
            return run

        except Exception as e:
            logger.exception(f"Optimization run {run.id} failed: {e}")
            run.status = RunStatus.FAILED
            run.error_message = str(e)
            run.updated_at = datetime.now(timezone.utc)
            db.session.commit()
            raise OptimizationError(f"Optimization failed: {e}") from e

    def _scan_manifests(self, manifest_path: str) -> list[WorkloadDescriptor]:
        """Scan manifests and return workload descriptors."""
        try:
            return self._scanner.scan_directory(manifest_path)
        except ManifestScanError as e:
            raise OptimizationError(f"Failed to scan manifests: {e}") from e

    def _collect_metrics(
        self,
        workloads: list[WorkloadDescriptor],
        lookback_days: int
    ) -> list[WorkloadMetrics]:
        """Collect metrics for all workloads."""
        metrics = []
        for workload in workloads:
            try:
                workload_metrics = self._metrics_collector.get_workload_metrics(
                    workload, lookback_days
                )
                metrics.append(workload_metrics)
            except MetricsCollectionError as e:
                logger.warning(f"Failed to collect metrics for {workload.name}: {e}")
                # Continue with empty metrics
                metrics.append(WorkloadMetrics(
                    workload_name=workload.name,
                    namespace=workload.namespace,
                    lookback_days=lookback_days,
                    container_metrics=[],
                ))
        return metrics

    def _create_snapshots(
        self,
        run: OptimizationRun,
        workloads: list[WorkloadDescriptor],
        metrics: list[WorkloadMetrics],
    ) -> dict[str, WorkloadSnapshot]:
        """Create workload snapshots in the database."""
        snapshots = {}

        # Create lookup for metrics
        metrics_lookup = {
            (m.workload_name, m.namespace): m
            for m in metrics
        }

        for workload in workloads:
            # Get corresponding metrics
            workload_metrics = metrics_lookup.get(
                (workload.name, workload.namespace)
            )

            # Map kind string to enum
            kind_str = workload.kind if isinstance(workload.kind, str) else workload.kind.value
            kind = WorkloadKind(kind_str)

            snapshot = WorkloadSnapshot(
                run_id=run.id,
                name=workload.name,
                namespace=workload.namespace,
                kind=kind,
                current_config=workload.model_dump(),
                metrics_summary=workload_metrics.model_dump() if workload_metrics else {},
            )
            db.session.add(snapshot)
            snapshots[f"{workload.namespace}/{workload.name}"] = snapshot

        db.session.commit()
        return snapshots

    def _generate_suggestions(
        self,
        workloads: list[WorkloadDescriptor],
        metrics: list[WorkloadMetrics],
    ):
        """Generate optimization suggestions via LLM."""
        try:
            return self._llm_client.generate_optimization_suggestions(
                workloads, metrics
            )
        except (LLMClientError, LLMResponseValidationError) as e:
            raise OptimizationError(f"Failed to generate suggestions: {e}") from e

    def _store_suggestions(
        self,
        run: OptimizationRun,
        snapshots: dict[str, WorkloadSnapshot],
        suggestions_response,
    ) -> None:
        """Store suggestions in the database."""
        for workload_suggestion in suggestions_response.workloads:
            key = f"{workload_suggestion.namespace}/{workload_suggestion.name}"
            snapshot = snapshots.get(key)

            if not snapshot:
                logger.warning(
                    f"No snapshot found for workload {key}, skipping suggestions"
                )
                continue

            # Generate diff text for this workload
            diff_text = generate_diff_for_suggestion(workload_suggestion)

            # Store container suggestions
            for container_suggestion in workload_suggestion.suggestions:
                suggestion = Suggestion(
                    workload_snapshot_id=snapshot.id,
                    container_name=container_suggestion.container,
                    suggestion_type="resources",
                    current_config=container_suggestion.current.model_dump(),
                    proposed_config=container_suggestion.proposed.model_dump(),
                    reasoning=container_suggestion.reasoning,
                    diff_text=diff_text,
                )
                db.session.add(suggestion)

            # Store HPA suggestion if present
            if workload_suggestion.hpa:
                hpa_suggestion = Suggestion(
                    workload_snapshot_id=snapshot.id,
                    container_name="_hpa",  # Special marker for HPA
                    suggestion_type="hpa",
                    current_config=workload_suggestion.hpa.current.model_dump()
                        if workload_suggestion.hpa.current else {},
                    proposed_config=workload_suggestion.hpa.proposed.model_dump()
                        if workload_suggestion.hpa.proposed else {},
                    reasoning=workload_suggestion.hpa.reasoning,
                    diff_text=None,
                )
                db.session.add(hpa_suggestion)

        db.session.commit()

    def get_run_details(self, run_id: str) -> Optional[dict]:
        """
        Get details of an optimization run.

        Args:
            run_id: The optimization run ID.

        Returns:
            Dictionary with run details, workloads, and suggestions.
        """
        run = db.session.get(OptimizationRun, run_id)
        if not run:
            return None

        # Get workload snapshots
        snapshots = WorkloadSnapshot.query.filter_by(run_id=run_id).all()

        # Get suggestions for all snapshots
        snapshot_ids = [s.id for s in snapshots]
        suggestions = Suggestion.query.filter(
            Suggestion.workload_snapshot_id.in_(snapshot_ids)
        ).all()

        return {
            "run": run.to_dict(),
            "workloads": [s.to_dict() for s in snapshots],
            "suggestions": [s.to_dict() for s in suggestions],
            "summary": {
                "workload_count": len(snapshots),
                "suggestion_count": len(suggestions),
                "status": run.status.value,
            },
        }


def create_optimizer_service(
    app_config: Optional[dict] = None,
    use_mock_llm: bool = False,
) -> OptimizerService:
    """
    Factory function to create an optimizer service with configuration.

    Args:
        app_config: Application configuration dictionary.
        use_mock_llm: If True, use mock LLM for testing.

    Returns:
        Configured OptimizerService instance.
    """
    config = app_config or {}

    return OptimizerService(
        prometheus_url=config.get("PROMETHEUS_BASE_URL"),
        llm_api_key=config.get("LLM_API_KEY"),
        llm_model_name=config.get("LLM_MODEL_NAME", "claude-sonnet-4-20250514"),
        use_mock_llm=use_mock_llm,
    )
