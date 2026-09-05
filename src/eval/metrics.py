"""Aggregation functions: per-dimension stats, precision/recall, agreement."""
from __future__ import annotations

import statistics
import uuid
from collections import defaultdict

from src.schemas import EvalResult, GoldenExample


def per_dimension_stats(eval_results: list[EvalResult]) -> dict:
    """Return {dimension: {count, mean, median, std, p5, p95, pass_rate}} across all results."""
    scores_by_dim: dict[str, list[float]] = defaultdict(list)
    passed_by_dim: dict[str, list[bool]] = defaultdict(list)

    for result in eval_results:
        for ds in result.dimension_scores:
            scores_by_dim[ds.dimension].append(ds.score)
            passed_by_dim[ds.dimension].append(ds.passed)

    stats: dict[str, dict] = {}
    for dim, scores in scores_by_dim.items():
        sorted_scores = sorted(scores)
        n = len(sorted_scores)
        p5_idx = max(0, int(0.05 * n) - 1)
        p95_idx = min(n - 1, int(0.95 * n))
        stats[dim] = {
            "count": n,
            "mean": round(statistics.mean(scores), 4),
            "median": round(statistics.median(scores), 4),
            "std": round(statistics.stdev(scores) if n > 1 else 0.0, 4),
            "p5": round(sorted_scores[p5_idx], 4),
            "p95": round(sorted_scores[p95_idx], 4),
            "pass_rate": round(sum(passed_by_dim[dim]) / n, 4),
        }
    return stats


def precision_recall_on_golden(
    eval_results: list[EvalResult],
    golden_examples: list[GoldenExample],
) -> dict[str, dict]:
    """Per-dimension precision / recall / f1 against golden labels.

    For each dimension:
      TP = golden says dimension should fail AND eval marked it failed
      FP = golden says dimension should pass AND eval marked it failed (false alarm)
      FN = golden says dimension should fail AND eval marked it passed (missed detection)
      TN = golden says dimension should pass AND eval marked it passed
    """
    example_map = {ex.example_id: ex for ex in golden_examples}
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "tn": 0})

    for result in eval_results:
        if result.example_id is None:
            continue
        example = example_map.get(result.example_id)
        if example is None:
            continue
        expected_failures = set(example.expected_failures)

        for ds in result.dimension_scores:
            dim = ds.dimension
            expected_fail = dim in expected_failures
            eval_failed = not ds.passed

            # For should-fail examples, skip dimensions not in expected_failures.
            # Cascading failures (e.g. faithfulness also fires when claim_accuracy is the intended
            # failure) are correct behaviour — the email IS bad — not false positives.
            # FP counts are meaningful only for should-pass examples.
            if example.expected_verdict == "fail" and not expected_fail:
                continue

            if expected_fail and eval_failed:
                counts[dim]["tp"] += 1
            elif not expected_fail and eval_failed:
                counts[dim]["fp"] += 1
            elif expected_fail and not eval_failed:
                counts[dim]["fn"] += 1
            else:
                counts[dim]["tn"] += 1

    results: dict[str, dict] = {}
    for dim, c in counts.items():
        tp, fp, fn, tn = c["tp"], c["fp"], c["fn"], c["tn"]
        support = tp + fn  # number of examples where this dimension is expected to fail
        precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
        results[dim] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": support,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
        }
    return results


def overall_verdict_confusion(
    eval_results: list[EvalResult],
    golden_examples: list[GoldenExample],
) -> dict:
    """Overall pass/fail agreement between eval verdicts and golden labels."""
    example_map = {ex.example_id: ex for ex in golden_examples}
    matrix = {
        "eval_pass_gold_pass": 0,
        "eval_pass_gold_fail": 0,
        "eval_fail_gold_pass": 0,
        "eval_fail_gold_fail": 0,
    }

    for result in eval_results:
        if result.example_id is None:
            continue
        example = example_map.get(result.example_id)
        if example is None:
            continue
        gold_pass = example.expected_verdict == "pass"
        eval_pass = result.overall_passed
        if eval_pass and gold_pass:
            matrix["eval_pass_gold_pass"] += 1
        elif eval_pass and not gold_pass:
            matrix["eval_pass_gold_fail"] += 1
        elif not eval_pass and gold_pass:
            matrix["eval_fail_gold_pass"] += 1
        else:
            matrix["eval_fail_gold_fail"] += 1
    return matrix


def eval_vs_guardrail_agreement(
    eval_results: list[EvalResult],
    guardrail_statuses: dict[uuid.UUID, str],
) -> dict:
    """Compare eval overall_passed vs guardrail pass/quarantine for real emails."""
    matrix = {
        "eval_pass_guardrail_pass": 0,
        "eval_pass_guardrail_fail": 0,
        "eval_fail_guardrail_pass": 0,
        "eval_fail_guardrail_fail": 0,
    }
    for result in eval_results:
        if result.email_id is None:
            continue
        guardrail_status = guardrail_statuses.get(result.email_id)
        if guardrail_status is None:
            continue
        guardrail_pass = guardrail_status == "pass"
        eval_pass = result.overall_passed
        if eval_pass and guardrail_pass:
            matrix["eval_pass_guardrail_pass"] += 1
        elif eval_pass and not guardrail_pass:
            matrix["eval_pass_guardrail_fail"] += 1
        elif not eval_pass and guardrail_pass:
            matrix["eval_fail_guardrail_pass"] += 1
        else:
            matrix["eval_fail_guardrail_fail"] += 1
    return matrix


def cost_summary(eval_results: list[EvalResult]) -> dict:
    """Aggregate cost across all eval results, broken down by dimension."""
    total_cost = sum(r.total_cost_usd for r in eval_results)
    dim_costs: dict[str, list[float]] = defaultdict(list)
    for result in eval_results:
        for ds in result.dimension_scores:
            cost = ds.metadata.get("cost_usd", 0.0)
            if cost:
                dim_costs[ds.dimension].append(cost)
    return {
        "total_cost_usd": round(total_cost, 6),
        "per_dimension_mean_cost_usd": {
            dim: round(sum(costs) / len(costs), 8)
            for dim, costs in dim_costs.items()
        },
    }
