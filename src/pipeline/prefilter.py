from __future__ import annotations

from typing import Optional

from supabase import Client

from src.data.blocks import ContentBlockRepository
from src.schemas import ContentBlock, Donor

BLOCK_TYPES = ("subject", "opener", "impact", "social_proof", "cta", "signoff")


class PrefilterCoverageError(Exception):
    """Raised when a donor segment has no candidate blocks for one or more slots.

    This indicates a gap in the content block library and must be fixed before
    the batch can proceed — failing loudly here prevents silent quality degradation.
    """


def prefilter_blocks_for_donor(
    donor: Donor,
    repo: Optional[ContentBlockRepository] = None,
    client: Optional[Client] = None,
) -> dict[str, list[ContentBlock]]:
    """Return candidate blocks per slot for a single donor.

    Returns a dict keyed by block_type with ≥1 ContentBlock per slot.
    Raises PrefilterCoverageError if any slot has zero candidates.
    """
    if repo is None:
        repo = ContentBlockRepository(client=client)

    candidates: dict[str, list[ContentBlock]] = {}
    empty_slots: list[str] = []

    for btype in BLOCK_TYPES:
        matches = repo.get_candidates_for_donor(donor, btype)
        candidates[btype] = matches
        if not matches:
            empty_slots.append(btype)

    if empty_slots:
        raise PrefilterCoverageError(
            f"No candidate blocks for donor "
            f"(lifecycle={donor.lifecycle_stage}, recency={donor.recency_tier}) "
            f"in slot(s): {empty_slots}. "
            "Add blocks to the library that match this segment."
        )

    return candidates
