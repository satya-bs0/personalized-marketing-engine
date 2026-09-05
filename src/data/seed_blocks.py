"""
Generate and insert 30 approved content blocks into Supabase.

Coverage guarantee: every (lifecycle_stage × recency_tier) segment observed
in the donor data has at least 1 matching block per block_type slot.

Run:
    python -m src.data.seed_blocks
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from supabase import create_client

from src.config import SUPABASE_KEY, SUPABASE_URL
from src.schemas import ContentBlock

rng = random.Random(42)

_SIX_MONTHS_AGO = datetime.now(timezone.utc) - timedelta(days=180)
_NOW = datetime.now(timezone.utc)


def _mlr_id(n: int) -> str:
    return f"MLR-2025-{n:04d}"


def _mlr_ts() -> datetime:
    delta = _NOW - _SIX_MONTHS_AGO
    return _SIX_MONTHS_AGO + timedelta(seconds=rng.randint(0, int(delta.total_seconds())))


def _block(
    block_id: str,
    block_type: str,
    version: int,
    approved_text: str,
    safe_tokens: list[str],
    lifecycle_stages: list[str],
    recency_tiers: list[str],
    mlr_n: int,
) -> ContentBlock:
    return ContentBlock(
        block_id=block_id,
        block_type=block_type,
        version=version,
        approved_text=approved_text,
        safe_tokens=safe_tokens,
        segment_fit={
            "lifecycle_stages": lifecycle_stages,
            "recency_tiers": recency_tiers,
        },
        mlr_approval_id=_mlr_id(mlr_n),
        mlr_approved_at=_mlr_ts(),
        status="approved",
        forbidden_modifications=["paraphrase", "rewrite", "expand"],
    )


ALL_LIFECYCLE = ["new", "regular", "champion", "at_risk", "lapsed"]
ALL_RECENCY = ["0-2wk", "3-5wk", "6-10wk", "11-20wk", "20wk+"]


def build_blocks() -> list[ContentBlock]:
    return [
        # ------------------------------------------------------------------ #
        # SUBJECT  (≤60 chars after token substitution)                       #
        # ------------------------------------------------------------------ #
        _block(
            "subject_new_welcome_v1",
            "subject", 1,
            "Welcome to the BioLife family, {first_name}",
            ["first_name"],
            ["new"], ["0-2wk", "3-5wk"],
            1001,
        ),
        _block(
            "subject_regular_appreciation_v1",
            "subject", 1,
            "Thank you for being there, {first_name}",
            ["first_name"],
            ["regular"], ["0-2wk", "3-5wk", "6-10wk"],
            1002,
        ),
        _block(
            "subject_champion_milestone_v1",
            "subject", 1,
            "{first_name}, your dedication inspires us",
            ["first_name"],
            ["champion"], ["0-2wk", "3-5wk"],
            1003,
        ),
        _block(
            "subject_atrisk_warmthink_v1",
            "subject", 1,
            "We've been thinking of you, {first_name}",
            ["first_name"],
            ["at_risk", "lapsed"], ["6-10wk", "11-20wk", "20wk+"],
            1004,
        ),
        _block(
            "subject_universal_update_v1",
            "subject", 1,
            "A note from the BioLife team",
            [],
            ALL_LIFECYCLE, ALL_RECENCY,
            1005,
        ),

        # ------------------------------------------------------------------ #
        # OPENER  (≤200 chars)                                                #
        # ------------------------------------------------------------------ #
        _block(
            "opener_new_welcome_v1",
            "opener", 1,
            "Hi {first_name}, welcome to the BioLife community — we're so glad you're here and inspired by your choice to donate.",
            ["first_name"],
            ["new"], ["0-2wk", "3-5wk"],
            1006,
        ),
        _block(
            "opener_regular_warm_v1",
            "opener", 1,
            "Hi {first_name}, your ongoing commitment to plasma donation continues to inspire us at {center_name}.",
            ["first_name", "center_name"],
            ["regular"], ["0-2wk", "3-5wk", "6-10wk"],
            1007,
        ),
        _block(
            "opener_champion_recognition_v1",
            "opener", 1,
            "Hi {first_name}, your commitment is remarkable — {lifetime_donations} donations and counting at {center_name}.",
            ["first_name", "lifetime_donations", "center_name"],
            ["champion"], ["0-2wk", "3-5wk"],
            1008,
        ),
        _block(
            "opener_atrisk_reconnect_v1",
            "opener", 1,
            "Hi {first_name}, we noticed it has been {weeks_since_last_donation} weeks since your last visit — we hope you're doing well.",
            ["first_name", "weeks_since_last_donation"],
            ["at_risk"], ["6-10wk", "11-20wk"],
            1009,
        ),
        _block(
            "opener_lapsed_warmwelcome_v1",
            "opener", 1,
            "Hi {first_name}, we miss seeing you at {center_name} and wanted to reach out with a warm hello.",
            ["first_name", "center_name"],
            ["lapsed"], ["11-20wk", "20wk+"],
            1010,
        ),

        # ------------------------------------------------------------------ #
        # IMPACT  (≤200 chars)                                                #
        # ------------------------------------------------------------------ #
        _block(
            "impact_personalized_v1",
            "impact", 1,
            "Your contributions have helped an estimated {estimated_patients_helped} patients receive life-saving therapies.",
            ["estimated_patients_helped"],
            ALL_LIFECYCLE, ALL_RECENCY,
            1011,
        ),
        _block(
            "impact_new_first_v1",
            "impact", 1,
            "Even early donations make a lasting difference — plasma donations like yours help patients who depend on a consistent supply.",
            [],
            ["new"], ["0-2wk", "3-5wk"],
            1012,
        ),
        _block(
            "impact_champion_legacy_v1",
            "impact", 1,
            "With {lifetime_donations} donations, your legacy at {center_name} has helped an estimated {estimated_patients_helped} patients in need.",
            ["lifetime_donations", "center_name", "estimated_patients_helped"],
            ["champion"], ["0-2wk", "3-5wk"],
            1013,
        ),
        _block(
            "impact_atrisk_consistent_v1",
            "impact", 1,
            "Each donation contributes to a steady supply that patients rely on throughout the year — your commitment matters more than you know.",
            [],
            ["at_risk", "regular"], ["6-10wk", "11-20wk"],
            1014,
        ),
        _block(
            "impact_lapsed_memory_v1",
            "impact", 1,
            "Your past donations have helped an estimated {estimated_patients_helped} patients — that generosity never goes unnoticed or forgotten.",
            ["estimated_patients_helped"],
            ["lapsed"], ["11-20wk", "20wk+"],
            1015,
        ),

        # ------------------------------------------------------------------ #
        # SOCIAL_PROOF  (≤200 chars)                                          #
        # ------------------------------------------------------------------ #
        _block(
            "social_proof_community_v1",
            "social_proof", 1,
            "You are part of a dedicated community of donors at {center_name} who show up for patients time after time.",
            ["center_name"],
            ALL_LIFECYCLE, ALL_RECENCY,
            1016,
        ),
        _block(
            "social_proof_new_joining_v1",
            "social_proof", 1,
            "Thousands of donors at BioLife centers have made the same commitment you have — you are joining something meaningful.",
            [],
            ["new"], ["0-2wk", "3-5wk"],
            1017,
        ),
        _block(
            "social_proof_champion_peers_v1",
            "social_proof", 1,
            "Donors with {lifetime_donations} or more donations are the backbone of the plasma community — your dedication places you among the most impactful.",
            ["lifetime_donations"],
            ["champion"], ["0-2wk", "3-5wk"],
            1018,
        ),
        _block(
            "social_proof_regular_consistency_v1",
            "social_proof", 1,
            "Your consistency sets an example — regular donors like you are exactly who patients count on to maintain a steady supply.",
            [],
            ["regular"], ["0-2wk", "3-5wk", "6-10wk"],
            1019,
        ),
        _block(
            "social_proof_lapsed_return_v1",
            "social_proof", 1,
            "Many donors who take a break choose to return — and every donation, whenever it happens, is a meaningful contribution to someone in need.",
            [],
            ["at_risk", "lapsed"], ["6-10wk", "11-20wk", "20wk+"],
            1020,
        ),

        # ------------------------------------------------------------------ #
        # CTA  (≤200 chars)                                                   #
        # ------------------------------------------------------------------ #
        _block(
            "cta_schedule_appointment_v1",
            "cta", 1,
            "Book your next appointment at {center_name} when you're ready.",
            ["center_name"],
            ["new", "regular", "champion"], ["0-2wk", "3-5wk", "6-10wk"],
            1021,
        ),
        _block(
            "cta_new_first_visit_v1",
            "cta", 1,
            "Schedule your next donation visit at {center_name} at your convenience — our team looks forward to seeing you.",
            ["center_name"],
            ["new"], ["0-2wk", "3-5wk"],
            1022,
        ),
        _block(
            "cta_champion_streak_v1",
            "cta", 1,
            "Your next visit to {center_name} will keep your remarkable giving streak going — book whenever works best for you.",
            ["center_name"],
            ["champion"], ["0-2wk", "3-5wk"],
            1023,
        ),
        _block(
            "cta_atrisk_gentle_v1",
            "cta", 1,
            "If the time feels right, we'd love to see you back at {center_name} — there's no pressure, just a warm welcome waiting.",
            ["center_name"],
            ["at_risk", "lapsed"], ["6-10wk", "11-20wk", "20wk+"],
            1024,
        ),
        _block(
            "cta_regular_reminder_v1",
            "cta", 1,
            "When you're ready to donate again, your {center_name} team will be there to welcome you back with appreciation.",
            ["center_name"],
            ["regular"], ["3-5wk", "6-10wk", "11-20wk"],
            1025,
        ),

        # ------------------------------------------------------------------ #
        # SIGNOFF  (≤80 chars)                                                #
        # ------------------------------------------------------------------ #
        _block(
            "signoff_warm_v1",
            "signoff", 1,
            "With gratitude, The BioLife team",
            [],
            ALL_LIFECYCLE, ALL_RECENCY,
            1026,
        ),
        _block(
            "signoff_new_v1",
            "signoff", 1,
            "We're glad you're with us, The BioLife team",
            [],
            ["new"], ["0-2wk", "3-5wk"],
            1027,
        ),
        _block(
            "signoff_champion_v1",
            "signoff", 1,
            "With deep appreciation for your dedication, The BioLife team",
            [],
            ["champion"], ["0-2wk", "3-5wk"],
            1028,
        ),
        _block(
            "signoff_atrisk_v1",
            "signoff", 1,
            "Wishing you well, The BioLife team at {center_name}",
            ["center_name"],
            ["at_risk"], ["6-10wk", "11-20wk"],
            1029,
        ),
        _block(
            "signoff_lapsed_v1",
            "signoff", 1,
            "Warmly, The BioLife team at {center_name}",
            ["center_name"],
            ["lapsed"], ["11-20wk", "20wk+"],
            1030,
        ),
    ]


# ---------------------------------------------------------------------------
# Supabase I/O
# ---------------------------------------------------------------------------

def _check_existing(client) -> int:
    result = client.table("content_blocks").select("block_id", count="exact").execute()
    return result.count or 0


def seed(confirm_replace: bool | None = None) -> list[ContentBlock]:
    """
    Insert 30 approved content blocks into Supabase.

    If blocks already exist, the caller must pass confirm_replace=True to
    truncate-and-reseed, or confirm_replace=False to abort.
    """
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    existing = _check_existing(client)
    if existing > 0:
        if confirm_replace is None:
            answer = input(
                f"content_blocks already has {existing} rows. Replace? [y/N]: "
            ).strip().lower()
            confirm_replace = answer == "y"
        if not confirm_replace:
            print("Aborting: existing blocks preserved.")
            return []
        client.table("content_blocks").delete().neq(
            "block_id", "__nonexistent__"
        ).execute()
        print(f"Deleted {existing} existing blocks.")

    blocks = build_blocks()
    rows = [b.to_db_dict() for b in blocks]
    client.table("content_blocks").insert(rows).execute()
    print(f"Inserted {len(blocks)} content blocks.")
    return blocks


def print_summary(blocks: list[ContentBlock]) -> None:
    from collections import Counter
    counts = Counter(b.block_type for b in blocks)
    print(f"\nTotal blocks: {len(blocks)}")
    for btype in ["subject", "opener", "impact", "social_proof", "cta", "signoff"]:
        print(f"  {btype:<15} {counts.get(btype, 0)}")


if __name__ == "__main__":
    print("Seeding content_blocks table...")
    inserted = seed()
    print_summary(inserted)
    print("\nDone.")
