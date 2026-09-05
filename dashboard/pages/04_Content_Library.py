"""Content Library page — approved block catalog + usage analytics."""
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import altair as alt
import pandas as pd
import streamlit as st

from dashboard.utils import fetch_block_usage, fetch_content_blocks

st.set_page_config(page_title="Content Library", layout="wide")
st.title("Content Library")
st.caption("30 MLR-approved content blocks — the only text the AI is allowed to use")

blocks = fetch_content_blocks()
if not blocks:
    st.warning("No content blocks found. Seed the database first.")
    st.stop()

# ---------------------------------------------------------------------------
# Filter by block type
# ---------------------------------------------------------------------------
block_types = sorted({b.get("block_type", "unknown") for b in blocks})
type_filter = st.selectbox("Filter by type", ["All"] + block_types)

filtered = blocks if type_filter == "All" else [b for b in blocks if b.get("block_type") == type_filter]

# ---------------------------------------------------------------------------
# Block catalog table
# ---------------------------------------------------------------------------
st.subheader(f"Approved blocks ({len(filtered)} shown)")

display_rows = []
for b in filtered:
    seg_fit = b.get("segment_fit") or {}
    seg_summary = "; ".join(
        f"{k}: {v}" for k, v in seg_fit.items()
        if isinstance(v, list)
    )[:80]
    display_rows.append({
        "block_id": b.get("block_id", ""),
        "type": b.get("block_type", ""),
        "v": b.get("version", 1),
        "approved_text": (b.get("approved_text") or "")[:120],
        "safe_tokens": ", ".join(b.get("safe_tokens") or []),
        "segment_fit": seg_summary,
        "mlr_approval_id": b.get("mlr_approval_id", ""),
    })

st.dataframe(
    pd.DataFrame(display_rows),
    use_container_width=True,
    hide_index=True,
    column_config={
        "approved_text": st.column_config.TextColumn("Approved text", width="large"),
    },
)

# Full block viewer
with st.expander("View full block text"):
    block_names = {b["block_id"]: b for b in filtered}
    selected_block_id = st.selectbox("Select block", list(block_names.keys()))
    if selected_block_id:
        blk = block_names[selected_block_id]
        st.markdown(f"**{blk['block_id']}** (type: `{blk['block_type']}`, version {blk['version']})")
        st.text(blk.get("approved_text", ""))
        col1, col2 = st.columns(2)
        col1.write(f"**Safe tokens:** {', '.join(blk.get('safe_tokens') or [])}")
        col1.write(f"**MLR approval:** {blk.get('mlr_approval_id', '—')}")
        col1.write(f"**Approved at:** {(blk.get('mlr_approved_at') or '')[:10]}")
        col2.write("**Segment fit:**")
        col2.json(blk.get("segment_fit") or {})
        col2.write("**Forbidden modifications:**")
        col2.json(blk.get("forbidden_modifications") or [])

st.divider()

# ---------------------------------------------------------------------------
# Usage analytics
# ---------------------------------------------------------------------------
st.subheader("Block usage across all batches")

usage_rows = fetch_block_usage()
all_block_ids = {b["block_id"] for b in blocks}

if usage_rows:
    usage_df = pd.DataFrame(usage_rows)
    usage_df["usage_count"] = pd.to_numeric(usage_df["usage_count"], errors="coerce").fillna(0).astype(int)

    # Join with block metadata for type and full ID
    block_meta = {b["block_id"]: b for b in blocks}
    usage_df["block_type"] = usage_df["block_id"].map(lambda x: block_meta.get(x, {}).get("block_type", "unknown"))

    # Find unused blocks
    used_ids = set(usage_df["block_id"].tolist())
    unused_ids = all_block_ids - used_ids

    col_a, col_b = st.columns([3, 1])
    with col_a:
        chart = (
            alt.Chart(usage_df.head(30))
            .mark_bar()
            .encode(
                x=alt.X("usage_count:Q", title="Times selected"),
                y=alt.Y("block_id:N", sort="-x", title=None),
                color=alt.Color("block_type:N", title="Block type"),
                tooltip=["block_id:N", "block_type:N", "usage_count:Q"],
            )
            .properties(height=max(300, len(usage_df) * 18))
        )
        st.altair_chart(chart, use_container_width=True)

    with col_b:
        max_usage = usage_df["usage_count"].max() if not usage_df.empty else 0
        dominant = usage_df[usage_df["usage_count"] > max_usage * 0.5]["block_id"].tolist()

        st.metric("Total blocks", len(all_block_ids))
        st.metric("Blocks used", len(used_ids))
        st.metric("Blocks never used", len(unused_ids))

        if unused_ids:
            st.warning("**Unused blocks:**\n\n" + "\n".join(f"- `{bid}`" for bid in sorted(unused_ids)))

        if dominant:
            st.info(
                "**Dominant blocks (>50% of max usage):**\n\n"
                + "\n".join(f"- `{bid}`" for bid in dominant)
            )
else:
    st.info("No usage data yet. Run a batch to populate.")
    st.metric("Total blocks in library", len(all_block_ids))
