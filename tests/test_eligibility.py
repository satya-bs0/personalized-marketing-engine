"""Tests for pipeline/eligibility.py.

Unit tests use a mock Supabase client — no live DB connection required.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, call

import pytest

from src.pipeline.eligibility import eligible_donor_ids, is_donor_eligible


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(rows: list[dict], count: int | None = None):
    mock_result = MagicMock()
    mock_result.data = rows
    mock_result.count = count

    mock_query = MagicMock()
    mock_query.select.return_value = mock_query
    mock_query.eq.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.execute.return_value = mock_result

    mock_client = MagicMock()
    mock_client.table.return_value = mock_query
    return mock_client, mock_query


# ---------------------------------------------------------------------------
# eligible_donor_ids
# ---------------------------------------------------------------------------

class TestEligibleDonorIds:
    def test_returns_uuids(self):
        ids = [str(uuid.uuid4()) for _ in range(5)]
        rows = [{"donor_id": i} for i in ids]
        client, _ = _make_client(rows)
        result = eligible_donor_ids(client=client)
        assert len(result) == 5
        assert all(isinstance(i, uuid.UUID) for i in result)

    def test_queries_v_donor_profile(self):
        client, _ = _make_client([])
        eligible_donor_ids(client=client)
        client.table.assert_called_once_with("v_donor_profile")

    def test_filters_on_is_eligible_to_send(self):
        client, mock_query = _make_client([])
        eligible_donor_ids(client=client)
        mock_query.eq.assert_called_once_with("is_eligible_to_send", True)

    def test_limit_is_forwarded(self):
        client, mock_query = _make_client([])
        eligible_donor_ids(limit=10, client=client)
        mock_query.limit.assert_called_once_with(10)

    def test_no_limit_skips_limit_call(self):
        client, mock_query = _make_client([])
        eligible_donor_ids(client=client)
        mock_query.limit.assert_not_called()

    def test_returns_empty_list_when_no_eligible(self):
        client, _ = _make_client([])
        result = eligible_donor_ids(client=client)
        assert result == []

    def test_count_matches_rows_returned(self):
        ids = [str(uuid.uuid4()) for _ in range(3)]
        rows = [{"donor_id": i} for i in ids]
        client, _ = _make_client(rows)
        result = eligible_donor_ids(client=client)
        assert len(result) == 3


# ---------------------------------------------------------------------------
# is_donor_eligible
# ---------------------------------------------------------------------------

class TestIsDonorEligible:
    def test_returns_true_when_eligible(self):
        donor_id = uuid.uuid4()
        rows = [{"is_eligible_to_send": True}]
        client, _ = _make_client(rows)
        assert is_donor_eligible(donor_id, client=client) is True

    def test_returns_false_when_ineligible(self):
        donor_id = uuid.uuid4()
        rows = [{"is_eligible_to_send": False}]
        client, _ = _make_client(rows)
        assert is_donor_eligible(donor_id, client=client) is False

    def test_returns_false_when_not_found(self):
        donor_id = uuid.uuid4()
        client, _ = _make_client([])
        assert is_donor_eligible(donor_id, client=client) is False

    def test_queries_by_donor_id(self):
        donor_id = uuid.uuid4()
        client, mock_query = _make_client([{"is_eligible_to_send": True}])
        is_donor_eligible(donor_id, client=client)
        mock_query.eq.assert_called_once_with("donor_id", str(donor_id))
