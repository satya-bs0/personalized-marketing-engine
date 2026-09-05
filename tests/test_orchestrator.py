"""
Unit tests for the single-donor orchestrator.

All LLM calls and Supabase writes are mocked.  Tests verify:
- Correct status returned for each scenario
- Correct number of audit rows emitted at each stage
- email_store.save() called at the right times
- Error paths produce status='error' without writing to generated_emails
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch, call
import uuid

import pytest

from src.pipeline.orchestrator import process_donor
from src.schemas import (
    AuditLog,
    BlockSelection,
    ContentBlock,
    Donor,
    GeneratedEmail,
    GuardrailCheck,
    GuardrailResult,
    LLMResponse,
    ProcessResult,
)
from src.pipeline.selection import SelectionError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def donor() -> Donor:
    return Donor(
        donor_hash="orchtest_hash",
        first_name="Carol",
        email="carol@example.com",
        center_name="BioLife Pune",
        weeks_since_last_donation=3,
        lifetime_donations=15,
        estimated_patients_helped=8,
        lifecycle_stage="regular",
        recency_tier="3-5wk",
    )


@pytest.fixture
def batch_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def mock_llm_resp() -> LLMResponse:
    return LLMResponse(
        tool_input={},
        input_tokens=300,
        output_tokens=100,
        latency_ms=600,
        model="claude-haiku-4-5",
        prompt_hash="cafebabe",
        raw_response_id="msg_mock",
    )


def _make_block(block_id: str, block_type: str) -> ContentBlock:
    return ContentBlock(
        block_id=block_id,
        block_type=block_type,
        version=1,
        approved_text="Sample approved text.",
        safe_tokens=[],
        segment_fit={"lifecycle_stages": ["regular"], "recency_tiers": ["3-5wk"]},
        mlr_approval_id="MLR-MOCK-001",
        mlr_approved_at=datetime.utcnow(),
        status="approved",
        forbidden_modifications=[],
    )


@pytest.fixture
def mock_candidates() -> dict:
    return {
        "subject": [_make_block("subj_001", "subject")],
        "opener": [_make_block("open_001", "opener")],
        "impact": [_make_block("impa_001", "impact")],
        "social_proof": [_make_block("socp_001", "social_proof")],
        "cta": [_make_block("cta__001", "cta")],
        "signoff": [_make_block("sign_001", "signoff")],
    }


@pytest.fixture
def mock_selection() -> BlockSelection:
    return BlockSelection(
        subject_block_id="subj_001",
        opener_block_id="open_001",
        impact_block_id="impa_001",
        social_proof_block_id="socp_001",
        cta_block_id="cta__001",
        signoff_block_id="sign_001",
        selection_reasoning="Mock selection.",
    )


@pytest.fixture
def mock_email() -> GeneratedEmail:
    return GeneratedEmail(
        subject="Thank you Carol",
        body="Sample approved text. Sample approved text. Sample approved text. Sample approved text. Sample approved text.",
        tokens_used=["first_name"],
    )


@pytest.fixture
def guardrail_pass() -> GuardrailResult:
    return GuardrailResult(
        verdict="pass",
        checks=[GuardrailCheck(check_name="token_substitution", passed=True)],
    )


@pytest.fixture
def guardrail_fail() -> GuardrailResult:
    return GuardrailResult(
        verdict="fail",
        checks=[
            GuardrailCheck(check_name="pii_leak", passed=False, reason="Found SSN"),
            GuardrailCheck(check_name="length", passed=True),
        ],
    )


def _make_stores():
    audit_store = MagicMock()
    email_store = MagicMock()
    block_repo = MagicMock()
    llm_client = MagicMock()
    return audit_store, email_store, block_repo, llm_client


# ---------------------------------------------------------------------------
# Test: ineligible donor → quarantine, 1 audit row, no email saved
# ---------------------------------------------------------------------------

def test_ineligible_donor_returns_quarantine(donor, batch_id):
    audit_store, email_store, block_repo, llm_client = _make_stores()

    with patch("src.pipeline.orchestrator.is_donor_eligible", return_value=False), \
         patch("src.pipeline.orchestrator.prefilter_blocks_for_donor") as mock_pf, \
         patch("src.pipeline.orchestrator.select_blocks_for_donor") as mock_sel, \
         patch("src.pipeline.orchestrator.assemble_email") as mock_asm:

        result = process_donor(donor, batch_id, llm_client, audit_store, email_store, block_repo)

    assert result.status == "quarantine"
    assert "ineligible" in result.quarantine_reasons
    assert result.email_id is None
    assert audit_store.emit.call_count == 1  # eligibility only
    email_store.save.assert_not_called()
    mock_pf.assert_not_called()
    mock_sel.assert_not_called()
    mock_asm.assert_not_called()


# ---------------------------------------------------------------------------
# Test: eligible donor, all passes → status='pass', 5 audit rows, 1 email row
# ---------------------------------------------------------------------------

def test_eligible_donor_pass(donor, batch_id, mock_candidates, mock_selection,
                              mock_email, mock_llm_resp, guardrail_pass):
    audit_store, email_store, block_repo, llm_client = _make_stores()

    with patch("src.pipeline.orchestrator.is_donor_eligible", return_value=True), \
         patch("src.pipeline.orchestrator.prefilter_blocks_for_donor", return_value=mock_candidates), \
         patch("src.pipeline.orchestrator.select_blocks_for_donor",
               return_value=(mock_selection, mock_llm_resp)), \
         patch("src.pipeline.orchestrator.assemble_email",
               return_value=(mock_email, mock_llm_resp)), \
         patch("src.pipeline.orchestrator.run_guardrails", return_value=guardrail_pass):

        result = process_donor(donor, batch_id, llm_client, audit_store, email_store, block_repo)

    assert result.status == "pass"
    assert result.email_id is not None
    # 5 audit rows: eligibility, prefilter, selection, assembly, guardrail
    assert audit_store.emit.call_count == 5
    email_store.save.assert_called_once()
    # Verify cost is populated
    assert result.total_cost_usd > 0
    assert result.total_latency_ms > 0


# ---------------------------------------------------------------------------
# Test: guardrails fail → status='quarantine', failure reasons propagated
# ---------------------------------------------------------------------------

def test_guardrail_failure_returns_quarantine(donor, batch_id, mock_candidates,
                                               mock_selection, mock_email,
                                               mock_llm_resp, guardrail_fail):
    audit_store, email_store, block_repo, llm_client = _make_stores()

    with patch("src.pipeline.orchestrator.is_donor_eligible", return_value=True), \
         patch("src.pipeline.orchestrator.prefilter_blocks_for_donor", return_value=mock_candidates), \
         patch("src.pipeline.orchestrator.select_blocks_for_donor",
               return_value=(mock_selection, mock_llm_resp)), \
         patch("src.pipeline.orchestrator.assemble_email",
               return_value=(mock_email, mock_llm_resp)), \
         patch("src.pipeline.orchestrator.run_guardrails", return_value=guardrail_fail):

        result = process_donor(donor, batch_id, llm_client, audit_store, email_store, block_repo)

    assert result.status == "quarantine"
    assert "pii_leak" in result.quarantine_reasons
    # All 5 stages still emit audit rows
    assert audit_store.emit.call_count == 5
    # Email is still saved (so it can be inspected)
    email_store.save.assert_called_once()
    save_kwargs = email_store.save.call_args[1]
    assert save_kwargs["status"] == "quarantine"


# ---------------------------------------------------------------------------
# Test: SelectionError → status='error', error audit at selection stage
# ---------------------------------------------------------------------------

def test_selection_error_returns_error(donor, batch_id, mock_candidates, mock_llm_resp):
    audit_store, email_store, block_repo, llm_client = _make_stores()

    with patch("src.pipeline.orchestrator.is_donor_eligible", return_value=True), \
         patch("src.pipeline.orchestrator.prefilter_blocks_for_donor", return_value=mock_candidates), \
         patch("src.pipeline.orchestrator.select_blocks_for_donor",
               side_effect=SelectionError("block ID not in candidate set")), \
         patch("src.pipeline.orchestrator.assemble_email") as mock_asm, \
         patch("src.pipeline.orchestrator.run_guardrails") as mock_gr:

        result = process_donor(donor, batch_id, llm_client, audit_store, email_store, block_repo)

    assert result.status == "error"
    assert any("selection_error" in r for r in result.quarantine_reasons)
    # 3 audit rows: eligibility, prefilter, error-at-selection
    assert audit_store.emit.call_count == 3
    # email_store.save must NOT be called — nothing to persist
    email_store.save.assert_not_called()
    mock_asm.assert_not_called()
    mock_gr.assert_not_called()


# ---------------------------------------------------------------------------
# Test: assembly raises → status='error', 4 audit rows
# ---------------------------------------------------------------------------

def test_assembly_error_returns_error(donor, batch_id, mock_candidates,
                                      mock_selection, mock_llm_resp):
    audit_store, email_store, block_repo, llm_client = _make_stores()

    with patch("src.pipeline.orchestrator.is_donor_eligible", return_value=True), \
         patch("src.pipeline.orchestrator.prefilter_blocks_for_donor", return_value=mock_candidates), \
         patch("src.pipeline.orchestrator.select_blocks_for_donor",
               return_value=(mock_selection, mock_llm_resp)), \
         patch("src.pipeline.orchestrator.assemble_email",
               side_effect=ValueError("LLM returned invalid JSON")), \
         patch("src.pipeline.orchestrator.run_guardrails") as mock_gr:

        result = process_donor(donor, batch_id, llm_client, audit_store, email_store, block_repo)

    assert result.status == "error"
    assert any("assembly_error" in r for r in result.quarantine_reasons)
    # 4 audit rows: eligibility, prefilter, selection, error-at-assembly
    assert audit_store.emit.call_count == 4
    email_store.save.assert_not_called()
    mock_gr.assert_not_called()
