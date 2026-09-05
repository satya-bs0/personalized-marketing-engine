from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


LifecycleStage = Literal["new", "regular", "champion", "at_risk", "lapsed"]
RecencyTier = Literal["0-2wk", "3-5wk", "6-10wk", "11-20wk", "20wk+"]
DeferralStatus = Literal["eligible", "temp_deferred", "permanently_deferred"]
BlockType = Literal["subject", "opener", "impact", "social_proof", "cta", "signoff"]
BlockStatus = Literal["draft", "approved", "deprecated"]

ALLOWED_SAFE_TOKENS = frozenset(
    {"first_name", "weeks_since_last_donation", "lifetime_donations",
     "estimated_patients_helped", "center_name"}
)


class Donor(BaseModel):
    donor_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    donor_hash: str
    first_name: str
    email: str
    center_name: str
    weeks_since_last_donation: int = Field(ge=0)
    lifetime_donations: int = Field(ge=0)
    estimated_patients_helped: int = Field(ge=0)
    lifecycle_stage: LifecycleStage
    recency_tier: RecencyTier
    deferral_status: DeferralStatus = "eligible"
    deferral_until: Optional[date] = None
    consent_email: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("deferral_until")
    @classmethod
    def deferral_until_only_when_temp(
        cls, v: Optional[date], info: any
    ) -> Optional[date]:
        status = info.data.get("deferral_status")
        if status == "temp_deferred" and v is None:
            raise ValueError("deferral_until must be set when deferral_status is temp_deferred")
        if status != "temp_deferred" and v is not None:
            raise ValueError("deferral_until must be null unless deferral_status is temp_deferred")
        return v

    def to_db_dict(self) -> dict:
        """Return a plain dict suitable for Supabase insert (no datetime objects)."""
        d = self.model_dump()
        d["donor_id"] = str(d["donor_id"])
        d["created_at"] = d["created_at"].isoformat()
        if d["deferral_until"] is not None:
            d["deferral_until"] = d["deferral_until"].isoformat()
        return d


class ContentBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    block_id: str
    block_type: BlockType
    version: int = Field(ge=1)
    approved_text: str
    safe_tokens: list[str]
    segment_fit: dict[str, list[str]]
    mlr_approval_id: str
    mlr_approved_at: datetime
    status: BlockStatus = "approved"
    forbidden_modifications: list[str]
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @model_validator(mode="after")
    def tokens_match_safe_list(self) -> "ContentBlock":
        tokens_in_text = set(re.findall(r"\{(\w+)\}", self.approved_text))
        bad = tokens_in_text - set(self.safe_tokens)
        if bad:
            raise ValueError(f"Tokens in approved_text not in safe_tokens: {bad}")
        disallowed = set(self.safe_tokens) - ALLOWED_SAFE_TOKENS
        if disallowed:
            raise ValueError(f"safe_tokens contains unsupported tokens: {disallowed}")
        return self

    def to_db_dict(self) -> dict:
        d = self.model_dump()
        d["mlr_approved_at"] = d["mlr_approved_at"].isoformat()
        d["created_at"] = d["created_at"].isoformat()
        return d


class LLMResponse(BaseModel):
    """Telemetry envelope returned by every AnthropicClient.call()."""
    tool_input: dict
    input_tokens: int
    output_tokens: int
    latency_ms: int
    model: str
    prompt_hash: str       # sha256(system + user) — enables prompt reproducibility audit
    raw_response_id: str   # Anthropic message ID for traceability
    cache_creation_input_tokens: int = 0   # tokens written to cache (first call)
    cache_read_input_tokens: int = 0       # tokens served from cache (subsequent calls)


class BlockSelection(BaseModel):
    """Stage 1 output: one approved block ID per email slot."""
    subject_block_id: str
    opener_block_id: str
    impact_block_id: str
    social_proof_block_id: str
    cta_block_id: str
    signoff_block_id: str
    selection_reasoning: str = Field(max_length=500)


class GeneratedEmail(BaseModel):
    """Stage 2 output: assembled email ready for guardrail checks."""
    subject: str = Field(max_length=80)
    body: str
    tokens_used: list[str]

    @model_validator(mode="after")
    def body_word_count(self) -> "GeneratedEmail":
        word_count = len(self.body.split())
        if word_count > 500:
            raise ValueError(f"Email body exceeds 500 words ({word_count} words)")
        return self


# ---------------------------------------------------------------------------
# Layer 5: Compliance & Guardrails
# ---------------------------------------------------------------------------

class BatchRun(BaseModel):
    """Metadata for one pipeline batch run."""
    batch_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    donor_count: int = 0
    pass_count: int = 0
    quarantine_count: int = 0
    error_count: int = 0
    model_versions: dict = Field(default_factory=dict)
    prompt_hashes: dict = Field(default_factory=dict)
    block_library_version: str = "1.0"
    total_cost_usd: float = 0.0


class GuardrailCheck(BaseModel):
    """Result of one individual guardrail rule."""
    check_name: str
    passed: bool
    reason: Optional[str] = None       # populated only when passed=False
    metadata: dict = Field(default_factory=dict)


class GuardrailResult(BaseModel):
    """Aggregated result of running all 8 guardrail checks."""
    verdict: Literal["pass", "fail"]
    checks: list[GuardrailCheck]

    @property
    def failure_reasons(self) -> list[str]:
        return [c.check_name for c in self.checks if not c.passed]


class AuditLog(BaseModel):
    """One row in the audit_log table — immutable once emitted."""
    audit_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    batch_id: uuid.UUID
    donor_hash: str          # SHA-256(donor_id + DONOR_SALT) — never raw donor_id
    stage: Literal["eligibility", "prefilter", "selection", "assembly", "guardrail"]
    timestamp_utc: datetime = Field(default_factory=datetime.utcnow)
    model_version: Optional[str] = None
    prompt_hash: Optional[str] = None
    input_summary: dict = Field(default_factory=dict)
    output: dict = Field(default_factory=dict)
    verdict: Optional[str] = None
    failure_reasons: Optional[list[str]] = None
    latency_ms: Optional[int] = None
    token_usage: Optional[dict] = None
    cost_usd: Optional[float] = None


class ProcessResult(BaseModel):
    """Outcome for one donor passing through the full pipeline."""
    donor_id: uuid.UUID
    email_id: Optional[uuid.UUID] = None
    status: Literal["pass", "quarantine", "error"]
    quarantine_reasons: list[str] = Field(default_factory=list)
    email: Optional[GeneratedEmail] = None
    selected_blocks: Optional[BlockSelection] = None
    total_cost_usd: float = 0.0
    total_latency_ms: int = 0


# ---------------------------------------------------------------------------
# Layer 7: Evaluation Framework
# ---------------------------------------------------------------------------

class DimensionScore(BaseModel):
    """Score for one evaluation dimension."""
    dimension: str
    score: float = Field(ge=0.0, le=1.0)
    passed: bool
    threshold: float
    reasoning: Optional[str] = None    # populated for LLM-judged dimensions
    judge_model: Optional[str] = None  # populated for LLM-judged dimensions
    metadata: dict = Field(default_factory=dict)


class EvalResult(BaseModel):
    """Aggregated evaluation result for one email or golden example."""
    email_id: Optional[uuid.UUID] = None    # null for golden set examples
    example_id: Optional[str] = None        # null for real emails
    dimension_scores: list[DimensionScore]
    overall_passed: bool                    # True iff ALL dimensions passed
    failed_dimensions: list[str]
    total_cost_usd: float = 0.0
    total_latency_ms: int = 0


class GoldenExample(BaseModel):
    """One hand-labeled evaluation example from the golden set."""
    example_id: str
    notes: str                              # what this example tests
    donor: Donor
    email: GeneratedEmail
    selected_blocks: dict[str, ContentBlock]
    expected_verdict: Literal["pass", "fail"]
    expected_failures: list[str] = Field(default_factory=list)  # dimension names


class GoldenSetResult(BaseModel):
    """Aggregated precision/recall results for the full golden set evaluation."""
    total_examples: int
    per_dimension: dict    # {dimension: {precision, recall, f1, support, tp, fp, fn, tn}}
    confusion_matrix: dict # overall verdict agreement
    total_cost_usd: float


class BatchEvalResult(BaseModel):
    """Aggregated eval results for a production batch."""
    batch_id: uuid.UUID
    emails_evaluated: int
    emails_skipped: int    # excluded by sampling
    per_dimension_stats: dict  # {dimension: {mean, median, std, p5, p95, pass_rate}}
    overall_pass_rate: float
    total_cost_usd: float
    eval_vs_guardrail_agreement: Optional[dict] = None
