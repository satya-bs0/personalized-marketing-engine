"""Eval Dimensions page — 8 dimension histograms, stats, agreement matrix."""
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import altair as alt
import pandas as pd
import streamlit as st

from dashboard.utils import fetch_batches, fetch_eval_scores_for_batch

st.set_page_config(page_title="Eval Dimensions", layout="wide")
st.title("Evaluation Dimensions")

DIMS = [
    "faithfulness",
    "claim_accuracy",
    "brand_voice",
    "toxicity_sensitivity",
    "segment_fit",
    "block_attribution",
    "length_readability",
    "donor_fact_correctness",
]

DIM_METHOD = {
    "faithfulness": "LLM judge",
    "claim_accuracy": "LLM judge",
    "brand_voice": "LLM judge",
    "toxicity_sensitivity": "LLM judge",
    "segment_fit": "LLM judge",
    "block_attribution": "Rule",
    "length_readability": "Rule",
    "donor_fact_correctness": "Rule",
}

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
selected_label = st.selectbox("Select batch", list(batch_options.keys()))
batch_id = batch_options[selected_label]

scores = fetch_eval_scores_for_batch(batch_id)

if not scores:
    st.info(
        "No eval scores found for this batch. "
        "Run evaluation first:\n\n"
        "```\npython scripts/run_demo_batch.py --size 100 --yes\n```"
    )
    st.stop()

df = pd.DataFrame(scores)
df["score"] = pd.to_numeric(df["score"], errors="coerce")
df["passed"] = df["passed"].astype(bool)

st.caption(f"{len(df):,} dimension scores across {df['email_id'].nunique():,} emails")

st.divider()

# ---------------------------------------------------------------------------
# 8 histograms — 2 rows × 4 columns
# ---------------------------------------------------------------------------
st.subheader("Score distributions")

rows_of_dims = [DIMS[:4], DIMS[4:]]
for row_dims in rows_of_dims:
    cols = st.columns(4)
    for col, dim in zip(cols, row_dims):
        dim_df = df[df["dimension"] == dim]
        if dim_df.empty:
            col.markdown(f"**{dim}**\n\n_no data_")
            continue

        mean_score = dim_df["score"].mean()
        pass_rate = dim_df["passed"].mean()
        method = DIM_METHOD.get(dim, "")

        hist = (
            alt.Chart(dim_df)
            .mark_bar(color="#3498db" if "LLM" in method else "#2ecc71")
            .encode(
                x=alt.X(
                    "score:Q",
                    bin=alt.Bin(step=0.1, extent=[0, 1]),
                    title="Score",
                ),
                y=alt.Y("count():Q", title="Count"),
                tooltip=[
                    alt.Tooltip("score:Q", bin=alt.Bin(step=0.1), title="Score range"),
                    alt.Tooltip("count():Q", title="Count"),
                ],
            )
            .properties(
                title=alt.TitleParams(
                    f"{dim} ({method})",
                    subtitle=f"mean={mean_score:.2f} · pass={pass_rate:.0%}",
                    fontSize=12,
                    subtitleFontSize=10,
                ),
                height=160,
            )
        )
        col.altair_chart(hist, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Stats table
# ---------------------------------------------------------------------------
st.subheader("Per-dimension statistics")

stats_rows = []
for dim in DIMS:
    dim_df = df[df["dimension"] == dim]
    if dim_df.empty:
        continue
    scores_list = dim_df["score"].dropna()
    stats_rows.append({
        "Dimension": dim,
        "Method": DIM_METHOD.get(dim, ""),
        "N": len(scores_list),
        "Mean": round(scores_list.mean(), 3),
        "Median": round(scores_list.median(), 3),
        "P5": round(scores_list.quantile(0.05), 3),
        "P95": round(scores_list.quantile(0.95), 3),
        "Pass rate": f"{dim_df['passed'].mean():.1%}",
        "Status": "✓" if scores_list.mean() >= 0.85 else "⚠",
    })

if stats_rows:
    st.dataframe(pd.DataFrame(stats_rows), use_container_width=True, hide_index=True)

st.divider()

# ---------------------------------------------------------------------------
# Eval-vs-Guardrail agreement
# ---------------------------------------------------------------------------
st.subheader("Eval-vs-Guardrail agreement")
st.caption(
    "Compares the eval framework's per-email verdict (all 8 dims pass?) "
    "against the guardrail verdict (status=pass vs quarantine/error). "
    "Off-diagonal cells signal potential miscalibration."
)

emails = fetch_eval_scores_for_batch(batch_id)
if emails:
    from dashboard.utils import fetch_emails_for_batch
    email_rows = fetch_emails_for_batch(batch_id)
    status_map = {r["email_id"]: r["status"] for r in email_rows}

    eval_by_email: dict[str, list[bool]] = {}
    for s in scores:
        eid = s.get("email_id")
        if eid:
            eval_by_email.setdefault(eid, []).append(bool(s.get("passed", False)))

    matrix = {"eval_pass_guard_pass": 0, "eval_pass_guard_fail": 0,
               "eval_fail_guard_pass": 0, "eval_fail_guard_fail": 0}

    for eid, passed_list in eval_by_email.items():
        eval_pass = all(passed_list)
        guard_pass = status_map.get(eid) == "pass"
        if eval_pass and guard_pass:
            matrix["eval_pass_guard_pass"] += 1
        elif eval_pass and not guard_pass:
            matrix["eval_pass_guard_fail"] += 1
        elif not eval_pass and guard_pass:
            matrix["eval_fail_guard_pass"] += 1
        else:
            matrix["eval_fail_guard_fail"] += 1

    heatmap_df = pd.DataFrame([
        {"Eval verdict": "Pass", "Guardrail verdict": "Pass",
         "Count": matrix["eval_pass_guard_pass"],
         "Meaning": "Agreement: both pass ✓"},
        {"Eval verdict": "Pass", "Guardrail verdict": "Fail",
         "Count": matrix["eval_pass_guard_fail"],
         "Meaning": "Guardrail too strict?"},
        {"Eval verdict": "Fail", "Guardrail verdict": "Pass",
         "Count": matrix["eval_fail_guard_pass"],
         "Meaning": "Eval catches what guardrails miss ⚠"},
        {"Eval verdict": "Fail", "Guardrail verdict": "Fail",
         "Count": matrix["eval_fail_guard_fail"],
         "Meaning": "Agreement: both fail ✓"},
    ])

    heatmap = (
        alt.Chart(heatmap_df)
        .mark_rect()
        .encode(
            x=alt.X("Guardrail verdict:N", title="Guardrail verdict"),
            y=alt.Y("Eval verdict:N", title="Eval verdict"),
            color=alt.Color(
                "Count:Q",
                scale=alt.Scale(scheme="blues"),
                legend=alt.Legend(title="Count"),
            ),
            tooltip=["Eval verdict:N", "Guardrail verdict:N", "Count:Q", "Meaning:N"],
        )
        .properties(width=300, height=200)
    )
    text = heatmap.mark_text(fontSize=18).encode(
        text="Count:Q",
        color=alt.condition(
            alt.datum.Count > heatmap_df["Count"].max() / 2,
            alt.value("white"),
            alt.value("black"),
        ),
    )
    st.altair_chart(heatmap + text)

    with st.expander("Cell descriptions"):
        for _, row in heatmap_df.iterrows():
            st.write(f"**{row['Eval verdict']} / {row['Guardrail verdict']}** ({row['Count']}) — {row['Meaning']}")

st.divider()

# ---------------------------------------------------------------------------
# Golden set calibration evidence (hardcoded from Layer 7a live run)
# ---------------------------------------------------------------------------
st.subheader("Golden set calibration (Layer 7a validation — 50 hand-labeled examples)")
st.caption(
    "Precision = fraction of flagged emails that truly fail. "
    "Recall = fraction of failing emails that are caught. "
    "Target ≥ 0.80 for both."
)

GOLDEN_RESULTS = [
    {"dimension": "faithfulness",          "precision": 1.000, "recall": 0.857, "f1": 0.923, "support": 7},
    {"dimension": "claim_accuracy",        "precision": 0.750, "recall": 1.000, "f1": 0.857, "support": 3},
    {"dimension": "brand_voice",           "precision": 1.000, "recall": 1.000, "f1": 1.000, "support": 4},
    {"dimension": "toxicity_sensitivity",  "precision": 1.000, "recall": 1.000, "f1": 1.000, "support": 3},
    {"dimension": "segment_fit",           "precision": 1.000, "recall": 1.000, "f1": 1.000, "support": 3},
    {"dimension": "block_attribution",     "precision": 1.000, "recall": 1.000, "f1": 1.000, "support": 1},
    {"dimension": "length_readability",    "precision": 1.000, "recall": 1.000, "f1": 1.000, "support": 1},
    {"dimension": "donor_fact_correctness","precision": 1.000, "recall": 1.000, "f1": 1.000, "support": 1},
]
golden_df = pd.DataFrame(GOLDEN_RESULTS)
golden_df["Status"] = golden_df.apply(
    lambda r: "✓" if r["precision"] >= 0.80 and r["recall"] >= 0.80 else "⚠", axis=1
)
st.dataframe(golden_df, use_container_width=True, hide_index=True)

avg_p = golden_df["precision"].mean()
avg_r = golden_df["recall"].mean()
st.success(
    f"Average precision: **{avg_p:.3f}** · Average recall: **{avg_r:.3f}** · "
    f"Overall verdict accuracy: **49/50 (98%)**"
)
