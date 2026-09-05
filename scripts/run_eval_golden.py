"""
Validate the evaluation framework on the 50 hand-labeled golden examples.

Usage:
    python scripts/run_eval_golden.py [--yes] [--persist]

Cost estimate: 50 examples × 5 LLM dimensions × ~$0.001/call ≈ $0.25
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import config
from src.eval.runner import evaluate_golden_set
from src.llm.client import AnthropicClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Run eval framework on golden set")
    parser.add_argument("--yes", action="store_true",
                        help="Skip confirmation prompt")
    parser.add_argument("--concurrency", type=int, default=1,
                        help="Max concurrent examples (default 1, safe under 50k token/min rate limit)")
    parser.add_argument("--persist", action="store_true",
                        help="Write scores to eval_scores table in Supabase")
    args = parser.parse_args()

    est_cost = 50 * 5 * 0.001
    print(f"Estimated cost: ~${est_cost:.2f} for golden set validation (50 ex × 5 LLM dims)")
    print(f"Model: {config.ANTHROPIC_MODEL_JUDGE}  Concurrency: {args.concurrency}")
    if args.persist:
        print("Persistence: ON — scores will be written to eval_scores")

    if not args.yes:
        confirm = input("Proceed? (y/N): ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return

    client = AnthropicClient(
        model=config.ANTHROPIC_MODEL_JUDGE,
        api_key=config.ANTHROPIC_API_KEY,
    )

    db_client = None
    if args.persist:
        from supabase import create_client
        db_client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)

    print("\nRunning evaluation on 50 golden examples…")
    result = asyncio.run(evaluate_golden_set(client, db_client=db_client, concurrency=args.concurrency))

    print(f"\n{'='*60}")
    print(f"GOLDEN SET RESULTS — {result.total_examples} examples")
    print(f"{'='*60}")

    dims = [
        "faithfulness", "claim_accuracy", "brand_voice",
        "toxicity_sensitivity", "segment_fit",
        "block_attribution", "length_readability", "donor_fact_correctness",
    ]

    print(f"\n{'dimension':<28} {'precision':>10} {'recall':>8} {'f1':>8} {'support':>8}")
    print("-" * 64)
    for dim in dims:
        stats = result.per_dimension.get(dim, {})
        if not stats:
            print(f"{dim:<28} {'—':>10} {'—':>8} {'—':>8} {'—':>8}")
            continue
        precision = stats.get("precision", 0.0)
        recall    = stats.get("recall", 0.0)
        f1        = stats.get("f1", 0.0)
        support   = stats.get("support", 0)
        warn = "  ⚠" if (precision < 0.7 or recall < 0.7) else ""
        print(f"{dim:<28} {precision:>10.3f} {recall:>8.3f} {f1:>8.3f} {support:>8}{warn}")

    cm = result.confusion_matrix
    total = sum(cm.values())
    correct = cm.get("eval_pass_gold_pass", 0) + cm.get("eval_fail_gold_fail", 0)
    accuracy = correct / total if total > 0 else 0.0
    print(f"\nOverall verdict accuracy: {correct}/{total} = {accuracy:.1%}")
    print(f"  eval_pass / gold_pass:  {cm.get('eval_pass_gold_pass', 0)}")
    print(f"  eval_fail / gold_fail:  {cm.get('eval_fail_gold_fail', 0)}")
    print(f"  eval_pass / gold_fail:  {cm.get('eval_pass_gold_fail', 0)}  (missed failures)")
    print(f"  eval_fail / gold_pass:  {cm.get('eval_fail_gold_pass', 0)}  (false alarms)")

    print(f"\nTotal cost: ${result.total_cost_usd:.4f}")

    # Flag dimensions below target
    avg_p = sum(result.per_dimension[d]["precision"] for d in result.per_dimension) / max(len(result.per_dimension), 1)
    avg_r = sum(result.per_dimension[d]["recall"] for d in result.per_dimension) / max(len(result.per_dimension), 1)
    print(f"\nAverage precision: {avg_p:.3f}  Average recall: {avg_r:.3f}")
    if avg_p < 0.80 or avg_r < 0.80:
        print("⚠  Below 0.80 target — review failing prompts and golden examples")
    else:
        print("✓  Meets ≥0.80 precision/recall target")


if __name__ == "__main__":
    main()
