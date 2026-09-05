#!/usr/bin/env python
"""
Supabase write access diagnostic.

Tests three scenarios:
  1. Sequential single writes (baseline)
  2. Concurrent writes from multiple threads sharing ONE client
  3. Concurrent writes with a SEPARATE client per thread

Run:  python scripts/test_supabase_writes.py
"""
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
from src.config import SUPABASE_URL, SUPABASE_KEY


BATCH_ID = str(uuid.uuid4())   # reused so test rows can be deleted together
N_THREADS = 5


def _make_audit_row(batch_id: str, label: str) -> dict:
    return {
        "audit_id": str(uuid.uuid4()),
        "batch_id": batch_id,
        "donor_hash": f"test_hash_{label}",
        "stage": "eligibility",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "input_summary": {"test": True, "label": label},
        "output": {"eligible": True},
    }


def _insert(client, batch_id: str, label: str) -> tuple[bool, str]:
    """Single insert; returns (success, error_message)."""
    try:
        row = _make_audit_row(batch_id, label)
        client.table("audit_log").insert(row).execute()
        return True, ""
    except Exception as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# Test 1: Sequential writes with one client
# ---------------------------------------------------------------------------

def test_sequential(n: int = 5) -> None:
    print(f"\n{'='*60}")
    print(f"TEST 1 — Sequential writes (n={n}, 1 shared client)")
    print(f"{'='*60}")
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    passed = 0
    for i in range(n):
        ok, err = _insert(client, BATCH_ID, f"seq_{i}")
        status = "OK" if ok else f"FAIL: {err[:80]}"
        print(f"  write {i+1:02d}: {status}")
        if ok:
            passed += 1
        time.sleep(0.05)
    print(f"  Result: {passed}/{n} succeeded")


# ---------------------------------------------------------------------------
# Test 2: Concurrent writes — ONE shared client (simulates batch runner bug)
# ---------------------------------------------------------------------------

def test_concurrent_shared_client(n: int = N_THREADS) -> None:
    print(f"\n{'='*60}")
    print(f"TEST 2 — Concurrent writes, ONE shared client (n={n} threads)")
    print(f"{'='*60}")
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    results: list[tuple[bool, str]] = [None] * n  # type: ignore[list-item]
    lock = threading.Lock()

    def worker(idx: int) -> None:
        ok, err = _insert(client, BATCH_ID, f"shared_{idx}")
        with lock:
            results[idx] = (ok, err)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    passed = sum(1 for ok, _ in results if ok)
    for i, (ok, err) in enumerate(results):
        status = "OK" if ok else f"FAIL: {err[:80]}"
        print(f"  thread {i+1}: {status}")
    print(f"  Result: {passed}/{n} succeeded")
    if passed < n:
        print(f"  *** SHARED CLIENT IS NOT THREAD-SAFE for concurrent writes ***")


# ---------------------------------------------------------------------------
# Test 3: Concurrent writes — SEPARATE client per thread (the fix)
# ---------------------------------------------------------------------------

def test_concurrent_per_thread_client(n: int = N_THREADS) -> None:
    print(f"\n{'='*60}")
    print(f"TEST 3 — Concurrent writes, separate client per thread (n={n} threads)")
    print(f"{'='*60}")
    results: list[tuple[bool, str]] = [None] * n  # type: ignore[list-item]
    lock = threading.Lock()

    def worker(idx: int) -> None:
        # Each thread creates its own client — separate HTTP connection pool
        thread_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        ok, err = _insert(thread_client, BATCH_ID, f"per_thread_{idx}")
        with lock:
            results[idx] = (ok, err)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    passed = sum(1 for ok, _ in results if ok)
    for i, (ok, err) in enumerate(results):
        status = "OK" if ok else f"FAIL: {err[:80]}"
        print(f"  thread {i+1}: {status}")
    print(f"  Result: {passed}/{n} succeeded")
    if passed == n:
        print(f"  *** PER-THREAD CLIENT WORKS — use this pattern in batch runner ***")


# ---------------------------------------------------------------------------
# Cleanup: remove test rows
# ---------------------------------------------------------------------------

def cleanup() -> None:
    print(f"\n{'='*60}")
    print("CLEANUP — removing test rows")
    print(f"{'='*60}")
    try:
        client = create_client(SUPABASE_URL, SUPABASE_KEY)
        res = client.table("audit_log").delete().eq("batch_id", BATCH_ID).execute()
        print(f"  Deleted test rows for batch_id={BATCH_ID[:8]}...")
    except Exception as exc:
        print(f"  Cleanup failed (rows left in DB): {exc}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"Supabase: {SUPABASE_URL[:40]}...")
    print(f"Test batch_id: {BATCH_ID[:8]}...")

    test_sequential()
    test_concurrent_shared_client()
    test_concurrent_per_thread_client()
    cleanup()

    print(f"\nDone.")
