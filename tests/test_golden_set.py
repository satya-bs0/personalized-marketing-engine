"""Tests for the golden set loader and distribution."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.eval.golden_set import load_golden_set
from src.schemas import GoldenExample


class TestGoldenSetLoader:
    @pytest.fixture(scope="class")
    def examples(self):
        return load_golden_set()

    def test_loads_50_examples(self, examples):
        assert len(examples) == 50

    def test_all_are_golden_examples(self, examples):
        for ex in examples:
            assert isinstance(ex, GoldenExample)

    def test_distribution_30_pass_20_fail(self, examples):
        pass_count = sum(1 for e in examples if e.expected_verdict == "pass")
        fail_count = sum(1 for e in examples if e.expected_verdict == "fail")
        assert pass_count == 30
        assert fail_count == 20

    def test_fail_examples_have_at_least_one_failure(self, examples):
        for ex in examples:
            if ex.expected_verdict == "fail":
                assert len(ex.expected_failures) >= 1, (
                    f"{ex.example_id} is expected to fail but has no expected_failures"
                )

    def test_pass_examples_have_empty_failures(self, examples):
        for ex in examples:
            if ex.expected_verdict == "pass":
                assert ex.expected_failures == [], (
                    f"{ex.example_id} is expected to pass but has {ex.expected_failures}"
                )

    def test_unique_example_ids(self, examples):
        ids = [e.example_id for e in examples]
        assert len(ids) == len(set(ids))

    def test_ids_are_sequential(self, examples):
        ids = sorted(e.example_id for e in examples)
        assert ids[0] == "gold_001"
        assert ids[-1] == "gold_050"

    def test_all_donors_are_eligible(self, examples):
        for ex in examples:
            assert ex.donor.deferral_status == "eligible"
            assert ex.donor.consent_email is True

    def test_selected_blocks_cover_all_slots(self, examples):
        required_slots = {"subject", "opener", "impact", "social_proof", "cta", "signoff"}
        for ex in examples:
            slots = set(ex.selected_blocks.keys())
            assert slots == required_slots, (
                f"{ex.example_id} missing slots: {required_slots - slots}"
            )

    def test_failure_mode_coverage(self, examples):
        """Each required failure mode has at least one example."""
        required_modes = {
            "faithfulness", "claim_accuracy", "brand_voice",
            "toxicity_sensitivity", "segment_fit",
            "block_attribution", "length_readability", "donor_fact_correctness",
        }
        covered = set()
        for ex in examples:
            covered.update(ex.expected_failures)
        missing = required_modes - covered
        assert not missing, f"Missing failure modes in golden set: {missing}"

    def test_emails_have_required_fields(self, examples):
        for ex in examples:
            email = ex.email
            assert hasattr(email, "subject")
            assert hasattr(email, "body")
            assert hasattr(email, "tokens_used")
            assert len(email.subject) <= 80

    def test_lifecycle_stage_distribution(self, examples):
        """Pass examples cover all 5 lifecycle stages."""
        pass_examples = [e for e in examples if e.expected_verdict == "pass"]
        stages = {e.donor.lifecycle_stage for e in pass_examples}
        assert stages == {"new", "regular", "champion", "at_risk", "lapsed"}

    def test_custom_path_loading(self):
        """load_golden_set accepts a custom Path."""
        default_path = Path(__file__).parent.parent / "data" / "golden_set.json"
        examples = load_golden_set(path=default_path)
        assert len(examples) == 50
