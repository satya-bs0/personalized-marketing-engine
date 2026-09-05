"""Tests for pipeline/prefilter.py.

Uses the real build_blocks() library in a mock repository to run offline.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from src.data.blocks import ContentBlockRepository
from src.data.seed_blocks import build_blocks
from src.pipeline.prefilter import BLOCK_TYPES, PrefilterCoverageError, prefilter_blocks_for_donor
from src.schemas import ContentBlock, Donor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

OBSERVED_SEGMENTS: list[tuple[str, str]] = [
    ("new",      "0-2wk"),
    ("new",      "3-5wk"),
    ("regular",  "0-2wk"),
    ("regular",  "3-5wk"),
    ("regular",  "6-10wk"),
    ("champion", "0-2wk"),
    ("champion", "3-5wk"),
    ("at_risk",  "6-10wk"),
    ("at_risk",  "11-20wk"),
    ("lapsed",   "11-20wk"),
    ("lapsed",   "20wk+"),
]


def _make_donor(lifecycle: str, recency: str, weeks: int = 3) -> Donor:
    return Donor(
        donor_id=uuid.uuid4(),
        donor_hash="testhash",
        first_name="Test",
        email="test@example.com",
        center_name="BioLife Mumbai",
        weeks_since_last_donation=weeks,
        lifetime_donations=10,
        estimated_patients_helped=7,
        lifecycle_stage=lifecycle,
        recency_tier=recency,
        deferral_status="eligible",
        consent_email=True,
    )


def _repo_from_blocks(blocks: list[ContentBlock]) -> ContentBlockRepository:
    """Build a repo that serves from the in-memory block list."""
    rows = [b.to_db_dict() for b in blocks]

    def _execute_side_effect(query_mock):
        mock_result = MagicMock()
        mock_result.data = rows
        return mock_result

    mock_result = MagicMock()
    mock_result.data = rows

    mock_query = MagicMock()
    mock_query.select.return_value = mock_query
    mock_query.eq.return_value = mock_query
    mock_query.execute.return_value = mock_result

    mock_client = MagicMock()
    mock_client.table.return_value = mock_query
    return ContentBlockRepository(client=mock_client)


# ---------------------------------------------------------------------------
# Prefilter output shape
# ---------------------------------------------------------------------------

class TestPrefilterShape:
    @pytest.fixture(scope="class")
    def repo(self) -> ContentBlockRepository:
        return _repo_from_blocks(build_blocks())

    def test_returns_all_six_keys(self, repo):
        donor = _make_donor("regular", "3-5wk")
        result = prefilter_blocks_for_donor(donor, repo=repo)
        assert set(result.keys()) == set(BLOCK_TYPES)

    def test_values_are_lists_of_content_blocks(self, repo):
        donor = _make_donor("regular", "3-5wk")
        result = prefilter_blocks_for_donor(donor, repo=repo)
        for btype, candidates in result.items():
            assert isinstance(candidates, list), f"{btype} value is not a list"
            assert all(isinstance(b, ContentBlock) for b in candidates), (
                f"{btype} list contains non-ContentBlock items"
            )

    def test_each_slot_has_at_least_one_candidate(self, repo):
        donor = _make_donor("regular", "3-5wk")
        result = prefilter_blocks_for_donor(donor, repo=repo)
        for btype, candidates in result.items():
            assert len(candidates) >= 1, f"Slot {btype} has zero candidates"

    def test_candidates_match_donor_segment(self, repo):
        donor = _make_donor("champion", "0-2wk")
        result = prefilter_blocks_for_donor(donor, repo=repo)
        for btype, candidates in result.items():
            for block in candidates:
                assert "champion" in block.segment_fit["lifecycle_stages"], (
                    f"Block {block.block_id} returned for champion but doesn't fit"
                )
                assert "0-2wk" in block.segment_fit["recency_tiers"], (
                    f"Block {block.block_id} returned for 0-2wk but doesn't fit"
                )


# ---------------------------------------------------------------------------
# Coverage across all observed segments
# ---------------------------------------------------------------------------

class TestPrefilterCoverageAllSegments:
    @pytest.fixture(scope="class")
    def repo(self) -> ContentBlockRepository:
        return _repo_from_blocks(build_blocks())

    @pytest.mark.parametrize("lifecycle,recency", OBSERVED_SEGMENTS)
    def test_all_slots_covered(self, lifecycle, recency, repo):
        donor = _make_donor(lifecycle, recency)
        result = prefilter_blocks_for_donor(donor, repo=repo)
        assert set(result.keys()) == set(BLOCK_TYPES)
        for btype, candidates in result.items():
            assert len(candidates) >= 1, (
                f"No candidates for ({lifecycle}, {recency}, {btype})"
            )


# ---------------------------------------------------------------------------
# PrefilterCoverageError
# ---------------------------------------------------------------------------

class TestPrefilterCoverageError:
    def test_raises_when_no_candidates_for_slot(self):
        # A repo that always returns empty (no blocks match anything)
        mock_result = MagicMock()
        mock_result.data = []

        mock_query = MagicMock()
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.execute.return_value = mock_result

        mock_client = MagicMock()
        mock_client.table.return_value = mock_query

        empty_repo = ContentBlockRepository(client=mock_client)
        donor = _make_donor("new", "0-2wk")

        with pytest.raises(PrefilterCoverageError) as exc_info:
            prefilter_blocks_for_donor(donor, repo=empty_repo)

        assert "new" in str(exc_info.value)
        assert "0-2wk" in str(exc_info.value)

    def test_error_message_contains_lifecycle_and_recency(self):
        mock_result = MagicMock()
        mock_result.data = []

        mock_query = MagicMock()
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.execute.return_value = mock_result

        mock_client = MagicMock()
        mock_client.table.return_value = mock_query

        empty_repo = ContentBlockRepository(client=mock_client)
        donor = _make_donor("lapsed", "20wk+")

        with pytest.raises(PrefilterCoverageError) as exc_info:
            prefilter_blocks_for_donor(donor, repo=empty_repo)

        err = str(exc_info.value)
        assert "lapsed" in err
        assert "20wk+" in err
