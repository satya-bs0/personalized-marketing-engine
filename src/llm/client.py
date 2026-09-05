from __future__ import annotations

import hashlib
import time

import anthropic
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src import config
from src.schemas import LLMResponse


# Pricing per token for supported models (as of 2025-05-18).
# Cache write = 1.25x input; cache read = 0.10x input.
_MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5": {
        "input": 0.80 / 1_000_000,
        "output": 4.00 / 1_000_000,
        "cache_write": 1.00 / 1_000_000,
        "cache_read": 0.08 / 1_000_000,
    },
    "claude-haiku-4-5-20251001": {
        "input": 0.80 / 1_000_000,
        "output": 4.00 / 1_000_000,
        "cache_write": 1.00 / 1_000_000,
        "cache_read": 0.08 / 1_000_000,
    },
    "claude-sonnet-4-6": {
        "input": 3.00 / 1_000_000,
        "output": 15.00 / 1_000_000,
        "cache_write": 3.75 / 1_000_000,
        "cache_read": 0.30 / 1_000_000,
    },
}
_DEFAULT_PRICING = _MODEL_PRICING["claude-haiku-4-5"]


def compute_llm_cost_usd(resp: LLMResponse) -> float:
    """Return the USD cost for one LLM call based on the response's model and token counts."""
    pricing = _MODEL_PRICING.get(resp.model, _DEFAULT_PRICING)
    return (
        resp.input_tokens * pricing["input"]
        + resp.output_tokens * pricing["output"]
        + resp.cache_creation_input_tokens * pricing["cache_write"]
        + resp.cache_read_input_tokens * pricing["cache_read"]
    )


class AnthropicClient:
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        enable_prompt_caching: bool | None = None,
    ) -> None:
        self.model = model
        self._client = anthropic.Anthropic(api_key=api_key)
        # Default reads from config; caller can override (e.g. tests can pass False)
        self.enable_prompt_caching = (
            enable_prompt_caching
            if enable_prompt_caching is not None
            else config.ENABLE_PROMPT_CACHING
        )

    def call(
        self,
        system: str,
        user: str,
        tool: dict,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        return self._call_with_retry(system, user, tool, temperature, max_tokens)

    @retry(
        retry=retry_if_exception_type((anthropic.RateLimitError, anthropic.APIConnectionError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def _call_with_retry(
        self,
        system: str,
        user: str,
        tool: dict,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        prompt_hash = hashlib.sha256((system + user).encode()).hexdigest()

        # System prompt caching: mark the system prompt as cacheable so that subsequent
        # calls with the same system prompt skip re-encoding those tokens.
        # The user prompt is never cached — it varies per donor.
        system_param: str | list = (
            [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
            if self.enable_prompt_caching
            else system
        )

        create_kwargs: dict = dict(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_param,
            messages=[{"role": "user", "content": user}],
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
        )
        if self.enable_prompt_caching:
            create_kwargs["extra_headers"] = {"anthropic-beta": "prompt-caching-2024-07-31"}

        t0 = time.perf_counter()
        response = self._client.messages.create(**create_kwargs)
        latency_ms = int((time.perf_counter() - t0) * 1000)

        tool_block = next(
            (b for b in response.content if b.type == "tool_use"),
            None,
        )
        if tool_block is None:
            raise ValueError(f"No tool_use block in API response. Content: {response.content}")

        usage = response.usage
        return LLMResponse(
            tool_input=tool_block.input,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            latency_ms=latency_ms,
            model=response.model,
            prompt_hash=prompt_hash,
            raw_response_id=response.id,
            cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        )
