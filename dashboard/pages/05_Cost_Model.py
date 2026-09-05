"""Cost Model page — POC actuals + production extrapolation."""
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import altair as alt
import pandas as pd
import streamlit as st

from dashboard.utils import fetch_batch_summary, fetch_eval_scores_for_batch

st.set_page_config(page_title="Cost Model", layout="wide")
st.title("Cost Model")
st.caption("POC actuals → production extrapolation → model selection story")

batches = fetch_batch_summary()

# ---------------------------------------------------------------------------
# Section 1: Actual POC cost
# ---------------------------------------------------------------------------
st.header("1 — Actual POC cost (Haiku 4.5)")

if batches:
    latest_batch = batches[0]
    batch_cost = float(latest_batch.get("total_cost_usd", 0) or 0)
    donor_count = latest_batch.get("donor_count", 0) or 1
    pass_count = latest_batch.get("pass_count", 0) or 0
    per_donor_gen = batch_cost / donor_count if donor_count else 0.0

    eval_scores = fetch_eval_scores_for_batch(latest_batch["batch_id"])
    eval_email_count = len({s["email_id"] for s in eval_scores if s.get("email_id")})
    eval_total_cost = sum(
        float(s.get("metadata", {}).get("cost_usd", 0) or 0)
        for s in eval_scores
    )
    per_donor_eval = eval_total_cost / eval_email_count if eval_email_count else 0.0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Batch size", f"{donor_count:,}")
    col2.metric("Generation cost/donor", f"${per_donor_gen:.4f}")
    col3.metric("Eval cost/donor", f"${per_donor_eval:.4f}")
    col4.metric("Total batch cost", f"${batch_cost:.4f}")

    st.caption(
        f"Latest batch: {latest_batch['batch_id'][:8]}… · "
        f"Pass rate: {pass_count / donor_count:.1%} · "
        f"Model: claude-haiku-4-5 (selection + assembly + eval)"
    )
else:
    per_donor_gen = 0.005     # empirical default
    per_donor_eval = 0.005
    batch_cost = 0.0
    donor_count = 0
    eval_email_count = 0
    st.info("No batch data. Showing illustrative projections based on empirical Haiku 4.5 costs.")
    per_donor_gen = 0.005
    per_donor_eval = 0.005

st.divider()

# ---------------------------------------------------------------------------
# Section 2: Production projection (400K donors/week)
# ---------------------------------------------------------------------------
st.header("2 — Production projection (400,000 donors/week)")

WEEKLY_DONORS = 400_000
WEEKS_PER_YEAR = 52

# Scenarios
scenarios = {
    "POC (Haiku, no caching)": {
        "gen_per_donor": per_donor_gen if per_donor_gen > 0 else 0.005,
        "eval_per_donor": per_donor_eval * 0.10,  # 10% sample in prod
        "note": "Current setup, no prompt caching",
    },
    "Prod A: Haiku + caching": {
        "gen_per_donor": (per_donor_gen if per_donor_gen > 0 else 0.005) * 0.35,
        "eval_per_donor": per_donor_eval * 0.05,
        "note": "Prompt caching cuts input cost ~65% after warm-up",
    },
    "Prod B: Mixed routing (Llama select + Haiku assemble)": {
        "gen_per_donor": 0.0008,
        "eval_per_donor": 0.0004,
        "note": "Mosaic AI Gateway: OSS model for selection, Haiku for assembly",
    },
    "Prod C: All Sonnet": {
        "gen_per_donor": 0.040,
        "eval_per_donor": 0.010,
        "note": "Highest quality, highest cost",
    },
}

proj_rows = []
for label, sc in scenarios.items():
    weekly_cost = WEEKLY_DONORS * (sc["gen_per_donor"] + sc["eval_per_donor"])
    yearly_cost = weekly_cost * WEEKS_PER_YEAR
    proj_rows.append({
        "Scenario": label,
        "Gen cost/donor": f"${sc['gen_per_donor']:.4f}",
        "Eval cost/donor": f"${sc['eval_per_donor']:.4f}",
        "Weekly (400K)": f"${weekly_cost:,.0f}",
        "Yearly": f"${yearly_cost:,.0f}",
        "Note": sc["note"],
    })

proj_df = pd.DataFrame(proj_rows)
st.dataframe(proj_df, use_container_width=True, hide_index=True)

# Bar chart of weekly costs
chart_df = pd.DataFrame([
    {"Scenario": r["Scenario"], "Weekly cost ($)": float(r["Weekly (400K)"].replace("$", "").replace(",", ""))}
    for r in proj_rows
])
bar = (
    alt.Chart(chart_df)
    .mark_bar()
    .encode(
        x=alt.X("Weekly cost ($):Q", title="Weekly cost (USD)"),
        y=alt.Y("Scenario:N", sort="-x", title=None),
        color=alt.Color(
            "Scenario:N",
            scale=alt.Scale(scheme="tableau10"),
            legend=None,
        ),
        tooltip=["Scenario:N", "Weekly cost ($):Q"],
    )
    .properties(height=220, title="Weekly cost at 400,000 donors")
)
st.altair_chart(bar, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Section 3: Model tier comparison table
# ---------------------------------------------------------------------------
st.header("3 — Model tier comparison")

MODELS = [
    {
        "Stage": "Selection",
        "POC (Haiku 4.5)": "$0.0025/donor",
        "Prod A (Haiku + cache)": "$0.0009/donor",
        "Prod B (Llama via Gateway)": "~$0.0001/donor",
        "Prod C (Sonnet 4.6)": "$0.018/donor",
    },
    {
        "Stage": "Assembly",
        "POC (Haiku 4.5)": "$0.0021/donor",
        "Prod A (Haiku + cache)": "$0.0008/donor",
        "Prod B (Haiku via Gateway)": "$0.0008/donor",
        "Prod C (Sonnet 4.6)": "$0.022/donor",
    },
    {
        "Stage": "Evaluation (10% sample)",
        "POC (Haiku 4.5)": "$0.0005/donor",
        "Prod A (Haiku + cache)": "$0.0002/donor",
        "Prod B (Haiku via Gateway)": "$0.0002/donor",
        "Prod C (Sonnet 4.6)": "$0.010/donor",
    },
    {
        "Stage": "Monthly at 400K/week",
        "POC (Haiku 4.5)": "~$8,700",
        "Prod A (Haiku + cache)": "~$3,000",
        "Prod B (Llama via Gateway)": "~$1,500",
        "Prod C (Sonnet 4.6)": "~$68,000",
    },
]
st.dataframe(pd.DataFrame(MODELS), use_container_width=True, hide_index=True)

st.divider()

# ---------------------------------------------------------------------------
# Section 4: Quality/cost frontier
# ---------------------------------------------------------------------------
st.header("4 — Quality / cost frontier")
st.markdown(
    """
    The POC uses **Haiku 4.5** throughout for cost-efficiency during development.
    The eval framework provides the objective signal to decide if and when to upgrade.

    The decision rule:
    - If **brand_voice mean score** drops below **0.70** → upgrade assembly to Sonnet
    - If **faithfulness mean score** drops below **0.75** → review selection or block library
    - If **claim_accuracy** drops below **0.80** → immediate audit regardless of cost

    This is the "data-driven model selection" story: the eval framework isn't just a
    quality gate — it's the instrument that tells us where quality/cost trade-offs are
    acceptable and where they aren't.
    """
)

# Show current brand_voice score from latest batch
if batches:
    scores = fetch_eval_scores_for_batch(batches[0]["batch_id"])
    bv_scores = [float(s["score"]) for s in scores if s.get("dimension") == "brand_voice"]
    if bv_scores:
        bv_mean = sum(bv_scores) / len(bv_scores)
        bv_ok = bv_mean >= 0.70
        st.metric(
            "Current brand_voice mean (latest batch)",
            f"{bv_mean:.3f}",
            delta="above threshold" if bv_ok else "⚠ below 0.70 threshold",
            delta_color="normal" if bv_ok else "inverse",
        )
        if bv_ok:
            st.success(
                f"Brand voice at **{bv_mean:.3f}** — Haiku 4.5 is sufficient. "
                "No model upgrade warranted."
            )
        else:
            st.warning(
                f"Brand voice at **{bv_mean:.3f}** — below 0.70. "
                "Consider upgrading assembly stage to Claude Sonnet."
            )
    else:
        st.info("No brand_voice scores in latest batch.")
