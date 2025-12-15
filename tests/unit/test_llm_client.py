"""
Unit tests for the LLM client and prompts.
"""

import json
import pytest
import respx
from httpx import Response

from kubeopt_ai.llm.client import (
    ClaudeLLMClient,
    MockLLMClient,
    LLMClientError,
    LLMResponseValidationError,
)
from kubeopt_ai.llm.prompts import (
    SYSTEM_PROMPT,
    build_user_prompt,
    format_workload_for_prompt,
)
from kubeopt_ai.core.schemas import (
    WorkloadDescriptor,
    WorkloadKind,
    WorkloadMetrics,
    ContainerConfig,
    ContainerMetrics,
    ContainerResources,
    ResourceRequirements,
)


CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"


@pytest.fixture
def sample_workload():
    """Create a sample workload descriptor."""
    return WorkloadDescriptor(
        kind=WorkloadKind.DEPLOYMENT,
        name="web-app",
        namespace="production",
        replicas=3,
        containers=[
            ContainerConfig(
                name="web",
                image="nginx:1.21",
                resources=ContainerResources(
                    requests=ResourceRequirements(cpu="100m", memory="128Mi"),
                    limits=ResourceRequirements(cpu="500m", memory="512Mi"),
                ),
            ),
        ],
    )


@pytest.fixture
def sample_metrics():
    """Create sample workload metrics."""
    return WorkloadMetrics(
        workload_name="web-app",
        namespace="production",
        lookback_days=7,
        container_metrics=[
            ContainerMetrics(
                container_name="web",
                avg_cpu_usage=0.08,
                p95_cpu_usage=0.15,
                max_cpu_usage=0.25,
                avg_memory_usage=100_000_000,
                p95_memory_usage=200_000_000,
                max_memory_usage=300_000_000,
            ),
        ],
        avg_replica_count=3.0,
        max_replica_count=5,
    )


@pytest.fixture
def valid_llm_response():
    """Create a valid LLM response."""
    return {
        "workloads": [
            {
                "name": "web-app",
                "namespace": "production",
                "kind": "Deployment",
                "suggestions": [
                    {
                        "container": "web",
                        "current": {
                            "requests": {"cpu": "100m", "memory": "128Mi"},
                            "limits": {"cpu": "500m", "memory": "512Mi"},
                        },
                        "proposed": {
                            "requests": {"cpu": "200m", "memory": "256Mi"},
                            "limits": {"cpu": "1000m", "memory": "1Gi"},
                        },
                        "reasoning": "Increased resources based on p95 usage metrics.",
                    }
                ],
                "hpa": {
                    "current": {"min_replicas": 1, "max_replicas": 3, "target_cpu_percent": 80},
                    "proposed": {"min_replicas": 2, "max_replicas": 5, "target_cpu_percent": 70},
                    "reasoning": "Adjusted HPA for better scaling.",
                },
            }
        ]
    }


def make_claude_api_response(content: str) -> dict:
    """Create a mock Claude API response."""
    return {
        "id": "msg_123",
        "type": "message",
        "role": "assistant",
        "content": [
            {
                "type": "text",
                "text": content,
            }
        ],
        "model": "claude-sonnet-4-20250514",
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": 100,
            "output_tokens": 200,
        },
    }


class TestPrompts:
    """Tests for prompt templates."""

    def test_system_prompt_content(self):
        """Test that system prompt contains key instructions."""
        assert "Kubernetes" in SYSTEM_PROMPT
        assert "resource optimizer" in SYSTEM_PROMPT.lower()
        assert "JSON" in SYSTEM_PROMPT
        assert "workloads" in SYSTEM_PROMPT

    def test_build_user_prompt(self):
        """Test building user prompt with workload data."""
        workloads_data = [
            {
                "name": "test-app",
                "namespace": "default",
                "kind": "Deployment",
                "containers": [{"name": "main", "resources": {}}],
            }
        ]

        prompt = build_user_prompt(workloads_data)

        assert "test-app" in prompt
        assert "Deployment" in prompt
        assert "default" in prompt

    def test_format_workload_for_prompt(self):
        """Test formatting workload data for prompt."""
        workload_dict = {
            "name": "api-server",
            "namespace": "production",
            "kind": "Deployment",
            "replicas": 3,
            "containers": [
                {
                    "name": "api",
                    "image": "api:v1",
                    "resources": {"requests": {"cpu": "100m"}},
                }
            ],
            "hpa": {"min_replicas": 2, "max_replicas": 10},
        }

        metrics_dict = {
            "lookback_days": 7,
            "container_metrics": [
                {"container_name": "api", "avg_cpu_usage": 0.1}
            ],
            "avg_replica_count": 3.5,
            "max_replica_count": 5,
        }

        result = format_workload_for_prompt(workload_dict, metrics_dict)

        assert result["name"] == "api-server"
        assert result["namespace"] == "production"
        assert result["kind"] == "Deployment"
        assert len(result["containers"]) == 1
        assert result["metrics"]["lookback_days"] == 7


class TestClaudeLLMClient:
    """Tests for ClaudeLLMClient."""

    @respx.mock
    def test_generate_optimization_suggestions_success(
        self, sample_workload, sample_metrics, valid_llm_response
    ):
        """Test successful optimization generation."""
        response_json = json.dumps(valid_llm_response)
        respx.post(CLAUDE_API_URL).mock(
            return_value=Response(
                200,
                json=make_claude_api_response(response_json),
            )
        )

        client = ClaudeLLMClient(
            api_key="test-key",
            retry_attempts=1,
        )

        result = client.generate_optimization_suggestions(
            workloads=[sample_workload],
            metrics=[sample_metrics],
        )

        assert len(result.workloads) == 1
        assert result.workloads[0].name == "web-app"
        assert len(result.workloads[0].suggestions) == 1
        assert result.workloads[0].suggestions[0].container == "web"

    @respx.mock
    def test_generate_optimization_with_markdown_wrapped_json(
        self, sample_workload, sample_metrics, valid_llm_response
    ):
        """Test handling JSON wrapped in markdown code blocks."""
        response_json = f"```json\n{json.dumps(valid_llm_response)}\n```"
        respx.post(CLAUDE_API_URL).mock(
            return_value=Response(
                200,
                json=make_claude_api_response(response_json),
            )
        )

        client = ClaudeLLMClient(api_key="test-key", retry_attempts=1)

        result = client.generate_optimization_suggestions(
            workloads=[sample_workload],
            metrics=[sample_metrics],
        )

        assert len(result.workloads) == 1

    @respx.mock
    def test_generate_optimization_api_error(self, sample_workload, sample_metrics):
        """Test handling API errors."""
        respx.post(CLAUDE_API_URL).mock(return_value=Response(500))

        client = ClaudeLLMClient(api_key="test-key", retry_attempts=1)

        with pytest.raises(LLMClientError):
            client.generate_optimization_suggestions(
                workloads=[sample_workload],
                metrics=[sample_metrics],
            )

    @respx.mock
    def test_generate_optimization_invalid_json(self, sample_workload, sample_metrics):
        """Test handling invalid JSON response."""
        respx.post(CLAUDE_API_URL).mock(
            return_value=Response(
                200,
                json=make_claude_api_response("This is not valid JSON"),
            )
        )

        client = ClaudeLLMClient(api_key="test-key", retry_attempts=1)

        with pytest.raises(LLMResponseValidationError):
            client.generate_optimization_suggestions(
                workloads=[sample_workload],
                metrics=[sample_metrics],
            )

    @respx.mock
    def test_generate_optimization_schema_mismatch(
        self, sample_workload, sample_metrics
    ):
        """Test handling response that doesn't match schema."""
        invalid_response = {"wrong_field": "wrong_value"}
        respx.post(CLAUDE_API_URL).mock(
            return_value=Response(
                200,
                json=make_claude_api_response(json.dumps(invalid_response)),
            )
        )

        client = ClaudeLLMClient(api_key="test-key", retry_attempts=1)

        with pytest.raises(LLMResponseValidationError):
            client.generate_optimization_suggestions(
                workloads=[sample_workload],
                metrics=[sample_metrics],
            )

    @respx.mock
    def test_retry_on_failure(self, sample_workload, sample_metrics, valid_llm_response):
        """Test retry mechanism on transient failures."""
        # First call fails, second succeeds
        route = respx.post(CLAUDE_API_URL)
        route.side_effect = [
            Response(500),
            Response(200, json=make_claude_api_response(json.dumps(valid_llm_response))),
        ]

        client = ClaudeLLMClient(api_key="test-key", retry_attempts=3)

        result = client.generate_optimization_suggestions(
            workloads=[sample_workload],
            metrics=[sample_metrics],
        )

        assert len(result.workloads) == 1
        assert route.call_count == 2


class TestMockLLMClient:
    """Tests for MockLLMClient."""

    def test_mock_client_generates_suggestions(self, sample_workload, sample_metrics):
        """Test that mock client generates default suggestions."""
        client = MockLLMClient()

        result = client.generate_optimization_suggestions(
            workloads=[sample_workload],
            metrics=[sample_metrics],
        )

        assert len(result.workloads) == 1
        assert result.workloads[0].name == "web-app"
        assert len(result.workloads[0].suggestions) == 1
        assert client.call_count == 1

    def test_mock_client_with_custom_response(
        self, sample_workload, sample_metrics, valid_llm_response
    ):
        """Test mock client with predefined response."""
        client = MockLLMClient(response_data=valid_llm_response)

        result = client.generate_optimization_suggestions(
            workloads=[sample_workload],
            metrics=[sample_metrics],
        )

        assert len(result.workloads) == 1
        assert result.workloads[0].hpa is not None
        assert result.workloads[0].hpa.reasoning == "Adjusted HPA for better scaling."


class TestJSONExtraction:
    """Tests for JSON extraction from responses."""

    def test_extract_json_from_code_block(self):
        """Test extracting JSON from markdown code blocks."""
        client = ClaudeLLMClient(api_key="test-key")

        text = '''Here's the optimization:

```json
{"workloads": []}
```

That's my recommendation.'''

        result = client._extract_json(text)
        assert result == '{"workloads": []}'

    def test_extract_raw_json(self):
        """Test extracting raw JSON without code blocks."""
        client = ClaudeLLMClient(api_key="test-key")

        text = 'The result is {"workloads": [{"name": "test"}]} and that is all.'

        result = client._extract_json(text)
        assert '"workloads"' in result
        assert '"name": "test"' in result

    def test_fix_trailing_comma(self):
        """Test fixing trailing commas in JSON."""
        client = ClaudeLLMClient(api_key="test-key")

        invalid_json = '{"items": [1, 2, 3,]}'
        fixed = client._fix_json(invalid_json)

        # Should be parseable after fix
        data = json.loads(fixed)
        assert data["items"] == [1, 2, 3]
