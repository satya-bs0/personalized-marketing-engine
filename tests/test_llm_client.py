"""Mocked unit tests for src/llm/client.py — no real API calls."""
from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, patch

import anthropic
import pytest

from src.llm.client import AnthropicClient
from src.schemas import LLMResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool_response(tool_input: dict) -> MagicMock:
    """Build a mock Anthropic message response containing one tool_use block."""
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.input = tool_input

    response = MagicMock()
    response.content = [tool_block]
    response.usage.input_tokens = 100
    response.usage.output_tokens = 50
    response.model = "claude-sonnet-4-6"
    response.id = "msg_test_abc123"
    return response


def _make_rate_limit_error() -> anthropic.RateLimitError:
    mock_http = MagicMock()
    mock_http.status_code = 429
    return anthropic.RateLimitError(
        message="rate limit exceeded",
        response=mock_http,
        body={},
    )


def _make_bad_request_error() -> anthropic.BadRequestError:
    mock_http = MagicMock()
    mock_http.status_code = 400
    return anthropic.BadRequestError(
        message="invalid request",
        response=mock_http,
        body={},
    )


@pytest.fixture
def tool_def() -> dict:
    return {
        "name": "my_tool",
        "description": "A test tool",
        "input_schema": {
            "type": "object",
            "properties": {"field": {"type": "string"}},
            "required": ["field"],
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_call_returns_llm_response(tool_def):
    mock_response = _make_tool_response({"field": "value"})

    with patch("anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value.messages.create.return_value = mock_response
        client = AnthropicClient(model="claude-sonnet-4-6", api_key="test-key")
        result = client.call(
            system="system prompt",
            user="user prompt",
            tool=tool_def,
            temperature=0.0,
            max_tokens=500,
        )

    assert isinstance(result, LLMResponse)
    assert result.tool_input == {"field": "value"}
    assert result.input_tokens == 100
    assert result.output_tokens == 50
    assert result.model == "claude-sonnet-4-6"
    assert result.raw_response_id == "msg_test_abc123"
    assert result.latency_ms >= 0


def test_prompt_hash_is_sha256_of_system_plus_user(tool_def):
    system = "the system prompt"
    user = "the user prompt"
    expected_hash = hashlib.sha256((system + user).encode()).hexdigest()
    mock_response = _make_tool_response({"field": "v"})

    with patch("anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value.messages.create.return_value = mock_response
        client = AnthropicClient(model="claude-sonnet-4-6", api_key="test-key")
        result = client.call(system=system, user=user, tool=tool_def, temperature=0.0, max_tokens=100)

    assert result.prompt_hash == expected_hash


def test_call_passes_tool_choice_to_api(tool_def):
    mock_response = _make_tool_response({"field": "v"})

    with patch("anthropic.Anthropic") as MockAnthropic:
        create = MockAnthropic.return_value.messages.create
        create.return_value = mock_response
        client = AnthropicClient(model="claude-sonnet-4-6", api_key="test-key")
        client.call(system="s", user="u", tool=tool_def, temperature=0.0, max_tokens=100)

    call_kwargs = create.call_args.kwargs
    assert call_kwargs["tool_choice"] == {"type": "tool", "name": "my_tool"}
    assert call_kwargs["tools"] == [tool_def]
    assert call_kwargs["temperature"] == 0.0
    assert call_kwargs["max_tokens"] == 100


def test_retries_on_rate_limit_error_and_succeeds(tool_def):
    """Retries up to 3 times on RateLimitError, succeeds on the third attempt."""
    mock_response = _make_tool_response({"field": "retried"})
    err = _make_rate_limit_error()

    with patch("anthropic.Anthropic") as MockAnthropic, patch("time.sleep"):
        create = MockAnthropic.return_value.messages.create
        create.side_effect = [err, err, mock_response]
        client = AnthropicClient(model="claude-sonnet-4-6", api_key="test-key")
        result = client.call(system="s", user="u", tool=tool_def, temperature=0.0, max_tokens=100)

    assert create.call_count == 3
    assert result.tool_input == {"field": "retried"}


def test_exhausts_retries_on_persistent_rate_limit(tool_def):
    """Raises RateLimitError after 3 consecutive failures with no success."""
    err = _make_rate_limit_error()

    with patch("anthropic.Anthropic") as MockAnthropic, patch("time.sleep"):
        create = MockAnthropic.return_value.messages.create
        create.side_effect = [err, err, err]
        client = AnthropicClient(model="claude-sonnet-4-6", api_key="test-key")
        with pytest.raises(anthropic.RateLimitError):
            client.call(system="s", user="u", tool=tool_def, temperature=0.0, max_tokens=100)

    assert create.call_count == 3


def test_does_not_retry_on_bad_request_error(tool_def):
    """Does not retry on 4xx errors — fails immediately after one attempt."""
    err = _make_bad_request_error()

    with patch("anthropic.Anthropic") as MockAnthropic:
        create = MockAnthropic.return_value.messages.create
        create.side_effect = err
        client = AnthropicClient(model="claude-sonnet-4-6", api_key="test-key")
        with pytest.raises(anthropic.BadRequestError):
            client.call(system="s", user="u", tool=tool_def, temperature=0.0, max_tokens=100)

    assert create.call_count == 1
