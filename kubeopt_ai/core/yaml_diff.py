"""
YAML diff generation for KubeOpt AI.

This module generates human-readable diff-style output showing
the proposed changes to Kubernetes resource configurations.
"""

import logging
from dataclasses import dataclass
from typing import Optional
from io import StringIO

from ruamel.yaml import YAML

from kubeopt_ai.core.schemas import (
    WorkloadSuggestion,
    ContainerSuggestion,
    HPASuggestion,
)

logger = logging.getLogger(__name__)


@dataclass
class ResourceChange:
    """Represents a single resource value change."""
    path: str
    old_value: Optional[str]
    new_value: Optional[str]


@dataclass
class ContainerDiff:
    """Diff for a single container's resource changes."""
    container_name: str
    changes: list[ResourceChange]
    reasoning: str


@dataclass
class HPADiff:
    """Diff for HPA configuration changes."""
    changes: list[ResourceChange]
    reasoning: str


@dataclass
class WorkloadDiff:
    """Complete diff for a workload including all containers and HPA."""
    workload_name: str
    namespace: str
    kind: str
    container_diffs: list[ContainerDiff]
    hpa_diff: Optional[HPADiff]


class YAMLDiffGenerator:
    """
    Generates diff-style output for Kubernetes resource changes.

    Creates human-readable diffs showing old vs new values for
    resource requests, limits, and HPA configuration.
    """

    def __init__(self):
        """Initialize the diff generator."""
        self._yaml = YAML()
        self._yaml.default_flow_style = False

    def generate_workload_diff(
        self,
        suggestion: WorkloadSuggestion
    ) -> WorkloadDiff:
        """
        Generate a structured diff for a workload suggestion.

        Args:
            suggestion: LLM-generated workload suggestion.

        Returns:
            WorkloadDiff containing all changes.
        """
        container_diffs = []

        for container_suggestion in suggestion.suggestions:
            diff = self._generate_container_diff(container_suggestion)
            container_diffs.append(diff)

        hpa_diff = None
        if suggestion.hpa:
            hpa_diff = self._generate_hpa_diff(suggestion.hpa)

        return WorkloadDiff(
            workload_name=suggestion.name,
            namespace=suggestion.namespace,
            kind=suggestion.kind,
            container_diffs=container_diffs,
            hpa_diff=hpa_diff,
        )

    def _generate_container_diff(
        self,
        suggestion: ContainerSuggestion
    ) -> ContainerDiff:
        """Generate diff for a container's resources."""
        changes = []

        # Compare requests
        if suggestion.current.requests and suggestion.proposed.requests:
            if suggestion.current.requests.cpu != suggestion.proposed.requests.cpu:
                changes.append(ResourceChange(
                    path="resources.requests.cpu",
                    old_value=suggestion.current.requests.cpu,
                    new_value=suggestion.proposed.requests.cpu,
                ))
            if suggestion.current.requests.memory != suggestion.proposed.requests.memory:
                changes.append(ResourceChange(
                    path="resources.requests.memory",
                    old_value=suggestion.current.requests.memory,
                    new_value=suggestion.proposed.requests.memory,
                ))

        # Compare limits
        if suggestion.current.limits and suggestion.proposed.limits:
            if suggestion.current.limits.cpu != suggestion.proposed.limits.cpu:
                changes.append(ResourceChange(
                    path="resources.limits.cpu",
                    old_value=suggestion.current.limits.cpu,
                    new_value=suggestion.proposed.limits.cpu,
                ))
            if suggestion.current.limits.memory != suggestion.proposed.limits.memory:
                changes.append(ResourceChange(
                    path="resources.limits.memory",
                    old_value=suggestion.current.limits.memory,
                    new_value=suggestion.proposed.limits.memory,
                ))

        return ContainerDiff(
            container_name=suggestion.container,
            changes=changes,
            reasoning=suggestion.reasoning,
        )

    def _generate_hpa_diff(self, suggestion: HPASuggestion) -> HPADiff:
        """Generate diff for HPA configuration."""
        changes = []

        current = suggestion.current
        proposed = suggestion.proposed

        if current and proposed:
            if current.min_replicas != proposed.min_replicas:
                changes.append(ResourceChange(
                    path="spec.minReplicas",
                    old_value=str(current.min_replicas) if current.min_replicas else None,
                    new_value=str(proposed.min_replicas) if proposed.min_replicas else None,
                ))
            if current.max_replicas != proposed.max_replicas:
                changes.append(ResourceChange(
                    path="spec.maxReplicas",
                    old_value=str(current.max_replicas) if current.max_replicas else None,
                    new_value=str(proposed.max_replicas) if proposed.max_replicas else None,
                ))
            if current.target_cpu_percent != proposed.target_cpu_percent:
                changes.append(ResourceChange(
                    path="spec.metrics[cpu].target.averageUtilization",
                    old_value=str(current.target_cpu_percent) if current.target_cpu_percent else None,
                    new_value=str(proposed.target_cpu_percent) if proposed.target_cpu_percent else None,
                ))
            if current.target_memory_percent != proposed.target_memory_percent:
                changes.append(ResourceChange(
                    path="spec.metrics[memory].target.averageUtilization",
                    old_value=str(current.target_memory_percent) if current.target_memory_percent else None,
                    new_value=str(proposed.target_memory_percent) if proposed.target_memory_percent else None,
                ))
        elif proposed:
            # New HPA recommended
            if proposed.min_replicas:
                changes.append(ResourceChange(
                    path="spec.minReplicas",
                    old_value=None,
                    new_value=str(proposed.min_replicas),
                ))
            if proposed.max_replicas:
                changes.append(ResourceChange(
                    path="spec.maxReplicas",
                    old_value=None,
                    new_value=str(proposed.max_replicas),
                ))

        return HPADiff(
            changes=changes,
            reasoning=suggestion.reasoning,
        )

    def format_diff_text(self, workload_diff: WorkloadDiff) -> str:
        """
        Format a workload diff as human-readable text.

        Args:
            workload_diff: The structured diff to format.

        Returns:
            Formatted diff text with - and + markers.
        """
        lines = []

        # Header
        lines.append(f"# {workload_diff.kind}: {workload_diff.namespace}/{workload_diff.workload_name}")
        lines.append("")

        # Container changes
        for container_diff in workload_diff.container_diffs:
            if not container_diff.changes:
                continue

            lines.append(f"## Container: {container_diff.container_name}")
            lines.append("")

            for change in container_diff.changes:
                if change.old_value:
                    lines.append(f"- {change.path}: {change.old_value}")
                if change.new_value:
                    lines.append(f"+ {change.path}: {change.new_value}")
                lines.append("")

            if container_diff.reasoning:
                lines.append(f"Reasoning: {container_diff.reasoning}")
                lines.append("")

        # HPA changes
        if workload_diff.hpa_diff and workload_diff.hpa_diff.changes:
            lines.append("## HorizontalPodAutoscaler")
            lines.append("")

            for change in workload_diff.hpa_diff.changes:
                if change.old_value:
                    lines.append(f"- {change.path}: {change.old_value}")
                if change.new_value:
                    lines.append(f"+ {change.path}: {change.new_value}")
                lines.append("")

            if workload_diff.hpa_diff.reasoning:
                lines.append(f"Reasoning: {workload_diff.hpa_diff.reasoning}")
                lines.append("")

        return "\n".join(lines)

    def generate_yaml_patch(
        self,
        workload_diff: WorkloadDiff,
        original_manifest: dict
    ) -> dict:
        """
        Generate an updated manifest with proposed changes applied.

        Args:
            workload_diff: The diff containing proposed changes.
            original_manifest: The original Kubernetes manifest.

        Returns:
            Updated manifest dictionary with changes applied.
        """
        import copy
        updated = copy.deepcopy(original_manifest)

        # Update container resources
        containers = updated.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])

        for container_diff in workload_diff.container_diffs:
            for container in containers:
                if container.get("name") == container_diff.container_name:
                    self._apply_container_changes(container, container_diff)
                    break

        return updated

    def _apply_container_changes(
        self,
        container: dict,
        container_diff: ContainerDiff
    ) -> None:
        """Apply resource changes to a container spec."""
        if "resources" not in container:
            container["resources"] = {}

        resources = container["resources"]

        for change in container_diff.changes:
            path_parts = change.path.split(".")

            if path_parts[0] == "resources" and len(path_parts) == 3:
                section = path_parts[1]  # "requests" or "limits"
                resource = path_parts[2]  # "cpu" or "memory"

                if section not in resources:
                    resources[section] = {}

                if change.new_value:
                    resources[section][resource] = change.new_value
                elif resource in resources.get(section, {}):
                    del resources[section][resource]

    def dump_yaml(self, data: dict) -> str:
        """
        Dump a dictionary to YAML string.

        Args:
            data: Dictionary to convert to YAML.

        Returns:
            YAML formatted string.
        """
        stream = StringIO()
        self._yaml.dump(data, stream)
        return stream.getvalue()


def generate_diff_for_suggestion(suggestion: WorkloadSuggestion) -> str:
    """
    Convenience function to generate diff text for a suggestion.

    Args:
        suggestion: LLM-generated workload suggestion.

    Returns:
        Formatted diff text.
    """
    generator = YAMLDiffGenerator()
    workload_diff = generator.generate_workload_diff(suggestion)
    return generator.format_diff_text(workload_diff)


def generate_all_diffs(suggestions: list[WorkloadSuggestion]) -> list[tuple[str, str]]:
    """
    Generate diffs for all workload suggestions.

    Args:
        suggestions: List of LLM-generated suggestions.

    Returns:
        List of (workload_name, diff_text) tuples.
    """
    generator = YAMLDiffGenerator()
    results = []

    for suggestion in suggestions:
        workload_diff = generator.generate_workload_diff(suggestion)
        diff_text = generator.format_diff_text(workload_diff)
        results.append((suggestion.name, diff_text))

    return results
