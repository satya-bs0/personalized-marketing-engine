from __future__ import annotations

import uuid
from typing import Optional

from supabase import create_client, Client

from src.config import SUPABASE_URL, SUPABASE_KEY
from src.schemas import Donor


def _client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)


class DonorRepository:
    def __init__(self, client: Optional[Client] = None) -> None:
        self._db: Client = client or _client()

    def get_donor_by_id(self, donor_id: uuid.UUID) -> Optional[Donor]:
        result = (
            self._db.table("donors")
            .select("*")
            .eq("donor_id", str(donor_id))
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        return Donor(**result.data[0])

    def list_donors(
        self,
        limit: int = 100,
        offset: int = 0,
        lifecycle_stage: Optional[str] = None,
    ) -> list[Donor]:
        query = self._db.table("donors").select("*")
        if lifecycle_stage is not None:
            query = query.eq("lifecycle_stage", lifecycle_stage)
        result = query.range(offset, offset + limit - 1).execute()
        return [Donor(**row) for row in result.data]

    def get_eligible_donors(self, limit: Optional[int] = None) -> list[Donor]:
        query = (
            self._db.table("v_donor_profile")
            .select("*")
            .eq("is_eligible_to_send", True)
        )
        if limit is not None:
            query = query.limit(limit)
        result = query.execute()
        # v_donor_profile has extra computed columns; Donor ignores unknowns via model_config
        return [_row_to_donor(row) for row in result.data]

    def get_segment_summary(self) -> list[dict]:
        result = self._db.table("v_donor_segment_summary").select("*").execute()
        return result.data


def _row_to_donor(row: dict) -> Donor:
    """Strip view-only computed columns before constructing Donor."""
    donor_fields = {k: v for k, v in row.items() if k not in ("is_eligible_to_send", "days_until_eligible")}
    return Donor(**donor_fields)
