"""
Guardrail service for KubeOpt AI.

Validates apply requests against safety policies before allowing
recommendation application.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from kubeopt_ai.core.models import (
    ApplyPolicy,
    Cluster,
    GuardrailCheckStatus,
    Suggestion,
)

logger = logging.getLogger(__name__)


@dataclass
class GuardrailCheckResult:
    """Result of a single guardrail check."""
    name: str
    status: GuardrailCheckStatus
    message: str
    current_value: Optional[Any] = None
    proposed_value: Optional[Any] = None
    threshold: Optional[Any] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "current_value": self.current_value,
            "proposed_value": self.proposed_value,
            "threshold": self.threshold,
        }


def parse_k8s_resource(value: str) -> float:
    """
    Parse Kubernetes resource string to numeric value.

    Args:
        value: Resource string (e.g., "100m", "1Gi", "500Mi").

    Returns:
        Numeric value (cores for CPU, bytes for memory).
    """
    if not value or value == "0":
        return 0.0

    value = str(value).strip()

    # CPU: millicores (m) or cores
    if value.endswith('m'):
        return float(value[:-1]) / 1000.0
    if value[-1].isdigit():
        # Check if it's a plain number (could be cores or bytes)
        try:
            return float(value)
        except ValueError:
            pass

    # Memory units
    units = {
        'Ki': 1024,
        'Mi': 1024 ** 2,
        'Gi': 1024 ** 3,
        'Ti': 1024 ** 4,
        'K': 1000,
        'M': 1000 ** 2,
        'G': 1000 ** 3,
        'T': 1000 ** 4,
    }

    for suffix, multiplier in units.items():
        if value.endswith(suffix):
            try:
                return float(value[:-len(suffix)]) * multiplier
            except ValueError:
                pass

    # Plain number
    try:
        return float(value)
    except ValueError:
        logger.warning(f"Could not parse resource value: {value}")
        return 0.0


def calculate_percent_change(current: float, proposed: float) -> float:
    """
    Calculate percentage change between current and proposed values.

    Returns:
        Percentage change (positive for increase, negative for decrease).
    """
    if current == 0:
        return 100.0 if proposed > 0 else 0.0
    return ((proposed - current) / current) * 100.0


class GuardrailService:
    """
    Validates apply requests against safety guardrails.

    Ensures that recommended changes are within acceptable limits
    and don't violate organizational policies.
    """

    def check_all(
        self,
        suggestion: Suggestion,
        policy: ApplyPolicy,
        cluster: Optional[Cluster] = None
    ) -> list[GuardrailCheckResult]:
        """
        Run all guardrail checks for a suggestion.

        Args:
            suggestion: The suggestion to validate.
            policy: The apply policy with guardrail settings.
            cluster: Optional cluster for cluster-specific checks.

        Returns:
            List of GuardrailCheckResult for each check.
        """
        results = []
        workload = suggestion.workload_snapshot

        # Skip HPA suggestions for resource checks
        if suggestion.suggestion_type != "hpa":
            # Resource change limit checks
            results.append(self.check_cpu_request_change(
                suggestion.current_config,
                suggestion.proposed_config,
                policy
            ))
            results.append(self.check_cpu_limit_change(
                suggestion.current_config,
                suggestion.proposed_config,
                policy
            ))
            results.append(self.check_memory_request_change(
                suggestion.current_config,
                suggestion.proposed_config,
                policy
            ))
            results.append(self.check_memory_limit_change(
                suggestion.current_config,
                suggestion.proposed_config,
                policy
            ))

            # Minimum resource checks
            results.append(self.check_minimum_cpu(
                suggestion.proposed_config,
                policy
            ))
            results.append(self.check_minimum_memory(
                suggestion.proposed_config,
                policy
            ))

        # Blackout window check
        results.append(self.check_blackout_window(policy))

        # Namespace exclusion check
        results.append(self.check_namespace_exclusions(
            workload.namespace,
            policy
        ))

        # Workload pattern exclusion check
        results.append(self.check_workload_exclusions(
            workload.name,
            policy
        ))

        return results

    def check_cpu_request_change(
        self,
        current: dict,
        proposed: dict,
        policy: ApplyPolicy
    ) -> GuardrailCheckResult:
        """Check if CPU request change is within limits."""
        current_val = parse_k8s_resource(
            current.get('requests', {}).get('cpu', '0')
        )
        proposed_val = parse_k8s_resource(
            proposed.get('requests', {}).get('cpu', '0')
        )

        return self._check_resource_change(
            name="cpu_request_change",
            resource_name="CPU request",
            current_val=current_val,
            proposed_val=proposed_val,
            max_increase=policy.max_cpu_increase_percent,
            max_decrease=policy.max_cpu_decrease_percent
        )

    def check_cpu_limit_change(
        self,
        current: dict,
        proposed: dict,
        policy: ApplyPolicy
    ) -> GuardrailCheckResult:
        """Check if CPU limit change is within limits."""
        current_val = parse_k8s_resource(
            current.get('limits', {}).get('cpu', '0')
        )
        proposed_val = parse_k8s_resource(
            proposed.get('limits', {}).get('cpu', '0')
        )

        return self._check_resource_change(
            name="cpu_limit_change",
            resource_name="CPU limit",
            current_val=current_val,
            proposed_val=proposed_val,
            max_increase=policy.max_cpu_increase_percent,
            max_decrease=policy.max_cpu_decrease_percent
        )

    def check_memory_request_change(
        self,
        current: dict,
        proposed: dict,
        policy: ApplyPolicy
    ) -> GuardrailCheckResult:
        """Check if memory request change is within limits."""
        current_val = parse_k8s_resource(
            current.get('requests', {}).get('memory', '0')
        )
        proposed_val = parse_k8s_resource(
            proposed.get('requests', {}).get('memory', '0')
        )

        return self._check_resource_change(
            name="memory_request_change",
            resource_name="Memory request",
            current_val=current_val,
            proposed_val=proposed_val,
            max_increase=policy.max_memory_increase_percent,
            max_decrease=policy.max_memory_decrease_percent
        )

    def check_memory_limit_change(
        self,
        current: dict,
        proposed: dict,
        policy: ApplyPolicy
    ) -> GuardrailCheckResult:
        """Check if memory limit change is within limits."""
        current_val = parse_k8s_resource(
            current.get('limits', {}).get('memory', '0')
        )
        proposed_val = parse_k8s_resource(
            proposed.get('limits', {}).get('memory', '0')
        )

        return self._check_resource_change(
            name="memory_limit_change",
            resource_name="Memory limit",
            current_val=current_val,
            proposed_val=proposed_val,
            max_increase=policy.max_memory_increase_percent,
            max_decrease=policy.max_memory_decrease_percent
        )

    def _check_resource_change(
        self,
        name: str,
        resource_name: str,
        current_val: float,
        proposed_val: float,
        max_increase: float,
        max_decrease: float
    ) -> GuardrailCheckResult:
        """Generic resource change check."""
        # If no current value, any proposed value is fine
        if current_val == 0:
            return GuardrailCheckResult(
                name=name,
                status=GuardrailCheckStatus.PASSED,
                message=f"{resource_name}: No current value, setting to {proposed_val}",
                current_value=current_val,
                proposed_value=proposed_val
            )

        # If no proposed value and there was a current value, this is a removal
        if proposed_val == 0 and current_val > 0:
            return GuardrailCheckResult(
                name=name,
                status=GuardrailCheckStatus.WARNING,
                message=f"{resource_name}: Removing resource specification",
                current_value=current_val,
                proposed_value=proposed_val
            )

        percent_change = calculate_percent_change(current_val, proposed_val)

        if percent_change > 0:
            # Increase
            if percent_change > max_increase:
                return GuardrailCheckResult(
                    name=name,
                    status=GuardrailCheckStatus.FAILED,
                    message=f"{resource_name} increase of {percent_change:.1f}% exceeds limit of {max_increase}%",
                    current_value=current_val,
                    proposed_value=proposed_val,
                    threshold=max_increase
                )
        else:
            # Decrease
            abs_change = abs(percent_change)
            if abs_change > max_decrease:
                return GuardrailCheckResult(
                    name=name,
                    status=GuardrailCheckStatus.FAILED,
                    message=f"{resource_name} decrease of {abs_change:.1f}% exceeds limit of {max_decrease}%",
                    current_value=current_val,
                    proposed_value=proposed_val,
                    threshold=max_decrease
                )

        return GuardrailCheckResult(
            name=name,
            status=GuardrailCheckStatus.PASSED,
            message=f"{resource_name} change of {percent_change:.1f}% is within limits",
            current_value=current_val,
            proposed_value=proposed_val,
            threshold=max_increase if percent_change > 0 else max_decrease
        )

    def check_minimum_cpu(
        self,
        proposed: dict,
        policy: ApplyPolicy
    ) -> GuardrailCheckResult:
        """Ensure CPU request doesn't go below minimum."""
        if not policy.min_cpu_request:
            return GuardrailCheckResult(
                name="minimum_cpu",
                status=GuardrailCheckStatus.PASSED,
                message="No minimum CPU configured"
            )

        proposed_val = parse_k8s_resource(
            proposed.get('requests', {}).get('cpu', '0')
        )
        min_val = parse_k8s_resource(policy.min_cpu_request)

        if proposed_val > 0 and proposed_val < min_val:
            return GuardrailCheckResult(
                name="minimum_cpu",
                status=GuardrailCheckStatus.FAILED,
                message=f"Proposed CPU request {proposed_val} is below minimum {policy.min_cpu_request}",
                proposed_value=proposed_val,
                threshold=min_val
            )

        return GuardrailCheckResult(
            name="minimum_cpu",
            status=GuardrailCheckStatus.PASSED,
            message="CPU request meets minimum requirement",
            proposed_value=proposed_val,
            threshold=min_val
        )

    def check_minimum_memory(
        self,
        proposed: dict,
        policy: ApplyPolicy
    ) -> GuardrailCheckResult:
        """Ensure memory request doesn't go below minimum."""
        if not policy.min_memory_request:
            return GuardrailCheckResult(
                name="minimum_memory",
                status=GuardrailCheckStatus.PASSED,
                message="No minimum memory configured"
            )

        proposed_val = parse_k8s_resource(
            proposed.get('requests', {}).get('memory', '0')
        )
        min_val = parse_k8s_resource(policy.min_memory_request)

        if proposed_val > 0 and proposed_val < min_val:
            return GuardrailCheckResult(
                name="minimum_memory",
                status=GuardrailCheckStatus.FAILED,
                message=f"Proposed memory request is below minimum {policy.min_memory_request}",
                proposed_value=proposed_val,
                threshold=min_val
            )

        return GuardrailCheckResult(
            name="minimum_memory",
            status=GuardrailCheckStatus.PASSED,
            message="Memory request meets minimum requirement",
            proposed_value=proposed_val,
            threshold=min_val
        )

    def check_blackout_window(
        self,
        policy: ApplyPolicy
    ) -> GuardrailCheckResult:
        """Check if current time is in a blackout window."""
        if not policy.blackout_windows:
            return GuardrailCheckResult(
                name="blackout_window",
                status=GuardrailCheckStatus.PASSED,
                message="No blackout windows configured"
            )

        now = datetime.now(timezone.utc)
        current_day = now.weekday()  # Monday=0, Sunday=6
        current_time = now.strftime("%H:%M")

        for window in policy.blackout_windows:
            # Window format: {day_of_week: int, start_time: "HH:MM", end_time: "HH:MM"}
            window_day = window.get('day_of_week')
            start_time = window.get('start_time', '00:00')
            end_time = window.get('end_time', '23:59')

            # Check if today matches (or window_day is None for every day)
            if window_day is not None and window_day != current_day:
                continue

            # Check if current time is within window
            if start_time <= current_time <= end_time:
                return GuardrailCheckResult(
                    name="blackout_window",
                    status=GuardrailCheckStatus.FAILED,
                    message=f"Current time {current_time} is within blackout window ({start_time}-{end_time})",
                    current_value=current_time,
                    threshold=f"{start_time}-{end_time}"
                )

        return GuardrailCheckResult(
            name="blackout_window",
            status=GuardrailCheckStatus.PASSED,
            message="Not within any blackout window"
        )

    def check_namespace_exclusions(
        self,
        namespace: str,
        policy: ApplyPolicy
    ) -> GuardrailCheckResult:
        """Check if namespace is excluded from auto-apply."""
        if not policy.excluded_namespaces:
            return GuardrailCheckResult(
                name="namespace_exclusion",
                status=GuardrailCheckStatus.PASSED,
                message="No namespace exclusions configured"
            )

        if namespace in policy.excluded_namespaces:
            return GuardrailCheckResult(
                name="namespace_exclusion",
                status=GuardrailCheckStatus.FAILED,
                message=f"Namespace '{namespace}' is excluded from auto-apply",
                current_value=namespace,
                threshold=policy.excluded_namespaces
            )

        return GuardrailCheckResult(
            name="namespace_exclusion",
            status=GuardrailCheckStatus.PASSED,
            message=f"Namespace '{namespace}' is not excluded"
        )

    def check_workload_exclusions(
        self,
        workload_name: str,
        policy: ApplyPolicy
    ) -> GuardrailCheckResult:
        """Check if workload matches an exclusion pattern."""
        if not policy.excluded_workload_patterns:
            return GuardrailCheckResult(
                name="workload_exclusion",
                status=GuardrailCheckStatus.PASSED,
                message="No workload exclusion patterns configured"
            )

        for pattern in policy.excluded_workload_patterns:
            try:
                if re.match(pattern, workload_name):
                    return GuardrailCheckResult(
                        name="workload_exclusion",
                        status=GuardrailCheckStatus.FAILED,
                        message=f"Workload '{workload_name}' matches exclusion pattern '{pattern}'",
                        current_value=workload_name,
                        threshold=pattern
                    )
            except re.error as e:
                logger.warning(f"Invalid exclusion pattern '{pattern}': {e}")

        return GuardrailCheckResult(
            name="workload_exclusion",
            status=GuardrailCheckStatus.PASSED,
            message=f"Workload '{workload_name}' does not match any exclusion pattern"
        )

    def should_auto_approve(
        self,
        suggestion: Suggestion,
        policy: ApplyPolicy
    ) -> bool:
        """
        Determine if a change is small enough for auto-approval.

        Args:
            suggestion: The suggestion to evaluate.
            policy: The apply policy with thresholds.

        Returns:
            True if the change can be auto-approved.
        """
        if not policy.auto_approve_below_threshold:
            return False

        # HPA suggestions always require approval
        if suggestion.suggestion_type == "hpa":
            return False

        current = suggestion.current_config
        proposed = suggestion.proposed_config

        # Check CPU request change
        current_cpu = parse_k8s_resource(
            current.get('requests', {}).get('cpu', '0')
        )
        proposed_cpu = parse_k8s_resource(
            proposed.get('requests', {}).get('cpu', '0')
        )

        if current_cpu > 0:
            cpu_change = abs(calculate_percent_change(current_cpu, proposed_cpu))
            if cpu_change > policy.approval_threshold_cpu_percent:
                return False

        # Check memory request change
        current_mem = parse_k8s_resource(
            current.get('requests', {}).get('memory', '0')
        )
        proposed_mem = parse_k8s_resource(
            proposed.get('requests', {}).get('memory', '0')
        )

        if current_mem > 0:
            mem_change = abs(calculate_percent_change(current_mem, proposed_mem))
            if mem_change > policy.approval_threshold_memory_percent:
                return False

        return True

    def has_any_failure(
        self,
        results: list[GuardrailCheckResult]
    ) -> bool:
        """Check if any guardrail check failed."""
        return any(r.status == GuardrailCheckStatus.FAILED for r in results)

    def get_failed_checks(
        self,
        results: list[GuardrailCheckResult]
    ) -> list[GuardrailCheckResult]:
        """Get list of failed guardrail checks."""
        return [r for r in results if r.status == GuardrailCheckStatus.FAILED]

    def results_to_dict(
        self,
        results: list[GuardrailCheckResult]
    ) -> dict:
        """Convert results list to dictionary for storage."""
        return {
            "checks": [r.to_dict() for r in results],
            "all_passed": not self.has_any_failure(results),
            "failed_count": len(self.get_failed_checks(results)),
            "checked_at": datetime.now(timezone.utc).isoformat()
        }
