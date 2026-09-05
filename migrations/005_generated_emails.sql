-- Layer 5: generated_emails table
-- Stores every email output (pass or quarantine) for inspection and audit.
-- Requires: 001_donors.sql, 004_batch_runs.sql applied first.

CREATE TABLE IF NOT EXISTS generated_emails (
    email_id           uuid PRIMARY KEY,
    batch_id           uuid NOT NULL REFERENCES batch_runs(batch_id),
    donor_id           uuid NOT NULL REFERENCES donors(donor_id),
    subject            text,
    body               text,
    selected_block_ids jsonb NOT NULL,
    status             text NOT NULL CHECK (status IN ('pass', 'quarantine', 'error')),
    quarantine_reasons jsonb,
    generated_at       timestamptz NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_generated_emails_batch_status
    ON generated_emails (batch_id, status);
