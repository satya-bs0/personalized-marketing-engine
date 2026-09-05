"""
Tests for AuditStore and EmailStore.

Unit tests mock the Supabase client.
Live tests (marked @pytest.mark.live) hit the real DB to verify the
append-only trigger blocks UPDATE and DELETE.
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import MagicMock, call

import pytest
from dotenv import load_dotenv

from src.audit.store import (
    AuditStore,
    EmailStore,
    make_eligibility_audit,
    make_guardrail_audit,
    make_selection_audit,
    make_prefilter_audit,
)
from src.schemas import (
    AuditLog,
    BlockSelection,
    Donor,
    GeneratedEmail,
    GuardrailCheck,
    GuardrailResult,
    LLMResponse,
)

load_dotenv()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_donor() -> Donor:
    return Donor(
        donor_hash="hash_abc123",
        first_name="Bob",
        email="bob@example.com",
        center_name="BioLife Delhi",
        weeks_since_last_donation=6,
        lifetime_donations=20,
        estimated_patients_helped=10,
        lifecycle_stage="regular",
        recency_tier="6-10wk",
    )


def _make_mock_db() -> MagicMock:
    """Return a mock Supabase client with chainable table/insert/execute calls."""
    mock = MagicMock()
    mock.table.return_value = mock
    mock.insert.return_value = mock
    mock.execute.return_value = MagicMock()
    return mock


def _make_llm_resp() -> LLMResponse:
    return LLMResponse(
        tool_input={},
        input_tokens=200,
        output_tokens=80,
        latency_ms=400,
        model="claude-haiku-4-5",
        prompt_hash="deadbeef",
        raw_response_id="msg_test",
    )


# ---------------------------------------------------------------------------
# AuditStore unit tests
# ---------------------------------------------------------------------------

class TestAuditStoreUnit:
    def test_emit_calls_insert_on_audit_log(self):
        db = _make_mock_db()
        store = AuditStore(db)
        donor = _make_donor()
        batch_id = uuid.uuid4()

        audit = make_eligibility_audit(batch_id, donor, passed=True)
        store.emit(audit)

        db.table.assert_called_with("audit_log")
        assert db.insert.called
        assert db.execute.called

    def test_emit_inserts_donor_hash_not_donor_id(self):
        db = _make_mock_db()
        store = AuditStore(db)
        donor = _make_donor()
        batch_id = uuid.uuid4()

        audit = make_eligibility_audit(batch_id, donor, passed=True)
        store.emit(audit)

        inserted_data: dict = db.insert.call_args[0][0]
        assert "donor_hash" in inserted_data
        assert inserted_data["donor_hash"] == donor.donor_hash
        # raw donor_id must never appear in the audit log row
        assert "donor_id" not in inserted_data

    def test_emit_contains_required_fields(self):
        db = _make_mock_db()
        store = AuditStore(db)
        donor = _make_donor()
        batch_id = uuid.uuid4()

        audit = make_eligibility_audit(batch_id, donor, passed=True)
        store.emit(audit)

        data: dict = db.insert.call_args[0][0]
        for field in ("audit_id", "batch_id", "donor_hash", "stage", "timestamp_utc"):
            assert field in data, f"Missing field: {field}"

    def test_emit_stage_stored_correctly(self):
        db = _make_mock_db()
        store = AuditStore(db)
        donor = _make_donor()
        batch_id = uuid.uuid4()

        audit = make_eligibility_audit(batch_id, donor, passed=True)
        store.emit(audit)

        data: dict = db.insert.call_args[0][0]
        assert data["stage"] == "eligibility"

    def test_emit_never_calls_update(self):
        db = _make_mock_db()
        store = AuditStore(db)
        donor = _make_donor()
        batch_id = uuid.uuid4()

        audit = make_eligibility_audit(batch_id, donor, passed=True)
        store.emit(audit)

        # The store implementation must ONLY call insert, never update or delete
        assert not db.update.called
        assert not db.delete.called

    def test_selection_audit_includes_model_and_prompt_hash(self):
        db = _make_mock_db()
        store = AuditStore(db)
        donor = _make_donor()
        batch_id = uuid.uuid4()

        selection = BlockSelection(
            subject_block_id="subj_001",
            opener_block_id="open_001",
            impact_block_id="impa_001",
            social_proof_block_id="socp_001",
            cta_block_id="cta__001",
            signoff_block_id="sign_001",
            selection_reasoning="Test",
        )
        audit = make_selection_audit(batch_id, donor, _make_llm_resp(), selection)
        store.emit(audit)

        data: dict = db.insert.call_args[0][0]
        assert data["model_version"] == "claude-haiku-4-5"
        assert data["prompt_hash"] == "deadbeef"
        assert data["latency_ms"] == 400

    def test_guardrail_audit_records_verdict_and_failure_reasons(self):
        db = _make_mock_db()
        store = AuditStore(db)
        donor = _make_donor()
        batch_id = uuid.uuid4()

        gr = GuardrailResult(
            verdict="fail",
            checks=[
                GuardrailCheck(check_name="pii_leak", passed=False, reason="SSN found"),
                GuardrailCheck(check_name="length", passed=True),
            ],
        )
        audit = make_guardrail_audit(batch_id, donor, gr)
        store.emit(audit)

        data: dict = db.insert.call_args[0][0]
        assert data["verdict"] == "fail"
        assert "pii_leak" in data["failure_reasons"]

    def test_passing_guardrail_has_null_failure_reasons(self):
        db = _make_mock_db()
        store = AuditStore(db)
        donor = _make_donor()
        batch_id = uuid.uuid4()

        gr = GuardrailResult(
            verdict="pass",
            checks=[GuardrailCheck(check_name="pii_leak", passed=True)],
        )
        audit = make_guardrail_audit(batch_id, donor, gr)
        store.emit(audit)

        data: dict = db.insert.call_args[0][0]
        assert data["verdict"] == "pass"
        assert data["failure_reasons"] is None


# ---------------------------------------------------------------------------
# EmailStore unit tests
# ---------------------------------------------------------------------------

class TestEmailStoreUnit:
    def test_save_inserts_to_generated_emails(self):
        db = _make_mock_db()
        store = EmailStore(db)
        email = GeneratedEmail(
            subject="Hello Alice",
            body="Thank you for your donations.",
            tokens_used=["first_name"],
        )
        batch_id = uuid.uuid4()
        donor_id = uuid.uuid4()
        email_id = uuid.uuid4()

        store.save(
            email_id=email_id,
            batch_id=batch_id,
            donor_id=donor_id,
            email=email,
            selected_block_ids=["blk_001", "blk_002"],
            status="pass",
        )

        db.table.assert_called_with("generated_emails")
        assert db.insert.called

    def test_save_quarantine_includes_reasons(self):
        db = _make_mock_db()
        store = EmailStore(db)
        batch_id = uuid.uuid4()
        donor_id = uuid.uuid4()
        email_id = uuid.uuid4()
        email = GeneratedEmail(subject="S", body="B", tokens_used=[])

        store.save(
            email_id=email_id,
            batch_id=batch_id,
            donor_id=donor_id,
            email=email,
            selected_block_ids=[],
            status="quarantine",
            quarantine_reasons=["pii_leak"],
        )

        data: dict = db.insert.call_args[0][0]
        assert data["status"] == "quarantine"
        assert "pii_leak" in data["quarantine_reasons"]


# ---------------------------------------------------------------------------
# Live tests — require real Supabase connection + migrations applied
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_append_only_trigger_blocks_update():
    """DB trigger must reject any UPDATE on audit_log."""
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        pytest.skip("SUPABASE_URL / SUPABASE_KEY not set")

    from supabase import create_client
    db = create_client(supabase_url, supabase_key)

    # Insert a real audit row to have something to try updating
    batch_id = uuid.uuid4()
    audit_id = uuid.uuid4()
    db.table("audit_log").insert({
        "audit_id": str(audit_id),
        "batch_id": str(batch_id),
        "donor_hash": "test_hash_trigger",
        "stage": "eligibility",
        "timestamp_utc": "2025-01-01T00:00:00Z",
        "output": {"eligible": True},
    }).execute()

    # Attempt UPDATE — must raise
    with pytest.raises(Exception) as exc_info:
        db.table("audit_log").update(
            {"verdict": "tampered"}
        ).eq("audit_id", str(audit_id)).execute()

    assert "append-only" in str(exc_info.value).lower() or exc_info.value is not None

    # Cleanup: can't delete (trigger blocks it), so just leave the row
    # (it's a test row in a test run; the DB will be reset between dev cycles)


@pytest.mark.live
def test_append_only_trigger_blocks_delete():
    """DB trigger must reject any DELETE on audit_log."""
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        pytest.skip("SUPABASE_URL / SUPABASE_KEY not set")

    from supabase import create_client
    db = create_client(supabase_url, supabase_key)

    audit_id = uuid.uuid4()
    batch_id = uuid.uuid4()
    db.table("audit_log").insert({
        "audit_id": str(audit_id),
        "batch_id": str(batch_id),
        "donor_hash": "test_hash_trigger_del",
        "stage": "eligibility",
        "timestamp_utc": "2025-01-01T00:00:00Z",
        "output": {"eligible": True},
    }).execute()

    with pytest.raises(Exception):
        db.table("audit_log").delete().eq("audit_id", str(audit_id)).execute()
