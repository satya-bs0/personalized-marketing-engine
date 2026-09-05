"""
AuditStore: append-only writer for the audit_log table.
EmailStore: writer for the generated_emails table.

Both classes take a Supabase client so they are testable with mocks.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from supabase import Client

from src.llm.client import compute_llm_cost_usd
from src.schemas import (
    AuditLog,
    BlockSelection,
    ContentBlock,
    Donor,
    GeneratedEmail,
    GuardrailResult,
    LLMResponse,
)


class AuditStore:
    """Writes audit rows to audit_log.  Only INSERT — never UPDATE or DELETE."""

    def __init__(self, client: Client) -> None:
        self._db = client

    def emit(self, audit: AuditLog) -> None:
        self._db.table("audit_log").insert(_audit_to_dict(audit)).execute()


class EmailStore:
    """Writes rows to generated_emails."""

    def __init__(self, client: Client) -> None:
        self._db = client

    def save(
        self,
        email_id: uuid.UUID,
        batch_id: uuid.UUID,
        donor_id: uuid.UUID,
        email: Optional[GeneratedEmail],
        selected_block_ids: list[str],
        status: str,
        quarantine_reasons: Optional[list[str]] = None,
    ) -> None:
        self._db.table("generated_emails").insert({
            "email_id": str(email_id),
            "batch_id": str(batch_id),
            "donor_id": str(donor_id),
            "subject": email.subject if email else None,
            "body": email.body if email else None,
            "selected_block_ids": selected_block_ids,
            "status": status,
            "quarantine_reasons": quarantine_reasons or [],
            "generated_at": datetime.utcnow().isoformat(),
        }).execute()


# ---------------------------------------------------------------------------
# AuditLog factory helpers
# Each helper creates an AuditLog for one pipeline stage.
# CRITICAL: donor_hash is used — never raw donor_id.
# ---------------------------------------------------------------------------

def make_eligibility_audit(
    batch_id: uuid.UUID,
    donor: Donor,
    passed: bool,
) -> AuditLog:
    return AuditLog(
        batch_id=batch_id,
        donor_hash=donor.donor_hash,
        stage="eligibility",
        input_summary={
            "lifecycle_stage": donor.lifecycle_stage,
            "deferral_status": donor.deferral_status,
            "consent_email": donor.consent_email,
        },
        output={"eligible": passed},
        verdict="pass" if passed else "fail",
    )


def make_prefilter_audit(
    batch_id: uuid.UUID,
    donor: Donor,
    candidates_by_slot: dict[str, list],
) -> AuditLog:
    return AuditLog(
        batch_id=batch_id,
        donor_hash=donor.donor_hash,
        stage="prefilter",
        input_summary={
            "lifecycle_stage": donor.lifecycle_stage,
            "recency_tier": donor.recency_tier,
        },
        output={
            "candidates_per_slot": {
                slot: len(blocks) for slot, blocks in candidates_by_slot.items()
            }
        },
    )


def make_selection_audit(
    batch_id: uuid.UUID,
    donor: Donor,
    llm_resp: LLMResponse,
    selection: BlockSelection,
) -> AuditLog:
    return AuditLog(
        batch_id=batch_id,
        donor_hash=donor.donor_hash,
        stage="selection",
        model_version=llm_resp.model,
        prompt_hash=llm_resp.prompt_hash,
        input_summary={
            "lifecycle_stage": donor.lifecycle_stage,
            "recency_tier": donor.recency_tier,
        },
        output={
            "subject_block_id": selection.subject_block_id,
            "opener_block_id": selection.opener_block_id,
            "impact_block_id": selection.impact_block_id,
            "social_proof_block_id": selection.social_proof_block_id,
            "cta_block_id": selection.cta_block_id,
            "signoff_block_id": selection.signoff_block_id,
            "selection_reasoning": selection.selection_reasoning[:200],
        },
        latency_ms=llm_resp.latency_ms,
        token_usage={
            "input_tokens": llm_resp.input_tokens,
            "output_tokens": llm_resp.output_tokens,
            "cache_read": llm_resp.cache_read_input_tokens,
            "cache_creation": llm_resp.cache_creation_input_tokens,
        },
        cost_usd=compute_llm_cost_usd(llm_resp),
    )


def make_assembly_audit(
    batch_id: uuid.UUID,
    donor: Donor,
    llm_resp: LLMResponse,
    email: GeneratedEmail,
) -> AuditLog:
    return AuditLog(
        batch_id=batch_id,
        donor_hash=donor.donor_hash,
        stage="assembly",
        model_version=llm_resp.model,
        prompt_hash=llm_resp.prompt_hash,
        input_summary={"tokens_requested": list(email.tokens_used)},
        output={
            "subject_len": len(email.subject),
            "body_word_count": len(email.body.split()),
            "tokens_used": email.tokens_used,
        },
        latency_ms=llm_resp.latency_ms,
        token_usage={
            "input_tokens": llm_resp.input_tokens,
            "output_tokens": llm_resp.output_tokens,
            "cache_read": llm_resp.cache_read_input_tokens,
            "cache_creation": llm_resp.cache_creation_input_tokens,
        },
        cost_usd=compute_llm_cost_usd(llm_resp),
    )


def make_guardrail_audit(
    batch_id: uuid.UUID,
    donor: Donor,
    result: GuardrailResult,
) -> AuditLog:
    return AuditLog(
        batch_id=batch_id,
        donor_hash=donor.donor_hash,
        stage="guardrail",
        output={
            "checks": [
                {
                    "check_name": c.check_name,
                    "passed": c.passed,
                    "reason": c.reason,
                    "metadata": c.metadata,
                }
                for c in result.checks
            ]
        },
        verdict=result.verdict,
        failure_reasons=result.failure_reasons if result.verdict == "fail" else None,
    )


def make_error_audit(
    batch_id: uuid.UUID,
    donor: Donor,
    stage: str,
    error_msg: str,
) -> AuditLog:
    return AuditLog(
        batch_id=batch_id,
        donor_hash=donor.donor_hash,
        stage=stage,  # type: ignore[arg-type]
        input_summary={"error": True},
        output={"error_message": error_msg[:500]},
        verdict="fail",
    )


# ---------------------------------------------------------------------------
# Internal serialiser
# ---------------------------------------------------------------------------

def _audit_to_dict(audit: AuditLog) -> dict:
    return {
        "audit_id": str(audit.audit_id),
        "batch_id": str(audit.batch_id),
        "donor_hash": audit.donor_hash,
        "stage": audit.stage,
        "timestamp_utc": audit.timestamp_utc.isoformat(),
        "model_version": audit.model_version,
        "prompt_hash": audit.prompt_hash,
        "input_summary": audit.input_summary,
        "output": audit.output,
        "verdict": audit.verdict,
        "failure_reasons": audit.failure_reasons,
        "latency_ms": audit.latency_ms,
        "token_usage": audit.token_usage,
        "cost_usd": float(audit.cost_usd) if audit.cost_usd is not None else None,
    }
