-- 008_dashboard_views.sql: convenience views for the Streamlit dashboard.
-- Apply via Supabase SQL Editor after 001–007 are in place.

-- ---------------------------------------------------------------------------
-- v_batch_summary: one row per batch with duration and pass_rate
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_batch_summary AS
SELECT
    batch_id,
    started_at,
    completed_at,
    donor_count,
    pass_count,
    quarantine_count,
    error_count,
    total_cost_usd,
    EXTRACT(EPOCH FROM (completed_at - started_at))::int AS duration_seconds,
    CASE
        WHEN donor_count > 0
        THEN ROUND(pass_count::numeric / donor_count, 4)
        ELSE 0
    END AS pass_rate,
    model_versions,
    prompt_hashes,
    block_library_version
FROM batch_runs
ORDER BY started_at DESC;

-- ---------------------------------------------------------------------------
-- v_email_with_eval: generated_emails + aggregated eval scores per email
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_email_with_eval AS
SELECT
    ge.email_id,
    ge.batch_id,
    ge.donor_id,
    ge.status,
    ge.subject,
    ge.body,
    ge.selected_block_ids,
    ge.quarantine_reasons,
    ge.generated_at,
    ROUND(AVG(es.score)::numeric, 4)                          AS overall_eval_score,
    COUNT(CASE WHEN es.passed  THEN 1 END)                    AS dimensions_passed,
    COUNT(CASE WHEN NOT es.passed THEN 1 END)                 AS dimensions_failed,
    COUNT(es.eval_id)                                         AS dimensions_scored
FROM generated_emails ge
LEFT JOIN eval_scores es ON ge.email_id = es.email_id
GROUP BY
    ge.email_id, ge.batch_id, ge.donor_id, ge.status,
    ge.subject, ge.body, ge.selected_block_ids,
    ge.quarantine_reasons, ge.generated_at;

-- ---------------------------------------------------------------------------
-- v_block_usage: times each block was selected, across all batches
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_block_usage AS
SELECT
    block_id_text                       AS block_id,
    COUNT(*)                            AS usage_count,
    MAX(ge.generated_at)                AS last_used_at
FROM generated_emails ge,
     LATERAL jsonb_array_elements_text(ge.selected_block_ids) AS block_id_text
WHERE ge.status IN ('pass', 'quarantine')
GROUP BY block_id_text
ORDER BY usage_count DESC;

-- ---------------------------------------------------------------------------
-- v_segment_pass_rate: pass rate and mean eval score per (lifecycle, recency)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_segment_pass_rate AS
SELECT
    d.lifecycle_stage,
    d.recency_tier,
    COUNT(ge.email_id)                                                          AS donor_count,
    SUM(CASE WHEN ge.status = 'pass' THEN 1 ELSE 0 END)                        AS pass_count,
    ROUND(
        SUM(CASE WHEN ge.status = 'pass' THEN 1 ELSE 0 END)::numeric
        / NULLIF(COUNT(ge.email_id), 0),
        4
    )                                                                           AS pass_rate,
    ROUND(AVG(es_agg.mean_score)::numeric, 4)                                  AS mean_eval_score
FROM generated_emails ge
JOIN donors d ON ge.donor_id = d.donor_id
LEFT JOIN (
    SELECT email_id, AVG(score) AS mean_score
    FROM eval_scores
    GROUP BY email_id
) es_agg ON ge.email_id = es_agg.email_id
GROUP BY d.lifecycle_stage, d.recency_tier
ORDER BY d.lifecycle_stage, d.recency_tier;
