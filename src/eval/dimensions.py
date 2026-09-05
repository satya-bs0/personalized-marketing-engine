"""8 evaluation dimension scorers: 3 rule-based + 5 LLM-judged."""
from __future__ import annotations

import re

import textstat

from src.schemas import ContentBlock, DimensionScore, Donor, GeneratedEmail

# Rule-based thresholds (all must be exactly met — any failure → 0 on that sub-check)
_RULE_THRESHOLDS: dict[str, float] = {
    "block_attribution": 1.0,
    "length_readability": 1.0,
    "donor_fact_correctness": 1.0,
}

# LLM-judged thresholds live in judge.py; listed here for reference only
_LLM_DIMENSIONS = frozenset([
    "faithfulness",
    "claim_accuracy",
    "brand_voice",
    "toxicity_sensitivity",
    "segment_fit",
])

# Matches comma-formatted digit sequences so "1,000" is treated as 1000
_COMMA_NUMBER_RE = re.compile(r"(\d),(\d)")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Collapse all whitespace to single spaces, lowercase."""
    return " ".join(text.lower().split())


def _substitute_tokens(text: str, donor: Donor) -> str:
    """Replace {safe_token} placeholders with donor values."""
    return (
        text
        .replace("{first_name}", donor.first_name)
        .replace("{weeks_since_last_donation}", str(donor.weeks_since_last_donation))
        .replace("{lifetime_donations}", str(donor.lifetime_donations))
        .replace("{estimated_patients_helped}", str(donor.estimated_patients_helped))
        .replace("{center_name}", donor.center_name)
    )


# ---------------------------------------------------------------------------
# Rule-based scorers
# ---------------------------------------------------------------------------

def score_block_attribution(
    email: GeneratedEmail,
    selected_blocks: dict[str, ContentBlock],
    donor: Donor,
) -> DimensionScore:
    """Every selected block's text (after token substitution) must appear verbatim in the email."""
    threshold = _RULE_THRESHOLDS["block_attribution"]
    found_map: dict[str, bool] = {}
    missing: list[str] = []

    for slot, block in selected_blocks.items():
        substituted = _substitute_tokens(block.approved_text, donor)
        norm_block = _normalize(substituted)
        target = _normalize(email.subject if block.block_type == "subject" else email.body)
        found = norm_block in target
        found_map[block.block_id] = found
        if not found:
            missing.append(block.block_id)

    total = len(selected_blocks)
    matched = total - len(missing)
    score = round(matched / total, 4) if total > 0 else 1.0
    passed = score >= threshold

    return DimensionScore(
        dimension="block_attribution",
        score=score,
        passed=passed,
        threshold=threshold,
        reasoning=(
            f"{matched}/{total} blocks found verbatim" +
            (f"; missing: {missing}" if missing else "")
        ),
        metadata={"block_found": found_map, "missing": missing},
    )


def score_length_readability(email: GeneratedEmail) -> DimensionScore:
    """Subject ≤80 chars, body ≤500 words, Flesch reading ease ≥60."""
    threshold = _RULE_THRESHOLDS["length_readability"]
    subject_len = len(email.subject)
    body_words = len(email.body.split())
    flesch = textstat.flesch_reading_ease(email.body)

    subject_ok = subject_len <= 80
    body_ok = body_words <= 500
    # Threshold=30 is calibrated for professional plasma-donation messaging.
    # Approved block texts score 35-65 (multisyllabic medical vocabulary is expected).
    # 30 separates deliberately jargon-dense content (<30) from standard professional text.
    flesch_ok = flesch >= 30.0

    score = round(sum([subject_ok, body_ok, flesch_ok]) / 3, 4)
    passed = score >= threshold

    reasons: list[str] = []
    if not subject_ok:
        reasons.append(f"subject {subject_len} chars (max 80)")
    if not body_ok:
        reasons.append(f"body {body_words} words (max 500)")
    if not flesch_ok:
        reasons.append(f"Flesch {flesch:.1f} (min 30.0)")

    return DimensionScore(
        dimension="length_readability",
        score=score,
        passed=passed,
        threshold=threshold,
        reasoning=("; ".join(reasons) if reasons else f"All checks pass (Flesch {flesch:.1f})"),
        metadata={
            "subject_chars": subject_len,
            "body_word_count": body_words,
            "flesch_reading_ease": round(flesch, 2),
            "subject_ok": subject_ok,
            "body_ok": body_ok,
            "flesch_ok": flesch_ok,
        },
    )


def score_donor_fact_correctness(
    email: GeneratedEmail,
    donor: Donor,
) -> DimensionScore:
    """All standalone integers in the email must be in the donor's 3-value allowed set."""
    threshold = _RULE_THRESHOLDS["donor_fact_correctness"]
    allowed = {
        donor.weeks_since_last_donation,
        donor.lifetime_donations,
        donor.estimated_patients_helped,
    }
    text = email.subject + " " + email.body
    text = _COMMA_NUMBER_RE.sub(r"\1\2", text)  # normalise "1,000" → "1000"
    integers_found = [int(m) for m in re.findall(r"\b\d+\b", text)]
    mismatched = [n for n in integers_found if n not in allowed]

    score = 1.0 if not mismatched else 0.0
    return DimensionScore(
        dimension="donor_fact_correctness",
        score=score,
        passed=score >= threshold,
        threshold=threshold,
        reasoning=(
            "All numbers match donor profile"
            if not mismatched
            else f"Numbers not in profile: {mismatched[:5]}"
        ),
        metadata={
            "allowed_values": sorted(allowed),
            "integers_found": integers_found,
            "mismatched": mismatched[:10],
        },
    )


# ---------------------------------------------------------------------------
# LLM-judged scorers (delegate to LLMJudge — pass judge as arg to avoid circular import)
# ---------------------------------------------------------------------------

def score_faithfulness(
    email: GeneratedEmail,
    donor: Donor,
    selected_blocks: dict[str, ContentBlock],
    judge,  # LLMJudge
) -> DimensionScore:
    return judge.score("faithfulness", email, donor, selected_blocks)


def score_claim_accuracy(
    email: GeneratedEmail,
    donor: Donor,
    selected_blocks: dict[str, ContentBlock],
    judge,  # LLMJudge
) -> DimensionScore:
    return judge.score("claim_accuracy", email, donor, selected_blocks)


def score_brand_voice(
    email: GeneratedEmail,
    donor: Donor,
    selected_blocks: dict[str, ContentBlock],
    judge,  # LLMJudge
) -> DimensionScore:
    return judge.score("brand_voice", email, donor, selected_blocks)


def score_toxicity_sensitivity(
    email: GeneratedEmail,
    donor: Donor,
    selected_blocks: dict[str, ContentBlock],
    judge,  # LLMJudge
) -> DimensionScore:
    return judge.score("toxicity_sensitivity", email, donor, selected_blocks)


def score_segment_fit(
    email: GeneratedEmail,
    donor: Donor,
    selected_blocks: dict[str, ContentBlock],
    judge,  # LLMJudge
) -> DimensionScore:
    return judge.score("segment_fit", email, donor, selected_blocks)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ALL_DIMENSION_NAMES: list[str] = [
    "faithfulness",
    "claim_accuracy",
    "brand_voice",
    "toxicity_sensitivity",
    "segment_fit",
    "block_attribution",
    "length_readability",
    "donor_fact_correctness",
]
