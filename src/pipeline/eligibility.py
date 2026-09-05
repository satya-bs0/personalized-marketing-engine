from __future__ import annotations

import uuid
from typing import Optional

from supabase import create_client, Client

from src.config import SUPABASE_URL, SUPABASE_KEY


def _client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def eligible_donor_ids(
    limit: Optional[int] = None,
    client: Optional[Client] = None,
) -> list[uuid.UUID]:
    """Return UUIDs of donors eligible to receive email this batch.

    Reads v_donor_profile where is_eligible_to_send = true.
    # TODO: add frequency cap check (donors emailed in last 7 days) once
    # the generated_emails table exists (Layer 5).
    """
    db = client or _client()
    query = (
        db.table("v_donor_profile")
        .select("donor_id")
        .eq("is_eligible_to_send", True)
    )
    if limit is not None:
        query = query.limit(limit)
    result = query.execute()
    return [uuid.UUID(row["donor_id"]) for row in result.data]


def is_donor_eligible(
    donor_id: uuid.UUID,
    client: Optional[Client] = None,
) -> bool:
    """Return True if a specific donor is eligible to receive email this batch."""
    db = client or _client()
    result = (
        db.table("v_donor_profile")
        .select("is_eligible_to_send")
        .eq("donor_id", str(donor_id))
        .limit(1)
        .execute()
    )
    if not result.data:
        return False
    return bool(result.data[0]["is_eligible_to_send"])
