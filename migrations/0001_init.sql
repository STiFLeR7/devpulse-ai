-- Enable required extensions
create extension if not exists vector;
create extension if not exists pgcrypto;

-- Source type (GitHub, HuggingFace, RSS)
do $$ begin
    create type source_kind as enum ('github', 'huggingface', 'rss');
exception when duplicate_object then null; end $$;

-- Item processing state
do $$ begin
    create type item_status as enum ('new', 'enriched', 'published', 'discarded');
exception when duplicate_object then null; end $$;

-- Trigger type
do $$ begin
    create type trigger_kind as enum ('n8n_webhook', 'agentlightning');
exception when duplicate_object then null; end $$;
