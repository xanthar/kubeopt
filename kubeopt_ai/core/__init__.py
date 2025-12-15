"""
Core package for KubeOpt AI.

Contains business logic, data models, and service components.
"""

from kubeopt_ai.core.models import OptimizationRun, WorkloadSnapshot, Suggestion

__all__ = ["OptimizationRun", "WorkloadSnapshot", "Suggestion"]
