"""
Async batch runner: orchestrates the full pipeline for a batch of donors.

Concurrency is bounded by a semaphore (default 5 parallel LLM workflows).
process_donor() is synchronous (uses the blocking Anthropic SDK), so each
donor is dispatched via asyncio.to_thread() to avoid blocking the event loop.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from supabase import create_client
from tqdm.asyncio import tqdm as atqdm

from src import config
from src.audit.store import AuditStore, EmailStore, make_error_audit
from src.data.blocks import ContentBlockRepository
from src.data.donors import DonorRepository
from src.llm.client import AnthropicClient
from src.pipeline.orchestrator import process_donor
from src.schemas import BatchRun, ProcessResult

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _sha256_file(filename: str) -> str:
    text = (_PROMPTS_DIR / filename).read_text()
    return hashlib.sha256(text.encode()).hexdigest()


async def _run_one(
    donor,
    batch_id: uuid.UUID,
    semaphore: asyncio.Semaphore,
    llm_client: AnthropicClient,
    audit_store: AuditStore,
    email_store: EmailStore,
    block_repo: ContentBlockRepository,
) -> ProcessResult:
    """Wrap synchronous process_donor() for async dispatch.

    The semaphore caps parallel LLM calls.  Any uncaught exception from
    process_donor is caught here so one bad donor cannot crash the batch.

    A FRESH AnthropicClient is created per thread to avoid HTTP/2 stream
    collisions: the sync httpx.Client inside AnthropicClient is not safe for
    concurrent use across threads sharing the same connection pool.  Supabase
    clients are thread-safe and are shared.
    """
    async with semaphore:
        # One client per thread — separate HTTP/2 connection pool per donor
        thread_client = AnthropicClient(
            model=llm_client.model,
            api_key=config.ANTHROPIC_API_KEY,
            enable_prompt_caching=llm_client.enable_prompt_caching,
        )
        try:
            return await asyncio.to_thread(
                process_donor,
                donor, batch_id, thread_client, audit_store, email_store, block_repo,
            )
        except Exception as exc:
            logger.error("Unexpected crash for donor %s: %s", donor.donor_id, exc, exc_info=True)
            # Best-effort audit record for the crash
            try:
                audit_store.emit(
                    make_error_audit(batch_id, donor, "selection", f"unexpected: {str(exc)[:200]}")
                )
            except Exception:
                pass
            return ProcessResult(
                donor_id=donor.donor_id,
                status="error",
                quarantine_reasons=[f"unexpected: {str(exc)[:200]}"],
            )


async def run_batch(
    batch_size: int = 100,
    concurrency: int = 5,
    block_library_version: str = "v1.0",
    llm_client: Optional[AnthropicClient] = None,
) -> BatchRun:
    """
    Orchestrate a full donor messaging batch:

    1. Create batch_runs row (started_at, model_versions, prompt_hashes)
    2. Fetch eligible donors via DonorRepository.get_eligible_donors(limit=batch_size)
    3. Process donors concurrently, bounded by asyncio.Semaphore(concurrency)
    4. Update batch_runs (completed_at, pass/quarantine/error counts, total_cost_usd)
    5. Return final BatchRun

    Re-running with the same batch_id is safe at the DB level (no idempotency
    key enforced here — each call mints a fresh batch_id).
    """
    db = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
    donor_repo = DonorRepository(client=db)
    block_repo = ContentBlockRepository(client=db)
    audit_store = AuditStore(client=db)
    email_store = EmailStore(client=db)

    if llm_client is None:
        llm_client = AnthropicClient(
            model=config.ANTHROPIC_MODEL_SELECTION,
            api_key=config.ANTHROPIC_API_KEY,
        )

    batch_id = uuid.uuid4()
    started_at = datetime.now(timezone.utc)

    model_versions = {
        "selection": config.ANTHROPIC_MODEL_SELECTION,
        "assembly": config.ANTHROPIC_MODEL_ASSEMBLY,
    }
    prompt_hashes = {
        "selection_system": _sha256_file("selection_system.md"),
        "assembly_system": _sha256_file("assembly_system.md"),
    }

    # ------------------------------------------------------------------
    # Create batch_runs row (donor_count=0 until we know the actual count)
    # ------------------------------------------------------------------
    db.table("batch_runs").insert({
        "batch_id": str(batch_id),
        "started_at": started_at.isoformat(),
        "donor_count": 0,
        "pass_count": 0,
        "quarantine_count": 0,
        "error_count": 0,
        "model_versions": model_versions,
        "prompt_hashes": prompt_hashes,
        "block_library_version": block_library_version,
        "total_cost_usd": 0.0,
    }).execute()

    # ------------------------------------------------------------------
    # Fetch eligible donors
    # ------------------------------------------------------------------
    donors = donor_repo.get_eligible_donors(limit=batch_size) if batch_size > 0 else []
    donor_count = len(donors)
    logger.info("Batch %s — %d eligible donors fetched (limit=%d)", batch_id, donor_count, batch_size)

    if donor_count == 0:
        completed_at = datetime.now(timezone.utc)
        _finalize_batch(db, batch_id, donor_count, 0, 0, 0, 0.0)
        return BatchRun(
            batch_id=batch_id,
            started_at=started_at,
            completed_at=completed_at,
            donor_count=0,
            pass_count=0,
            quarantine_count=0,
            error_count=0,
            model_versions=model_versions,
            prompt_hashes=prompt_hashes,
            block_library_version=block_library_version,
            total_cost_usd=0.0,
        )

    # ------------------------------------------------------------------
    # Dispatch donors concurrently
    # ------------------------------------------------------------------
    semaphore = asyncio.Semaphore(concurrency)
    tasks = [
        _run_one(d, batch_id, semaphore, llm_client, audit_store, email_store, block_repo)
        for d in donors
    ]

    t0 = time.perf_counter()
    results: list[ProcessResult] = await atqdm.gather(
        *tasks,
        desc=f"batch {str(batch_id)[:8]}",
        total=donor_count,
    )
    elapsed = time.perf_counter() - t0

    # ------------------------------------------------------------------
    # Aggregate and persist final counts
    # ------------------------------------------------------------------
    pass_count = sum(1 for r in results if r.status == "pass")
    quarantine_count = sum(1 for r in results if r.status == "quarantine")
    error_count = sum(1 for r in results if r.status == "error")
    total_cost_usd = sum(r.total_cost_usd for r in results)

    _finalize_batch(db, batch_id, donor_count, pass_count, quarantine_count, error_count, total_cost_usd)

    completed_at = datetime.now(timezone.utc)

    print(
        f"\n[batch {str(batch_id)[:8]}] {donor_count} donors | "
        f"{elapsed:.1f}s | "
        f"pass={pass_count} quarantine={quarantine_count} error={error_count} | "
        f"${total_cost_usd:.4f}"
    )

    return BatchRun(
        batch_id=batch_id,
        started_at=started_at,
        completed_at=completed_at,
        donor_count=donor_count,
        pass_count=pass_count,
        quarantine_count=quarantine_count,
        error_count=error_count,
        model_versions=model_versions,
        prompt_hashes=prompt_hashes,
        block_library_version=block_library_version,
        total_cost_usd=total_cost_usd,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _finalize_batch(
    db,
    batch_id: uuid.UUID,
    donor_count: int,
    pass_count: int,
    quarantine_count: int,
    error_count: int,
    total_cost_usd: float,
) -> None:
    db.table("batch_runs").update({
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "donor_count": donor_count,
        "pass_count": pass_count,
        "quarantine_count": quarantine_count,
        "error_count": error_count,
        "total_cost_usd": float(total_cost_usd),
    }).eq("batch_id", str(batch_id)).execute()
