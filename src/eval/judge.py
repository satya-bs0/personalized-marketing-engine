"""LLM-as-judge for the 5 LLM-evaluated dimensions."""
from __future__ import annotations

import time
from pathlib import Path

from src import config as _config
from src.llm.client import AnthropicClient, compute_llm_cost_usd
from src.schemas import ContentBlock, DimensionScore, Donor, GeneratedEmail

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

_THRESHOLDS: dict[str, float] = {
    "faithfulness": 0.8,
    "claim_accuracy": 0.9,
    "brand_voice": 0.7,
    # 0.70 (was 0.95): calibrated to approved at-risk reconnection language
    # ("your commitment matters more than you know", "patients rely on a steady supply")
    # which Haiku scores ~0.75. Explicit guilt-tripping scores 0.0-0.4.
    "toxicity_sensitivity": 0.70,
    "segment_fit": 0.7,
}

_SCORE_DIMENSION_TOOL: dict = {
    "name": "score_dimension",
    "description": "Report the evaluation score and reasoning for the given dimension.",
    "input_schema": {
        "type": "object",
        "properties": {
            "score": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Numeric score 0.0 (worst) to 1.0 (best)",
            },
            "reasoning": {
                "type": "string",
                "description": "Concise reasoning for the score (max 300 characters)",
            },
        },
        "required": ["score", "reasoning"],
    },
}


class LLMJudge:
    def __init__(
        self,
        client: AnthropicClient,
        model: str | None = None,
    ) -> None:
        judge_model = model or _config.ANTHROPIC_MODEL_JUDGE
        # If the supplied client uses a different model, create a dedicated judge client.
        if client.model == judge_model:
            self._client = client
        else:
            self._client = AnthropicClient(
                model=judge_model,
                api_key=_config.ANTHROPIC_API_KEY,
                enable_prompt_caching=client.enable_prompt_caching,
            )
        self._model_name = judge_model

    def score(
        self,
        dimension: str,
        email: GeneratedEmail,
        donor: Donor,
        selected_blocks: dict[str, ContentBlock] | None = None,
    ) -> DimensionScore:
        if dimension not in _THRESHOLDS:
            raise ValueError(f"Unknown LLM-judged dimension: {dimension!r}")

        system_prompt = self._load_prompt(dimension)
        user_prompt = self._format_user_prompt(dimension, email, donor, selected_blocks)

        t0 = time.perf_counter()
        resp = self._client.call(
            system=system_prompt,
            user=user_prompt,
            tool=_SCORE_DIMENSION_TOOL,
            temperature=0,
            max_tokens=200,
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)

        score_val = float(resp.tool_input.get("score", 0.0))
        score_val = max(0.0, min(1.0, score_val))
        reasoning = str(resp.tool_input.get("reasoning", ""))[:300]
        threshold = _THRESHOLDS[dimension]

        return DimensionScore(
            dimension=dimension,
            score=round(score_val, 4),
            passed=score_val >= threshold,
            threshold=threshold,
            reasoning=reasoning,
            judge_model=resp.model,
            metadata={
                "input_tokens": resp.input_tokens,
                "output_tokens": resp.output_tokens,
                "latency_ms": latency_ms,
                "cost_usd": round(compute_llm_cost_usd(resp), 8),
                "prompt_hash": resp.prompt_hash,
            },
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _load_prompt(self, dimension: str) -> str:
        path = _PROMPTS_DIR / f"judge_{dimension}.md"
        return path.read_text(encoding="utf-8").strip()

    def _format_user_prompt(
        self,
        dimension: str,
        email: GeneratedEmail,
        donor: Donor,
        selected_blocks: dict[str, ContentBlock] | None,
    ) -> str:
        donor_section = (
            f"DONOR PROFILE:\n"
            f"  first_name: {donor.first_name}\n"
            f"  lifecycle_stage: {donor.lifecycle_stage}\n"
            f"  recency_tier: {donor.recency_tier}\n"
            f"  weeks_since_last_donation: {donor.weeks_since_last_donation}\n"
            f"  lifetime_donations: {donor.lifetime_donations}\n"
            f"  estimated_patients_helped: {donor.estimated_patients_helped}\n"
            f"  center_name: {donor.center_name}"
        )

        blocks_section = ""
        if selected_blocks:
            lines = ["\nAPPROVED BLOCKS USED:"]
            for slot, block in selected_blocks.items():
                lines.append(f"  [{slot}] {block.block_id}: {block.approved_text!r}")
            blocks_section = "\n".join(lines)

        return (
            f"{donor_section}"
            f"{blocks_section}\n"
            f"\nEMAIL TO EVALUATE:\n"
            f"Subject: {email.subject}\n\n"
            f"Body:\n{email.body}"
        )
