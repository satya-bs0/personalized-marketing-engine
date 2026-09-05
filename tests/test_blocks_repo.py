"""Tests for ContentBlockRepository and the seeded block library.

Unit tests use a mock Supabase client. The coverage-matrix test uses the
actual build_blocks() output (no DB needed) so it runs offline.
"""
from __future__ import annotations

import re
from collections import defaultdict
from unittest.mock import MagicMock

import pytest

from src.data.blocks import ContentBlockRepository
from src.data.seed_blocks import build_blocks
from src.schemas import ContentBlock, LifecycleStage, RecencyTier

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BLOCK_TYPES = ["subject", "opener", "impact", "social_proof", "cta", "signoff"]

# All (lifecycle_stage, recency_tier) combos that can occur given seed.py ranges
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


def _make_block_row(**overrides) -> dict:
    base = {
        "block_id": "subject_new_welcome_v1",
        "block_type": "subject",
        "version": 1,
        "approved_text": "Welcome, {first_name}",
        "safe_tokens": ["first_name"],
        "segment_fit": {"lifecycle_stages": ["new"], "recency_tiers": ["0-2wk", "3-5wk"]},
        "mlr_approval_id": "MLR-2025-0001",
        "mlr_approved_at": "2025-12-01T10:00:00+00:00",
        "status": "approved",
        "forbidden_modifications": ["paraphrase", "rewrite", "expand"],
        "created_at": "2025-12-01T10:00:00+00:00",
    }
    base.update(overrides)
    return base


def _make_repo(rows: list[dict]) -> ContentBlockRepository:
    mock_result = MagicMock()
    mock_result.data = rows

    mock_query = MagicMock()
    mock_query.select.return_value = mock_query
    mock_query.eq.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.execute.return_value = mock_result

    mock_client = MagicMock()
    mock_client.table.return_value = mock_query

    return ContentBlockRepository(client=mock_client)


# ---------------------------------------------------------------------------
# Library shape tests (offline — uses build_blocks())
# ---------------------------------------------------------------------------

class TestLibraryShape:
    @pytest.fixture(scope="class")
    def blocks(self) -> list[ContentBlock]:
        return build_blocks()

    def test_total_block_count(self, blocks):
        assert len(blocks) == 30

    def test_five_blocks_per_type(self, blocks):
        for btype in BLOCK_TYPES:
            count = sum(1 for b in blocks if b.block_type == btype)
            assert count == 5, f"Expected 5 {btype} blocks, got {count}"

    def test_all_blocks_approved(self, blocks):
        assert all(b.status == "approved" for b in blocks)

    def test_token_validation(self, blocks):
        for b in blocks:
            tokens_in_text = set(re.findall(r"\{(\w+)\}", b.approved_text))
            assert tokens_in_text <= set(b.safe_tokens), (
                f"Block {b.block_id}: tokens in text not all in safe_tokens"
            )

    def test_no_forbidden_claims(self, blocks):
        forbidden_phrases = [
            "cure", "treat", "guarantee", "guaranteed",
            "act now", "limited time",
        ]
        for b in blocks:
            text_lower = b.approved_text.lower()
            for phrase in forbidden_phrases:
                assert phrase not in text_lower, (
                    f"Block {b.block_id} contains forbidden phrase: '{phrase}'"
                )

    def test_subject_length_within_limit(self, blocks):
        for b in blocks:
            if b.block_type == "subject":
                # Substitute max-length token values for a conservative check
                text = (
                    b.approved_text
                    .replace("{first_name}", "A" * 10)
                    .replace("{lifetime_donations}", "999")
                    .replace("{weeks_since_last_donation}", "99")
                    .replace("{estimated_patients_helped}", "9999")
                    .replace("{center_name}", "BioLife Bengaluru")
                )
                assert len(text) <= 60, (
                    f"Subject block {b.block_id} exceeds 60 chars: {len(text)}"
                )

    def test_signoff_length_within_limit(self, blocks):
        for b in blocks:
            if b.block_type == "signoff":
                text = (
                    b.approved_text
                    .replace("{center_name}", "BioLife Bengaluru")
                )
                assert len(text) <= 80, (
                    f"Signoff block {b.block_id} exceeds 80 chars: {len(text)}"
                )

    def test_body_block_length_within_limit(self, blocks):
        body_types = {"opener", "impact", "social_proof", "cta"}
        for b in blocks:
            if b.block_type in body_types:
                text = (
                    b.approved_text
                    .replace("{first_name}", "A" * 10)
                    .replace("{lifetime_donations}", "999")
                    .replace("{weeks_since_last_donation}", "99")
                    .replace("{estimated_patients_helped}", "9999")
                    .replace("{center_name}", "BioLife Bengaluru")
                )
                assert len(text) <= 200, (
                    f"Block {b.block_id} ({b.block_type}) exceeds 200 chars: {len(text)}"
                )

    def test_forbidden_modifications_set(self, blocks):
        expected = {"paraphrase", "rewrite", "expand"}
        for b in blocks:
            assert set(b.forbidden_modifications) == expected, (
                f"Block {b.block_id} has wrong forbidden_modifications"
            )

    def test_mlr_approval_id_format(self, blocks):
        for b in blocks:
            assert re.fullmatch(r"MLR-2025-\d{4}", b.mlr_approval_id), (
                f"Block {b.block_id} has malformed mlr_approval_id: {b.mlr_approval_id}"
            )


# ---------------------------------------------------------------------------
# Coverage matrix test (offline)
# ---------------------------------------------------------------------------

class TestCoverageMatrix:
    @pytest.fixture(scope="class")
    def blocks(self) -> list[ContentBlock]:
        return build_blocks()

    def test_every_segment_has_coverage_in_all_slots(self, blocks):
        """Every (lifecycle_stage, recency_tier) segment must have ≥1 block per slot."""
        missing: list[str] = []
        for stage, tier in OBSERVED_SEGMENTS:
            for btype in BLOCK_TYPES:
                matches = [
                    b for b in blocks
                    if b.block_type == btype
                    and stage in b.segment_fit.get("lifecycle_stages", [])
                    and tier in b.segment_fit.get("recency_tiers", [])
                ]
                if not matches:
                    missing.append(f"({stage}, {tier}, {btype})")

        assert not missing, (
            f"Coverage gaps — no blocks for: {missing}"
        )

    def test_coverage_counts_table(self, blocks):
        """Each cell should have ≥1 candidate; aim for 2-3 average."""
        coverage: dict[tuple[str, str, str], int] = defaultdict(int)
        for b in blocks:
            for stage in b.segment_fit.get("lifecycle_stages", []):
                for tier in b.segment_fit.get("recency_tiers", []):
                    coverage[(stage, tier, b.block_type)] += 1

        for stage, tier in OBSERVED_SEGMENTS:
            for btype in BLOCK_TYPES:
                count = coverage.get((stage, tier, btype), 0)
                assert count >= 1, f"No coverage for ({stage}, {tier}, {btype})"


# ---------------------------------------------------------------------------
# Repository unit tests (mock client)
# ---------------------------------------------------------------------------

class TestGetBlockById:
    def test_returns_block_when_found(self):
        row = _make_block_row()
        repo = _make_repo([row])
        block = repo.get_block_by_id("subject_new_welcome_v1")
        assert block is not None
        assert isinstance(block, ContentBlock)
        assert block.block_id == "subject_new_welcome_v1"

    def test_returns_none_when_not_found(self):
        repo = _make_repo([])
        result = repo.get_block_by_id("nonexistent_block")
        assert result is None


class TestListBlocks:
    def test_returns_pydantic_models(self):
        rows = [_make_block_row(block_id=f"block_{i}") for i in range(3)]
        repo = _make_repo(rows)
        results = repo.list_blocks()
        assert all(isinstance(b, ContentBlock) for b in results)

    def test_filters_by_block_type(self):
        mock_result = MagicMock()
        mock_result.data = [_make_block_row()]

        mock_query = MagicMock()
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.execute.return_value = mock_result

        mock_client = MagicMock()
        mock_client.table.return_value = mock_query

        repo = ContentBlockRepository(client=mock_client)
        repo.list_blocks(block_type="subject")

        calls = [str(c) for c in mock_query.eq.call_args_list]
        assert any("subject" in c for c in calls)

    def test_filters_by_status(self):
        mock_result = MagicMock()
        mock_result.data = []

        mock_query = MagicMock()
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.execute.return_value = mock_result

        mock_client = MagicMock()
        mock_client.table.return_value = mock_query

        repo = ContentBlockRepository(client=mock_client)
        repo.list_blocks(status="approved")

        calls = [str(c) for c in mock_query.eq.call_args_list]
        assert any("approved" in c for c in calls)


class TestGetCandidatesForDonor:
    def _make_donor(self, lifecycle: str, recency: str):
        from src.schemas import Donor
        import uuid
        return Donor(
            donor_id=uuid.uuid4(),
            donor_hash="abc",
            first_name="Test",
            email="test@example.com",
            center_name="BioLife Mumbai",
            weeks_since_last_donation=3,
            lifetime_donations=10,
            estimated_patients_helped=7,
            lifecycle_stage=lifecycle,
            recency_tier=recency,
            deferral_status="eligible",
            consent_email=True,
        )

    def _make_repo_with_blocks(self, blocks: list[ContentBlock]) -> ContentBlockRepository:
        rows = [b.to_db_dict() for b in blocks]
        mock_result = MagicMock()
        mock_result.data = rows

        mock_query = MagicMock()
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.execute.return_value = mock_result

        mock_client = MagicMock()
        mock_client.table.return_value = mock_query
        return ContentBlockRepository(client=mock_client)

    def test_returns_matching_blocks(self):
        blocks = build_blocks()
        subject_blocks = [b for b in blocks if b.block_type == "subject"]
        repo = self._make_repo_with_blocks(subject_blocks)
        donor = self._make_donor("new", "0-2wk")
        candidates = repo.get_candidates_for_donor(donor, "subject")
        assert len(candidates) >= 1
        for b in candidates:
            assert "new" in b.segment_fit["lifecycle_stages"]
            assert "0-2wk" in b.segment_fit["recency_tiers"]

    def test_filters_out_non_matching(self):
        blocks = build_blocks()
        subject_blocks = [b for b in blocks if b.block_type == "subject"]
        repo = self._make_repo_with_blocks(subject_blocks)
        # champion donors should NOT get new-only blocks
        donor = self._make_donor("champion", "0-2wk")
        candidates = repo.get_candidates_for_donor(donor, "subject")
        for b in candidates:
            assert "champion" in b.segment_fit["lifecycle_stages"]

    def test_returns_empty_for_unmatched_segment(self):
        # Block that matches only "new" donors
        block = ContentBlock(
            block_id="subject_test",
            block_type="subject",
            version=1,
            approved_text="Hi {first_name}",
            safe_tokens=["first_name"],
            segment_fit={"lifecycle_stages": ["new"], "recency_tiers": ["0-2wk"]},
            mlr_approval_id="MLR-2025-9999",
            mlr_approved_at="2025-12-01T00:00:00+00:00",
            status="approved",
            forbidden_modifications=["paraphrase", "rewrite", "expand"],
        )
        repo = self._make_repo_with_blocks([block])
        donor = self._make_donor("lapsed", "20wk+")
        candidates = repo.get_candidates_for_donor(donor, "subject")
        assert candidates == []
