"""Mocked unit tests for src/pipeline/assembly.py — no real API calls."""
from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from src.pipeline.assembly import assemble_email
from src.schemas import ContentBlock, Donor, GeneratedEmail, LLMResponse


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_donor() -> Donor:
    return Donor(
        donor_id=uuid.uuid4(),
        donor_hash="testhash002",
        first_name="Raj",
        email="raj@example.com",
        center_name="BioLife Mumbai",
        weeks_since_last_donation=3,
        lifetime_donations=25,
        estimated_patients_helped=75,
        lifecycle_stage="champion",
        recency_tier="3-5wk",
    )


def _make_block(block_id: str, block_type: str, text: str) -> ContentBlock:
    safe = []
    import re
    safe = list(set(re.findall(r"\{(\w+)\}", text)))
    return ContentBlock(
        block_id=block_id,
        block_type=block_type,
        version=1,
        approved_text=text,
        safe_tokens=safe if safe else [],
        segment_fit={"lifecycle_stages": ["champion"], "recency_tiers": ["3-5wk"]},
        mlr_approval_id="MLR-TEST-002",
        mlr_approved_at=datetime(2025, 1, 1),
        status="approved",
        forbidden_modifications=[],
    )


def _make_selected_blocks() -> dict[str, ContentBlock]:
    return {
        "subject": _make_block("subj_champ_001", "subject", "Your impact matters, {first_name}"),
        "opener": _make_block("open_champ_001", "opener", "Dear {first_name}, thank you for your dedication."),
        "impact": _make_block("impa_champ_001", "impact", "Your {lifetime_donations} donations have helped {estimated_patients_helped} patients."),
        "social_proof": _make_block("soci_champ_001", "social_proof", "Donors like you are the reason lives are saved every week."),
        "cta": _make_block("cta_champ_001", "cta", "We would love to see you again at {center_name}."),
        "signoff": _make_block("sign_001", "signoff", "With deep gratitude, The BioLife Team"),
    }


def _make_llm_response(tool_input: dict) -> LLMResponse:
    return LLMResponse(
        tool_input=tool_input,
        input_tokens=310,
        output_tokens=160,
        latency_ms=580,
        model="claude-sonnet-4-6",
        prompt_hash="fedcba654321",
        raw_response_id="msg_asm_001",
    )


def _mock_client(tool_input: dict) -> MagicMock:
    client = MagicMock()
    client.call.return_value = _make_llm_response(tool_input)
    return client


def _valid_email_tool_input(donor: Donor) -> dict:
    return {
        "subject": f"Your impact matters, {donor.first_name}",
        "body": (
            f"Dear {donor.first_name}, thank you for your dedication.\n\n"
            f"Your {donor.lifetime_donations} donations have helped {donor.estimated_patients_helped} patients.\n\n"
            "Donors like you are the reason lives are saved every week.\n\n"
            f"We would love to see you again at {donor.center_name}.\n\n"
            "With deep gratitude, The BioLife Team"
        ),
        "tokens_used": ["first_name", "lifetime_donations", "estimated_patients_helped", "center_name"],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_returns_generated_email():
    """Returns a GeneratedEmail with all fields populated."""
    donor = _make_donor()
    blocks = _make_selected_blocks()
    client = _mock_client(_valid_email_tool_input(donor))

    email, response = assemble_email(donor, blocks, client)

    assert isinstance(email, GeneratedEmail)
    assert email.subject == "Your impact matters, Raj"
    assert "Raj" in email.body
    assert response.output_tokens == 160


def test_subject_max_80_chars_passes():
    """An 80-character subject passes validation."""
    donor = _make_donor()
    blocks = _make_selected_blocks()
    tool_input = {**_valid_email_tool_input(donor), "subject": "A" * 80}
    client = _mock_client(tool_input)

    email, _ = assemble_email(donor, blocks, client)

    assert len(email.subject) == 80


def test_subject_over_80_chars_raises():
    """Pydantic rejects subjects longer than 80 characters."""
    donor = _make_donor()
    blocks = _make_selected_blocks()
    tool_input = {**_valid_email_tool_input(donor), "subject": "X" * 81}
    client = _mock_client(tool_input)

    with pytest.raises(Exception):
        assemble_email(donor, blocks, client)


def test_body_at_500_words_passes():
    """A 500-word body passes the word-count validator."""
    donor = _make_donor()
    blocks = _make_selected_blocks()
    tool_input = {**_valid_email_tool_input(donor), "body": " ".join(["word"] * 500)}
    client = _mock_client(tool_input)

    email, _ = assemble_email(donor, blocks, client)

    assert len(email.body.split()) == 500


def test_body_over_500_words_raises():
    """model_validator rejects bodies with more than 500 words."""
    donor = _make_donor()
    blocks = _make_selected_blocks()
    tool_input = {**_valid_email_tool_input(donor), "body": " ".join(["word"] * 501)}
    client = _mock_client(tool_input)

    with pytest.raises(Exception, match="500 words"):
        assemble_email(donor, blocks, client)


def test_prompt_contains_selected_block_texts():
    """User prompt includes the approved block texts for Claude to use verbatim."""
    donor = _make_donor()
    blocks = _make_selected_blocks()
    client = _mock_client(_valid_email_tool_input(donor))

    assemble_email(donor, blocks, client)

    call_kwargs = client.call.call_args.kwargs
    user_prompt: str = call_kwargs["user"]

    assert "Your impact matters, {first_name}" in user_prompt
    assert "Dear {first_name}, thank you for your dedication." in user_prompt
    assert "The BioLife Team" in user_prompt


def test_prompt_contains_donor_token_values():
    """User prompt includes the resolved token values for Claude to substitute."""
    donor = _make_donor()
    blocks = _make_selected_blocks()
    client = _mock_client(_valid_email_tool_input(donor))

    assemble_email(donor, blocks, client)

    call_kwargs = client.call.call_args.kwargs
    user_prompt: str = call_kwargs["user"]

    assert "Raj" in user_prompt            # first_name
    assert "BioLife Mumbai" in user_prompt  # center_name
    assert "75" in user_prompt             # estimated_patients_helped
    assert "25" in user_prompt             # lifetime_donations


def test_block_token_placeholders_preserved_in_prompt():
    """Block {token} placeholders must reach Claude unchanged — not pre-substituted."""
    donor = _make_donor()
    blocks = _make_selected_blocks()
    client = _mock_client(_valid_email_tool_input(donor))

    assemble_email(donor, blocks, client)

    call_kwargs = client.call.call_args.kwargs
    user_prompt: str = call_kwargs["user"]

    # The block text "{first_name}" should appear verbatim so Claude knows to substitute it
    assert "{first_name}" in user_prompt


def test_called_with_temperature_03_and_max_tokens_800():
    """Stage 2 must use temperature=0.3 and max_tokens=800."""
    donor = _make_donor()
    blocks = _make_selected_blocks()
    client = _mock_client(_valid_email_tool_input(donor))

    assemble_email(donor, blocks, client)

    call_kwargs = client.call.call_args.kwargs
    assert call_kwargs["temperature"] == 0.3
    assert call_kwargs["max_tokens"] == 800
