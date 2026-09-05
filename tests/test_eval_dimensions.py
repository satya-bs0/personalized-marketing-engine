"""Tests for the 8 evaluation dimension scorers."""
from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from src.eval.dimensions import (
    score_block_attribution,
    score_donor_fact_correctness,
    score_length_readability,
    score_faithfulness,
    score_claim_accuracy,
    score_brand_voice,
    score_toxicity_sensitivity,
    score_segment_fit,
)
from src.schemas import ContentBlock, DimensionScore, Donor, GeneratedEmail


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _donor(**kwargs) -> Donor:
    defaults = dict(
        donor_id=uuid.uuid4(),
        donor_hash="a" * 64,
        first_name="Priya",
        email="priya@example.com",
        center_name="BioLife Mumbai",
        weeks_since_last_donation=4,
        lifetime_donations=18,
        estimated_patients_helped=9,
        lifecycle_stage="regular",
        recency_tier="3-5wk",
        deferral_status="eligible",
        deferral_until=None,
        consent_email=True,
        created_at=datetime.utcnow(),
    )
    defaults.update(kwargs)
    return Donor(**defaults)


def _email(subject="Thank you, Priya", body="Hi Priya, thank you.", tokens_used=None):
    return GeneratedEmail.model_construct(
        subject=subject,
        body=body,
        tokens_used=tokens_used or ["first_name"],
    )


def _block(block_id, block_type, approved_text, safe_tokens=None):
    return ContentBlock(
        block_id=block_id,
        block_type=block_type,
        version=1,
        approved_text=approved_text,
        safe_tokens=safe_tokens or [],
        segment_fit={"lifecycle_stages": ["regular"], "recency_tiers": ["3-5wk"]},
        mlr_approval_id="MLR-2025-9999",
        mlr_approved_at=datetime.utcnow(),
        status="approved",
        forbidden_modifications=["paraphrase"],
    )


# ---------------------------------------------------------------------------
# score_block_attribution
# ---------------------------------------------------------------------------

class TestScoreBlockAttribution:
    def test_verbatim_blocks_pass(self):
        donor = _donor()
        # Subject block
        subj = _block("subj_1", "subject", "Thank you, {first_name}", ["first_name"])
        # Body block (no tokens)
        body_blk = _block("body_1", "opener", "We appreciate your commitment.", [])
        email = _email(
            subject="Thank you, Priya",
            body="We appreciate your commitment.",
        )
        selected = {"subject": subj, "opener": body_blk}
        result = score_block_attribution(email, selected, donor)
        assert result.passed is True
        assert result.score == 1.0

    def test_paraphrased_block_fails(self):
        donor = _donor()
        blk = _block("opener_1", "opener", "Hi {first_name}, your commitment inspires us.", ["first_name"])
        # Email has different wording
        email = _email(body="Hi Priya, your dedication inspires us.")
        selected = {"opener": blk}
        result = score_block_attribution(email, selected, donor)
        assert result.passed is False
        assert result.score < 1.0
        assert "opener_1" in result.metadata["missing"]

    def test_partial_match_scores_fractionally(self):
        donor = _donor()
        blk1 = _block("op1", "opener", "Hello {first_name}.", ["first_name"])
        blk2 = _block("op2", "impact", "Patients thank you.", [])
        # Email only has blk1 verbatim, not blk2
        email = _email(body="Hello Priya. Something else entirely.")
        selected = {"opener": blk1, "impact": blk2}
        result = score_block_attribution(email, selected, donor)
        assert result.score == 0.5
        assert result.passed is False

    def test_empty_blocks_scores_one(self):
        donor = _donor()
        email = _email()
        result = score_block_attribution(email, {}, donor)
        assert result.score == 1.0
        assert result.passed is True


# ---------------------------------------------------------------------------
# score_length_readability
# ---------------------------------------------------------------------------

class TestScoreLengthReadability:
    def test_clean_email_passes(self):
        body = "Hi Priya. We value your support. Thank you for donating. See you soon. With gratitude."
        email = _email(body=body)
        result = score_length_readability(email)
        assert result.passed is True
        assert result.score == 1.0

    def test_dense_jargon_fails_flesch(self):
        dense = (
            "The biospecimen collection, fractionation, and reconstitution methodologies employed "
            "in immunoglobulin manufacturing necessitate rigorous quality control protocols "
            "encompassing immunochemical characterization, spectrophotometric quantification, "
            "electrophoretic verification, chromatographic purification, pathogen inactivation "
            "procedures, sterility testing, and final formulation analytics before pharmaceutical-grade "
            "immunoglobulin concentrates can be administered therapeutically to immunocompromised "
            "recipients requiring ongoing immunological supplementation."
        )
        email = _email(body=dense)
        result = score_length_readability(email)
        assert result.passed is False
        assert result.metadata["flesch_reading_ease"] < 30.0

    def test_metadata_contains_word_count_and_flesch(self):
        email = _email(body="Short and clear message. Easy to read. Thank you.")
        result = score_length_readability(email)
        assert "body_word_count" in result.metadata
        assert "flesch_reading_ease" in result.metadata
        assert "subject_chars" in result.metadata


# ---------------------------------------------------------------------------
# score_donor_fact_correctness
# ---------------------------------------------------------------------------

class TestScoreDonorFactCorrectness:
    def test_no_integers_passes(self):
        donor = _donor(weeks_since_last_donation=4, lifetime_donations=18, estimated_patients_helped=9)
        email = _email(body="Hi Priya, thank you for your ongoing support. We appreciate you.")
        result = score_donor_fact_correctness(email, donor)
        assert result.passed is True
        assert result.score == 1.0

    def test_matching_integers_pass(self):
        donor = _donor(weeks_since_last_donation=4, lifetime_donations=18, estimated_patients_helped=9)
        email = _email(body="Your 18 donations have helped 9 patients. It has been 4 weeks.")
        result = score_donor_fact_correctness(email, donor)
        assert result.passed is True

    def test_wrong_integer_fails(self):
        donor = _donor(weeks_since_last_donation=4, lifetime_donations=18, estimated_patients_helped=9)
        email = _email(body="Your 50 donations have inspired us.")  # 50 not in {4, 18, 9}
        result = score_donor_fact_correctness(email, donor)
        assert result.passed is False
        assert result.score == 0.0
        assert 50 in result.metadata["mismatched"]

    def test_comma_formatted_numbers_normalised(self):
        donor = _donor(weeks_since_last_donation=4, lifetime_donations=1000, estimated_patients_helped=9)
        email = _email(body="Your 1,000 donations are remarkable.")  # 1,000 → 1000
        result = score_donor_fact_correctness(email, donor)
        assert result.passed is True


# ---------------------------------------------------------------------------
# LLM-judged dimension scorers (mocked judge)
# ---------------------------------------------------------------------------

def _make_judge(score: float, reasoning: str = "test reasoning"):
    ds = DimensionScore(
        dimension="faithfulness",
        score=score,
        passed=score >= 0.8,
        threshold=0.8,
        reasoning=reasoning,
        judge_model="claude-haiku-4-5",
    )
    judge = MagicMock()
    judge.score.return_value = ds
    return judge, ds


class TestLLMJudgedDimensions:
    def test_faithfulness_delegates_to_judge(self):
        donor = _donor()
        email = _email()
        judge, expected_ds = _make_judge(0.9)
        result = score_faithfulness(email, donor, {}, judge)
        judge.score.assert_called_once_with("faithfulness", email, donor, {})
        assert result.score == expected_ds.score

    def test_claim_accuracy_delegates_to_judge(self):
        donor = _donor()
        email = _email()
        judge, _ = _make_judge(0.95)
        judge.score.return_value = DimensionScore(
            dimension="claim_accuracy", score=0.95, passed=True, threshold=0.9
        )
        result = score_claim_accuracy(email, donor, {}, judge)
        judge.score.assert_called_once_with("claim_accuracy", email, donor, {})

    def test_brand_voice_delegates_to_judge(self):
        donor = _donor()
        email = _email()
        judge, _ = _make_judge(0.85)
        judge.score.return_value = DimensionScore(
            dimension="brand_voice", score=0.85, passed=True, threshold=0.7
        )
        result = score_brand_voice(email, donor, {}, judge)
        judge.score.assert_called_once_with("brand_voice", email, donor, {})

    def test_toxicity_sensitivity_delegates_to_judge(self):
        donor = _donor()
        email = _email()
        judge, _ = _make_judge(0.98)
        judge.score.return_value = DimensionScore(
            dimension="toxicity_sensitivity", score=0.98, passed=True, threshold=0.95
        )
        result = score_toxicity_sensitivity(email, donor, {}, judge)
        judge.score.assert_called_once_with("toxicity_sensitivity", email, donor, {})

    def test_segment_fit_delegates_to_judge(self):
        donor = _donor()
        email = _email()
        judge, _ = _make_judge(0.75)
        judge.score.return_value = DimensionScore(
            dimension="segment_fit", score=0.75, passed=True, threshold=0.7
        )
        result = score_segment_fit(email, donor, {}, judge)
        judge.score.assert_called_once_with("segment_fit", email, donor, {})
