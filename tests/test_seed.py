"""
Sanity tests for seed.py: verify that generated donor distributions
match targets within acceptable statistical tolerance.

These tests run against generated data only — no Supabase connection required.
"""
from __future__ import annotations

import pytest
from src.data.seed import generate_donors
from src.schemas import Donor


TOTAL = 1000
TOLERANCE = 0.05  # ±5 percentage points


@pytest.fixture(scope="module")
def donors() -> list[Donor]:
    return generate_donors(TOTAL)


def _pct(donors: list[Donor], predicate) -> float:
    return sum(1 for d in donors if predicate(d)) / len(donors)


# ---------------------------------------------------------------------------
# Lifecycle stage proportions
# ---------------------------------------------------------------------------

class TestLifecycleDistribution:
    TARGETS = {
        "new": 0.20,
        "regular": 0.40,
        "champion": 0.15,
        "at_risk": 0.15,
        "lapsed": 0.10,
    }

    def test_all_stages_present(self, donors):
        stages = {d.lifecycle_stage for d in donors}
        assert stages == set(self.TARGETS)

    @pytest.mark.parametrize("stage,target", TARGETS.items())
    def test_stage_proportion(self, donors, stage, target):
        actual = _pct(donors, lambda d: d.lifecycle_stage == stage)
        assert abs(actual - target) <= TOLERANCE, (
            f"lifecycle_stage={stage}: got {actual:.2%}, expected {target:.2%} ±{TOLERANCE:.0%}"
        )


# ---------------------------------------------------------------------------
# Donation counts correlated with lifecycle
# ---------------------------------------------------------------------------

class TestDonationRanges:
    RANGES = {
        "new": (0, 3),
        "regular": (4, 30),
        "champion": (30, 200),
        "at_risk": (5, 50),
        "lapsed": (1, 40),
    }

    @pytest.mark.parametrize("stage,rng", RANGES.items())
    def test_donations_in_range(self, donors, stage, rng):
        lo, hi = rng
        bad = [
            d.lifetime_donations
            for d in donors
            if d.lifecycle_stage == stage and not (lo <= d.lifetime_donations <= hi)
        ]
        assert not bad, f"Donors with stage={stage} have out-of-range donations: {bad[:5]}"


# ---------------------------------------------------------------------------
# Weeks since last donation correlated with lifecycle
# ---------------------------------------------------------------------------

class TestWeeksRanges:
    RANGES = {
        "new": (0, 4),
        "regular": (0, 6),
        "champion": (0, 4),
        "at_risk": (8, 20),
        "lapsed": (20, 104),
    }

    @pytest.mark.parametrize("stage,rng", RANGES.items())
    def test_weeks_in_range(self, donors, stage, rng):
        lo, hi = rng
        bad = [
            d.weeks_since_last_donation
            for d in donors
            if d.lifecycle_stage == stage and not (lo <= d.weeks_since_last_donation <= hi)
        ]
        assert not bad, f"Donors with stage={stage} have out-of-range weeks: {bad[:5]}"


# ---------------------------------------------------------------------------
# Recency tier derivation
# ---------------------------------------------------------------------------

class TestRecencyTier:
    def test_tier_matches_weeks(self, donors):
        def expected_tier(weeks: int) -> str:
            if weeks <= 2:
                return "0-2wk"
            if weeks <= 5:
                return "3-5wk"
            if weeks <= 10:
                return "6-10wk"
            if weeks <= 20:
                return "11-20wk"
            return "20wk+"

        mismatches = [
            (d.weeks_since_last_donation, d.recency_tier, expected_tier(d.weeks_since_last_donation))
            for d in donors
            if d.recency_tier != expected_tier(d.weeks_since_last_donation)
        ]
        assert not mismatches, f"Recency tier mismatches: {mismatches[:5]}"


# ---------------------------------------------------------------------------
# Deferral status proportions
# ---------------------------------------------------------------------------

class TestDeferralDistribution:
    TARGETS = {
        "eligible": 0.90,
        "temp_deferred": 0.08,
        "permanently_deferred": 0.02,
    }

    @pytest.mark.parametrize("status,target", TARGETS.items())
    def test_deferral_proportion(self, donors, status, target):
        actual = _pct(donors, lambda d: d.deferral_status == status)
        assert abs(actual - target) <= TOLERANCE, (
            f"deferral_status={status}: got {actual:.2%}, expected {target:.2%} ±{TOLERANCE:.0%}"
        )

    def test_deferral_until_set_iff_temp(self, donors):
        for d in donors:
            if d.deferral_status == "temp_deferred":
                assert d.deferral_until is not None, f"donor {d.donor_id}: temp_deferred with null deferral_until"
            else:
                assert d.deferral_until is None, f"donor {d.donor_id}: non-temp has deferral_until set"


# ---------------------------------------------------------------------------
# Consent email proportion
# ---------------------------------------------------------------------------

class TestConsentEmail:
    def test_consent_proportion(self, donors):
        actual = _pct(donors, lambda d: d.consent_email)
        assert abs(actual - 0.95) <= TOLERANCE, (
            f"consent_email=True: got {actual:.2%}, expected 95% ±{TOLERANCE:.0%}"
        )


# ---------------------------------------------------------------------------
# Estimated patients helped derivation
# ---------------------------------------------------------------------------

class TestPatientsHelped:
    def test_patients_equals_floor_70pct_donations(self, donors):
        bad = [
            (d.lifetime_donations, d.estimated_patients_helped)
            for d in donors
            if d.estimated_patients_helped != int(d.lifetime_donations * 0.7)
        ]
        assert not bad, f"estimated_patients_helped mismatch: {bad[:5]}"


# ---------------------------------------------------------------------------
# Donor hash integrity
# ---------------------------------------------------------------------------

class TestDonorHash:
    def test_hashes_are_unique(self, donors):
        hashes = [d.donor_hash for d in donors]
        assert len(hashes) == len(set(hashes)), "Duplicate donor hashes found"

    def test_hash_is_64_chars(self, donors):
        bad = [d.donor_hash for d in donors if len(d.donor_hash) != 64]
        assert not bad, f"Unexpected hash lengths: {bad[:3]}"


# ---------------------------------------------------------------------------
# Center names
# ---------------------------------------------------------------------------

class TestCenterNames:
    VALID = {
        "BioLife Bengaluru", "BioLife Mumbai", "BioLife Delhi",
        "BioLife Hyderabad", "BioLife Pune",
    }

    def test_all_centers_valid(self, donors):
        bad = [d.center_name for d in donors if d.center_name not in self.VALID]
        assert not bad, f"Unknown center names: {set(bad)}"

    def test_all_centers_used(self, donors):
        used = {d.center_name for d in donors}
        assert used == self.VALID, f"Not all centers represented: missing {self.VALID - used}"
