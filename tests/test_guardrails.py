"""
Unit tests for the 8 individual guardrail rule functions.

Each test: positive case (clean email passes) + ≥2 negative cases.
No I/O — all inputs are constructed in-memory.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from src.schemas import ContentBlock, Donor, GeneratedEmail
from src.guardrails.rules import (
    check_pii_leak,
    check_claim_allowlist,
    check_donor_fact_match,
    check_length,
    check_link_validation,
    check_block_attribution,
    check_banned_words,
    check_token_substitution,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def donor() -> Donor:
    return Donor(
        donor_hash="testhash_abc123",
        first_name="Alice",
        email="alice@biolife.example.com",
        center_name="BioLife Mumbai",
        weeks_since_last_donation=4,
        lifetime_donations=50,
        estimated_patients_helped=25,
        lifecycle_stage="regular",
        recency_tier="3-5wk",
    )


def _email(subject: str = "Thank you for being there, Alice",
           body: str = "Hi Alice, thank you for your 50 donations. You helped 25 patients.",
           tokens_used: list[str] | None = None) -> GeneratedEmail:
    return GeneratedEmail(
        subject=subject,
        body=body,
        tokens_used=tokens_used or ["first_name", "lifetime_donations", "estimated_patients_helped"],
    )


def _block(block_id: str, block_type: str, approved_text: str,
           safe_tokens: list[str] | None = None) -> ContentBlock:
    return ContentBlock(
        block_id=block_id,
        block_type=block_type,
        version=1,
        approved_text=approved_text,
        safe_tokens=safe_tokens or [],
        segment_fit={"lifecycle_stages": ["regular"], "recency_tiers": ["3-5wk"]},
        mlr_approval_id="MLR-TEST-001",
        mlr_approved_at=datetime.utcnow(),
        status="approved",
        forbidden_modifications=[],
    )


# ---------------------------------------------------------------------------
# 1. check_pii_leak
# ---------------------------------------------------------------------------

class TestPiiLeak:
    def test_clean_email_passes(self, donor):
        result = check_pii_leak(_email())
        assert result.passed
        assert result.check_name == "pii_leak"

    def test_us_phone_fails(self, donor):
        email = _email(body="Call us at 555-867-5309 for more info.")
        result = check_pii_leak(email)
        assert not result.passed
        assert "pii" in result.check_name

    def test_ssn_fails(self, donor):
        email = _email(body="Your SSN 123-45-6789 was found.")
        result = check_pii_leak(email)
        assert not result.passed

    def test_email_address_fails(self, donor):
        email = _email(body="Contact support@evil.com for help.")
        result = check_pii_leak(email)
        assert not result.passed

    def test_indian_phone_fails(self, donor):
        email = _email(body="Call 9876543210 to book.")
        result = check_pii_leak(email)
        assert not result.passed

    def test_pii_in_subject_fails(self, donor):
        email = _email(subject="Call 555-123-4567 Alice")
        result = check_pii_leak(email)
        assert not result.passed


# ---------------------------------------------------------------------------
# 2. check_claim_allowlist
# ---------------------------------------------------------------------------

class TestClaimAllowlist:
    def test_clean_email_passes(self):
        result = check_claim_allowlist(_email())
        assert result.passed

    def test_cure_fails(self):
        email = _email(body="Our plasma can cure diseases.")
        result = check_claim_allowlist(email)
        assert not result.passed
        assert "claim_allowlist" == result.check_name

    def test_clinical_trial_fails(self):
        email = _email(body="Participate in our clinical trial today.")
        result = check_claim_allowlist(email)
        assert not result.passed

    def test_therapy_name_fails(self):
        email = _email(body="Your plasma is used to make Hizentra.")
        result = check_claim_allowlist(email)
        assert not result.passed

    def test_urgent_fails(self):
        email = _email(subject="URGENT: Donate today!")
        result = check_claim_allowlist(email)
        assert not result.passed

    def test_case_insensitive(self):
        email = _email(body="This is PROVEN to work.")
        result = check_claim_allowlist(email)
        assert not result.passed


# ---------------------------------------------------------------------------
# 3. check_donor_fact_match
# ---------------------------------------------------------------------------

class TestDonorFactMatch:
    def test_matching_donor_values_passes(self, donor):
        # donor.lifetime_donations=50, estimated_patients_helped=25, weeks=4
        email = _email(body="You donated 50 times and helped 25 patients in 4 weeks.")
        result = check_donor_fact_match(email, donor)
        assert result.passed

    def test_no_numbers_passes(self, donor):
        email = _email(body="Thank you for your commitment to plasma donation.")
        result = check_donor_fact_match(email, donor)
        assert result.passed

    def test_hallucinated_count_fails(self, donor):
        # "10 patients" but donor.estimated_patients_helped=25
        email = _email(body="You helped 10 patients.")
        result = check_donor_fact_match(email, donor)
        assert not result.passed
        assert "donor_fact_match" == result.check_name

    def test_non_donor_number_fails(self, donor):
        # donor values: 4, 50, 25 — "100" is none of these
        email = _email(body="Join over 100 donors today.")
        result = check_donor_fact_match(email, donor)
        assert not result.passed

    def test_exact_patient_count_passes(self, donor):
        # donor.estimated_patients_helped = 25
        email = _email(body="You helped 25 patients.")
        result = check_donor_fact_match(email, donor)
        assert result.passed

    def test_metadata_includes_disallowed(self, donor):
        email = _email(body="Donate 999 times.")
        result = check_donor_fact_match(email, donor)
        assert not result.passed
        assert 999 in result.metadata["disallowed"]


# ---------------------------------------------------------------------------
# 4. check_length
# ---------------------------------------------------------------------------

class TestLength:
    def test_clean_email_passes(self):
        result = check_length(_email())
        assert result.passed
        assert result.metadata["subject_len"] <= 80

    def test_exact_80_char_subject_passes(self):
        subject = "A" * 80
        email = _email(subject=subject)
        result = check_length(email)
        assert result.passed

    def test_subject_too_long_fails(self):
        # Pydantic enforces max_length=80 on GeneratedEmail, so we use a mock to test
        # the check_length function directly with an over-long subject.
        from unittest.mock import MagicMock
        mock_email = MagicMock()
        mock_email.subject = "A" * 81
        mock_email.body = "Short body."
        result = check_length(mock_email)
        assert not result.passed
        assert "81" in result.reason

    def test_body_word_count_reported(self):
        body = " ".join(["word"] * 200)
        email = _email(body=body)
        result = check_length(email)
        assert result.passed
        assert result.metadata["body_word_count"] == 200

    def test_oversized_body_fails(self):
        from unittest.mock import MagicMock
        mock_email = MagicMock()
        mock_email.subject = "Short subject"
        mock_email.body = " ".join(["word"] * 501)
        result = check_length(mock_email)
        assert not result.passed
        assert "501" in result.reason or "word" in result.reason


# ---------------------------------------------------------------------------
# 5. check_link_validation
# ---------------------------------------------------------------------------

class TestLinkValidation:
    def test_no_links_passes(self):
        result = check_link_validation(_email())
        assert result.passed

    def test_allowed_domain_passes(self):
        email = _email(body="Visit https://biolifeplasma.com/schedule to book.")
        result = check_link_validation(email)
        assert result.passed

    def test_allowed_subdomain_passes(self):
        email = _email(body="See https://biolife.takeda.com/info for details.")
        result = check_link_validation(email)
        assert result.passed

    def test_unknown_domain_fails(self):
        email = _email(body="Visit https://evil.com for info.")
        result = check_link_validation(email)
        assert not result.passed
        assert "link_validation" == result.check_name

    def test_partial_domain_match_does_not_pass(self):
        # "notbiolifeplasma.com" should NOT match "biolifeplasma.com"
        email = _email(body="Visit https://notbiolifeplasma.com today.")
        result = check_link_validation(email)
        assert not result.passed

    def test_bad_url_metadata(self):
        email = _email(body="See https://phishing.example.com now.")
        result = check_link_validation(email)
        assert not result.passed
        assert result.metadata.get("bad_urls")


# ---------------------------------------------------------------------------
# 6. check_block_attribution
# ---------------------------------------------------------------------------

class TestBlockAttribution:
    def test_verbatim_block_passes(self, donor):
        # donor.first_name = "Alice", donor.center_name = "BioLife Mumbai"
        approved_text = "Hi {first_name}, your commitment inspires us at {center_name}."
        block = _block("opener_001", "opener", approved_text,
                       safe_tokens=["first_name", "center_name"])
        body = "Hi Alice, your commitment inspires us at BioLife Mumbai."
        email = _email(body=body)
        result = check_block_attribution(email, {"opener": block}, donor)
        assert result.passed
        assert result.metadata["block_found"]["opener_001"] is True

    def test_paraphrased_block_fails(self, donor):
        approved_text = "Hi {first_name}, your commitment inspires us at {center_name}."
        block = _block("opener_001", "opener", approved_text,
                       safe_tokens=["first_name", "center_name"])
        # Paraphrase: "dedication" instead of "commitment"
        body = "Hi Alice, your dedication inspires us at BioLife Mumbai."
        email = _email(body=body)
        result = check_block_attribution(email, {"opener": block}, donor)
        assert not result.passed
        assert "opener_001" in result.reason
        assert result.metadata["block_found"]["opener_001"] is False

    def test_subject_block_checked_against_subject(self, donor):
        approved_text = "Thank you, {first_name}"
        block = _block("subj_001", "subject", approved_text, safe_tokens=["first_name"])
        email = _email(subject="Thank you, Alice", body="Body text here.")
        result = check_block_attribution(email, {"subject": block}, donor)
        assert result.passed

    def test_multiple_blocks_all_must_match(self, donor):
        b1 = _block("b1", "opener", "Hi {first_name}.", safe_tokens=["first_name"])
        b2 = _block("b2", "signoff", "With gratitude.", safe_tokens=[])
        body = "Hi Alice. Thank you. With gratitude."
        email = _email(body=body)
        result = check_block_attribution(email, {"opener": b1, "signoff": b2}, donor)
        assert result.passed

    def test_one_missing_block_fails(self, donor):
        b1 = _block("b1", "opener", "Hi {first_name}.", safe_tokens=["first_name"])
        b2 = _block("b2", "signoff", "Warm regards from the team.", safe_tokens=[])
        body = "Hi Alice. Thank you."  # signoff text is missing
        email = _email(body=body)
        result = check_block_attribution(email, {"opener": b1, "signoff": b2}, donor)
        assert not result.passed
        assert result.metadata["block_found"]["b2"] is False

    def test_whitespace_normalisation(self, donor):
        # Extra spaces in email body should still match
        approved_text = "Hi {first_name}, we appreciate you."
        block = _block("b1", "opener", approved_text, safe_tokens=["first_name"])
        body = "Hi  Alice,   we   appreciate   you."
        email = _email(body=body)
        result = check_block_attribution(email, {"opener": block}, donor)
        assert result.passed


# ---------------------------------------------------------------------------
# 7. check_banned_words
# ---------------------------------------------------------------------------

class TestBannedWords:
    def test_clean_email_passes(self):
        result = check_banned_words(_email())
        assert result.passed

    def test_donate_now_fails(self):
        email = _email(body="Donate now and make a difference.")
        result = check_banned_words(email)
        assert not result.passed
        assert "banned_words" == result.check_name

    def test_click_here_fails(self):
        email = _email(body="Click here to schedule your appointment.")
        result = check_banned_words(email)
        assert not result.passed

    def test_free_fails(self):
        email = _email(body="Enjoy a free gift with your donation.")
        result = check_banned_words(email)
        assert not result.passed

    def test_claim_phrases_also_caught(self):
        # banned_words is a superset of claim_allowlist — medical claims should also fail
        email = _email(body="Our plasma is proven to work.")
        result = check_banned_words(email)
        assert not result.passed

    def test_freedom_does_not_match_free(self):
        # Word boundary: "freedom" should NOT match "\bfree\b"
        email = _email(body="We believe in your freedom to give.")
        result = check_banned_words(email)
        assert result.passed


# ---------------------------------------------------------------------------
# 8. check_token_substitution
# ---------------------------------------------------------------------------

class TestTokenSubstitution:
    def test_no_placeholders_passes(self):
        result = check_token_substitution(_email())
        assert result.passed
        assert result.check_name == "token_substitution"

    def test_unresolved_first_name_fails(self):
        email = _email(body="Hi {first_name}, thank you for your donations.")
        result = check_token_substitution(email)
        assert not result.passed
        assert "{first_name}" in result.reason

    def test_unresolved_placeholder_in_subject_fails(self):
        email = _email(subject="Hello {first_name}")
        result = check_token_substitution(email)
        assert not result.passed

    def test_unresolved_unknown_token_fails(self):
        email = _email(body="You have {unknown_token} left.")
        result = check_token_substitution(email)
        assert not result.passed

    def test_curly_brace_in_middle_of_sentence_fails(self):
        email = _email(body="Your {center_name} team welcomes you.")
        result = check_token_substitution(email)
        assert not result.passed
