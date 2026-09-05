"""
Guardrail engine: runs all 8 checks in order and returns a combined GuardrailResult.

Order: cheapest / most likely to fail first, but ALL checks always run
so the audit log captures the complete picture for every email.
"""
from __future__ import annotations

from src.schemas import ContentBlock, Donor, GeneratedEmail, GuardrailCheck, GuardrailResult
from src.guardrails.rules import (
    check_token_substitution,
    check_length,
    check_pii_leak,
    check_claim_allowlist,
    check_banned_words,
    check_donor_fact_match,
    check_block_attribution,
    check_link_validation,
)


def run_guardrails(
    email: GeneratedEmail,
    selected_blocks: dict[str, ContentBlock],
    donor: Donor,
) -> GuardrailResult:
    """Run all 8 guardrail checks.  ALL checks run regardless of earlier failures
    so the audit log always contains a complete failure picture."""
    checks: list[GuardrailCheck] = [
        check_token_substitution(email),
        check_length(email),
        check_pii_leak(email),
        check_claim_allowlist(email),
        check_banned_words(email),
        check_donor_fact_match(email, donor),
        check_block_attribution(email, selected_blocks, donor),
        check_link_validation(email),
    ]

    verdict = "pass" if all(c.passed for c in checks) else "fail"
    return GuardrailResult(verdict=verdict, checks=checks)
