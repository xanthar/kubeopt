"""
LLM package for KubeOpt AI.

Provides Claude API client and prompt management for generating
Kubernetes resource optimization suggestions.
"""

from kubeopt_ai.llm.client import (
    ClaudeLLMClient,
    MockLLMClient,
    LLMClientError,
    LLMResponseValidationError,
)
from kubeopt_ai.llm.prompts import (
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
    build_user_prompt,
    format_workload_for_prompt,
)

__all__ = [
    "ClaudeLLMClient",
    "MockLLMClient",
    "LLMClientError",
    "LLMResponseValidationError",
    "SYSTEM_PROMPT",
    "USER_PROMPT_TEMPLATE",
    "build_user_prompt",
    "format_workload_for_prompt",
]
