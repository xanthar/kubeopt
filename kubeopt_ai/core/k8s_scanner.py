"""
Kubernetes manifest scanner for KubeOpt AI.

This module scans Kubernetes YAML manifests and extracts workload descriptors
for optimization analysis. Supports Deployments, StatefulSets, DaemonSets,
and HorizontalPodAutoscalers.
"""

import logging
import os
from pathlib import Path
from typing import Optional

import yaml
from ruamel.yaml import YAML

from kubeopt_ai.core.schemas import (
    WorkloadDescriptor,
    WorkloadKind,
    ContainerConfig,
    ContainerResources,
    ResourceRequirements,
    HPAConfig,
)

logger = logging.getLogger(__name__)

# Supported Kubernetes workload kinds
SUPPORTED_WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet"}
HPA_KIND = "HorizontalPodAutoscaler"


class ManifestScanError(Exception):
    """Exception raised when manifest scanning fails."""
    pass


class K8sScanner:
    """
    Kubernetes manifest scanner.

    Scans a directory of Kubernetes YAML manifests and extracts
    normalized workload descriptors suitable for optimization analysis.
    """

    def __init__(self):
        """Initialize the scanner."""
        self._yaml = YAML()
        self._yaml.preserve_quotes = True

    def scan_directory(self, manifest_path: str) -> list[WorkloadDescriptor]:
        """
        Scan a directory for Kubernetes manifests and extract workload descriptors.

        Args:
            manifest_path: Path to directory containing Kubernetes YAML files,
                          or path to a single YAML file.

        Returns:
            List of WorkloadDescriptor objects for all discovered workloads.

        Raises:
            ManifestScanError: If the path is invalid or scanning fails.
        """
        path = Path(manifest_path)

        if not path.exists():
            raise ManifestScanError(f"Path does not exist: {manifest_path}")

        yaml_files = []
        if path.is_file():
            if self._is_yaml_file(path):
                yaml_files = [path]
            else:
                raise ManifestScanError(f"Not a YAML file: {manifest_path}")
        elif path.is_dir():
            yaml_files = self._find_yaml_files(path)
        else:
            raise ManifestScanError(f"Invalid path type: {manifest_path}")

        if not yaml_files:
            logger.warning(f"No YAML files found in: {manifest_path}")
            return []

        # First pass: collect all documents
        all_documents: list[tuple[Path, dict]] = []
        for yaml_file in yaml_files:
            try:
                documents = self._load_yaml_file(yaml_file)
                all_documents.extend((yaml_file, doc) for doc in documents)
            except Exception as e:
                logger.error(f"Failed to parse {yaml_file}: {e}")
                continue

        # Separate workloads and HPAs
        workloads: list[WorkloadDescriptor] = []
        hpas: dict[str, HPAConfig] = {}  # keyed by "namespace/name"

        for yaml_file, document in all_documents:
            if not isinstance(document, dict):
                continue

            kind = document.get("kind", "")

            if kind == HPA_KIND:
                hpa_key, hpa_config = self._parse_hpa(document)
                if hpa_key and hpa_config:
                    hpas[hpa_key] = hpa_config
            elif kind in SUPPORTED_WORKLOAD_KINDS:
                workload = self._parse_workload(document, str(yaml_file))
                if workload:
                    workloads.append(workload)

        # Second pass: associate HPAs with workloads
        for workload in workloads:
            hpa_key = f"{workload.namespace}/{workload.name}"
            if hpa_key in hpas:
                workload.hpa = hpas[hpa_key]

        logger.info(f"Scanned {len(yaml_files)} files, found {len(workloads)} workloads")
        return workloads

    def scan_manifest_content(self, content: str, source_path: str = "<inline>") -> list[WorkloadDescriptor]:
        """
        Scan YAML content directly and extract workload descriptors.

        Args:
            content: YAML content as string.
            source_path: Optional source path for reference.

        Returns:
            List of WorkloadDescriptor objects.
        """
        workloads: list[WorkloadDescriptor] = []
        hpas: dict[str, HPAConfig] = {}

        try:
            documents = list(yaml.safe_load_all(content))
        except yaml.YAMLError as e:
            raise ManifestScanError(f"Failed to parse YAML content: {e}")

        for document in documents:
            if not isinstance(document, dict):
                continue

            kind = document.get("kind", "")

            if kind == HPA_KIND:
                hpa_key, hpa_config = self._parse_hpa(document)
                if hpa_key and hpa_config:
                    hpas[hpa_key] = hpa_config
            elif kind in SUPPORTED_WORKLOAD_KINDS:
                workload = self._parse_workload(document, source_path)
                if workload:
                    workloads.append(workload)

        # Associate HPAs with workloads
        for workload in workloads:
            hpa_key = f"{workload.namespace}/{workload.name}"
            if hpa_key in hpas:
                workload.hpa = hpas[hpa_key]

        return workloads

    def _is_yaml_file(self, path: Path) -> bool:
        """Check if a path is a YAML file."""
        return path.suffix.lower() in {".yaml", ".yml"}

    def _find_yaml_files(self, directory: Path) -> list[Path]:
        """Find all YAML files in a directory (non-recursive by default)."""
        yaml_files = []
        for item in directory.iterdir():
            if item.is_file() and self._is_yaml_file(item):
                yaml_files.append(item)
        return sorted(yaml_files)

    def _load_yaml_file(self, path: Path) -> list[dict]:
        """Load all YAML documents from a file."""
        with open(path, "r") as f:
            documents = list(yaml.safe_load_all(f))
        return [doc for doc in documents if doc is not None]

    def _parse_workload(self, document: dict, manifest_path: str) -> Optional[WorkloadDescriptor]:
        """
        Parse a Kubernetes workload manifest into a WorkloadDescriptor.

        Args:
            document: Parsed YAML document.
            manifest_path: Path to the source manifest file.

        Returns:
            WorkloadDescriptor or None if parsing fails.
        """
        try:
            kind = document.get("kind")
            metadata = document.get("metadata", {})
            spec = document.get("spec", {})

            name = metadata.get("name")
            if not name:
                logger.warning("Workload missing name in metadata")
                return None

            namespace = metadata.get("namespace", "default")
            labels = metadata.get("labels", {})

            # Get replica count (not applicable to DaemonSet)
            replicas = None
            if kind != "DaemonSet":
                replicas = spec.get("replicas", 1)

            # Parse containers from pod template
            pod_spec = spec.get("template", {}).get("spec", {})
            containers = self._parse_containers(pod_spec.get("containers", []))

            return WorkloadDescriptor(
                kind=WorkloadKind(kind),
                name=name,
                namespace=namespace,
                replicas=replicas,
                containers=containers,
                labels=labels,
                manifest_path=manifest_path,
            )

        except Exception as e:
            logger.error(f"Failed to parse workload: {e}")
            return None

    def _parse_containers(self, containers: list[dict]) -> list[ContainerConfig]:
        """
        Parse container specifications from a pod spec.

        Args:
            containers: List of container specs from pod template.

        Returns:
            List of ContainerConfig objects.
        """
        parsed_containers = []

        for container in containers:
            name = container.get("name")
            if not name:
                continue

            image = container.get("image", "unknown")
            resources = self._parse_resources(container.get("resources", {}))

            parsed_containers.append(ContainerConfig(
                name=name,
                image=image,
                resources=resources,
            ))

        return parsed_containers

    def _parse_resources(self, resources: dict) -> ContainerResources:
        """
        Parse container resource requirements.

        Args:
            resources: Resources dict from container spec.

        Returns:
            ContainerResources object.
        """
        requests = resources.get("requests", {})
        limits = resources.get("limits", {})

        return ContainerResources(
            requests=ResourceRequirements(
                cpu=requests.get("cpu"),
                memory=requests.get("memory"),
            ),
            limits=ResourceRequirements(
                cpu=limits.get("cpu"),
                memory=limits.get("memory"),
            ),
        )

    def _parse_hpa(self, document: dict) -> tuple[Optional[str], Optional[HPAConfig]]:
        """
        Parse a HorizontalPodAutoscaler manifest.

        Args:
            document: Parsed YAML document.

        Returns:
            Tuple of (namespace/name key, HPAConfig) or (None, None) if parsing fails.
        """
        try:
            metadata = document.get("metadata", {})
            spec = document.get("spec", {})

            name = metadata.get("name")
            namespace = metadata.get("namespace", "default")

            if not name:
                return None, None

            # Get the target reference (the workload this HPA scales)
            scale_target_ref = spec.get("scaleTargetRef", {})
            target_name = scale_target_ref.get("name")

            if not target_name:
                return None, None

            # Parse HPA configuration
            min_replicas = spec.get("minReplicas", 1)
            max_replicas = spec.get("maxReplicas", 1)

            # Parse metrics (v2 API)
            target_cpu_percent = None
            target_memory_percent = None

            metrics = spec.get("metrics", [])
            for metric in metrics:
                if metric.get("type") == "Resource":
                    resource = metric.get("resource", {})
                    resource_name = resource.get("name")
                    target = resource.get("target", {})

                    if target.get("type") == "Utilization":
                        utilization = target.get("averageUtilization")
                        if resource_name == "cpu":
                            target_cpu_percent = utilization
                        elif resource_name == "memory":
                            target_memory_percent = utilization

            # Fallback to v1 API format
            if target_cpu_percent is None:
                target_cpu_percent = spec.get("targetCPUUtilizationPercentage")

            hpa_key = f"{namespace}/{target_name}"
            hpa_config = HPAConfig(
                min_replicas=min_replicas,
                max_replicas=max_replicas,
                target_cpu_percent=target_cpu_percent,
                target_memory_percent=target_memory_percent,
            )

            return hpa_key, hpa_config

        except Exception as e:
            logger.error(f"Failed to parse HPA: {e}")
            return None, None


# Module-level scanner instance
_scanner: Optional[K8sScanner] = None


def get_scanner() -> K8sScanner:
    """Get or create the module-level scanner instance."""
    global _scanner
    if _scanner is None:
        _scanner = K8sScanner()
    return _scanner


def scan_manifests(manifest_path: str) -> list[WorkloadDescriptor]:
    """
    Convenience function to scan manifests at the given path.

    Args:
        manifest_path: Path to directory or file containing Kubernetes manifests.

    Returns:
        List of WorkloadDescriptor objects.
    """
    return get_scanner().scan_directory(manifest_path)
