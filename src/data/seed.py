"""
Generate 1000 synthetic donors with realistic, correlated distributions and
insert them into Supabase.

Run:
    python -m src.data.seed
"""
from __future__ import annotations

import hashlib
import random
import uuid
from datetime import date, datetime, timedelta

from faker import Faker
from supabase import create_client

from src.config import CENTERS, DONOR_INSERT_CHUNK, DONOR_SALT, SUPABASE_KEY, SUPABASE_URL
from src.schemas import Donor, DeferralStatus, LifecycleStage, RecencyTier

fake = Faker("en_IN")
rng = random.Random()


# ---------------------------------------------------------------------------
# Distribution tables
# ---------------------------------------------------------------------------

LIFECYCLE_DIST: list[tuple[LifecycleStage, float]] = [
    ("new", 0.20),
    ("regular", 0.40),
    ("champion", 0.15),
    ("at_risk", 0.15),
    ("lapsed", 0.10),
]

# (min_weeks, max_weeks) per lifecycle stage
WEEKS_RANGE: dict[LifecycleStage, tuple[int, int]] = {
    "new": (0, 4),
    "regular": (0, 6),
    "champion": (0, 4),
    "at_risk": (8, 20),
    "lapsed": (20, 104),
}

DONATIONS_RANGE: dict[LifecycleStage, tuple[int, int]] = {
    "new": (0, 3),
    "regular": (4, 30),
    "champion": (30, 200),
    "at_risk": (5, 50),
    "lapsed": (1, 40),
}

DEFERRAL_DIST: list[tuple[DeferralStatus, float]] = [
    ("eligible", 0.90),
    ("temp_deferred", 0.08),
    ("permanently_deferred", 0.02),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _weighted_choice(choices: list[tuple[str, float]], r: random.Random) -> str:
    items, weights = zip(*choices)
    return r.choices(items, weights=weights, k=1)[0]


def _recency_tier(weeks: int) -> RecencyTier:
    if weeks <= 2:
        return "0-2wk"
    if weeks <= 5:
        return "3-5wk"
    if weeks <= 10:
        return "6-10wk"
    if weeks <= 20:
        return "11-20wk"
    return "20wk+"


def _donor_hash(donor_id: uuid.UUID) -> str:
    return hashlib.sha256((str(donor_id) + DONOR_SALT).encode()).hexdigest()


def _deferral_until(status: DeferralStatus) -> date | None:
    if status != "temp_deferred":
        return None
    return date.today() + timedelta(days=rng.randint(7, 90))


def _make_donor() -> Donor:
    donor_id = uuid.uuid4()
    stage: LifecycleStage = _weighted_choice(LIFECYCLE_DIST, rng)

    weeks = rng.randint(*WEEKS_RANGE[stage])
    lifetime = rng.randint(*DONATIONS_RANGE[stage])
    deferral_status: DeferralStatus = _weighted_choice(DEFERRAL_DIST, rng)

    return Donor(
        donor_id=donor_id,
        donor_hash=_donor_hash(donor_id),
        first_name=fake.first_name(),
        email=fake.email(),
        center_name=rng.choice(CENTERS),
        weeks_since_last_donation=weeks,
        lifetime_donations=lifetime,
        estimated_patients_helped=int(lifetime * 0.7),
        lifecycle_stage=stage,
        recency_tier=_recency_tier(weeks),
        deferral_status=deferral_status,
        deferral_until=_deferral_until(deferral_status),
        consent_email=rng.random() < 0.95,
        created_at=datetime.utcnow(),
    )


def generate_donors(n: int = 1000) -> list[Donor]:
    return [_make_donor() for _ in range(n)]


# ---------------------------------------------------------------------------
# Supabase I/O
# ---------------------------------------------------------------------------

def _check_existing(client) -> int:
    result = client.table("donors").select("donor_id", count="exact").execute()
    return result.count or 0


def _truncate(client) -> None:
    client.rpc("truncate_donors").execute()


def _insert_batch(client, donors: list[Donor]) -> None:
    rows = [d.to_db_dict() for d in donors]
    client.table("donors").insert(rows).execute()


def seed(n: int = 1000, confirm_truncate: bool | None = None) -> list[Donor]:
    """
    Generate n donors and insert into Supabase.

    If the table already has rows the caller must either pass
    confirm_truncate=True to truncate-and-reseed or confirm_truncate=False
    to abort. When confirm_truncate is None (interactive), the user is prompted.
    """
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    existing = _check_existing(client)
    if existing > 0:
        if confirm_truncate is None:
            answer = input(
                f"donors table already has {existing} rows. Truncate and re-seed? [y/N]: "
            ).strip().lower()
            confirm_truncate = answer == "y"
        if not confirm_truncate:
            print("Aborting: existing data preserved.")
            return []
        # Supabase JS/REST doesn't expose TRUNCATE directly; use DELETE without filter.
        client.table("donors").delete().neq("donor_id", "00000000-0000-0000-0000-000000000000").execute()
        print(f"Deleted {existing} existing rows.")

    donors = generate_donors(n)

    chunks = [donors[i : i + DONOR_INSERT_CHUNK] for i in range(0, len(donors), DONOR_INSERT_CHUNK)]
    for idx, chunk in enumerate(chunks, 1):
        _insert_batch(client, chunk)
        print(f"  Inserted chunk {idx}/{len(chunks)} ({len(chunk)} rows)")

    return donors


# ---------------------------------------------------------------------------
# Summary printing
# ---------------------------------------------------------------------------

def print_summary(donors: list[Donor]) -> None:
    if not donors:
        return

    total = len(donors)
    print(f"\nTotal donors: {total}\n")

    print("Lifecycle stage distribution:")
    stages = ["new", "regular", "champion", "at_risk", "lapsed"]
    for stage in stages:
        count = sum(1 for d in donors if d.lifecycle_stage == stage)
        print(f"  {stage:<12} {count:>4}  ({count / total * 100:.1f}%)")

    print("\nRecency tier distribution:")
    tiers = ["0-2wk", "3-5wk", "6-10wk", "11-20wk", "20wk+"]
    for tier in tiers:
        count = sum(1 for d in donors if d.recency_tier == tier)
        print(f"  {tier:<10} {count:>4}  ({count / total * 100:.1f}%)")

    print("\nDeferral status distribution:")
    for status in ["eligible", "temp_deferred", "permanently_deferred"]:
        count = sum(1 for d in donors if d.deferral_status == status)
        print(f"  {status:<25} {count:>4}  ({count / total * 100:.1f}%)")

    consent_yes = sum(1 for d in donors if d.consent_email)
    print(f"\nConsent email: {consent_yes}/{total} ({consent_yes / total * 100:.1f}%)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Seeding donors table...")
    inserted = seed(n=1000)
    print_summary(inserted)
    print("\nDone.")
