from __future__ import annotations

from typing import Optional

from supabase import create_client, Client

from src.config import SUPABASE_URL, SUPABASE_KEY
from src.schemas import ContentBlock, Donor


def _client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)


class ContentBlockRepository:
    def __init__(self, client: Optional[Client] = None) -> None:
        self._db: Client = client or _client()

    def get_block_by_id(self, block_id: str) -> Optional[ContentBlock]:
        result = (
            self._db.table("content_blocks")
            .select("*")
            .eq("block_id", block_id)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        return ContentBlock(**result.data[0])

    def list_blocks(
        self,
        block_type: Optional[str] = None,
        status: str = "approved",
    ) -> list[ContentBlock]:
        query = self._db.table("content_blocks").select("*").eq("status", status)
        if block_type is not None:
            query = query.eq("block_type", block_type)
        result = query.execute()
        return [ContentBlock(**row) for row in result.data]

    def get_candidates_for_donor(
        self, donor: Donor, block_type: str
    ) -> list[ContentBlock]:
        """Return approved blocks of block_type whose segment_fit matches donor."""
        blocks = self.list_blocks(block_type=block_type, status="approved")
        return [
            b for b in blocks
            if donor.lifecycle_stage in b.segment_fit.get("lifecycle_stages", [])
            and donor.recency_tier in b.segment_fit.get("recency_tiers", [])
        ]
