"""
Single-donor pipeline orchestrator.

Ties together eligibility → prefilter → selection → assembly → guardrails → persist.
Each stage emits one audit row.  Errors at selection or assembly short-circuit the
pipeline and return status='error' without saving to generated_emails.
"""
from __future__ import annotations

import logging
import uuid

from src.audit.store import (
    AuditStore,
    EmailStore,
    make_assembly_audit,
    make_eligibility_audit,
    make_error_audit,
    make_guardrail_audit,
    make_prefilter_audit,
    make_selection_audit,
)
from src.data.blocks import ContentBlockRepository
from src.guardrails.engine import run_guardrails
from src.llm.client import AnthropicClient, compute_llm_cost_usd
from src.pipeline.assembly import assemble_email
from src.pipeline.eligibility import is_donor_eligible
from src.pipeline.prefilter import prefilter_blocks_for_donor
from src.pipeline.selection import SelectionError, select_blocks_for_donor
from src.schemas import BlockSelection, ContentBlock, Donor, ProcessResult

logger = logging.getLogger(__name__)


def process_donor(
    donor: Donor,
    batch_id: uuid.UUID,
    llm_client: AnthropicClient,
    audit_store: AuditStore,
    email_store: EmailStore,
    block_repo: ContentBlockRepository,
) -> ProcessResult:
    """Run the full pipeline for one donor and return the outcome.

    Audit rows are emitted at every stage.  On selection/assembly error the
    pipeline returns status='error' without writing to generated_emails.
    On guardrail failure the email is still persisted (status='quarantine')
    so it can be inspected.
    """
    email_id = uuid.uuid4()
    total_cost: float = 0.0
    total_latency: int = 0

    # ------------------------------------------------------------------
    # Stage 0: Eligibility (deterministic SQL, no LLM)
    # ------------------------------------------------------------------
    eligible = is_donor_eligible(donor.donor_id, client=block_repo._db)
    audit_store.emit(make_eligibility_audit(batch_id, donor, eligible))
    if not eligible:
        return ProcessResult(
            donor_id=donor.donor_id,
            status="quarantine",
            quarantine_reasons=["ineligible"],
        )

    # ------------------------------------------------------------------
    # Stage 0b: Prefilter (deterministic SQL, no LLM)
    # ------------------------------------------------------------------
    candidates = prefilter_blocks_for_donor(donor, repo=block_repo)
    audit_store.emit(make_prefilter_audit(batch_id, donor, candidates))

    # ------------------------------------------------------------------
    # Stage 1: Block Selection (LLM)
    # ------------------------------------------------------------------
    try:
        selection, sel_resp = select_blocks_for_donor(donor, candidates, llm_client)
        audit_store.emit(make_selection_audit(batch_id, donor, sel_resp, selection))
        total_cost += compute_llm_cost_usd(sel_resp)
        total_latency += sel_resp.latency_ms
    except (SelectionError, Exception) as exc:
        logger.error("Selection failed for donor %s: %s", donor.donor_id, exc)
        audit_store.emit(make_error_audit(batch_id, donor, "selection", str(exc)))
        return ProcessResult(
            donor_id=donor.donor_id,
            status="error",
            quarantine_reasons=[f"selection_error: {str(exc)[:200]}"],
        )

    selected_blocks_dict = _resolve_selected_blocks(selection, candidates)

    # ------------------------------------------------------------------
    # Stage 2: Email Assembly (LLM)
    # ------------------------------------------------------------------
    try:
        email, asm_resp = assemble_email(donor, selected_blocks_dict, llm_client)
        audit_store.emit(make_assembly_audit(batch_id, donor, asm_resp, email))
        total_cost += compute_llm_cost_usd(asm_resp)
        total_latency += asm_resp.latency_ms
    except Exception as exc:
        logger.error("Assembly failed for donor %s: %s", donor.donor_id, exc)
        audit_store.emit(make_error_audit(batch_id, donor, "assembly", str(exc)))
        return ProcessResult(
            donor_id=donor.donor_id,
            status="error",
            quarantine_reasons=[f"assembly_error: {str(exc)[:200]}"],
        )

    # ------------------------------------------------------------------
    # Stage 3: Rule-based Guardrails
    # ------------------------------------------------------------------
    guardrail_result = run_guardrails(email, selected_blocks_dict, donor)
    audit_store.emit(make_guardrail_audit(batch_id, donor, guardrail_result))

    if guardrail_result.verdict == "fail":
        status = "quarantine"
        quarantine_reasons = guardrail_result.failure_reasons
    else:
        status = "pass"
        quarantine_reasons = []

    # ------------------------------------------------------------------
    # Stage 4: Persist to generated_emails
    # ------------------------------------------------------------------
    selected_block_ids = [
        selection.subject_block_id,
        selection.opener_block_id,
        selection.impact_block_id,
        selection.social_proof_block_id,
        selection.cta_block_id,
        selection.signoff_block_id,
    ]
    email_store.save(
        email_id=email_id,
        batch_id=batch_id,
        donor_id=donor.donor_id,
        email=email,
        selected_block_ids=selected_block_ids,
        status=status,
        quarantine_reasons=quarantine_reasons if quarantine_reasons else None,
    )

    return ProcessResult(
        donor_id=donor.donor_id,
        email_id=email_id,
        status=status,
        quarantine_reasons=quarantine_reasons,
        email=email,
        selected_blocks=selection,
        total_cost_usd=total_cost,
        total_latency_ms=total_latency,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_selected_blocks(
    selection: BlockSelection,
    candidates: dict[str, list[ContentBlock]],
) -> dict[str, ContentBlock]:
    """Return {slot: ContentBlock} by matching each selected ID in the candidate list."""
    slot_to_field = {
        "subject": "subject_block_id",
        "opener": "opener_block_id",
        "impact": "impact_block_id",
        "social_proof": "social_proof_block_id",
        "cta": "cta_block_id",
        "signoff": "signoff_block_id",
    }
    return {
        slot: next(b for b in candidates[slot] if b.block_id == getattr(selection, field))
        for slot, field in slot_to_field.items()
    }
