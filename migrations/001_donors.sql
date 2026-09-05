-- Migration 001: donors table
-- Stores plasma donor profiles. PII is minimal by design: only first_name is kept.
-- donor_id is never written to audit_log; use donor_hash instead.

create extension if not exists "pgcrypto";

create table if not exists donors (
    donor_id                  uuid primary key default gen_random_uuid(),
    donor_hash                text unique not null,
    first_name                text not null,
    email                     text not null,
    center_name               text not null,
    weeks_since_last_donation integer not null check (weeks_since_last_donation >= 0),
    lifetime_donations        integer not null check (lifetime_donations >= 0),
    estimated_patients_helped integer not null check (estimated_patients_helped >= 0),
    lifecycle_stage           text not null check (
                                  lifecycle_stage in ('new', 'regular', 'champion', 'at_risk', 'lapsed')
                              ),
    recency_tier              text not null check (
                                  recency_tier in ('0-2wk', '3-5wk', '6-10wk', '11-20wk', '20wk+')
                              ),
    deferral_status           text not null default 'eligible' check (
                                  deferral_status in ('eligible', 'temp_deferred', 'permanently_deferred')
                              ),
    deferral_until            date,
    consent_email             boolean not null default true,
    created_at                timestamptz not null default now()
);

-- Index for eligibility filter (most frequent query pattern)
create index if not exists idx_donors_eligibility
    on donors (deferral_status, consent_email);

-- Index for lifecycle segmentation queries
create index if not exists idx_donors_lifecycle
    on donors (lifecycle_stage, recency_tier);
