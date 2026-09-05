"""Live end-to-end test for one donor through the full pipeline:
eligibility → prefilter → selection → assembly → guardrails.

Run with:  pytest tests/test_e2e_single_donor.py -m live -s

Requires:
  - ANTHROPIC_API_KEY set in .env
  - Supabase populated (run seed.py + seed_blocks.py first)
  - Network access to api.anthropic.com
"""
from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

# Cost reference for claude-haiku-4-5 (as of 2025-05-18)
_INPUT_COST_PER_TOKEN = 0.80 / 1_000_000   # $0.80 per million (regular input)
_OUTPUT_COST_PER_TOKEN = 4.00 / 1_000_000   # $4.00 per million
_CACHE_WRITE_COST_PER_TOKEN = _INPUT_COST_PER_TOKEN * 1.25  # cache write: 1.25x input
_CACHE_READ_COST_PER_TOKEN = _INPUT_COST_PER_TOKEN * 0.10   # cache read: 10% of input


def _call_cost(resp) -> float:
    """Compute total cost for one API call, accounting for cache hits/writes."""
    return (
        resp.input_tokens * _INPUT_COST_PER_TOKEN
        + resp.output_tokens * _OUTPUT_COST_PER_TOKEN
        + resp.cache_creation_input_tokens * _CACHE_WRITE_COST_PER_TOKEN
        + resp.cache_read_input_tokens * _CACHE_READ_COST_PER_TOKEN
    )


@pytest.mark.live
def test_single_donor_end_to_end():
    """Full pipeline on ONE real donor: eligibility → prefilter → selection → assembly."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        pytest.skip("ANTHROPIC_API_KEY not set — skipping live test")

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    assert supabase_url and supabase_key, "SUPABASE_URL and SUPABASE_KEY required"

    model = os.getenv("ANTHROPIC_MODEL_SELECTION", "claude-sonnet-4-6")

    # --- Import here to avoid affecting mocked test collection ---
    from src.data.blocks import ContentBlockRepository
    from src.data.donors import DonorRepository
    from src.llm.client import AnthropicClient
    from src.pipeline.eligibility import is_donor_eligible
    from src.pipeline.prefilter import prefilter_blocks_for_donor
    from src.pipeline.selection import select_blocks_for_donor
    from src.pipeline.assembly import assemble_email
    from src.schemas import Donor

    db_client = create_client(supabase_url, supabase_key)
    block_repo = ContentBlockRepository(db_client)
    donor_repo = DonorRepository(db_client)
    llm_client = AnthropicClient(model=model, api_key=api_key)

    # Guard: verify the DB has eligible donors before proceeding
    eligible_donors = donor_repo.get_eligible_donors(limit=1)
    assert len(eligible_donors) == 1, (
        "Live test must process exactly 1 donor — no eligible donors found. "
        "Run: python -m src.data.seed && python -m src.data.seed_blocks"
    )

    # --- Find a regular, 3-5wk eligible donor ---
    result = (
        db_client.table("donors")
        .select("*")
        .eq("lifecycle_stage", "regular")
        .eq("recency_tier", "3-5wk")
        .eq("consent_email", True)
        .eq("deferral_status", "eligible")
        .limit(1)
        .execute()
    )
    assert result.data, (
        "No regular/3-5wk/eligible donors found. "
        "Run: python -m src.data.seed && python -m src.data.seed_blocks"
    )

    donor = Donor(**result.data[0])

    print(f"\n{'='*60}")
    print(f"DONOR PROFILE")
    print(f"  name:              {donor.first_name}")
    print(f"  lifecycle_stage:   {donor.lifecycle_stage}")
    print(f"  recency_tier:      {donor.recency_tier}")
    print(f"  weeks_since:       {donor.weeks_since_last_donation}")
    print(f"  lifetime_donations:{donor.lifetime_donations}")
    print(f"  patients_helped:   {donor.estimated_patients_helped}")
    print(f"  center_name:       {donor.center_name}")
    print(f"{'='*60}")

    # --- Stage 0: Eligibility ---
    eligible = is_donor_eligible(donor.donor_id, client=db_client)
    assert eligible, f"Donor {donor.donor_id} is not eligible per v_donor_profile"
    print(f"\n[STAGE 0 — ELIGIBILITY] PASS")

    # --- Stage 0b: Prefilter ---
    candidates = prefilter_blocks_for_donor(donor, repo=block_repo)
    print(f"\n[STAGE 0b — PREFILTER] Candidates per slot:")
    for slot, blocks in candidates.items():
        print(f"  {slot:14s}: {[b.block_id for b in blocks]}")

    # --- Stage 1: Block Selection (LLM call 1) ---
    print(f"\n[STAGE 1 — SELECTION] Calling {model} (temp=0, max_tokens=500) ...")
    selection, sel_resp = select_blocks_for_donor(donor, candidates, llm_client)

    sel_cost = _call_cost(sel_resp)
    print(f"\n  prompt_hash:      {sel_resp.prompt_hash[:16]}...")
    print(f"  tokens:           {sel_resp.input_tokens} in / {sel_resp.output_tokens} out")
    print(f"  Cache creation tokens: {sel_resp.cache_creation_input_tokens}")
    print(f"  Cache read tokens:     {sel_resp.cache_read_input_tokens}")
    print(f"  Selection cost (this call): ${sel_cost:.6f}")
    print(f"  latency:          {sel_resp.latency_ms} ms")
    print(f"  response_id:      {sel_resp.raw_response_id}")
    print(f"\n  Selected blocks:")
    print(f"    subject:      {selection.subject_block_id}")
    print(f"    opener:       {selection.opener_block_id}")
    print(f"    impact:       {selection.impact_block_id}")
    print(f"    social_proof: {selection.social_proof_block_id}")
    print(f"    cta:          {selection.cta_block_id}")
    print(f"    signoff:      {selection.signoff_block_id}")
    print(f"  reasoning:    {selection.selection_reasoning}")

    # Validate selected IDs are in candidate sets
    from src.pipeline.selection import _SLOT_TO_FIELD
    for slot, field in _SLOT_TO_FIELD.items():
        returned_id = getattr(selection, field)
        valid_ids = {b.block_id for b in candidates[slot]}
        assert returned_id in valid_ids, (
            f"Selected {field}={returned_id!r} not in candidates {sorted(valid_ids)}"
        )

    # Resolve selected blocks
    selected_blocks = {}
    for slot, field in _SLOT_TO_FIELD.items():
        bid = getattr(selection, field)
        selected_blocks[slot] = next(b for b in candidates[slot] if b.block_id == bid)

    # --- Stage 2: Email Assembly (LLM call 2) ---
    print(f"\n[STAGE 2 — ASSEMBLY] Calling {model} (temp=0.3, max_tokens=800) ...")
    email, asm_resp = assemble_email(donor, selected_blocks, llm_client)

    asm_cost = _call_cost(asm_resp)
    print(f"\n  prompt_hash:      {asm_resp.prompt_hash[:16]}...")
    print(f"  tokens:           {asm_resp.input_tokens} in / {asm_resp.output_tokens} out")
    print(f"  Cache creation tokens: {asm_resp.cache_creation_input_tokens}")
    print(f"  Cache read tokens:     {asm_resp.cache_read_input_tokens}")
    print(f"  Assembly cost (this call): ${asm_cost:.6f}")
    print(f"  latency:          {asm_resp.latency_ms} ms")
    print(f"  response_id:      {asm_resp.raw_response_id}")
    print(f"  tokens_used:      {email.tokens_used}")

    print(f"\n{'='*60}")
    print("GENERATED EMAIL")
    print(f"{'='*60}")
    print(f"Subject: {email.subject}\n")
    print(email.body)
    print(f"{'='*60}")

    # --- Cost summary ---
    total_cost = sel_cost + asm_cost
    total_in = sel_resp.input_tokens + asm_resp.input_tokens
    total_out = sel_resp.output_tokens + asm_resp.output_tokens
    total_cache_create = sel_resp.cache_creation_input_tokens + asm_resp.cache_creation_input_tokens
    total_cache_read = sel_resp.cache_read_input_tokens + asm_resp.cache_read_input_tokens
    print(f"\n[COST]")
    print(f"  Selection cost (this call): ${sel_cost:.6f}")
    print(f"  Assembly cost (this call):  ${asm_cost:.6f}")
    print(f"  Total live test cost:       ${total_cost:.6f}")
    print(f"  Tokens: {total_in} in / {total_out} out / {total_cache_create} cache_write / {total_cache_read} cache_read")
    print(f"  Projected ${total_cost * 1_000:.3f} for 1K donors")
    print(f"  Projected ${total_cost * 400_000:.0f} for 400K donors/week")

    # --- Assertions ---
    assert len(email.subject) <= 80, f"Subject too long: {len(email.subject)} chars"
    assert donor.first_name in email.body, "Donor first_name not found in email body"
    assert "{" not in email.subject, f"Unresolved token placeholder in subject: {email.subject!r}"
    assert "{" not in email.body, "Unresolved token placeholder in body"

    print(f"\n[STAGE 1+2 ASSERTIONS PASSED]")

    # --- Stage 3: Guardrails ---
    print(f"\n{'='*60}")
    print("STAGE 3 — GUARDRAILS")
    print(f"{'='*60}")

    from src.guardrails.engine import run_guardrails

    guardrail_result = run_guardrails(email, selected_blocks, donor)

    print(f"\n  Verdict: {guardrail_result.verdict.upper()}")
    print(f"\n  Check results:")
    for check in guardrail_result.checks:
        status_icon = "PASS" if check.passed else "FAIL"
        print(f"    [{status_icon}] {check.check_name}")
        if not check.passed:
            print(f"           reason: {check.reason}")

    # Block attribution detail — shows if Haiku paraphrased any block
    attribution = next(
        (c for c in guardrail_result.checks if c.check_name == "block_attribution"),
        None,
    )
    if attribution:
        print(f"\n  Block attribution (verbatim match per block):")
        for block_id, found in attribution.metadata.get("block_found", {}).items():
            icon = "YES" if found else "NO (paraphrased?)"
            print(f"    {block_id}: {icon}")

    if guardrail_result.failure_reasons:
        print(f"\n  Failed checks: {guardrail_result.failure_reasons}")

    final_status = "PASS" if guardrail_result.verdict == "pass" else "QUARANTINE"
    print(f"\n  Final status: {final_status}")

    # Accept pass OR quarantine — we discover paraphrasing empirically here.
    # Do NOT assert verdict == 'pass'.
    print(f"\n[E2E TEST COMPLETE — stage-3 verdict: {guardrail_result.verdict}]")
