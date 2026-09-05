-- Migration 003: content_blocks table
-- Stores the approved content block library. All LLM-generated emails must be
-- assembled exclusively from blocks in this table (status = 'approved').

create table if not exists content_blocks (
    block_id              text        primary key,
    block_type            text        not null
                              check (block_type in ('subject', 'opener', 'impact', 'social_proof', 'cta', 'signoff')),
    version               int         not null check (version >= 1),
    approved_text         text        not null,
    safe_tokens           jsonb       not null default '[]',
    segment_fit           jsonb       not null default '{}',
    mlr_approval_id       text        not null,
    mlr_approved_at       timestamptz not null,
    status                text        not null default 'approved'
                              check (status in ('draft', 'approved', 'deprecated')),
    forbidden_modifications jsonb     not null default '["paraphrase", "rewrite", "expand"]',
    created_at            timestamptz not null default now()
);

-- Efficient lookup by type + status (the most common query pattern)
create index if not exists idx_content_blocks_type_status
    on content_blocks (block_type, status);

-- GIN index for JSONB containment queries on segment_fit
create index if not exists idx_content_blocks_segment_fit
    on content_blocks using gin (segment_fit);
