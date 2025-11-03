-- Users
create table if not exists users (
    id uuid primary key default gen_random_uuid(),
    email text unique,
    created_at timestamptz not null default now()
);

-- Source registry (GitHub repo, HF namespace, RSS feed)
create table if not exists sources (
    id bigint generated always as identity primary key,
    kind source_kind not null,
    name text not null,
    url text not null,
    weight real not null default 1.0,
    enabled boolean not null default true,
    created_at timestamptz not null default now(),
    unique(kind, url)
);

-- Raw feed items
create table if not exists items (
    id bigint generated always as identity primary key,
    source_id bigint not null references sources(id) on delete cascade,
    kind source_kind not null,
    origin_id text not null,              -- unique pointer (repo@sha, hf:model, rss guid)
    title text,
    url text not null,
    author text,
    summary_raw text,
    event_time timestamptz,
    status item_status not null default 'new',
    stars_delta int default 0,
    created_at timestamptz not null default now(),
    unique(kind, origin_id)
);

-- Enriched layer for LLM output + embeddings
create table if not exists item_enriched (
    item_id bigint primary key references items(id) on delete cascade,
    summary_ai text,
    tags text[],
    keywords text[],
    embedding vector(768),
    score real not null default 0.0,
    metadata jsonb default '{}'::jsonb,
    updated_at timestamptz not null default now()
);

-- Automation events triggered by high-score items
create table if not exists automations (
    id bigint generated always as identity primary key,
    item_id bigint not null references items(id) on delete cascade,
    trigger trigger_kind not null,
    endpoint text not null,
    payload jsonb not null,
    fired_at timestamptz not null default now()
);

-- User preferences for filtering
create table if not exists user_prefs (
    user_id uuid primary key references users(id) on delete cascade,
    min_score real not null default 0.65,
    include_tags text[] default null,
    exclude_tags text[] default null
);
