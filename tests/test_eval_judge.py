"""Tests for LLMJudge (all mocked — no live API calls)."""
from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.eval.judge import LLMJudge, _THRESHOLDS
from src.schemas import Donor, GeneratedEmail, LLMResponse


def _donor():
    return Donor(
        donor_id=uuid.uuid4(),
        donor_hash="b" * 64,
        first_name="Ananya",
        email="ananya@example.com",
        center_name="BioLife Delhi",
        weeks_since_last_donation=3,
        lifetime_donations=20,
        estimated_patients_helped=10,
        lifecycle_stage="regular",
        recency_tier="3-5wk",
        deferral_status="eligible",
        deferral_until=None,
        consent_email=True,
        created_at=datetime.utcnow(),
    )


def _email():
    return GeneratedEmail.model_construct(
        subject="Thank you, Ananya",
        body="Hi Ananya, your commitment inspires us at BioLife Delhi.",
        tokens_used=["first_name", "center_name"],
    )


def _make_llm_resp(score: float, reasoning: str = "looks good") -> LLMResponse:
    return LLMResponse(
        tool_input={"score": score, "reasoning": reasoning},
        input_tokens=100,
        output_tokens=30,
        latency_ms=500,
        model="claude-haiku-4-5",
        prompt_hash="abc123",
        raw_response_id="msg_test",
    )


def _make_client(score: float = 0.9, reasoning: str = "test"):
    client = MagicMock()
    client.model = "claude-haiku-4-5"
    client.enable_prompt_caching = False
    client.call.return_value = _make_llm_resp(score, reasoning)
    return client


class TestLLMJudge:
    def test_score_returns_dimension_score(self):
        client = _make_client(score=0.85)
        judge = LLMJudge(client)
        result = judge.score("faithfulness", _email(), _donor())
        assert result.dimension == "faithfulness"
        assert result.score == pytest.approx(0.85)
        assert result.passed is True  # 0.85 >= 0.8
        assert result.threshold == 0.8

    def test_score_clamps_above_one(self):
        client = _make_client(score=1.5)
        judge = LLMJudge(client)
        result = judge.score("brand_voice", _email(), _donor())
        assert result.score == 1.0

    def test_score_clamps_below_zero(self):
        client = _make_client(score=-0.5)
        judge = LLMJudge(client)
        result = judge.score("brand_voice", _email(), _donor())
        assert result.score == 0.0

    def test_fails_when_below_threshold(self):
        client = _make_client(score=0.6)
        judge = LLMJudge(client)
        result = judge.score("claim_accuracy", _email(), _donor())  # threshold=0.9
        assert result.passed is False

    def test_reasoning_truncated_to_300_chars(self):
        long_reason = "x" * 400
        client = _make_client(reasoning=long_reason)
        judge = LLMJudge(client)
        result = judge.score("faithfulness", _email(), _donor())
        assert len(result.reasoning) <= 300

    def test_judge_model_recorded(self):
        client = _make_client()
        judge = LLMJudge(client)
        result = judge.score("segment_fit", _email(), _donor())
        assert result.judge_model == "claude-haiku-4-5"

    def test_metadata_contains_cost(self):
        client = _make_client()
        judge = LLMJudge(client)
        result = judge.score("faithfulness", _email(), _donor())
        assert "cost_usd" in result.metadata
        assert "input_tokens" in result.metadata
        assert "output_tokens" in result.metadata

    def test_unknown_dimension_raises(self):
        client = _make_client()
        judge = LLMJudge(client)
        with pytest.raises(ValueError, match="Unknown LLM-judged dimension"):
            judge.score("made_up_dimension", _email(), _donor())

    def test_loads_correct_prompt_file_per_dimension(self):
        """Judge must load the right prompt file for each dimension."""
        client = _make_client()
        judge = LLMJudge(client)
        for dim in _THRESHOLDS:
            # This should not raise FileNotFoundError
            prompt = judge._load_prompt(dim)
            assert len(prompt) > 100, f"Prompt for {dim!r} is suspiciously short"
            assert "score_dimension" in prompt.lower() or "score" in prompt.lower()

    def test_user_prompt_contains_donor_info(self):
        client = _make_client()
        judge = LLMJudge(client)
        donor = _donor()
        user_prompt = judge._format_user_prompt("faithfulness", _email(), donor, None)
        assert donor.first_name in user_prompt
        assert donor.lifecycle_stage in user_prompt
        assert str(donor.lifetime_donations) in user_prompt
        assert str(donor.estimated_patients_helped) in user_prompt

    def test_user_prompt_contains_block_info(self):
        from datetime import datetime
        from src.schemas import ContentBlock
        client = _make_client()
        judge = LLMJudge(client)
        blk = ContentBlock(
            block_id="test_blk", block_type="opener", version=1,
            approved_text="Hi there.", safe_tokens=[],
            segment_fit={"lifecycle_stages": ["regular"], "recency_tiers": ["3-5wk"]},
            mlr_approval_id="MLR-9999", mlr_approved_at=datetime.utcnow(),
            status="approved", forbidden_modifications=[],
        )
        prompt = judge._format_user_prompt("faithfulness", _email(), _donor(), {"opener": blk})
        assert "test_blk" in prompt
        assert "APPROVED BLOCKS USED" in prompt

    def test_different_model_creates_new_client(self):
        """If client.model != ANTHROPIC_MODEL_JUDGE, a new client is spun up."""
        client = _make_client()
        client.model = "claude-sonnet-4-6"  # not the judge model
        with patch("src.eval.judge.AnthropicClient") as MockClient:
            mock_inner = MagicMock()
            mock_inner.call.return_value = _make_llm_resp(0.9)
            MockClient.return_value = mock_inner
            judge = LLMJudge(client, model="claude-haiku-4-5")
            MockClient.assert_called_once()
