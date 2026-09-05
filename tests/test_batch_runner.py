"""
Unit tests for the async batch runner.

All LLM calls and Supabase writes are mocked.  Tests verify:
  - Correct BatchRun aggregation (pass/quarantine/error counts, total_cost_usd)
  - Error isolation: one crashing donor does not crash the batch
  - Concurrency semaphore actually limits parallel execution
  - Zero-donor batch returns gracefully
"""
from __future__ import annotations

import asyncio
import threading
import time
import uuid
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from src.schemas import BatchRun, Donor, ProcessResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PER_DONOR_COST = 0.005  # $0.005 matches empirical Haiku cost


def _make_donor(n: int) -> Donor:
    return Donor(
        donor_hash=f"hash_{n:04d}",
        first_name=f"Donor{n}",
        email=f"donor{n}@example.com",
        center_name="BioLife Bengaluru",
        weeks_since_last_donation=3,
        lifetime_donations=10,
        estimated_patients_helped=5,
        lifecycle_stage="regular",
        recency_tier="3-5wk",
    )


def _pass_result(donor: Donor) -> ProcessResult:
    return ProcessResult(
        donor_id=donor.donor_id,
        email_id=uuid.uuid4(),
        status="pass",
        total_cost_usd=_PER_DONOR_COST,
    )


def _mock_db() -> MagicMock:
    """Return a mock Supabase client whose chained builder methods all work."""
    db = MagicMock()
    # Chain: db.table(...).insert(...).execute() → all return MagicMocks
    db.table.return_value.insert.return_value.execute.return_value = MagicMock()
    db.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
    return db


def _patch_infrastructure(mock_db: MagicMock, donors: list[Donor]):
    """Return a list of context managers that patch all of run_batch's dependencies."""
    return [
        patch("src.pipeline.batch_runner.create_client", return_value=mock_db),
        patch("src.pipeline.batch_runner.DonorRepository") ,
        patch("src.pipeline.batch_runner.ContentBlockRepository"),
        patch("src.pipeline.batch_runner.AuditStore"),
        patch("src.pipeline.batch_runner.EmailStore"),
    ]


# ---------------------------------------------------------------------------
# Test 1: 10-donor batch, all pass
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_pass_batch():
    """10 donors all pass → BatchRun has correct counts and summed cost."""
    donors = [_make_donor(i) for i in range(10)]
    mock_db = _mock_db()

    def fake_process_donor(donor, *args, **kwargs) -> ProcessResult:
        return _pass_result(donor)

    with patch("src.pipeline.batch_runner.create_client", return_value=mock_db), \
         patch("src.pipeline.batch_runner.DonorRepository") as MockDonorRepo, \
         patch("src.pipeline.batch_runner.ContentBlockRepository"), \
         patch("src.pipeline.batch_runner.AuditStore"), \
         patch("src.pipeline.batch_runner.EmailStore"), \
         patch("src.pipeline.batch_runner.process_donor", side_effect=fake_process_donor):

        MockDonorRepo.return_value.get_eligible_donors.return_value = donors

        from src.pipeline.batch_runner import run_batch
        batch = await run_batch(batch_size=10, concurrency=5)

    assert isinstance(batch, BatchRun)
    assert batch.donor_count == 10
    assert batch.pass_count == 10
    assert batch.quarantine_count == 0
    assert batch.error_count == 0
    assert abs(batch.total_cost_usd - 10 * _PER_DONOR_COST) < 1e-9
    assert batch.completed_at is not None
    assert batch.batch_id is not None

    # batch_runs row was created (INSERT) and updated (UPDATE ... eq)
    assert mock_db.table.return_value.insert.called
    assert mock_db.table.return_value.update.called


# ---------------------------------------------------------------------------
# Test 2: 5-donor batch, 2 donors crash unexpectedly
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_error_donors_do_not_crash_batch():
    """2 out of 5 donors raise an exception; batch still completes with error_count=2."""
    donors = [_make_donor(i) for i in range(5)]
    mock_db = _mock_db()

    crash_ids = {donors[1].donor_id, donors[3].donor_id}

    def fake_process_donor(donor, *args, **kwargs) -> ProcessResult:
        if donor.donor_id in crash_ids:
            raise RuntimeError("simulated crash")
        return _pass_result(donor)

    with patch("src.pipeline.batch_runner.create_client", return_value=mock_db), \
         patch("src.pipeline.batch_runner.DonorRepository") as MockDonorRepo, \
         patch("src.pipeline.batch_runner.ContentBlockRepository"), \
         patch("src.pipeline.batch_runner.AuditStore"), \
         patch("src.pipeline.batch_runner.EmailStore"), \
         patch("src.pipeline.batch_runner.process_donor", side_effect=fake_process_donor):

        MockDonorRepo.return_value.get_eligible_donors.return_value = donors

        from src.pipeline.batch_runner import run_batch
        batch = await run_batch(batch_size=5, concurrency=5)

    assert batch.pass_count == 3
    assert batch.error_count == 2
    assert batch.quarantine_count == 0
    assert batch.donor_count == 5
    assert batch.completed_at is not None


# ---------------------------------------------------------------------------
# Test 3: Semaphore limits concurrency
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrency_semaphore_is_respected():
    """At most `max_concurrent` donors run simultaneously regardless of batch size."""
    max_concurrent = 3
    n_donors = 12
    donors = [_make_donor(i) for i in range(n_donors)]
    mock_db = _mock_db()

    running = 0
    max_seen = 0
    lock = threading.Lock()

    def slow_process_donor(donor, *args, **kwargs) -> ProcessResult:
        nonlocal running, max_seen
        with lock:
            running += 1
            max_seen = max(max_seen, running)
        time.sleep(0.02)  # 20 ms — enough for other tasks to start if semaphore leaks
        with lock:
            running -= 1
        return _pass_result(donor)

    with patch("src.pipeline.batch_runner.create_client", return_value=mock_db), \
         patch("src.pipeline.batch_runner.DonorRepository") as MockDonorRepo, \
         patch("src.pipeline.batch_runner.ContentBlockRepository"), \
         patch("src.pipeline.batch_runner.AuditStore"), \
         patch("src.pipeline.batch_runner.EmailStore"), \
         patch("src.pipeline.batch_runner.process_donor", side_effect=slow_process_donor):

        MockDonorRepo.return_value.get_eligible_donors.return_value = donors

        from src.pipeline.batch_runner import run_batch
        batch = await run_batch(batch_size=n_donors, concurrency=max_concurrent)

    assert batch.pass_count == n_donors
    assert max_seen <= max_concurrent, (
        f"Semaphore violated: {max_seen} ran simultaneously (limit={max_concurrent})"
    )


# ---------------------------------------------------------------------------
# Test 4: Zero-size batch returns gracefully
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_zero_size_batch_returns_gracefully():
    """batch_size=0 means no donors are processed; batch_runs row still created."""
    mock_db = _mock_db()

    with patch("src.pipeline.batch_runner.create_client", return_value=mock_db), \
         patch("src.pipeline.batch_runner.DonorRepository") as MockDonorRepo, \
         patch("src.pipeline.batch_runner.ContentBlockRepository"), \
         patch("src.pipeline.batch_runner.AuditStore"), \
         patch("src.pipeline.batch_runner.EmailStore"), \
         patch("src.pipeline.batch_runner.process_donor") as mock_pd:

        MockDonorRepo.return_value.get_eligible_donors.return_value = []

        from src.pipeline.batch_runner import run_batch
        batch = await run_batch(batch_size=0, concurrency=5)

    assert batch.donor_count == 0
    assert batch.pass_count == 0
    assert batch.quarantine_count == 0
    assert batch.error_count == 0
    assert batch.total_cost_usd == 0.0
    assert batch.completed_at is not None
    # process_donor must not have been called
    mock_pd.assert_not_called()
    # batch_runs INSERT still happened
    assert mock_db.table.return_value.insert.called
