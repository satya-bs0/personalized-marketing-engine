"""Tests for the evaluation runner and metrics."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.eval.metrics import (
    cost_summary,
    eval_vs_guardrail_agreement,
    overall_verdict_confusion,
    per_dimension_stats,
    precision_recall_on_golden,
)
from src.eval.runner import evaluate_email, evaluate_golden_set
from src.schemas import (
    ContentBlock,
    DimensionScore,
    Donor,
    EvalResult,
    GeneratedEmail,
    GoldenExample,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ds(dimension, score, threshold=0.8):
    return DimensionScore(
        dimension=dimension,
        score=score,
        passed=score >= threshold,
        threshold=threshold,
        reasoning=f"score={score}",
    )


def _eval_result(dim_scores, email_id=None, example_id=None):
    failed = [ds.dimension for ds in dim_scores if not ds.passed]
    return EvalResult(
        email_id=email_id,
        example_id=example_id,
        dimension_scores=dim_scores,
        overall_passed=len(failed) == 0,
        failed_dimensions=failed,
        total_cost_usd=0.001,
        total_latency_ms=500,
    )


def _donor():
    return Donor(
        donor_id=uuid.uuid4(),
        donor_hash="c" * 64,
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


def _email():
    return GeneratedEmail.model_construct(
        subject="Thank you, Priya",
        body="Hi Priya, thank you for your support.",
        tokens_used=["first_name"],
    )


def _block(bid, btype, text):
    return ContentBlock(
        block_id=bid, block_type=btype, version=1,
        approved_text=text, safe_tokens=[],
        segment_fit={"lifecycle_stages": ["regular"], "recency_tiers": ["3-5wk"]},
        mlr_approval_id="MLR-9999", mlr_approved_at=datetime.utcnow(),
        status="approved", forbidden_modifications=[],
    )


# ---------------------------------------------------------------------------
# per_dimension_stats
# ---------------------------------------------------------------------------

class TestPerDimensionStats:
    def test_basic_stats(self):
        results = [
            _eval_result([_ds("faithfulness", 0.9), _ds("brand_voice", 0.8)]),
            _eval_result([_ds("faithfulness", 0.7), _ds("brand_voice", 0.6)]),
        ]
        stats = per_dimension_stats(results)
        assert "faithfulness" in stats
        assert stats["faithfulness"]["mean"] == pytest.approx(0.8)
        assert stats["faithfulness"]["count"] == 2

    def test_pass_rate_computed(self):
        results = [
            _eval_result([_ds("faithfulness", 0.9)]),  # passes (0.9 >= 0.8)
            _eval_result([_ds("faithfulness", 0.7)]),  # fails
        ]
        stats = per_dimension_stats(results)
        assert stats["faithfulness"]["pass_rate"] == pytest.approx(0.5)

    def test_empty_results_returns_empty(self):
        stats = per_dimension_stats([])
        assert stats == {}


# ---------------------------------------------------------------------------
# precision_recall_on_golden
# ---------------------------------------------------------------------------

class TestPrecisionRecallOnGolden:
    def _golden_ex(self, example_id, expected_failures):
        return GoldenExample(
            example_id=example_id,
            notes="test",
            donor=_donor(),
            email=_email(),
            selected_blocks={},
            expected_verdict="fail" if expected_failures else "pass",
            expected_failures=expected_failures,
        )

    def test_perfect_detection(self):
        golden = [self._golden_ex("ex1", ["faithfulness"])]
        results = [_eval_result([_ds("faithfulness", 0.5)], example_id="ex1")]
        pr = precision_recall_on_golden(results, golden)
        assert pr["faithfulness"]["precision"] == 1.0
        assert pr["faithfulness"]["recall"] == 1.0
        assert pr["faithfulness"]["f1"] == 1.0

    def test_missed_failure_reduces_recall(self):
        golden = [self._golden_ex("ex1", ["faithfulness"])]
        results = [_eval_result([_ds("faithfulness", 0.9)], example_id="ex1")]  # passes, should fail
        pr = precision_recall_on_golden(results, golden)
        assert pr["faithfulness"]["recall"] == 0.0  # FN
        assert pr["faithfulness"]["fn"] == 1

    def test_false_alarm_reduces_precision(self):
        golden = [self._golden_ex("ex1", [])]  # no expected failure
        results = [_eval_result([_ds("faithfulness", 0.5)], example_id="ex1")]  # fails unexpectedly
        pr = precision_recall_on_golden(results, golden)
        assert pr["faithfulness"]["precision"] == 0.0
        assert pr["faithfulness"]["fp"] == 1

    def test_ignores_results_without_example_id(self):
        golden = [self._golden_ex("ex1", ["faithfulness"])]
        email_id = uuid.uuid4()
        results = [_eval_result([_ds("faithfulness", 0.5)], email_id=email_id)]
        pr = precision_recall_on_golden(results, golden)
        # No matching example_id → no counts recorded
        assert pr == {}


# ---------------------------------------------------------------------------
# overall_verdict_confusion
# ---------------------------------------------------------------------------

class TestOverallVerdictConfusion:
    def _golden_ex(self, eid, verdict):
        return GoldenExample(
            example_id=eid, notes="test", donor=_donor(), email=_email(),
            selected_blocks={},
            expected_verdict=verdict,
            expected_failures=[] if verdict == "pass" else ["faithfulness"],
        )

    def test_correct_classifications(self):
        golden = [
            self._golden_ex("a", "pass"),
            self._golden_ex("b", "fail"),
        ]
        results = [
            _eval_result([_ds("faithfulness", 0.9)], example_id="a"),  # pass → gold pass
            _eval_result([_ds("faithfulness", 0.5)], example_id="b"),  # fail → gold fail
        ]
        cm = overall_verdict_confusion(results, golden)
        assert cm["eval_pass_gold_pass"] == 1
        assert cm["eval_fail_gold_fail"] == 1
        assert cm["eval_pass_gold_fail"] == 0
        assert cm["eval_fail_gold_pass"] == 0


# ---------------------------------------------------------------------------
# eval_vs_guardrail_agreement
# ---------------------------------------------------------------------------

class TestEvalVsGuardrailAgreement:
    def test_agreement_matrix(self):
        eid1 = uuid.uuid4()
        eid2 = uuid.uuid4()
        results = [
            _eval_result([_ds("faithfulness", 0.9)], email_id=eid1),  # eval pass
            _eval_result([_ds("faithfulness", 0.5)], email_id=eid2),  # eval fail
        ]
        guardrail_statuses = {eid1: "pass", eid2: "quarantine"}
        cm = eval_vs_guardrail_agreement(results, guardrail_statuses)
        assert cm["eval_pass_guardrail_pass"] == 1
        assert cm["eval_fail_guardrail_fail"] == 1

    def test_unknown_email_id_skipped(self):
        eid = uuid.uuid4()
        results = [_eval_result([_ds("faithfulness", 0.9)], email_id=eid)]
        cm = eval_vs_guardrail_agreement(results, {})  # eid not in statuses
        assert all(v == 0 for v in cm.values())


# ---------------------------------------------------------------------------
# evaluate_email (mocked pipeline)
# ---------------------------------------------------------------------------

class TestEvaluateEmail:
    def test_runs_all_8_dimensions(self):
        from src.eval.dimensions import ALL_DIMENSION_NAMES
        donor = _donor()
        email = _email()
        selected_blocks = {
            "subject": _block("s1", "subject", "Thank you, Priya"),
            "opener":  _block("o1", "opener",  "Hi Priya, thank you."),
        }

        llm_client = MagicMock()
        llm_client.model = "claude-haiku-4-5"
        llm_client.enable_prompt_caching = False

        # Mock every call() to return a valid LLM response
        from src.schemas import LLMResponse
        mock_resp = LLMResponse(
            tool_input={"score": 0.9, "reasoning": "ok"},
            input_tokens=100, output_tokens=20, latency_ms=300,
            model="claude-haiku-4-5", prompt_hash="abc", raw_response_id="msg_x",
        )
        llm_client.call.return_value = mock_resp

        result = asyncio.run(evaluate_email(email, donor, selected_blocks, llm_client))

        assert len(result.dimension_scores) == 8
        dims = {ds.dimension for ds in result.dimension_scores}
        assert dims == set(ALL_DIMENSION_NAMES)

    def test_overall_passed_reflects_all_dimensions(self):
        donor = _donor()
        email = _email()
        llm_client = MagicMock()
        llm_client.model = "claude-haiku-4-5"
        llm_client.enable_prompt_caching = False
        from src.schemas import LLMResponse
        # Low score → faithfulness fails
        mock_resp = LLMResponse(
            tool_input={"score": 0.5, "reasoning": "bad"},
            input_tokens=100, output_tokens=20, latency_ms=300,
            model="claude-haiku-4-5", prompt_hash="abc", raw_response_id="msg_x",
        )
        llm_client.call.return_value = mock_resp

        result = asyncio.run(evaluate_email(email, donor, {}, llm_client))
        # Some LLM dimensions should fail at score=0.5
        assert result.overall_passed is False
        assert len(result.failed_dimensions) > 0
