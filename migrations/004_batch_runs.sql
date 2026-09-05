-- Layer 5: batch_runs table
-- Tracks each batch run's outcomes, model versions, and prompt hashes for reproducibility.

CREATE TABLE IF NOT EXISTS batch_runs (
    batch_id              uuid PRIMARY KEY,
    started_at            timestamptz NOT NULL DEFAULT NOW(),
    completed_at          timestamptz,
    donor_count           int NOT NULL DEFAULT 0,
    pass_count            int NOT NULL DEFAULT 0,
    quarantine_count      int NOT NULL DEFAULT 0,
    error_count           int NOT NULL DEFAULT 0,
    model_versions        jsonb NOT NULL,
    prompt_hashes         jsonb NOT NULL,
    block_library_version text NOT NULL,
    total_cost_usd        numeric(10, 4) DEFAULT 0
);
