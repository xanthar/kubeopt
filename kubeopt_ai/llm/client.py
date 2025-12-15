"""
LLM client abstraction for KubeOpt AI.

This module provides a client for interacting with the Claude API
to generate Kubernetes resource optimization suggestions.
"""

import json
import logging
import re
from typing import Optional

import httpx
from pydantic import ValidationError

from kubeopt_ai.core.schemas import (
    LLMOptimizationResponse,
    WorkloadDescriptor,
    WorkloadMetrics,
)
from kubeopt_ai.llm.prompts import (
    SYSTEM_PROMPT,
    build_user_prompt,
    format_workload_for_prompt,
)

logger = logging.getLogger(__name__)


class LLMClientError(Exception):
    """Exception raised when LLM client operations fail."""
    pass


class LLMResponseValidationError(LLMClientError):
    """Exception raised when LLM response fails validation."""
    pass


class ClaudeLLMClient:
    """
    Client for interacting with the Claude API.

    Handles prompt construction, API calls, response parsing,
    and validation of optimization suggestions.
    """

    def __init__(
        self,
        api_key: str,
        model_name: str = "claude-sonnet-4-20250514",
        api_base_url: str = "https://api.anthropic.com/v1",
        max_tokens: int = 4096,
        retry_attempts: int = 3,
        timeout: int = 60,
    ):
        """
        Initialize the Claude LLM client.

        Args:
            api_key: Anthropic API key.
            model_name: Claude model to use.
            api_base_url: Base URL for the API.
            max_tokens: Maximum tokens in response.
            retry_attempts: Number of retry attempts for failed requests.
            timeout: Request timeout in seconds.
        """
        self.api_key = api_key
        self.model_name = model_name
        self.api_base_url = api_base_url.rstrip("/")
        self.max_tokens = max_tokens
        self.retry_attempts = retry_attempts
        self.timeout = timeout

        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def generate_optimization_suggestions(
        self,
        workloads: list[WorkloadDescriptor],
        metrics: list[WorkloadMetrics],
    ) -> LLMOptimizationResponse:
        """
        Generate optimization suggestions for the given workloads.

        Args:
            workloads: List of workload descriptors.
            metrics: List of corresponding workload metrics.

        Returns:
            Validated LLMOptimizationResponse with suggestions.

        Raises:
            LLMClientError: If the API call fails.
            LLMResponseValidationError: If the response is invalid.
        """
        # Build the prompt with workload data
        workloads_data = self._build_workloads_data(workloads, metrics)
        user_prompt = build_user_prompt(workloads_data)

        # Make API call with retries
        response_text = self._call_api_with_retry(user_prompt)

        # Parse and validate the response
        return self._parse_response(response_text)

    def _build_workloads_data(
        self,
        workloads: list[WorkloadDescriptor],
        metrics: list[WorkloadMetrics],
    ) -> list[dict]:
        """Build the workloads data structure for the prompt."""
        workloads_data = []

        # Create a lookup for metrics by workload name
        metrics_lookup = {
            (m.workload_name, m.namespace): m
            for m in metrics
        }

        for workload in workloads:
            workload_dict = workload.model_dump()
            workload_metrics = metrics_lookup.get(
                (workload.name, workload.namespace)
            )

            if workload_metrics:
                metrics_dict = workload_metrics.model_dump()
            else:
                metrics_dict = {}

            formatted = format_workload_for_prompt(workload_dict, metrics_dict)
            workloads_data.append(formatted)

        return workloads_data

    def _call_api(self, user_prompt: str) -> str:
        """
        Make a single API call to Claude.

        Args:
            user_prompt: The user prompt to send.

        Returns:
            Response text from Claude.

        Raises:
            LLMClientError: If the API call fails.
        """
        url = f"{self.api_base_url}/messages"

        payload = {
            "model": self.model_name,
            "max_tokens": self.max_tokens,
            "system": SYSTEM_PROMPT,
            "messages": [
                {"role": "user", "content": user_prompt}
            ],
        }

        try:
            response = self._client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

            # Extract text from response
            content = data.get("content", [])
            if not content:
                raise LLMClientError("Empty response from Claude API")

            text_parts = [
                block.get("text", "")
                for block in content
                if block.get("type") == "text"
            ]

            return "".join(text_parts)

        except httpx.HTTPStatusError as e:
            logger.error(f"Claude API HTTP error: {e.response.status_code}")
            raise LLMClientError(f"Claude API request failed: {e}")
        except httpx.RequestError as e:
            logger.error(f"Claude API request error: {e}")
            raise LLMClientError(f"Claude API request error: {e}")
        except (KeyError, TypeError) as e:
            logger.error(f"Failed to parse Claude API response: {e}")
            raise LLMClientError(f"Failed to parse response: {e}")

    def _call_api_with_retry(self, user_prompt: str) -> str:
        """
        Make an API call with retries for transient failures.

        Args:
            user_prompt: The user prompt to send.

        Returns:
            Response text from Claude.

        Raises:
            LLMClientError: If all retry attempts fail.
        """
        last_error = None

        for attempt in range(self.retry_attempts):
            try:
                return self._call_api(user_prompt)
            except LLMClientError as e:
                last_error = e
                logger.warning(
                    f"API call attempt {attempt + 1}/{self.retry_attempts} failed: {e}"
                )

        raise LLMClientError(f"All {self.retry_attempts} API attempts failed: {last_error}")

    def _parse_response(self, response_text: str) -> LLMOptimizationResponse:
        """
        Parse and validate the LLM response.

        Args:
            response_text: Raw response text from Claude.

        Returns:
            Validated LLMOptimizationResponse.

        Raises:
            LLMResponseValidationError: If parsing or validation fails.
        """
        # Extract JSON from the response (it might be wrapped in markdown)
        json_str = self._extract_json(response_text)

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from response: {e}")
            # Try to fix common JSON issues
            json_str = self._fix_json(json_str)
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                raise LLMResponseValidationError(
                    f"Invalid JSON in LLM response: {e}"
                )

        # Validate against schema
        try:
            return LLMOptimizationResponse.model_validate(data)
        except ValidationError as e:
            logger.error(f"Response validation failed: {e}")
            raise LLMResponseValidationError(
                f"LLM response does not match expected schema: {e}"
            )

    def _extract_json(self, text: str) -> str:
        """
        Extract JSON from response text.

        Handles cases where JSON is wrapped in markdown code blocks.

        Args:
            text: Response text that may contain JSON.

        Returns:
            Extracted JSON string.
        """
        # Try to find JSON in markdown code blocks
        json_pattern = r"```(?:json)?\s*([\s\S]*?)```"
        matches = re.findall(json_pattern, text)

        if matches:
            # Return the first JSON block found
            return matches[0].strip()

        # Try to find raw JSON (object or array)
        # Look for content starting with { and ending with }
        json_obj_pattern = r"(\{[\s\S]*\})"
        obj_matches = re.findall(json_obj_pattern, text)

        if obj_matches:
            # Return the largest match (likely the complete JSON)
            return max(obj_matches, key=len)

        # Return original text if no patterns matched
        return text.strip()

    def _fix_json(self, json_str: str) -> str:
        """
        Attempt to fix common JSON formatting issues.

        Args:
            json_str: Potentially malformed JSON string.

        Returns:
            Fixed JSON string (best effort).
        """
        # Remove trailing commas before closing brackets
        fixed = re.sub(r",(\s*[}\]])", r"\1", json_str)

        # Fix single quotes to double quotes (common LLM mistake)
        # Only for string values, not contractions
        fixed = re.sub(r"'([^']*)'(?=\s*[,}\]])", r'"\1"', fixed)

        return fixed


class MockLLMClient:
    """
    Mock LLM client for testing without real API calls.

    Returns predefined responses for testing the optimization pipeline.
    """

    def __init__(self, response_data: Optional[dict] = None):
        """
        Initialize the mock client.

        Args:
            response_data: Optional predefined response data.
        """
        self.response_data = response_data
        self.call_count = 0
        self.last_workloads = None

    def generate_optimization_suggestions(
        self,
        workloads: list[WorkloadDescriptor],
        metrics: list[WorkloadMetrics],
    ) -> LLMOptimizationResponse:
        """Generate mock optimization suggestions."""
        self.call_count += 1
        self.last_workloads = workloads

        if self.response_data:
            return LLMOptimizationResponse.model_validate(self.response_data)

        # Generate default mock suggestions
        mock_workloads = []
        for workload in workloads:
            suggestions = []
            for container in workload.containers:
                suggestions.append({
                    "container": container.name,
                    "current": {
                        "requests": container.resources.requests.model_dump(),
                        "limits": container.resources.limits.model_dump(),
                    },
                    "proposed": {
                        "requests": {"cpu": "200m", "memory": "256Mi"},
                        "limits": {"cpu": "1000m", "memory": "1Gi"},
                    },
                    "reasoning": "Mock optimization suggestion for testing",
                })

            mock_workloads.append({
                "name": workload.name,
                "namespace": workload.namespace,
                "kind": workload.kind if isinstance(workload.kind, str) else workload.kind.value,
                "suggestions": suggestions,
                "hpa": None,
            })

        return LLMOptimizationResponse.model_validate({"workloads": mock_workloads})
