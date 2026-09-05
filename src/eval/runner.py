"""Evaluation orchestrator: score emails and golden examples, persist results."""
from __future__ import annotations

import asyncio
import random
import time
import uuid
from datetime import datetime

from supabase import Client

from src.eval.dimensions import (
    ALL_DIMENSION_NAMES,
    score_block_attribution,
    score_brand_voice,
    score_claim_accuracy,
    score_donor_fact_correctness,
    score_faithfulness,
    score_length_readability,
    score_segment_fit,
    score_toxicity_sensitivity,
)
from src.eval.golden_set import load_golden_set
from src.eval.judge import LLMJudge
from src.eval.metrics import overall_verdict_confusion, precision_recall_on_golden
from src.llm.client import AnthropicClient
from src.schemas import (
    BatchEvalResult,
    ContentBlock,
    DimensionScore,
    Donor,
    EvalResult,
    GeneratedEmail,
    GoldenExample,
    GoldenSetResult,
)

# ---------------------------------------------------------------------------
# Batch evaluation (real emails from a pipeline run)
# ---------------------------------------------------------------------------


async def evaluate_email(
    email: GeneratedEmail,
    donor: Donor,
    selected_blocks: dict[str, ContentBlock],
    llm_client: AnthropicClient,
    db_client: Client | None = None,
    email_id: uuid.UUID | None = None,
    dimensions: list[str] | None = None,
) -> EvalResult:
    """Score one email on all (or a subset of) dimensions. Persist to eval_scores if db_client supplied."""
    return await asyncio.to_thread(
        _evaluate_sync,
        email, donor, selected_blocks, llm_client, db_client, email_id, None, dimensions,
    )


async def evaluate_example(
    example: GoldenExample,
    llm_client: AnthropicClient,
    db_client: Client | None = None,
) -> EvalResult:
    """Score one golden set example on all 8 dimensions."""
    return await asyncio.to_thread(
        _evaluate_sync,
        example.email, example.donor, example.selected_blocks,
        llm_client, db_client, None, example.example_id, None,
    )


async def evaluate_golden_set(
    llm_client: AnthropicClient,
    db_client: Client | None = None,
    concurrency: int = 1,
) -> GoldenSetResult:
    """Run all 8 dimensions on every golden example. Returns GoldenSetResult.

    concurrency=1 (default) is safe under API tier-1 rate limits (50k tokens/min).
    Each example makes 5 LLM calls × ~1k tokens = ~5k tokens; 50 examples total
    needs ~250k tokens. Sequential prevents burst rejections.
    Raise to 3 if on higher tiers.
    """
    examples = load_golden_set()
    sem = asyncio.Semaphore(concurrency)
    total_cost = 0.0

    async def _run_one(ex: GoldenExample) -> EvalResult:
        async with sem:
            return await asyncio.to_thread(
                _evaluate_sync,
                ex.email, ex.donor, ex.selected_blocks,
                llm_client, db_client, None, ex.example_id, None,
            )

    results: list[EvalResult] = await asyncio.gather(*[_run_one(ex) for ex in examples])

    for r in results:
        total_cost += r.total_cost_usd

    pr = precision_recall_on_golden(results, examples)
    confusion = overall_verdict_confusion(results, examples)

    return GoldenSetResult(
        total_examples=len(examples),
        per_dimension=pr,
        confusion_matrix=confusion,
        total_cost_usd=round(total_cost, 6),
    )


# ---------------------------------------------------------------------------
# Synchronous internals (run inside asyncio.to_thread)
# ---------------------------------------------------------------------------

def _evaluate_sync(
    email: GeneratedEmail,
    donor: Donor,
    selected_blocks: dict[str, ContentBlock],
    llm_client: AnthropicClient,
    db_client: Client | None,
    email_id: uuid.UUID | None,
    example_id: str | None,
    dimensions: list[str] | None,
) -> EvalResult:
    dims = dimensions or ALL_DIMENSION_NAMES
    judge = LLMJudge(llm_client)

    t0 = time.perf_counter()
    scores: list[DimensionScore] = []
    total_cost = 0.0

    for dim in dims:
        ds = _score_dimension(dim, email, donor, selected_blocks, judge)
        scores.append(ds)
        total_cost += ds.metadata.get("cost_usd", 0.0)

    total_latency_ms = int((time.perf_counter() - t0) * 1000)
    failed = [ds.dimension for ds in scores if not ds.passed]

    result = EvalResult(
        email_id=email_id,
        example_id=example_id,
        dimension_scores=scores,
        overall_passed=len(failed) == 0,
        failed_dimensions=failed,
        total_cost_usd=round(total_cost, 6),
        total_latency_ms=total_latency_ms,
    )

    if db_client is not None:
        _persist_eval_result(db_client, result)

    return result


def _score_dimension(
    dimension: str,
    email: GeneratedEmail,
    donor: Donor,
    selected_blocks: dict[str, ContentBlock],
    judge: LLMJudge,
) -> DimensionScore:
    if dimension == "block_attribution":
        return score_block_attribution(email, selected_blocks, donor)
    if dimension == "length_readability":
        return score_length_readability(email)
    if dimension == "donor_fact_correctness":
        return score_donor_fact_correctness(email, donor)
    if dimension == "faithfulness":
        return score_faithfulness(email, donor, selected_blocks, judge)
    if dimension == "claim_accuracy":
        return score_claim_accuracy(email, donor, selected_blocks, judge)
    if dimension == "brand_voice":
        return score_brand_voice(email, donor, selected_blocks, judge)
    if dimension == "toxicity_sensitivity":
        return score_toxicity_sensitivity(email, donor, selected_blocks, judge)
    if dimension == "segment_fit":
        return score_segment_fit(email, donor, selected_blocks, judge)
    raise ValueError(f"Unknown dimension: {dimension!r}")


def _persist_eval_result(db_client: Client, result: EvalResult) -> None:
    rows = [
        {
            "eval_id": str(uuid.uuid4()),
            "email_id": str(result.email_id) if result.email_id else None,
            "example_id": result.example_id,
            "dimension": ds.dimension,
            "score": float(ds.score),
            "passed": ds.passed,
            "threshold": float(ds.threshold),
            "reasoning": ds.reasoning,
            "judge_model": ds.judge_model,
            "metadata": ds.metadata,
            "evaluated_at": datetime.utcnow().isoformat(),
        }
        for ds in result.dimension_scores
    ]
    db_client.table("eval_scores").insert(rows).execute()


# ---------------------------------------------------------------------------
# Batch evaluation (real emails from a pipeline run)
# ---------------------------------------------------------------------------

async def evaluate_batch(
    batch_id: uuid.UUID,
    llm_client: AnthropicClient,
    db_client: Client | None = None,
    sample_rate: float = 1.0,
    concurrency: int = 1,
    persist: bool = True,
) -> BatchEvalResult:
    """Evaluate a sampled set of pass emails from a batch run.

    Fetches emails with status='pass', samples by sample_rate, scores all
    8 dimensions, persists to eval_scores (unless persist=False).
    Returns a BatchEvalResult with per-dimension stats.
    """
    from supabase import create_client
    from src import config
    from src.eval.metrics import per_dimension_stats

    if db_client is None:
        db_client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)

    email_rows = (
        db_client.table("generated_emails")
        .select("*")
        .eq("batch_id", str(batch_id))
        .eq("status", "pass")
        .execute()
        .data
    )

    total_emails = len(email_rows)

    if sample_rate < 1.0:
        n = max(1, int(total_emails * sample_rate))
        email_rows = random.sample(email_rows, n)

    emails_skipped = total_emails - len(email_rows)

    if not email_rows:
        return BatchEvalResult(
            batch_id=batch_id,
            emails_evaluated=0,
            emails_skipped=emails_skipped,
            per_dimension_stats={},
            overall_pass_rate=0.0,
            total_cost_usd=0.0,
        )

    donor_ids = list({r["donor_id"] for r in email_rows})
    donor_rows = (
        db_client.table("donors")
        .select("*")
        .in_("donor_id", donor_ids)
        .execute()
        .data
    )
    donor_map: dict[str, Donor] = {r["donor_id"]: _parse_donor(r) for r in donor_rows}

    all_block_ids: set[str] = {
        bid
        for r in email_rows
        for bid in (r["selected_block_ids"] if isinstance(r["selected_block_ids"], list) else [])
    }
    block_rows = (
        db_client.table("content_blocks")
        .select("*")
        .in_("block_id", list(all_block_ids))
        .execute()
        .data
        if all_block_ids
        else []
    )
    block_map: dict[str, ContentBlock] = {r["block_id"]: _parse_block(r) for r in block_rows}

    tasks = []
    for row in email_rows:
        donor = donor_map.get(row["donor_id"])
        if donor is None:
            continue

        email = GeneratedEmail.model_construct(
            subject=row["subject"] or "",
            body=row["body"] or "",
            tokens_used=[],
        )

        block_ids: list[str] = (
            row["selected_block_ids"]
            if isinstance(row["selected_block_ids"], list)
            else []
        )
        selected_blocks: dict[str, ContentBlock] = {
            block_map[bid].block_type: block_map[bid]
            for bid in block_ids
            if bid in block_map
        }

        tasks.append((email, donor, selected_blocks, uuid.UUID(row["email_id"])))

    sem = asyncio.Semaphore(concurrency)

    async def _run_one_eval(
        email: GeneratedEmail,
        donor: Donor,
        selected_blocks: dict[str, ContentBlock],
        email_id: uuid.UUID,
    ) -> EvalResult:
        async with sem:
            return await asyncio.to_thread(
                _evaluate_sync,
                email, donor, selected_blocks,
                llm_client,
                db_client if persist else None,
                email_id,
                None,
                None,
            )

    results: list[EvalResult] = await asyncio.gather(
        *[_run_one_eval(e, d, sb, eid) for e, d, sb, eid in tasks]
    )

    total_cost = sum(r.total_cost_usd for r in results)
    stats = per_dimension_stats(list(results))
    overall_pass_rate = (
        sum(1 for r in results if r.overall_passed) / len(results)
        if results
        else 0.0
    )

    return BatchEvalResult(
        batch_id=batch_id,
        emails_evaluated=len(results),
        emails_skipped=emails_skipped,
        per_dimension_stats=stats,
        overall_pass_rate=round(overall_pass_rate, 4),
        total_cost_usd=round(total_cost, 6),
    )


def _parse_donor(row: dict) -> Donor:
    """Reconstruct a Donor from a Supabase row dict."""
    return Donor.model_validate(row)


def _parse_block(row: dict) -> ContentBlock:
    """Reconstruct a ContentBlock from a Supabase row dict."""
    return ContentBlock.model_validate(row)
