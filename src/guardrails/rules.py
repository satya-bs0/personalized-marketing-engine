"""
Eight individual guardrail rule functions.

Each returns a GuardrailCheck (passed=True or False + reason + metadata).
All checks are pure functions — no I/O, no side effects.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from src.schemas import ContentBlock, Donor, GeneratedEmail, GuardrailCheck

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _full_text(email: GeneratedEmail) -> str:
    return email.subject + " " + email.body


def _normalize(text: str) -> str:
    """Collapse all whitespace to single spaces and lowercase."""
    return " ".join(text.lower().split())


def _substitute_tokens(text: str, donor: Donor) -> str:
    """Replace all {safe_token} placeholders with the donor's actual values."""
    return (
        text
        .replace("{first_name}", donor.first_name)
        .replace("{weeks_since_last_donation}", str(donor.weeks_since_last_donation))
        .replace("{lifetime_donations}", str(donor.lifetime_donations))
        .replace("{estimated_patients_helped}", str(donor.estimated_patients_helped))
        .replace("{center_name}", donor.center_name)
    )


# ---------------------------------------------------------------------------
# Patterns (compiled once at module load)
# ---------------------------------------------------------------------------

_PII_PATTERNS = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),                            # SSN
    re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"),               # US phone
    re.compile(r"\b(?:\+91[-\s]?)?[6-9]\d{9}\b"),                    # Indian mobile
    re.compile(r"\b[\w._%+\-]+@[\w.\-]+\.[A-Za-z]{2,}\b"),          # email address
]

_CLAIM_PATTERNS = [
    re.compile(r"\bcure\b", re.IGNORECASE),
    re.compile(r"\btreats?\b", re.IGNORECASE),
    re.compile(r"\bguarantee[ds]?\b", re.IGNORECASE),
    re.compile(r"\bproven\b", re.IGNORECASE),
    re.compile(r"\bclinical trial\b", re.IGNORECASE),
    re.compile(r"\bHizentra\b", re.IGNORECASE),
    re.compile(r"\bPrivigen\b", re.IGNORECASE),
    re.compile(r"\bGammagard\b", re.IGNORECASE),
    re.compile(r"\blimited time\b", re.IGNORECASE),
    re.compile(r"\bact now\b", re.IGNORECASE),
    re.compile(r"\bfinal notice\b", re.IGNORECASE),
    re.compile(r"\burgent\b", re.IGNORECASE),
    re.compile(r"\bamazing\b", re.IGNORECASE),
    re.compile(r"\bincredible\b", re.IGNORECASE),
    re.compile(r"\brevolutionary\b", re.IGNORECASE),
    re.compile(r"\bmiracle\b", re.IGNORECASE),
]

_EXTRA_BANNED = [
    re.compile(r"\bdonate now\b", re.IGNORECASE),
    re.compile(r"\bclick here\b", re.IGNORECASE),
    re.compile(r"\bfree\b", re.IGNORECASE),
    re.compile(r"\bsale\b", re.IGNORECASE),
    re.compile(r"\bdiscount\b", re.IGNORECASE),
]

_BANNED_WORD_PATTERNS = _CLAIM_PATTERNS + _EXTRA_BANNED

_ALLOWED_DOMAINS = frozenset(["biolife.takeda.com", "biolifeplasma.com", "takeda.com"])

_URL_RE = re.compile(r"https?://[^\s<>\"']+")

# Matches comma-formatted digit sequences so "1,000" is treated as 1000.
_COMMA_NUMBER_RE = re.compile(r"(\d),(\d)")


# ---------------------------------------------------------------------------
# Check 1: PII leak
# ---------------------------------------------------------------------------

def check_pii_leak(email: GeneratedEmail) -> GuardrailCheck:
    text = _full_text(email)
    for pattern in _PII_PATTERNS:
        m = pattern.search(text)
        if m:
            return GuardrailCheck(
                check_name="pii_leak",
                passed=False,
                reason=f"PII pattern matched: {m.re.pattern!r}",
                metadata={"matched_snippet": text[max(0, m.start() - 10): m.end() + 10]},
            )
    return GuardrailCheck(check_name="pii_leak", passed=True)


# ---------------------------------------------------------------------------
# Check 2: Claim allowlist
# ---------------------------------------------------------------------------

def check_claim_allowlist(email: GeneratedEmail) -> GuardrailCheck:
    text = _full_text(email)
    for pattern in _CLAIM_PATTERNS:
        m = pattern.search(text)
        if m:
            return GuardrailCheck(
                check_name="claim_allowlist",
                passed=False,
                reason=f"Disallowed claim phrase matched: {m.group()!r}",
                metadata={"matched": m.group()},
            )
    return GuardrailCheck(check_name="claim_allowlist", passed=True)


# ---------------------------------------------------------------------------
# Check 3: Donor fact match
# ---------------------------------------------------------------------------

def check_donor_fact_match(email: GeneratedEmail, donor: Donor) -> GuardrailCheck:
    """All standalone integers in the email must match one of the donor's three factual values."""
    allowed = {
        donor.weeks_since_last_donation,
        donor.lifetime_donations,
        donor.estimated_patients_helped,
    }
    text = _full_text(email)
    # Normalise comma-formatted numbers: "1,000" → "1000"
    text = _COMMA_NUMBER_RE.sub(r"\1\2", text)
    integers_found = [int(m) for m in re.findall(r"\b\d+\b", text)]
    disallowed = [n for n in integers_found if n not in allowed]
    if disallowed:
        return GuardrailCheck(
            check_name="donor_fact_match",
            passed=False,
            reason=f"Integers not in donor profile: {disallowed[:5]}",
            metadata={"disallowed": disallowed[:10], "allowed": sorted(allowed)},
        )
    return GuardrailCheck(check_name="donor_fact_match", passed=True)


# ---------------------------------------------------------------------------
# Check 4: Length
# ---------------------------------------------------------------------------

def check_length(email: GeneratedEmail) -> GuardrailCheck:
    subject_len = len(email.subject)
    word_count = len(email.body.split())
    errors: list[str] = []
    if subject_len > 80:
        errors.append(f"subject {subject_len} chars (max 80)")
    if word_count > 500:
        errors.append(f"body {word_count} words (max 500)")
    if errors:
        return GuardrailCheck(
            check_name="length",
            passed=False,
            reason="; ".join(errors),
            metadata={"subject_len": subject_len, "body_word_count": word_count},
        )
    return GuardrailCheck(
        check_name="length",
        passed=True,
        metadata={"subject_len": subject_len, "body_word_count": word_count},
    )


# ---------------------------------------------------------------------------
# Check 5: Link validation
# ---------------------------------------------------------------------------

def check_link_validation(email: GeneratedEmail) -> GuardrailCheck:
    text = _full_text(email)
    urls = _URL_RE.findall(text)
    bad: list[str] = []
    for url in urls:
        parsed = urlparse(url)
        domain = (parsed.hostname or "").lower()
        allowed = any(
            domain == d or domain.endswith("." + d)
            for d in _ALLOWED_DOMAINS
        )
        if not allowed:
            bad.append(url)
    if bad:
        return GuardrailCheck(
            check_name="link_validation",
            passed=False,
            reason=f"Non-allowed domains: {[u[:80] for u in bad]}",
            metadata={"bad_urls": bad[:5]},
        )
    return GuardrailCheck(check_name="link_validation", passed=True)


# ---------------------------------------------------------------------------
# Check 6: Block attribution
# ---------------------------------------------------------------------------

def check_block_attribution(
    email: GeneratedEmail,
    selected_blocks: dict[str, ContentBlock],
    donor: Donor,
) -> GuardrailCheck:
    """Every selected block's approved text (after token substitution) must appear
    verbatim in the email.  Catches paraphrasing — the most important compliance check."""
    found_map: dict[str, bool] = {}
    missing: list[str] = []

    for slot, block in selected_blocks.items():
        substituted = _substitute_tokens(block.approved_text, donor)
        normalized_block = _normalize(substituted)

        if block.block_type == "subject":
            target = _normalize(email.subject)
        else:
            target = _normalize(email.body)

        found = normalized_block in target
        found_map[block.block_id] = found
        if not found:
            missing.append(block.block_id)

    if missing:
        return GuardrailCheck(
            check_name="block_attribution",
            passed=False,
            reason=f"Block text not found verbatim: {missing}",
            metadata={"block_found": found_map},
        )
    return GuardrailCheck(
        check_name="block_attribution",
        passed=True,
        metadata={"block_found": found_map},
    )


# ---------------------------------------------------------------------------
# Check 7: Banned words
# ---------------------------------------------------------------------------

def check_banned_words(email: GeneratedEmail) -> GuardrailCheck:
    text = _full_text(email)
    for pattern in _BANNED_WORD_PATTERNS:
        m = pattern.search(text)
        if m:
            return GuardrailCheck(
                check_name="banned_words",
                passed=False,
                reason=f"Banned word/phrase matched: {m.group()!r}",
                metadata={"matched": m.group()},
            )
    return GuardrailCheck(check_name="banned_words", passed=True)


# ---------------------------------------------------------------------------
# Check 8: Token substitution
# ---------------------------------------------------------------------------

def check_token_substitution(email: GeneratedEmail) -> GuardrailCheck:
    """Fail if any {placeholder} survived into the final email."""
    text = _full_text(email)
    if "{" in text:
        # Find the first unresolved token for the error message
        m = re.search(r"\{[^}]+\}", text)
        snippet = m.group() if m else "unknown"
        return GuardrailCheck(
            check_name="token_substitution",
            passed=False,
            reason=f"Unresolved token placeholder found: {snippet!r}",
        )
    return GuardrailCheck(check_name="token_substitution", passed=True)
