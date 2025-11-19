# backend/ingest/ingest_adapter.py
"""
Ingest adapter for writing to ingest_items_v2 in Supabase Postgres.

Environment variables:
 - SUPABASE_DB_URL : preferred Postgres connection string (postgresql://...)
 - DATABASE_URL    : fallback Postgres connection string
 - SUPABASE_URL    : HTTP Supabase URL (NOT used here except as a last-resort if it looks like a postgres URI)

Provides:
 - upsert_item_v2_sync(item)  -> blocking upsert
 - upsert_item_v2(item)       -> async wrapper (runs sync op in threadpool)
"""
from __future__ import annotations

import os
import re
import json
import asyncio
from typing import Dict, Any, Optional
from contextlib import contextmanager

import psycopg2
import psycopg2.extras

# >>> patch start: ensure adapter uses DB connection env without clobbering SUPABASE_URL used by REST
def _looks_like_postgres_uri(u: Optional[str]) -> bool:
    return bool(u and re.match(r'^(postgres|postgresql)://', u))

# Prefer explicit DB env var for Postgres; fall back to DATABASE_URL
DATABASE_URL = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")

# If still empty, only accept SUPABASE_URL if it *looks like* a postgres URI (defensive)
if not DATABASE_URL:
    maybe = os.getenv("SUPABASE_URL")
    if maybe and _looks_like_postgres_uri(maybe):
        DATABASE_URL = maybe

# If DATABASE_URL remains None, we handle it lazily at connection time (so other parts that use SUPABASE_URL won't break)
# >>> patch end

@contextmanager
def get_conn():
    if not DATABASE_URL:
        raise RuntimeError(
            "SUPABASE_DB_URL (or DATABASE_URL) env var not set for ingest_adapter. "
            "Set SUPABASE_DB_URL to the Postgres connection string (postgresql://...)."
        )
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    try:
        yield conn
    finally:
        conn.close()


def upsert_item_v2_sync(item: Dict[str, Any]) -> None:
    """
    Blocking upsert into ingest_items_v2.

    Expected item keys (best-effort):
      id, kind, title, url, domain, event_time (ISO string or None), inferred_time,
      score (numeric), tags (list or None), summary_ai (str), raw_json (dict),
      is_suspected_mock (bool), source (str)
    """
    if not DATABASE_URL:
        raise RuntimeError("SUPABASE_DB_URL is not configured for synchronous upsert")

    # Normalize tags: accept list or string
    tags = item.get("tags")
    if tags is None:
        tags_param = None
    elif isinstance(tags, list):
        tags_param = tags
    else:
        # try to parse newline or comma separated strings
        if isinstance(tags, str):
            parts = [t.strip() for t in tags.replace("\\n", "\n").splitlines() if t.strip()]
            if not parts:
                parts = [t.strip() for t in tags.split(",") if t.strip()]
            tags_param = parts or None
        else:
            tags_param = None

    raw_json = item.get("raw_json") or {}
    try:
        raw_text = json.dumps(raw_json)
    except Exception:
        raw_text = json.dumps({"_raw_repr": str(raw_json)})

    with get_conn() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.register_default_jsonb(conn)
            sql = """
            INSERT INTO ingest_items_v2
              (id, kind, title, url, domain, event_time, inferred_time, score, tags, summary_ai, raw, is_suspected_mock, source, created_at, updated_at)
            VALUES (%(id)s, %(kind)s, %(title)s, %(url)s, %(domain)s, %(event_time)s::timestamptz, %(inferred_time)s::timestamptz, %(score)s, %(tags)s, %(summary_ai)s, %(raw)s::jsonb, %(is_suspected_mock)s, %(source)s, now(), now())
            ON CONFLICT (id) DO UPDATE SET
              title = EXCLUDED.title,
              url = EXCLUDED.url,
              domain = EXCLUDED.domain,
              event_time = COALESCE(EXCLUDED.event_time, ingest_items_v2.event_time),
              inferred_time = COALESCE(EXCLUDED.inferred_time, ingest_items_v2.inferred_time),
              score = GREATEST(COALESCE(EXCLUDED.score,0), COALESCE(ingest_items_v2.score,0)),
              tags = COALESCE(EXCLUDED.tags, ingest_items_v2.tags),
              summary_ai = COALESCE(EXCLUDED.summary_ai, ingest_items_v2.summary_ai),
              raw = EXCLUDED.raw,
              is_suspected_mock = COALESCE(EXCLUDED.is_suspected_mock, ingest_items_v2.is_suspected_mock),
              source = COALESCE(EXCLUDED.source, ingest_items_v2.source),
              updated_at = now();
            """
            params = {
                "id": item.get("id"),
                "kind": item.get("kind"),
                "title": item.get("title"),
                "url": item.get("url"),
                "domain": item.get("domain"),
                "event_time": item.get("event_time"),
                "inferred_time": item.get("inferred_time"),
                "score": item.get("score"),
                "tags": tags_param,
                "summary_ai": item.get("summary_ai"),
                "raw": raw_text,
                "is_suspected_mock": bool(item.get("is_suspected_mock", False)),
                "source": item.get("source"),
            }
            cur.execute(sql, params)
        conn.commit()


async def upsert_item_v2(item: Dict[str, Any]) -> None:
    """
    Async wrapper: runs upsert_item_v2_sync in threadpool to avoid blocking async event loop.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, upsert_item_v2_sync, item)
