"""Shared database connection and cached query helpers for the Streamlit dashboard."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure project root is importable when streamlit is launched from any directory
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

import streamlit as st
from supabase import Client, create_client


@st.cache_resource
def get_db() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    return create_client(url, key)


# ---------------------------------------------------------------------------
# Cached queries (TTL 60s — fresh enough for a live demo)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60)
def fetch_batches() -> list[dict]:
    return (
        get_db()
        .table("batch_runs")
        .select("*")
        .order("started_at", desc=True)
        .execute()
        .data
    )


@st.cache_data(ttl=60)
def fetch_batch_summary() -> list[dict]:
    """v_batch_summary view — adds duration_seconds and pass_rate."""
    return (
        get_db()
        .table("v_batch_summary")
        .select("*")
        .execute()
        .data
    )


@st.cache_data(ttl=60)
def fetch_emails_for_batch(batch_id: str) -> list[dict]:
    return (
        get_db()
        .table("generated_emails")
        .select("*")
        .eq("batch_id", batch_id)
        .execute()
        .data
    )


@st.cache_data(ttl=60)
def fetch_eval_scores_for_batch(batch_id: str) -> list[dict]:
    """Eval scores for all emails in a batch (via join through generated_emails)."""
    email_rows = fetch_emails_for_batch(batch_id)
    email_ids = [r["email_id"] for r in email_rows if r.get("email_id")]
    if not email_ids:
        return []
    return (
        get_db()
        .table("eval_scores")
        .select("*")
        .in_("email_id", email_ids)
        .execute()
        .data
    )


@st.cache_data(ttl=60)
def fetch_eval_scores_for_email(email_id: str) -> list[dict]:
    return (
        get_db()
        .table("eval_scores")
        .select("*")
        .eq("email_id", email_id)
        .execute()
        .data
    )


@st.cache_data(ttl=60)
def fetch_donor(donor_id: str) -> dict | None:
    rows = (
        get_db()
        .table("donors")
        .select("*")
        .eq("donor_id", donor_id)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else None


@st.cache_data(ttl=60)
def fetch_donors_by_ids(donor_ids: list[str]) -> list[dict]:
    if not donor_ids:
        return []
    return (
        get_db()
        .table("donors")
        .select("*")
        .in_("donor_id", donor_ids)
        .execute()
        .data
    )


@st.cache_data(ttl=60)
def fetch_audit_trail(batch_id: str, donor_hash: str) -> list[dict]:
    return (
        get_db()
        .table("audit_log")
        .select("*")
        .eq("batch_id", batch_id)
        .eq("donor_hash", donor_hash)
        .order("timestamp_utc")
        .execute()
        .data
    )


@st.cache_data(ttl=120)
def fetch_content_blocks() -> list[dict]:
    return (
        get_db()
        .table("content_blocks")
        .select("*")
        .eq("status", "approved")
        .order("block_type")
        .execute()
        .data
    )


@st.cache_data(ttl=60)
def fetch_block_usage() -> list[dict]:
    return (
        get_db()
        .table("v_block_usage")
        .select("*")
        .execute()
        .data
    )


@st.cache_data(ttl=60)
def fetch_segment_pass_rate() -> list[dict]:
    return (
        get_db()
        .table("v_segment_pass_rate")
        .select("*")
        .execute()
        .data
    )


@st.cache_data(ttl=60)
def fetch_audit_costs_for_batch(batch_id: str) -> list[dict]:
    """Audit rows with cost_usd and latency_ms for a batch — stage-level breakdown."""
    return (
        get_db()
        .table("audit_log")
        .select("stage,cost_usd,latency_ms,model_version")
        .eq("batch_id", batch_id)
        .execute()
        .data
    )


@st.cache_data(ttl=60)
def fetch_blocks_by_ids(block_ids: list[str]) -> list[dict]:
    if not block_ids:
        return []
    return (
        get_db()
        .table("content_blocks")
        .select("*")
        .in_("block_id", block_ids)
        .execute()
        .data
    )
