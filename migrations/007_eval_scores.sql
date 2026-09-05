-- eval_scores: one row per (email|example, dimension) evaluation result.
-- email_id XOR example_id: real emails link to generated_emails; golden set
-- examples use example_id only.

CREATE TABLE IF NOT EXISTS eval_scores (
    eval_id       UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    email_id      UUID         REFERENCES generated_emails(email_id) ON DELETE CASCADE,
    example_id    TEXT,
    batch_id      UUID         REFERENCES batch_runs(batch_id) ON DELETE SET NULL,
    dimension     TEXT         NOT NULL CHECK (dimension IN (
                                   'faithfulness',
                                   'claim_accuracy',
                                   'brand_voice',
                                   'toxicity_sensitivity',
                                   'segment_fit',
                                   'block_attribution',
                                   'length_readability',
                                   'donor_fact_correctness'
                               )),
    score         NUMERIC(5,4) NOT NULL CHECK (score >= 0 AND score <= 1),
    passed        BOOLEAN      NOT NULL,
    threshold     NUMERIC(5,4) NOT NULL,
    reasoning     TEXT,
    judge_model   TEXT,
    metadata      JSONB        NOT NULL DEFAULT '{}'::jsonb,
    evaluated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),

    -- Exactly one of email_id / example_id must be set
    CONSTRAINT eval_scores_source_check CHECK (
        (email_id IS NOT NULL AND example_id IS NULL)
        OR (email_id IS NULL AND example_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_eval_scores_email_id
    ON eval_scores (email_id);
CREATE INDEX IF NOT EXISTS idx_eval_scores_example_id
    ON eval_scores (example_id);
CREATE INDEX IF NOT EXISTS idx_eval_scores_batch_id
    ON eval_scores (batch_id);
CREATE INDEX IF NOT EXISTS idx_eval_scores_dimension
    ON eval_scores (dimension);
