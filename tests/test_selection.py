"""Mocked unit tests for src/pipeline/selection.py — no real API calls."""
from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from src.pipeline.selection import SelectionError, select_blocks_for_donor
from src.schemas import BlockSelection, ContentBlock, Donor, LLMResponse


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_donor() -> Donor:
    return Donor(
        donor_id=uuid.uuid4(),
        donor_hash="testhash001",
        first_name="Priya",
        email="priya@example.com",
        center_name="BioLife Bengaluru",
        weeks_since_last_donation=4,
        lifetime_donations=12,
        estimated_patients_helped=36,
        lifecycle_stage="regular",
        recency_tier="3-5wk",
    )


def _make_block(block_id: str, block_type: str) -> ContentBlock:
    return ContentBlock(
        block_id=block_id,
        block_type=block_type,
        version=1,
        approved_text="Dear {first_name}, thank you for your {lifetime_donations} donations.",
        safe_tokens=["first_name", "lifetime_donations"],
        segment_fit={"lifecycle_stages": ["regular"], "recency_tiers": ["3-5wk"]},
        mlr_approval_id="MLR-TEST-001",
        mlr_approved_at=datetime(2025, 1, 1),
        status="approved",
        forbidden_modifications=["Do not change tone"],
    )


def _make_candidates() -> dict[str, list[ContentBlock]]:
    return {
        "subject": [_make_block("subj_regular_001", "subject")],
        "opener": [_make_block("open_regular_001", "opener")],
        "impact": [_make_block("impa_001", "impact")],
        "social_proof": [_make_block("soci_001", "social_proof")],
        "cta": [_make_block("cta_001", "cta")],
        "signoff": [_make_block("sign_001", "signoff")],
    }


def _valid_tool_input() -> dict:
    return {
        "subject_block_id": "subj_regular_001",
        "opener_block_id": "open_regular_001",
        "impact_block_id": "impa_001",
        "social_proof_block_id": "soci_001",
        "cta_block_id": "cta_001",
        "signoff_block_id": "sign_001",
        "selection_reasoning": "Regular donor at 3-5wk recency — warm appreciation blocks fit well.",
    }


def _make_llm_response(tool_input: dict) -> LLMResponse:
    return LLMResponse(
        tool_input=tool_input,
        input_tokens=210,
        output_tokens=85,
        latency_ms=320,
        model="claude-sonnet-4-6",
        prompt_hash="abcdef123456",
        raw_response_id="msg_sel_001",
    )


def _mock_client(tool_input: dict) -> MagicMock:
    client = MagicMock()
    client.call.return_value = _make_llm_response(tool_input)
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_returns_valid_block_selection():
    """Returns BlockSelection with all six IDs when LLM output is valid."""
    donor = _make_donor()
    candidates = _make_candidates()
    client = _mock_client(_valid_tool_input())

    selection, response = select_blocks_for_donor(donor, candidates, client)

    assert isinstance(selection, BlockSelection)
    assert selection.subject_block_id == "subj_regular_001"
    assert selection.opener_block_id == "open_regular_001"
    assert selection.cta_block_id == "cta_001"
    assert response.input_tokens == 210


def test_raises_selection_error_for_invalid_subject_id():
    """Raises SelectionError when LLM returns a subject_block_id not in candidates."""
    donor = _make_donor()
    candidates = _make_candidates()
    bad_input = {**_valid_tool_input(), "subject_block_id": "INVENTED_ID_XYZ"}
    client = _mock_client(bad_input)

    with pytest.raises(SelectionError, match="INVENTED_ID_XYZ"):
        select_blocks_for_donor(donor, candidates, client)


def test_raises_selection_error_for_invalid_cta_id():
    """Raises SelectionError when an LLM returns an ID not in candidates for any slot."""
    donor = _make_donor()
    candidates = _make_candidates()
    bad_input = {**_valid_tool_input(), "cta_block_id": "hallucinated_cta_99"}
    client = _mock_client(bad_input)

    with pytest.raises(SelectionError, match="hallucinated_cta_99"):
        select_blocks_for_donor(donor, candidates, client)


def test_prompt_contains_all_donor_dimensions():
    """The user prompt passed to the client contains all five donor dimensions."""
    donor = _make_donor()
    candidates = _make_candidates()
    client = _mock_client(_valid_tool_input())

    select_blocks_for_donor(donor, candidates, client)

    call_kwargs = client.call.call_args.kwargs
    user_prompt: str = call_kwargs["user"]

    assert "Priya" in user_prompt           # first_name
    assert "regular" in user_prompt         # lifecycle_stage
    assert "3-5wk" in user_prompt           # recency_tier
    assert "BioLife Bengaluru" in user_prompt  # center_name
    assert "12" in user_prompt              # lifetime_donations
    assert "36" in user_prompt              # estimated_patients_helped


def test_prompt_contains_candidate_block_ids():
    """The user prompt includes the candidate block IDs so Claude can choose."""
    donor = _make_donor()
    candidates = _make_candidates()
    client = _mock_client(_valid_tool_input())

    select_blocks_for_donor(donor, candidates, client)

    call_kwargs = client.call.call_args.kwargs
    user_prompt: str = call_kwargs["user"]

    assert "subj_regular_001" in user_prompt
    assert "open_regular_001" in user_prompt
    assert "cta_001" in user_prompt


def test_called_with_temperature_zero_and_max_tokens_500():
    """Stage 1 must use temperature=0 (deterministic) and max_tokens=500."""
    donor = _make_donor()
    candidates = _make_candidates()
    client = _mock_client(_valid_tool_input())

    select_blocks_for_donor(donor, candidates, client)

    call_kwargs = client.call.call_args.kwargs
    assert call_kwargs["temperature"] == 0.0
    assert call_kwargs["max_tokens"] == 500


def test_block_token_placeholders_not_substituted_in_prompt():
    """Block text {token} placeholders must reach the LLM unchanged (for context)."""
    donor = _make_donor()
    candidates = _make_candidates()
    client = _mock_client(_valid_tool_input())

    select_blocks_for_donor(donor, candidates, client)

    call_kwargs = client.call.call_args.kwargs
    user_prompt: str = call_kwargs["user"]

    # Block text contains {first_name} — it should appear as-is in the prompt,
    # not substituted with "Priya" (that substitution is Claude's job in Stage 2).
    assert "{first_name}" in user_prompt
