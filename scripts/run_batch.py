#!/usr/bin/env python
"""CLI entry point for running a donor messaging batch.

Usage:
    python scripts/run_batch.py --size 5 --yes
    python scripts/run_batch.py --size 100
    ALLOW_LARGE_BATCH=true python scripts/run_batch.py --size 500
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

# Ensure project root is on the path when run as a script
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pipeline.batch_runner import run_batch

COST_PER_DONOR_USD = 0.005  # empirical, from Layer 4-5 testing with claude-haiku-4-5


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a donor messaging batch.")
    parser.add_argument("--size", type=int, default=100, help="Number of donors to process")
    parser.add_argument("--concurrency", type=int, default=3,
                        help="Max parallel LLM calls (keep ≤5 to avoid HTTP/2 saturation on sync client)")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    # Cost guard: refuse large batches unless env override is set
    if args.size > 200 and not os.getenv("ALLOW_LARGE_BATCH"):
        print(f"ERROR: Batch size {args.size} exceeds the POC limit of 200 donors.")
        print("Set ALLOW_LARGE_BATCH=true to override.")
        sys.exit(1)

    est_cost = args.size * COST_PER_DONOR_USD
    print(f"Estimated cost: ${est_cost:.2f} for {args.size} donors "
          f"(concurrency={args.concurrency})")

    if not args.yes and est_cost > 0.10:
        try:
            confirm = input("Proceed? (y/N): ")
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            sys.exit(0)
        if confirm.strip().lower() != "y":
            print("Aborted.")
            sys.exit(0)

    batch = asyncio.run(run_batch(
        batch_size=args.size,
        concurrency=args.concurrency,
    ))

    print(f"\n=== BATCH COMPLETE: {batch.batch_id} ===")
    print(f"  Pass:       {batch.pass_count}")
    print(f"  Quarantine: {batch.quarantine_count}")
    print(f"  Error:      {batch.error_count}")
    print(f"  Total cost: ${batch.total_cost_usd:.4f}")
    if batch.completed_at and batch.started_at:
        duration = (batch.completed_at - batch.started_at).total_seconds()
        print(f"  Duration:   {duration:.1f}s")


if __name__ == "__main__":
    main()
