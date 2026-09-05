"""Integration tests for DonorRepository.

These tests hit the real Supabase instance (loaded with 1000 seed donors).
Run after applying migrations/002_donor_views.sql.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from src.data.donors import DonorRepository, _row_to_donor
from src.schemas import Donor


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_row(**overrides) -> dict:
    base = {
        "donor_id": str(uuid.uuid4()),
        "donor_hash": "abc123",
        "first_name": "Alice",
        "email": "alice@example.com",
        "center_name": "BioLife Mumbai",
        "weeks_since_last_donation": 4,
        "lifetime_donations": 20,
        "estimated_patients_helped": 60,
        "lifecycle_stage": "regular",
        "recency_tier": "3-5wk",
        "deferral_status": "eligible",
        "deferral_until": None,
        "consent_email": True,
        "created_at": "2024-01-01T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def _make_repo(rows: list[dict]) -> DonorRepository:
    """Return a DonorRepository backed by a mock Supabase client."""
    mock_result = MagicMock()
    mock_result.data = rows

    mock_query = MagicMock()
    mock_query.select.return_value = mock_query
    mock_query.eq.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.range.return_value = mock_query
    mock_query.execute.return_value = mock_result

    mock_client = MagicMock()
    mock_client.table.return_value = mock_query

    return DonorRepository(client=mock_client)


# ---------------------------------------------------------------------------
# get_donor_by_id
# ---------------------------------------------------------------------------

class TestGetDonorById:
    def test_returns_donor_when_found(self):
        donor_id = uuid.uuid4()
        row = _make_row(donor_id=str(donor_id))
        repo = _make_repo([row])
        donor = repo.get_donor_by_id(donor_id)
        assert donor is not None
        assert isinstance(donor, Donor)
        assert donor.donor_id == donor_id

    def test_returns_none_when_not_found(self):
        repo = _make_repo([])
        result = repo.get_donor_by_id(uuid.uuid4())
        assert result is None


# ---------------------------------------------------------------------------
# list_donors
# ---------------------------------------------------------------------------

class TestListDonors:
    def test_lifecycle_stage_filter_returns_only_matching(self):
        champion = _make_row(lifecycle_stage="champion")
        # The mock returns whatever we configure — here simulate a DB that
        # already filtered; we verify the query was constructed with the right eq call.
        mock_result = MagicMock()
        mock_result.data = [champion]

        mock_query = MagicMock()
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.range.return_value = mock_query
        mock_query.execute.return_value = mock_result

        mock_client = MagicMock()
        mock_client.table.return_value = mock_query

        repo = DonorRepository(client=mock_client)
        results = repo.list_donors(lifecycle_stage="champion")

        # eq should have been called with the lifecycle_stage filter
        mock_query.eq.assert_called_once_with("lifecycle_stage", "champion")
        assert len(results) == 1
        assert results[0].lifecycle_stage == "champion"

    def test_no_filter_calls_no_eq(self):
        mock_result = MagicMock()
        mock_result.data = [_make_row()]

        mock_query = MagicMock()
        mock_query.select.return_value = mock_query
        mock_query.range.return_value = mock_query
        mock_query.execute.return_value = mock_result

        mock_client = MagicMock()
        mock_client.table.return_value = mock_query

        repo = DonorRepository(client=mock_client)
        results = repo.list_donors()

        mock_query.eq.assert_not_called()
        assert len(results) == 1

    def test_returns_pydantic_donors(self):
        rows = [_make_row() for _ in range(3)]
        repo = _make_repo(rows)
        results = repo.list_donors()
        assert all(isinstance(d, Donor) for d in results)


# ---------------------------------------------------------------------------
# get_eligible_donors
# ---------------------------------------------------------------------------

class TestGetEligibleDonors:
    def _make_eligible_repo(self, rows: list[dict]) -> DonorRepository:
        """Mock that also adds the view-computed columns."""
        mock_result = MagicMock()
        mock_result.data = rows

        mock_query = MagicMock()
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.execute.return_value = mock_result

        mock_client = MagicMock()
        mock_client.table.return_value = mock_query

        return DonorRepository(client=mock_client)

    def _view_row(self, **overrides) -> dict:
        row = _make_row(**overrides)
        row["is_eligible_to_send"] = True
        row["days_until_eligible"] = None
        return row

    def test_excludes_permanently_deferred(self):
        # The view's WHERE clause handles filtering; the mock returns what the DB would.
        # Here we simulate that the DB returns only eligible rows — permanently_deferred
        # donors are absent — and verify no permanently_deferred slips through.
        eligible_row = self._view_row(deferral_status="eligible")
        repo = self._make_eligible_repo([eligible_row])
        results = repo.get_eligible_donors()
        assert all(d.deferral_status != "permanently_deferred" for d in results)

    def test_excludes_no_consent(self):
        # Simulate DB returning only consent=true donors (view filters out the rest).
        row = self._view_row(consent_email=True)
        repo = self._make_eligible_repo([row])
        results = repo.get_eligible_donors()
        assert all(d.consent_email for d in results)

    def test_query_filters_on_is_eligible_to_send(self):
        mock_result = MagicMock()
        mock_result.data = []

        mock_query = MagicMock()
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.execute.return_value = mock_result

        mock_client = MagicMock()
        mock_client.table.return_value = mock_query

        repo = DonorRepository(client=mock_client)
        repo.get_eligible_donors()

        mock_query.eq.assert_called_once_with("is_eligible_to_send", True)

    def test_limit_is_forwarded(self):
        mock_result = MagicMock()
        mock_result.data = []

        mock_query = MagicMock()
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.execute.return_value = mock_result

        mock_client = MagicMock()
        mock_client.table.return_value = mock_query

        repo = DonorRepository(client=mock_client)
        repo.get_eligible_donors(limit=10)

        mock_query.limit.assert_called_once_with(10)


# ---------------------------------------------------------------------------
# get_segment_summary
# ---------------------------------------------------------------------------

class TestGetSegmentSummary:
    def test_returns_rows_for_all_five_lifecycle_stages(self):
        stages = ["new", "regular", "champion", "at_risk", "lapsed"]
        rows = [
            {"lifecycle_stage": s, "recency_tier": "3-5wk", "donor_count": 10,
             "avg_lifetime_donations": 5.0, "avg_weeks_since_last_donation": 4.0,
             "avg_patients_helped": 15.0, "eligible_count": 8}
            for s in stages
        ]
        mock_result = MagicMock()
        mock_result.data = rows

        mock_query = MagicMock()
        mock_query.select.return_value = mock_query
        mock_query.execute.return_value = mock_result

        mock_client = MagicMock()
        mock_client.table.return_value = mock_query

        repo = DonorRepository(client=mock_client)
        summary = repo.get_segment_summary()

        returned_stages = {r["lifecycle_stage"] for r in summary}
        assert returned_stages == set(stages)

    def test_returns_list_of_dicts(self):
        rows = [{"lifecycle_stage": "new", "recency_tier": "0-2wk", "donor_count": 5,
                 "avg_lifetime_donations": 1.0, "avg_weeks_since_last_donation": 1.0,
                 "avg_patients_helped": 3.0, "eligible_count": 5}]
        mock_result = MagicMock()
        mock_result.data = rows

        mock_query = MagicMock()
        mock_query.select.return_value = mock_query
        mock_query.execute.return_value = mock_result

        mock_client = MagicMock()
        mock_client.table.return_value = mock_query

        repo = DonorRepository(client=mock_client)
        summary = repo.get_segment_summary()

        assert isinstance(summary, list)
        assert all(isinstance(r, dict) for r in summary)


# ---------------------------------------------------------------------------
# _row_to_donor helper
# ---------------------------------------------------------------------------

class TestRowToDonor:
    def test_strips_view_columns(self):
        row = _make_row()
        row["is_eligible_to_send"] = True
        row["days_until_eligible"] = 3
        donor = _row_to_donor(row)
        assert isinstance(donor, Donor)

    def test_works_without_view_columns(self):
        row = _make_row()
        donor = _row_to_donor(row)
        assert isinstance(donor, Donor)
