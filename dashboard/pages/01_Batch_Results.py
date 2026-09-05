"""Batch Results page — distributions, pass rates, latency."""
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import altair as alt
import pandas as pd
import streamlit as st

from dashboard.utils import (
    fetch_audit_costs_for_batch,
    fetch_batches,
    fetch_emails_for_batch,
    fetch_segment_pass_rate,
)

st.set_page_config(page_title="Batch Results", layout="wide")
st.title("Batch Results")

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
batch = next(b for b in batches if b["batch_id"] == batch_id)

# ---------------------------------------------------------------------------
# Batch summary header
# ---------------------------------------------------------------------------
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Donors", batch.get("donor_count", 0))
col2.metric("Pass", batch.get("pass_count", 0))
col3.metric("Quarantine", batch.get("quarantine_count", 0))
col4.metric("Error", batch.get("error_count", 0))
cost = float(batch.get("total_cost_usd", 0) or 0)
col5.metric("Cost", f"${cost:.4f}")

with st.expander("Batch metadata"):
    st.json({
        "batch_id": batch["batch_id"],
        "started_at": batch.get("started_at"),
        "completed_at": batch.get("completed_at"),
        "model_versions": batch.get("model_versions"),
        "prompt_hashes": batch.get("prompt_hashes"),
        "block_library_version": batch.get("block_library_version"),
    })

st.divider()

# ---------------------------------------------------------------------------
# Status distribution (arc / pie chart)
# ---------------------------------------------------------------------------
st.subheader("Email status distribution")

status_data = pd.DataFrame([
    {"status": "Pass", "count": batch.get("pass_count", 0), "color": "#2ecc71"},
    {"status": "Quarantine", "count": batch.get("quarantine_count", 0), "color": "#e67e22"},
    {"status": "Error", "count": batch.get("error_count", 0), "color": "#e74c3c"},
])
status_data = status_data[status_data["count"] > 0]

if not status_data.empty:
    arc = (
        alt.Chart(status_data)
        .mark_arc(outerRadius=100)
        .encode(
            theta=alt.Theta("count:Q"),
            color=alt.Color(
                "status:N",
                scale=alt.Scale(
                    domain=["Pass", "Quarantine", "Error"],
                    range=["#2ecc71", "#e67e22", "#e74c3c"],
                ),
                legend=alt.Legend(title="Status"),
            ),
            tooltip=["status:N", "count:Q"],
        )
        .properties(width=300, height=300)
    )
    st.altair_chart(arc, use_container_width=False)

st.divider()

# ---------------------------------------------------------------------------
# Pass rate by segment
# ---------------------------------------------------------------------------
st.subheader("Pass rate by donor segment")

segment_data = fetch_segment_pass_rate()

if segment_data:
    seg_df = pd.DataFrame(segment_data)

    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("**By lifecycle stage**")
        stage_df = (
            seg_df.groupby("lifecycle_stage", as_index=False)
            .agg(
                pass_count=("pass_count", "sum"),
                donor_count=("donor_count", "sum"),
            )
        )
        stage_df["pass_rate"] = stage_df["pass_count"] / stage_df["donor_count"].clip(lower=1)
        stage_chart = (
            alt.Chart(stage_df)
            .mark_bar()
            .encode(
                x=alt.X("lifecycle_stage:N", title="Lifecycle stage", sort="-y"),
                y=alt.Y("pass_rate:Q", title="Pass rate", scale=alt.Scale(domain=[0, 1]),
                        axis=alt.Axis(format=".0%")),
                color=alt.Color("lifecycle_stage:N", legend=None),
                tooltip=[
                    alt.Tooltip("lifecycle_stage:N", title="Stage"),
                    alt.Tooltip("pass_rate:Q", format=".1%", title="Pass rate"),
                    alt.Tooltip("donor_count:Q", title="Donors"),
                ],
            )
            .properties(height=250)
        )
        st.altair_chart(stage_chart, use_container_width=True)

    with col_b:
        st.markdown("**By recency tier**")
        recency_df = (
            seg_df.groupby("recency_tier", as_index=False)
            .agg(
                pass_count=("pass_count", "sum"),
                donor_count=("donor_count", "sum"),
            )
        )
        recency_df["pass_rate"] = recency_df["pass_count"] / recency_df["donor_count"].clip(lower=1)
        recency_order = ["0-2wk", "3-5wk", "6-10wk", "11-20wk", "20wk+"]
        recency_chart = (
            alt.Chart(recency_df)
            .mark_bar(color="#3498db")
            .encode(
                x=alt.X("recency_tier:N", title="Recency tier",
                        sort=recency_order),
                y=alt.Y("pass_rate:Q", title="Pass rate", scale=alt.Scale(domain=[0, 1]),
                        axis=alt.Axis(format=".0%")),
                tooltip=[
                    alt.Tooltip("recency_tier:N", title="Recency"),
                    alt.Tooltip("pass_rate:Q", format=".1%", title="Pass rate"),
                    alt.Tooltip("donor_count:Q", title="Donors"),
                ],
            )
            .properties(height=250)
        )
        st.altair_chart(recency_chart, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Cost and latency breakdown from audit_log
# ---------------------------------------------------------------------------
st.subheader("Stage-level cost & latency")

audit_rows = fetch_audit_costs_for_batch(batch_id)

if audit_rows:
    audit_df = pd.DataFrame(audit_rows)
    audit_df["cost_usd"] = pd.to_numeric(audit_df["cost_usd"], errors="coerce").fillna(0)
    audit_df["latency_ms"] = pd.to_numeric(audit_df["latency_ms"], errors="coerce").fillna(0)

    cost_by_stage = (
        audit_df[audit_df["cost_usd"] > 0]
        .groupby("stage")["cost_usd"]
        .sum()
        .reset_index()
        .rename(columns={"cost_usd": "total_cost_usd"})
    )

    latency_stats = (
        audit_df[audit_df["latency_ms"] > 0]
        .groupby("stage")["latency_ms"]
        .agg(
            p50=lambda x: x.quantile(0.5),
            p95=lambda x: x.quantile(0.95),
            p99=lambda x: x.quantile(0.99),
            count="count",
        )
        .reset_index()
    )

    col_c, col_d = st.columns(2)

    with col_c:
        st.markdown("**Cost by stage (USD)**")
        if not cost_by_stage.empty:
            cost_chart = (
                alt.Chart(cost_by_stage)
                .mark_bar(color="#9b59b6")
                .encode(
                    x=alt.X("stage:N", title="Stage"),
                    y=alt.Y("total_cost_usd:Q", title="Total cost (USD)"),
                    tooltip=[
                        alt.Tooltip("stage:N", title="Stage"),
                        alt.Tooltip("total_cost_usd:Q", format="$.4f", title="Cost"),
                    ],
                )
                .properties(height=200)
            )
            st.altair_chart(cost_chart, use_container_width=True)
        else:
            st.info("No cost data in audit log for this batch.")

    with col_d:
        st.markdown("**Latency p50 / p95 / p99 (ms)**")
        if not latency_stats.empty:
            latency_stats_display = latency_stats.copy()
            for col in ["p50", "p95", "p99"]:
                latency_stats_display[col] = latency_stats_display[col].round(0).astype(int)
            st.dataframe(latency_stats_display, use_container_width=True, hide_index=True)
        else:
            st.info("No latency data in audit log for this batch.")
else:
    st.info("No audit log data for this batch.")
