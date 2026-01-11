"""
Kubernetes apply service for KubeOpt AI.

Provides functionality for applying resource changes to Kubernetes clusters,
including patches, rollbacks, and dry-run operations.
"""

import logging
import tempfile
import time
from dataclasses import dataclass
from typing import Optional

import yaml

from kubeopt_ai.core.models import Cluster, Suggestion, WorkloadKind

logger = logging.getLogger(__name__)


class K8sApplyError(Exception):
    """Exception raised for Kubernetes apply errors."""
    pass


class K8sConnectionError(K8sApplyError):
    """Exception raised when cluster connection fails."""
    pass


class K8sResourceNotFoundError(K8sApplyError):
    """Exception raised when a resource is not found."""
    pass


@dataclass
class ApplyResult:
    """Result of a Kubernetes apply operation."""
    success: bool
    message: str
    resource_version: Optional[str] = None
    output: Optional[str] = None
    duration_ms: Optional[int] = None
    dry_run: bool = False
    previous_config: Optional[dict] = None


@dataclass
class ResourcePatch:
    """Represents a patch to be applied to a Kubernetes resource."""
    namespace: str
    kind: str
    name: str
    patch: dict
    container_name: Optional[str] = None


class K8sApplyService:
    """
    Service for applying resource changes to Kubernetes clusters.

    Uses the official kubernetes Python client for type-safe operations.
    """

    def __init__(self, cluster: Cluster, timeout: int = 30):
        """
        Initialize the K8s apply service.

        Args:
            cluster: The Cluster model with connection configuration.
            timeout: Timeout for API operations in seconds.
        """
        self.cluster = cluster
        self.timeout = timeout
        self._api_client = None
        self._apps_v1 = None
        self._core_v1 = None
        self._autoscaling_v2 = None

    def _get_api_client(self):
        """
        Create a Kubernetes API client from cluster kubeconfig.

        Returns:
            kubernetes.client.ApiClient instance.

        Raises:
            K8sConnectionError: If client creation fails.
        """
        if self._api_client is not None:
            return self._api_client

        try:
            from kubernetes import client, config
            from kubernetes.config import ConfigException

            if self.cluster.kubeconfig:
                # Load from kubeconfig string
                kubeconfig_dict = yaml.safe_load(self.cluster.kubeconfig)

                # Write to temp file for kubernetes client
                with tempfile.NamedTemporaryFile(
                    mode='w', suffix='.yaml', delete=False
                ) as f:
                    yaml.dump(kubeconfig_dict, f)
                    kubeconfig_path = f.name

                config.load_kube_config(
                    config_file=kubeconfig_path,
                    context=self.cluster.kubeconfig_context
                )
                self._api_client = client.ApiClient()

            elif self.cluster.api_server_url:
                # Create client with just API server URL (for testing/dev)
                configuration = client.Configuration()
                configuration.host = self.cluster.api_server_url
                configuration.verify_ssl = False  # In prod, handle TLS properly
                self._api_client = client.ApiClient(configuration)

            else:
                # Try in-cluster config
                config.load_incluster_config()
                self._api_client = client.ApiClient()

            return self._api_client

        except ImportError:
            raise K8sConnectionError(
                "kubernetes package not installed. Run: pip install kubernetes"
            )
        except ConfigException as e:
            raise K8sConnectionError(f"Failed to load kubeconfig: {e}")
        except Exception as e:
            raise K8sConnectionError(f"Failed to create K8s client: {e}")

    def _get_apps_v1(self):
        """Get AppsV1Api client."""
        if self._apps_v1 is None:
            from kubernetes import client
            self._apps_v1 = client.AppsV1Api(self._get_api_client())
        return self._apps_v1

    def _get_core_v1(self):
        """Get CoreV1Api client."""
        if self._core_v1 is None:
            from kubernetes import client
            self._core_v1 = client.CoreV1Api(self._get_api_client())
        return self._core_v1

    def _get_autoscaling_v2(self):
        """Get AutoscalingV2Api client."""
        if self._autoscaling_v2 is None:
            from kubernetes import client
            self._autoscaling_v2 = client.AutoscalingV2Api(self._get_api_client())
        return self._autoscaling_v2

    def get_current_resource(
        self,
        namespace: str,
        kind: str,
        name: str
    ) -> dict:
        """
        Fetch current resource state from cluster.

        Args:
            namespace: Resource namespace.
            kind: Resource kind (Deployment, StatefulSet, DaemonSet).
            name: Resource name.

        Returns:
            Resource specification as dictionary.

        Raises:
            K8sResourceNotFoundError: If resource is not found.
            K8sApplyError: If fetch fails.
        """
        try:
            from kubernetes.client.rest import ApiException

            apps_v1 = self._get_apps_v1()

            if kind.lower() == "deployment":
                resource = apps_v1.read_namespaced_deployment(name, namespace)
            elif kind.lower() == "statefulset":
                resource = apps_v1.read_namespaced_stateful_set(name, namespace)
            elif kind.lower() == "daemonset":
                resource = apps_v1.read_namespaced_daemon_set(name, namespace)
            else:
                raise K8sApplyError(f"Unsupported resource kind: {kind}")

            # Convert to dictionary
            return self._resource_to_dict(resource)

        except ApiException as e:
            if e.status == 404:
                raise K8sResourceNotFoundError(
                    f"Resource not found: {namespace}/{kind}/{name}"
                )
            raise K8sApplyError(f"Failed to get resource: {e}")
        except Exception as e:
            raise K8sApplyError(f"Failed to get resource: {e}")

    def _resource_to_dict(self, resource) -> dict:
        """Convert kubernetes resource object to dictionary."""
        if hasattr(resource, 'to_dict'):
            return resource.to_dict()
        return dict(resource)

    def apply_patch(
        self,
        namespace: str,
        kind: str,
        name: str,
        patch: dict,
        dry_run: bool = False
    ) -> ApplyResult:
        """
        Apply a strategic merge patch to a resource.

        Args:
            namespace: Resource namespace.
            kind: Resource kind (Deployment, StatefulSet, DaemonSet).
            name: Resource name.
            patch: Strategic merge patch to apply.
            dry_run: If True, validate without applying.

        Returns:
            ApplyResult with operation status.

        Raises:
            K8sApplyError: If patch fails.
        """
        start_time = time.time()
        previous_config = None

        try:
            from kubernetes.client.rest import ApiException

            apps_v1 = self._get_apps_v1()
            dry_run_param = ["All"] if dry_run else None

            # Get current state before apply (for rollback)
            if not dry_run:
                try:
                    previous_config = self.get_current_resource(namespace, kind, name)
                except K8sResourceNotFoundError:
                    pass

            # Apply the patch
            if kind.lower() == "deployment":
                result = apps_v1.patch_namespaced_deployment(
                    name=name,
                    namespace=namespace,
                    body=patch,
                    dry_run=dry_run_param,
                    field_manager="kubeopt-ai"
                )
            elif kind.lower() == "statefulset":
                result = apps_v1.patch_namespaced_stateful_set(
                    name=name,
                    namespace=namespace,
                    body=patch,
                    dry_run=dry_run_param,
                    field_manager="kubeopt-ai"
                )
            elif kind.lower() == "daemonset":
                result = apps_v1.patch_namespaced_daemon_set(
                    name=name,
                    namespace=namespace,
                    body=patch,
                    dry_run=dry_run_param,
                    field_manager="kubeopt-ai"
                )
            else:
                raise K8sApplyError(f"Unsupported resource kind: {kind}")

            duration_ms = int((time.time() - start_time) * 1000)
            resource_version = getattr(result.metadata, 'resource_version', None)

            action = "validated (dry-run)" if dry_run else "applied"
            return ApplyResult(
                success=True,
                message=f"Patch {action} successfully to {namespace}/{kind}/{name}",
                resource_version=resource_version,
                output=yaml.dump(patch, default_flow_style=False),
                duration_ms=duration_ms,
                dry_run=dry_run,
                previous_config=previous_config
            )

        except ApiException as e:
            duration_ms = int((time.time() - start_time) * 1000)
            error_body = e.body if hasattr(e, 'body') else str(e)
            logger.error(f"Patch failed for {namespace}/{kind}/{name}: {error_body}")
            return ApplyResult(
                success=False,
                message=f"Patch failed: {e.reason if hasattr(e, 'reason') else str(e)}",
                output=str(error_body),
                duration_ms=duration_ms,
                dry_run=dry_run
            )
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Patch failed for {namespace}/{kind}/{name}: {e}")
            return ApplyResult(
                success=False,
                message=f"Patch failed: {e}",
                duration_ms=duration_ms,
                dry_run=dry_run
            )

    def rollback(
        self,
        namespace: str,
        kind: str,
        name: str,
        previous_config: dict
    ) -> ApplyResult:
        """
        Restore resource to previous configuration.

        Args:
            namespace: Resource namespace.
            kind: Resource kind.
            name: Resource name.
            previous_config: Complete previous resource specification.

        Returns:
            ApplyResult with rollback status.
        """
        # Extract just the spec.template.spec.containers section for resources
        try:
            containers = previous_config.get('spec', {}).get(
                'template', {}
            ).get('spec', {}).get('containers', [])

            if not containers:
                return ApplyResult(
                    success=False,
                    message="No container configuration found in previous config"
                )

            # Build patch from previous container resources
            patch = {
                'spec': {
                    'template': {
                        'spec': {
                            'containers': [
                                {
                                    'name': c.get('name'),
                                    'resources': c.get('resources', {})
                                }
                                for c in containers
                                if c.get('name')
                            ]
                        }
                    }
                }
            }

            return self.apply_patch(namespace, kind, name, patch, dry_run=False)

        except Exception as e:
            logger.error(f"Rollback failed for {namespace}/{kind}/{name}: {e}")
            return ApplyResult(
                success=False,
                message=f"Rollback failed: {e}"
            )

    def build_patch_from_suggestion(self, suggestion: Suggestion) -> ResourcePatch:
        """
        Build a strategic merge patch from a suggestion.

        Args:
            suggestion: The Suggestion model with proposed changes.

        Returns:
            ResourcePatch ready to apply.
        """
        workload = suggestion.workload_snapshot
        proposed = suggestion.proposed_config

        if suggestion.suggestion_type == "hpa":
            # HPA suggestion - different patch structure
            return self._build_hpa_patch(suggestion)

        # Resource suggestion - patch container resources
        resources_patch = {}

        if 'requests' in proposed:
            resources_patch['requests'] = proposed['requests']
        if 'limits' in proposed:
            resources_patch['limits'] = proposed['limits']

        patch = {
            'spec': {
                'template': {
                    'spec': {
                        'containers': [
                            {
                                'name': suggestion.container_name,
                                'resources': resources_patch
                            }
                        ]
                    }
                }
            }
        }

        return ResourcePatch(
            namespace=workload.namespace,
            kind=workload.kind.value if isinstance(workload.kind, WorkloadKind) else workload.kind,
            name=workload.name,
            patch=patch,
            container_name=suggestion.container_name
        )

    def _build_hpa_patch(self, suggestion: Suggestion) -> ResourcePatch:
        """Build HPA configuration patch from suggestion."""
        workload = suggestion.workload_snapshot
        proposed = suggestion.proposed_config

        # HPA patches are applied to HPA resources, not deployments
        # This creates/updates an HPA resource
        hpa_spec = {
            'apiVersion': 'autoscaling/v2',
            'kind': 'HorizontalPodAutoscaler',
            'metadata': {
                'name': workload.name,
                'namespace': workload.namespace
            },
            'spec': {
                'scaleTargetRef': {
                    'apiVersion': 'apps/v1',
                    'kind': workload.kind.value if isinstance(workload.kind, WorkloadKind) else workload.kind,
                    'name': workload.name
                },
                'minReplicas': proposed.get('minReplicas', 1),
                'maxReplicas': proposed.get('maxReplicas', 10),
                'metrics': proposed.get('metrics', [])
            }
        }

        return ResourcePatch(
            namespace=workload.namespace,
            kind='HorizontalPodAutoscaler',
            name=workload.name,
            patch=hpa_spec,
            container_name=None
        )

    def apply_hpa(
        self,
        namespace: str,
        name: str,
        hpa_spec: dict,
        dry_run: bool = False
    ) -> ApplyResult:
        """
        Apply or update an HPA resource.

        Args:
            namespace: HPA namespace.
            name: HPA name.
            hpa_spec: Complete HPA specification.
            dry_run: If True, validate without applying.

        Returns:
            ApplyResult with operation status.
        """
        start_time = time.time()

        try:
            from kubernetes.client.rest import ApiException

            autoscaling = self._get_autoscaling_v2()
            dry_run_param = ["All"] if dry_run else None

            # Try to update existing HPA
            try:
                result = autoscaling.patch_namespaced_horizontal_pod_autoscaler(
                    name=name,
                    namespace=namespace,
                    body=hpa_spec,
                    dry_run=dry_run_param,
                    field_manager="kubeopt-ai"
                )
                action = "updated"
            except ApiException as e:
                if e.status == 404:
                    # Create new HPA
                    result = autoscaling.create_namespaced_horizontal_pod_autoscaler(
                        namespace=namespace,
                        body=hpa_spec,
                        dry_run=dry_run_param,
                        field_manager="kubeopt-ai"
                    )
                    action = "created"
                else:
                    raise

            duration_ms = int((time.time() - start_time) * 1000)

            if dry_run:
                action = f"validated (dry-run, would be {action})"

            return ApplyResult(
                success=True,
                message=f"HPA {action} successfully: {namespace}/{name}",
                resource_version=getattr(result.metadata, 'resource_version', None),
                output=yaml.dump(hpa_spec, default_flow_style=False),
                duration_ms=duration_ms,
                dry_run=dry_run
            )

        except ApiException as e:
            duration_ms = int((time.time() - start_time) * 1000)
            error_body = e.body if hasattr(e, 'body') else str(e)
            return ApplyResult(
                success=False,
                message=f"HPA apply failed: {e.reason if hasattr(e, 'reason') else str(e)}",
                output=str(error_body),
                duration_ms=duration_ms,
                dry_run=dry_run
            )
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return ApplyResult(
                success=False,
                message=f"HPA apply failed: {e}",
                duration_ms=duration_ms,
                dry_run=dry_run
            )

    def test_connection(self) -> ApplyResult:
        """
        Test connection to the cluster.

        Returns:
            ApplyResult indicating connection status.
        """
        start_time = time.time()

        try:
            from kubernetes.client.rest import ApiException

            core_v1 = self._get_core_v1()
            core_v1.get_api_resources()  # Verify connection works

            duration_ms = int((time.time() - start_time) * 1000)

            return ApplyResult(
                success=True,
                message=f"Connected to cluster: {self.cluster.name}",
                duration_ms=duration_ms
            )

        except ApiException as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return ApplyResult(
                success=False,
                message=f"Connection failed: {e.reason if hasattr(e, 'reason') else str(e)}",
                duration_ms=duration_ms
            )
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return ApplyResult(
                success=False,
                message=f"Connection failed: {e}",
                duration_ms=duration_ms
            )

    def close(self):
        """Close the API client connection."""
        if self._api_client:
            self._api_client.close()
            self._api_client = None
            self._apps_v1 = None
            self._core_v1 = None
            self._autoscaling_v2 = None
