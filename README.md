# Personalised Messaging Engine POC

> **An AI-powered personalized messaging platform for large-scale Phrama company.**

A production-oriented prototype for generating **personalized, compliant, and auditable weekly emails** for a donor population of ~400,000 recipients.

The system uses donor history, lifecycle stage, engagement behavior, preferences, and impact interests to generate relevant messaging while enforcing deterministic guardrails, content controls, evaluation, and auditability.

### Business Problem

Organizations running large-scale donor programs often send broadly similar messages to large recipient populations. This creates an opportunity to improve:

* **Conversion** — encourage eligible donors to take the desired action
* **Retention** — strengthen long-term donor engagement
* **Donor experience** — make communication more relevant and meaningful
* **Operational efficiency** — automate personalized content generation at scale

The challenge is to introduce AI without sacrificing **control, compliance, privacy, consistency, or traceability**.

### Solution

This project explores an end-to-end architecture for:

**Donor Data → Segmentation → Content Selection → AI Generation → Guardrails → Evaluation → Audit Trail → Campaign Analytics**

Instead of allowing an LLM to generate unrestricted content, the system follows a **controlled generation approach**:

1. Identify eligible donors
2. Build a donor profile from structured attributes
3. Determine the appropriate communication segment
4. Retrieve/select approved content blocks
5. Generate a personalized email
6. Run deterministic compliance and safety guardrails
7. Evaluate generated content
8. Quarantine failed messages
9. Store complete lineage and audit information
10. Measure campaign outcomes and continuously improve the system

---

## Architecture

```text
                    ┌─────────────────────┐
                    │     Donor Data      │
                    │  History / Profile  │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │     Eligibility     │
                    │    & Segmentation   │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │  Content Retrieval  │
                    │ Approved MLR Blocks │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │   LLM Selection     │
                    │   & Personalization │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │   Email Assembly    │
                    │      via LLM        │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │     Guardrails      │
                    │ Rules + Compliance  │
                    └──────────┬──────────┘
                               │
                    ┌──────────┴──────────┐
                    ▼                     ▼
                 PASS                  QUARANTINE
                    │
                    ▼
            ┌───────────────────┐
            │ Evaluation / QA   │
            │ LLM Judge + Rules │
            └─────────┬─────────┘
                      │
                      ▼
            ┌───────────────────┐
            │ Audit & Lineage   │
            │ Full Traceability │
            └─────────┬─────────┘
                      │
                      ▼
            ┌───────────────────┐
            │ Campaign Delivery │
            │ & Measurement     │
            └───────────────────┘
```

### Production Architecture Context

The conceptual production architecture assumes:

* **Databricks** — donor data management, transformation, segmentation, and analytics
* **Salesforce** — donor engagement and campaign execution
* **AI generation layer** — controlled personalization and content generation
* **Guardrail/evaluation layer** — compliance, quality, and risk controls
* **Audit layer** — immutable lineage and traceability

This repository focuses primarily on the **AI generation, control, evaluation, audit, and prototype layers**.

---

## Key Design Principles

### 1. Controlled Personalization

The LLM does not receive unrestricted freedom to invent messaging.

Personalization is grounded in structured donor attributes and approved content blocks.

Examples of personalization signals include:

* Lifecycle stage
* Recency of donation
* Donation frequency
* Lifetime donations
* Engagement history
* Donor preferences
* Impact interests

### 2. Retrieval + Generation

Approved content blocks are stored separately from the generation layer.

The pipeline first identifies appropriate content candidates and then uses an LLM to select and assemble them into a personalized message.

This provides a balance between:

**Personalization ↔ Control**

### 3. Guardrails Before Delivery

Every generated message passes through deterministic checks before it can be delivered.

Messages can be:

* `PASS`
* `QUARANTINE`
* `ERROR`

A failed message is never silently sent.

### 4. Evaluation

Generated emails are evaluated across multiple dimensions using a combination of:

* Rule-based checks
* LLM-as-a-judge evaluation
* Golden-set validation
* Per-dimension metrics
* Agreement analysis

### 5. Auditability

The system maintains lineage across:

```text
Donor
  ↓
Donor Profile
  ↓
Selected Content Blocks
  ↓
Generated Email
  ↓
Guardrail Results
  ↓
Evaluation Scores
  ↓
Audit Event
```

This makes it possible to answer:

> **"Why did this donor receive this message?"**

---

# Business & Scale

The target use case is a **weekly campaign of approximately 400,000 recipients**.

The system therefore considers:

| Requirement             | Approach                                      |
| ----------------------- | --------------------------------------------- |
| ~400K weekly recipients | Async batch processing                        |
| Personalization         | Donor segmentation + profile-based generation |
| Cost control            | Smaller models / sampling for evaluation      |
| Latency                 | Concurrent batch execution                    |
| Content safety          | Deterministic guardrails                      |
| Compliance              | Approved content blocks + validation          |
| Quality                 | LLM judge + rule-based evaluation             |
| Traceability            | Append-only audit trail                       |
| Continuous improvement  | Golden set + campaign metrics                 |

The prototype can be run on smaller datasets while preserving the architectural patterns required for a much larger deployment.

---

# Evaluation Strategy

The system evaluates generated content across **8 dimensions** combining deterministic rules and LLM-based assessment.

The evaluation pipeline produces:

* Overall pass rate
* Per-dimension scores
* Failure distribution
* Segment-level performance
* Agreement matrix
* Golden-set precision/recall
* Cost per generated email
* Batch execution time

The goal is not simply to ask:

> "Does the email sound good?"

but rather:

> **"Is the email appropriate, compliant, personalized, and safe enough to be delivered?"**

---

# GxP / Compliance Considerations

Because the system generates externally-facing communications in a regulated environment, the architecture treats the LLM as a **controlled component rather than an autonomous decision-maker**.

Key considerations include:

### Auditability

Store:

* Input profile
* Selected content blocks
* Prompt/version information
* Generated content
* Guardrail results
* Evaluation results
* Final disposition

### Traceability

Every generated message should be traceable back to the donor attributes and approved content that influenced its generation.

### Change Control

Changes to:

* Prompts
* Models
* Guardrail rules
* Content blocks
* Evaluation criteria

should be versioned and validated before production use.

### Validation

A golden dataset is used to evaluate system behavior after significant changes.

### Human Oversight

Messages failing predefined controls are quarantined rather than automatically delivered.

---

# Cost Awareness

At ~400,000 recipients per weekly campaign, LLM cost becomes an important architectural constraint.

The prototype therefore considers:

* Pre-filtering content candidates before LLM calls
* Using smaller models where appropriate
* Separating content selection from generation
* Evaluating a sample of messages instead of every message when appropriate
* Batch/concurrent execution
* Tracking token usage and cost per email
* Comparing model tiers

The dashboard includes a **Cost Model** for estimating campaign-level economics.

---

# Setup

## Prerequisites

* Python 3.11+
* [uv](https://github.com/astral-sh/uv) (recommended) or pip
* Supabase project (free tier works for POC)

## 1. Clone and install

```bash
# Install base + dev dependencies
uv pip install -e ".[dev]"

# Or with pip
pip install -e ".[dev]"
```

## 2. Configure environment

```bash
cp .env.example .env
```

Fill in `.env`:

| Variable       | Description                                       |
| -------------- | ------------------------------------------------- |
| `SUPABASE_URL` | Your Supabase project URL                         |
| `SUPABASE_KEY` | Service role key                                  |
| `DONOR_SALT`   | Random string for hashing donor IDs in audit logs |
| `BATCH_SIZE`   | Donor batch size (default: 1000)                  |

## 3. Apply database migrations

Run migrations in order using the Supabase SQL Editor or `psql`.

```bash
psql "$SUPABASE_URL" -f migrations/001_donors.sql
```

## 4. Seed sample donor data

```bash
python -m src.data.seed
```

The seed script:

* Generates 1,000 synthetic donors
* Uses realistic, correlated distributions
* Inserts records in batches
* Prompts before truncating an existing dataset
* Prints a distribution summary

Example:

```text
Total donors: 1000

Lifecycle stage distribution:

  new:       200 (20.0%)
  regular:   400 (40.0%)
  champion:  150 (15.0%)
  at_risk:   150 (15.0%)
  lapsed:    100 (10.0%)
```

---

# Running Tests

```bash
pytest tests/
```

---

# Running the Demo

## Generate and evaluate a batch

```bash
# Full demo
python scripts/run_demo_batch.py --size 100 --yes

# Smaller smoke test
python scripts/run_demo_batch.py --size 20 --yes

# Custom evaluation sampling rate
python scripts/run_demo_batch.py \
    --size 100 \
    --eval-sample-rate 0.1 \
    --yes
```

The demo:

1. Selects eligible donors
2. Generates personalized emails
3. Applies guardrails
4. Evaluates passing emails
5. Produces batch-level metrics
6. Tracks execution cost and latency

---

# Dashboard

Launch the Streamlit dashboard:

```bash
pip install -e ".[dashboard,eval]"

streamlit run dashboard/app.py
```

Open:

```text
http://localhost:8501
```

### Dashboard Pages

| Page                | Description                                                                    |
| ------------------- | ------------------------------------------------------------------------------ |
| **Main**            | Campaign metrics, batch history, architecture                                  |
| **Batch Results**   | Pass/quarantine/error distribution, segment performance, latency               |
| **Eval Dimensions** | Evaluation distributions, statistics, agreement matrix, golden-set calibration |
| **Email Inspector** | Donor → content blocks → email → guardrails → audit trail                      |
| **Content Library** | Approved content blocks and usage analytics                                    |
| **Cost Model**      | Per-email cost, campaign projections, model comparison                         |

---

# Project Structure

```text
src/
  config.py                  # Environment variables and model configuration
  schemas.py                 # Pydantic v2 models

  data/
    seed.py                  # Generate + insert synthetic donors
    seed_blocks.py           # Insert approved content blocks

  pipeline/
    eligibility.py           # Deterministic donor eligibility filter
    prefilter.py             # Content candidate pre-filter
    selection.py             # LLM content selection
    assembly.py              # LLM email assembly
    orchestrator.py          # Single-donor pipeline
    batch_runner.py          # Async batch execution

  guardrails/
    rules.py                 # Individual rule checks
    engine.py                # Guardrail orchestration

  eval/
    dimensions.py             # Evaluation dimensions
    judge.py                  # LLM-as-a-judge
    runner.py                 # Email and batch evaluation
    metrics.py                # Evaluation metrics

  audit/
    store.py                  # Append-only audit + email storage

migrations/
  001_donors.sql
  002_donor_views.sql
  003_content_blocks.sql
  004_batch_runs.sql
  005_generated_emails.sql
  006_audit_log.sql
  007_eval_scores.sql
  008_dashboard_views.sql

scripts/
  run_demo_batch.py           # Generate + evaluate + summarize
  run_batch.py                # Generation only
  run_eval_golden.py          # Golden-set validation

dashboard/
  app.py                      # Streamlit application
  pages/                      # Dashboard pages

data/
  golden_set.json             # Hand-labelled evaluation examples

tests/
  # Pytest test suite
```

---

# Example Demo

```bash
python scripts/run_demo_batch.py \
    --size 50 \
    --concurrency 3 \
    --yes
```

Inspect the latest batch:

```sql
SELECT
    pass_count,
    quarantine_count,
    error_count,
    total_cost_usd
FROM batch_runs
ORDER BY started_at DESC
LIMIT 1;
```

Inspect generated emails:

```sql
SELECT
    donor_id,
    first_name,
    lifecycle_stage,
    recency_tier,
    lifetime_donations
FROM v_email_with_eval
WHERE status = 'pass'
  AND lifecycle_stage IN ('regular', 'champion')
  AND lifetime_donations BETWEEN 5 AND 30
LIMIT 5;
```

---

# Project Status

**Feature-complete prototype through Layer 7b.**

The project demonstrates the core patterns required to move from:

**LLM prototype → controlled AI system → production-oriented architecture**

with particular emphasis on **personalization, scale, evaluation, guardrails, cost, and auditability**.
