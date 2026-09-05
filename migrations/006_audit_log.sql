-- Layer 5: audit_log table
-- Immutable append-only ledger for every pipeline decision.
-- The UPDATE/DELETE trigger is the GxP-aligned control that makes this table tamper-proof.

CREATE TABLE IF NOT EXISTS audit_log (
    audit_id        uuid PRIMARY KEY,
    batch_id        uuid NOT NULL,
    donor_hash      text NOT NULL,
    stage           text NOT NULL CHECK (stage IN
                        ('eligibility', 'prefilter', 'selection', 'assembly', 'guardrail')),
    timestamp_utc   timestamptz NOT NULL DEFAULT NOW(),
    model_version   text,
    prompt_hash     text,
    input_summary   jsonb,
    output          jsonb,
    verdict         text,
    failure_reasons jsonb,
    latency_ms      int,
    token_usage     jsonb,
    cost_usd        numeric(10, 6)
);

CREATE INDEX IF NOT EXISTS idx_audit_log_batch_stage
    ON audit_log (batch_id, stage);

CREATE INDEX IF NOT EXISTS idx_audit_log_donor_hash
    ON audit_log (donor_hash);

-- Append-only enforcement: any UPDATE or DELETE raises an exception.
-- This is the GxP play — every decision is permanently on record.
CREATE OR REPLACE FUNCTION prevent_audit_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only: % is not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_log_immutable ON audit_log;
CREATE TRIGGER audit_log_immutable
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION prevent_audit_modification();
