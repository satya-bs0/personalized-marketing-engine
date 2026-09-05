#!/usr/bin/env python
"""Run a complete demo batch: generate → evaluate → summarize.

Usage:
    python scripts/run_demo_batch.py --size 100 --yes
    python scripts/run_demo_batch.py --size 50 --eval-sample-rate 0.5 --concurrency 3
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import config
from src.eval.runner import evaluate_batch
from src.llm.client import AnthropicClient
from src.pipeline.batch_runner import run_batch
from src.schemas import BatchEvalResult, BatchRun

COST_PER_DONOR_USD = 0.005     # generation: empirical (Haiku selection + assembly)
COST_PER_EVAL_DIM_USD = 0.001  # per LLM-judged dimension per email (5 LLM dims)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run demo batch: generate → evaluate → summarize"
    )
    parser.add_argument("--size", type=int, default=100,
                        help="Number of donors to process (default 100)")
    parser.add_argument("--concurrency", type=int, default=3,
                        help="Max parallel generation workers (default 3)")
    parser.add_argument("--eval-sample-rate", type=float, default=1.0,
                        help="Fraction of pass emails to evaluate (default 1.0)")
    parser.add_argument("--eval-concurrency", type=int, default=1,
                        help="Max parallel eval workers (default 1 — rate-limit safe)")
    parser.add_argument("--yes", action="store_true",
                        help="Skip confirmation prompt")
    args = parser.parse_args()

    gen_cost = args.size * COST_PER_DONOR_USD
    eval_cost = args.size * args.eval_sample_rate * 5 * COST_PER_EVAL_DIM_USD
    total_est = gen_cost + eval_cost

    print("=" * 56)
    print("  TAKEDA DONOR MESSAGING — DEMO BATCH")
    print("=" * 56)
    print(f"  Donors:           {args.size}")
    print(f"  Concurrency:      {args.concurrency}")
    print(f"  Eval sample rate: {args.eval_sample_rate:.0%}")
    print(f"  Model (gen):      {config.ANTHROPIC_MODEL_SELECTION}")
    print(f"  Model (eval):     {config.ANTHROPIC_MODEL_JUDGE}")
    print()
    print(f"  Est. generation:  ${gen_cost:.2f}")
    print(f"  Est. evaluation:  ${eval_cost:.2f}")
    print(f"  Est. total:       ${total_est:.2f}")
    print("=" * 56)

    if not args.yes:
        try:
            confirm = input("\nProceed? (y/N): ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            sys.exit(0)
        if confirm != "y":
            print("Aborted.")
            sys.exit(0)

    wall_t0 = time.perf_counter()

    # ------------------------------------------------------------------
    # Step 1: Generate emails
    # ------------------------------------------------------------------
    print(f"\n[1/2] Generating emails for {args.size} donors…")
    batch: BatchRun = asyncio.run(
        run_batch(batch_size=args.size, concurrency=args.concurrency)
    )

    # ------------------------------------------------------------------
    # Step 2: Evaluate the batch
    # ------------------------------------------------------------------
    print(f"\n[2/2] Evaluating batch {str(batch.batch_id)[:8]}… "
          f"(sample_rate={args.eval_sample_rate:.0%})")

    judge_client = AnthropicClient(
        model=config.ANTHROPIC_MODEL_JUDGE,
        api_key=config.ANTHROPIC_API_KEY,
    )
    eval_result: BatchEvalResult = asyncio.run(
        evaluate_batch(
            batch_id=batch.batch_id,
            llm_client=judge_client,
            sample_rate=args.eval_sample_rate,
            concurrency=args.eval_concurrency,
            persist=True,
        )
    )

    wall_time = time.perf_counter() - wall_t0

    # ------------------------------------------------------------------
    # Step 3: Summary
    # ------------------------------------------------------------------
    _print_summary(batch, eval_result, wall_time)


def _print_summary(batch: BatchRun, eval_result: BatchEvalResult, wall_time: float) -> None:
    pass_rate = batch.pass_count / batch.donor_count if batch.donor_count else 0.0

    print()
    print("=" * 56)
    print("  BATCH COMPLETE")
    print("=" * 56)
    print(f"  Batch ID:    {batch.batch_id}")
    print(f"  Donors:      {batch.donor_count}")
    print(f"  Pass:        {batch.pass_count} ({pass_rate:.1%})")
    print(f"  Quarantine:  {batch.quarantine_count}")
    print(f"  Error:       {batch.error_count}")
    print()
    print("  EVAL SCORES (mean per dimension)")
    print("  " + "-" * 40)

    dims = [
        "faithfulness",
        "claim_accuracy",
        "brand_voice",
        "toxicity_sensitivity",
        "segment_fit",
        "block_attribution",
        "length_readability",
        "donor_fact_correctness",
    ]
    all_pass = True
    for dim in dims:
        stats = eval_result.per_dimension_stats.get(dim, {})
        if not stats:
            print(f"  {dim:<28} —")
            continue
        mean = stats.get("mean", 0.0)
        pr = stats.get("pass_rate", 0.0)
        flag = "  ⚠" if mean < 0.85 else ""
        print(f"  {dim:<28} {mean:.3f}  ({pr:.1%} pass){flag}")
        if mean < 0.85:
            all_pass = False

    print()
    print(f"  Emails evaluated:  {eval_result.emails_evaluated}")
    print(f"  Eval pass rate:    {eval_result.overall_pass_rate:.1%}")
    print()
    print("  COST")
    print("  " + "-" * 40)
    print(f"  Generation:  ${batch.total_cost_usd:.4f}")
    print(f"  Evaluation:  ${eval_result.total_cost_usd:.4f}")
    total = batch.total_cost_usd + eval_result.total_cost_usd
    per_donor = total / batch.donor_count if batch.donor_count else 0.0
    print(f"  Total:       ${total:.4f}  (${per_donor:.4f}/donor)")
    print()
    print(f"  Wall time:   {wall_time:.1f}s")
    print("=" * 56)

    if all_pass:
        print("  ✓  All dimensions ≥ 0.85 mean score")
    else:
        print("  ⚠  Some dimensions below 0.85 — review eval page")

    print()
    print("  Launch dashboard:")
    print("    streamlit run dashboard/app.py")
    print()


if __name__ == "__main__":
    main()
