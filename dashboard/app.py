"""Takeda Donor Messaging POC — main dashboard page."""
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st
from dashboard.utils import fetch_batch_summary, fetch_eval_scores_for_batch

st.set_page_config(
    page_title="Takeda Donor Messaging POC",
    page_icon="💉",
    layout="wide",
)

st.title("Personalized Donor Messaging — POC")
st.caption("AI-personalized weekly emails with GxP-aligned controls · Takeda BioLife")

# ---------------------------------------------------------------------------
# Top-level metrics
# ---------------------------------------------------------------------------
batches = fetch_batch_summary()

total_donors = sum(b.get("donor_count", 0) for b in batches)
total_pass = sum(b.get("pass_count", 0) for b in batches)
total_cost = sum(float(b.get("total_cost_usd", 0) or 0) for b in batches)
overall_pass_rate = total_pass / total_donors if total_donors else 0.0

# Mean eval score: aggregate from latest batch that has eval data
mean_eval_score = None
for b in batches:
    scores = fetch_eval_scores_for_batch(b["batch_id"])
    if scores:
        mean_eval_score = sum(float(s["score"]) for s in scores) / len(scores)
        break

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total donors processed", f"{total_donors:,}")
col2.metric("Overall guardrail pass rate", f"{overall_pass_rate:.1%}")
col3.metric(
    "Mean eval score (latest batch)",
    f"{mean_eval_score:.3f}" if mean_eval_score is not None else "—",
)
col4.metric("Total spend (all batches)", f"${total_cost:.2f}")

st.divider()

# ---------------------------------------------------------------------------
# Narrative
# ---------------------------------------------------------------------------
st.subheader("What you're looking at")
st.markdown("""
This dashboard demonstrates an end-to-end AI pipeline that generates personalized
plasma donor emails at scale. Each email is produced by two Claude AI stages
(block selection → email assembly), validated by 8 rule-based guardrails, and scored
on 8 evaluation dimensions — giving the team full traceability from donor profile to
delivered message.

Use the sidebar pages to explore batch outcomes, per-dimension quality scores,
individual email lineage, the approved content library, and the production cost model.
""")

# ---------------------------------------------------------------------------
# Architecture overview
# ---------------------------------------------------------------------------
st.subheader("Pipeline architecture")
st.markdown("""
| Step | Module | Description |
|---|---|---|
| 0 | Eligibility filter | SQL — excludes deferred, no-consent, frequency-capped donors |
| 0b | Block pre-filter | SQL — returns 5–10 candidate blocks per slot per donor |
| 1 | LLM block selection | Claude Haiku — picks best block per slot (temp=0, JSON tool-use) |
| 2 | LLM email assembly | Claude Haiku — stitches blocks, substitutes tokens (temp=0.3) |
| 3 | Rule-based guardrails | 8 checks: PII, claims, donor facts, length, links, banned words… |
| 4 | Audit log | Immutable append-only row per stage — full GxP lineage |
| 5 | Offline evaluation | 8 scored dimensions: 3 rule-based + 5 LLM-as-judge |
""")

# ---------------------------------------------------------------------------
# Batch table
# ---------------------------------------------------------------------------
if batches:
    st.subheader(f"Batch history ({len(batches)} run{'s' if len(batches) != 1 else ''})")
    import pandas as pd
    df = pd.DataFrame([
        {
            "Batch ID": b["batch_id"][:8] + "…",
            "Started": b.get("started_at", "")[:19],
            "Donors": b.get("donor_count", 0),
            "Pass": b.get("pass_count", 0),
            "Quarantine": b.get("quarantine_count", 0),
            "Error": b.get("error_count", 0),
            "Pass rate": f"{b.get('pass_rate', 0):.1%}" if b.get("pass_rate") is not None else "—",
            "Cost ($)": f"{float(b.get('total_cost_usd', 0) or 0):.4f}",
            "Duration (s)": b.get("duration_seconds", "—"),
        }
        for b in batches
    ])
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.info(
        "No batches found. Run a batch first:\n\n"
        "```\npython scripts/run_demo_batch.py --size 100 --yes\n```"
    )

st.divider()
st.caption(
    "Use the sidebar to navigate between pages. "
    "Data refreshes every 60 seconds. "
    "Built with Claude Haiku + Supabase."
)
