-- Migration 002: donor views
-- v_donor_profile — denormalized donor with derived eligibility fields
-- v_donor_segment_summary — monitoring aggregations by lifecycle/recency

create or replace view v_donor_profile as
select
    donor_id,
    donor_hash,
    first_name,
    email,
    center_name,
    weeks_since_last_donation,
    lifetime_donations,
    estimated_patients_helped,
    lifecycle_stage,
    recency_tier,
    deferral_status,
    deferral_until,
    consent_email,
    created_at,

    -- Eligible to receive email this batch
    (
        consent_email = true
        and deferral_status != 'permanently_deferred'
        and (deferral_status = 'eligible' or deferral_until <= now())
    ) as is_eligible_to_send,

    -- Days until temp deferral lifts; NULL when not temp_deferred
    case
        when deferral_status = 'temp_deferred' then
            (deferral_until - now()::date)
        else null
    end as days_until_eligible

from donors;


create or replace view v_donor_segment_summary as
select
    lifecycle_stage,
    recency_tier,
    count(*)                                   as donor_count,
    round(avg(lifetime_donations)::numeric, 2) as avg_lifetime_donations,
    round(avg(weeks_since_last_donation)::numeric, 2) as avg_weeks_since_last_donation,
    round(avg(estimated_patients_helped)::numeric, 2) as avg_patients_helped,
    count(*) filter (
        where consent_email = true
          and deferral_status != 'permanently_deferred'
          and (deferral_status = 'eligible' or deferral_until <= now())
    ) as eligible_count
from donors
group by lifecycle_stage, recency_tier
order by lifecycle_stage, recency_tier;