"""Email Inspector — GxP traceability showcase. Full email lineage per message."""
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st

from dashboard.utils import (
    fetch_audit_trail,
    fetch_batches,
    fetch_blocks_by_ids,
    fetch_donor,
    fetch_emails_for_batch,
    fetch_eval_scores_for_email,
)

st.set_page_config(page_title="Email Inspector", layout="wide")
st.title("Email Inspector")
st.caption("Full GxP traceability: donor profile → block selection → assembly → guardrails → audit trail")

# ---------------------------------------------------------------------------
# Batch picker
# ---------------------------------------------------------------------------
batches = fetch_batches()
if not batches:
    st.warning("No batches found. Run a batch first.")
    st.stop()

batch_options = {
    f"{b['batch_id'][:8]}… — {b.get('started_at', '')[:16]} "
    f"({b.get('donor_count', 0)} donors)": b["batch_id"]
    for b in batches
}
selected_batch_label = st.selectbox("Select batch", list(batch_options.keys()))
batch_id = batch_options[selected_batch_label]

# ---------------------------------------------------------------------------
# Email picker
# ---------------------------------------------------------------------------
email_rows = fetch_emails_for_batch(batch_id)
if not email_rows:
    st.info("No emails in this batch.")
    st.stop()

# Fetch donor names for the selectbox
donor_id_map: dict[str, dict] = {}
for row in email_rows:
    did = row.get("donor_id")
    if did and did not in donor_id_map:
        donor_data = fetch_donor(did)
        if donor_data:
            donor_id_map[did] = donor_data

def _email_label(row: dict) -> str:
    donor = donor_id_map.get(row.get("donor_id", ""), {})
    name = donor.get("first_name", "Unknown")
    status = row.get("status", "?")
    eid = row.get("email_id", "")[:8]
    return f"{name} ({status}) · {eid}…"

email_options = {_email_label(r): r for r in email_rows}
selected_email_label = st.selectbox("Select email", list(email_options.keys()))
email_row = email_options[selected_email_label]

donor_data = donor_id_map.get(email_row.get("donor_id", ""), {})

st.divider()

# ---------------------------------------------------------------------------
# Three-column layout
# ---------------------------------------------------------------------------
left, mid, right = st.columns([1, 1.2, 1.4])

with left:
    st.markdown("### Donor profile")
    if donor_data:
        st.write(f"**Name:** {donor_data.get('first_name', '—')}")
        st.write(f"**Center:** {donor_data.get('center_name', '—')}")
        st.write(f"**Lifecycle:** {donor_data.get('lifecycle_stage', '—')}")
        st.write(f"**Recency:** {donor_data.get('recency_tier', '—')}")
        st.write(f"**Weeks since last:** {donor_data.get('weeks_since_last_donation', '—')}")
        st.write(f"**Lifetime donations:** {donor_data.get('lifetime_donations', '—')}")
        st.write(f"**Patients helped:** {donor_data.get('estimated_patients_helped', '—')}")
        st.write(f"**Deferral:** {donor_data.get('deferral_status', '—')}")
        st.divider()
        st.markdown("**Audit ID (donor hash)**")
        hash_val = donor_data.get("donor_hash", "—")
        st.code(hash_val[:20] + "…" if len(hash_val) > 20 else hash_val, language=None)
    else:
        st.info("Donor profile not found.")

with mid:
    st.markdown("### Selected blocks")
    block_ids: list[str] = email_row.get("selected_block_ids") or []

    if block_ids:
        blocks = fetch_blocks_by_ids(block_ids)
        block_map = {b["block_id"]: b for b in blocks}

        # Attempt to recover selection reasoning from audit_log
        audit_rows = []
        if donor_data:
            donor_hash = donor_data.get("donor_hash", "")
            audit_rows = fetch_audit_trail(batch_id, donor_hash)
        selection_audit = next((r for r in audit_rows if r.get("stage") == "selection"), None)
        reasoning = ""
        if selection_audit:
            reasoning = (selection_audit.get("output") or {}).get("selection_reasoning", "")

        for bid in block_ids:
            block = block_map.get(bid, {})
            btype = block.get("block_type", "?")
            text = block.get("approved_text", bid)
            with st.expander(f"**{btype}** — `{bid}`"):
                st.write(text)
                mlr = block.get("mlr_approval_id", "")
                if mlr:
                    st.caption(f"MLR approval: {mlr}")

        if reasoning:
            st.divider()
            st.markdown("**Selection reasoning (LLM Stage 1)**")
            st.caption(reasoning[:300])
    else:
        st.info("No block IDs recorded for this email.")

with right:
    st.markdown("### Assembled email")
    status = email_row.get("status", "unknown")
    status_color = {"pass": "🟢", "quarantine": "🟠", "error": "🔴"}.get(status, "⚪")
    st.markdown(f"**Status:** {status_color} **{status.upper()}**")
    st.markdown(f"**Subject:** {email_row.get('subject') or '—'}")
    st.divider()
    body = email_row.get("body") or ""
    if body:
        st.text(body)
    else:
        st.info("No email body (generation may have failed).")

    if status == "quarantine":
        reasons = email_row.get("quarantine_reasons") or []
        if reasons:
            st.error("Quarantine reasons: " + ", ".join(reasons))

st.divider()

# ---------------------------------------------------------------------------
# Detail tabs
# ---------------------------------------------------------------------------
if donor_data:
    donor_hash = donor_data.get("donor_hash", "")
    audit_rows = fetch_audit_trail(batch_id, donor_hash)
else:
    audit_rows = []

eval_scores = fetch_eval_scores_for_email(email_row.get("email_id", ""))

tab_eval, tab_guard, tab_audit, tab_cost = st.tabs([
    "Eval Scores", "Guardrail Results", "Audit Trail", "Cost",
])

# --- Eval Scores ---
with tab_eval:
    if eval_scores:
        THRESHOLDS = {
            "faithfulness": 0.75, "claim_accuracy": 0.75, "brand_voice": 0.75,
            "toxicity_sensitivity": 0.70, "segment_fit": 0.75,
            "block_attribution": 1.0, "length_readability": 1.0, "donor_fact_correctness": 1.0,
        }
        rows_display = []
        for s in sorted(eval_scores, key=lambda x: x.get("dimension", "")):
            score = float(s.get("score", 0))
            passed = bool(s.get("passed", False))
            rows_display.append({
                "Dimension": s.get("dimension", ""),
                "Score": f"{score:.3f}",
                "Threshold": f"{s.get('threshold', '—')}",
                "Passed": "✓" if passed else "✗",
                "Judge model": s.get("judge_model") or "rule-based",
            })
        st.dataframe(pd.DataFrame(rows_display), use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("**LLM judge reasoning**")
        for s in eval_scores:
            reasoning_text = s.get("reasoning") or ""
            if reasoning_text and s.get("judge_model"):
                with st.expander(f"{s.get('dimension')} — {s.get('judge_model')}"):
                    st.write(reasoning_text)
    else:
        st.info("No eval scores for this email. Run evaluation to populate.")

# --- Guardrail Results ---
with tab_guard:
    guardrail_row = next((r for r in audit_rows if r.get("stage") == "guardrail"), None)
    if guardrail_row:
        checks = (guardrail_row.get("output") or {}).get("checks", [])
        verdict = guardrail_row.get("verdict", "unknown")
        st.markdown(f"**Overall verdict:** {'🟢 PASS' if verdict == 'pass' else '🔴 FAIL'}")
        if checks:
            check_rows = [
                {
                    "Check": c.get("check_name", ""),
                    "Passed": "✓" if c.get("passed") else "✗",
                    "Reason": c.get("reason") or "",
                }
                for c in checks
            ]
            st.dataframe(pd.DataFrame(check_rows), use_container_width=True, hide_index=True)
        else:
            failure_reasons = guardrail_row.get("failure_reasons") or []
            if failure_reasons:
                st.error("Failed checks: " + ", ".join(failure_reasons))
            else:
                st.success("All guardrail checks passed.")
    else:
        st.info("No guardrail audit row found for this email.")

# --- Audit Trail ---
with tab_audit:
    st.markdown("Full GxP lineage: one row per pipeline stage.")
    if audit_rows:
        for row in audit_rows:
            stage = row.get("stage", "unknown")
            ts = (row.get("timestamp_utc") or "")[:19]
            model = row.get("model_version") or "—"
            prompt_hash = (row.get("prompt_hash") or "—")[:16]
            latency = row.get("latency_ms")
            cost = row.get("cost_usd")
            verdict = row.get("verdict")

            icon = {"eligibility": "🔍", "prefilter": "📋", "selection": "🎯",
                    "assembly": "✍️", "guardrail": "🛡️"}.get(stage, "📌")

            with st.expander(f"{icon} **{stage}** — {ts}"):
                col_a, col_b = st.columns(2)
                col_a.write(f"**Model:** {model}")
                col_a.write(f"**Prompt hash:** `{prompt_hash}…`")
                if latency:
                    col_b.write(f"**Latency:** {latency} ms")
                if cost is not None:
                    col_b.write(f"**Cost:** ${float(cost):.6f}")
                if verdict:
                    col_b.write(f"**Verdict:** {verdict}")
                with st.container():
                    st.caption("Input summary")
                    st.json(row.get("input_summary") or {})
                    st.caption("Output")
                    output = row.get("output") or {}
                    if stage == "guardrail" and "checks" in output:
                        # Simplified view for guardrail
                        passed_checks = [c["check_name"] for c in output["checks"] if c.get("passed")]
                        failed_checks = [c["check_name"] for c in output["checks"] if not c.get("passed")]
                        st.json({"passed": passed_checks, "failed": failed_checks})
                    else:
                        st.json(output)
    else:
        st.info("No audit trail found. The audit log stores at most 5 rows per donor per batch.")

# --- Cost ---
with tab_cost:
    sel_audit = next((r for r in audit_rows if r.get("stage") == "selection"), None)
    asm_audit = next((r for r in audit_rows if r.get("stage") == "assembly"), None)

    sel_cost = float(sel_audit.get("cost_usd") or 0) if sel_audit else 0.0
    asm_cost = float(asm_audit.get("cost_usd") or 0) if asm_audit else 0.0
    eval_cost = sum(float(s.get("metadata", {}).get("cost_usd", 0) or 0) for s in eval_scores)
    total = sel_cost + asm_cost + eval_cost

    cost_rows = [
        {"Stage": "Selection (LLM Stage 1)", "Cost (USD)": f"${sel_cost:.6f}",
         "Tokens": str((sel_audit or {}).get("token_usage", {}) or "—")},
        {"Stage": "Assembly (LLM Stage 2)", "Cost (USD)": f"${asm_cost:.6f}",
         "Tokens": str((asm_audit or {}).get("token_usage", {}) or "—")},
        {"Stage": "Evaluation (LLM judge)", "Cost (USD)": f"${eval_cost:.6f}", "Tokens": ""},
        {"Stage": "**Total**", "Cost (USD)": f"**${total:.6f}**", "Tokens": ""},
    ]
    st.dataframe(pd.DataFrame(cost_rows), use_container_width=True, hide_index=True)

    if total > 0:
        weekly_400k = total * 400_000
        st.caption(f"At this per-email cost, 400,000 donors/week ≈ **${weekly_400k:,.0f}/week**")
