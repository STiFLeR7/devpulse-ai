# core/bridge_api/gemini_client.py
from __future__ import annotations
import os
import asyncio
from typing import List, Dict, Any, Optional
import textwrap
import datetime
import logging

# Optional HTTP client import (only used if GEMINI_API_KEY is configured)
try:
    import httpx
except Exception:
    httpx = None

from app.settings import settings

_LOG = logging.getLogger(__name__)

# ---------- public helpers ----------

def gemini_is_active() -> bool:
    """
    Return True if an external Gemini-like API is available (based on env var presence).
    We still handle failures gracefully and fall back to the local summarizer.
    """
    key = getattr(settings, "GEMINI_API_KEY", None)
    return bool(key and str(key).strip())

def ping() -> str:
    """Simple local ping used by /debug/gemini/test"""
    return "PING"

# ---------- local (extractive) summarizer fallback ----------
def _local_summary_from_rows(rows: List[Dict[str, Any]], hours: int = 24, max_items: int = 6) -> str:
    """
    Fast, deterministic extractive summary:
    - Picks top-scored rows (rows are already ranked in store.top_digest)
    - Emits 1-line bullets describing the change (title + short summary_ai if available)
    - Adds a small top-line sentence with window/hours info.
    """
    if not rows:
        return ""

    top = rows[:max_items]
    bullets = []
    for r in top:
        title = r.get("title") or r.get("summary_ai") or r.get("url") or "(no title)"
        summary_ai = (r.get("summary_ai") or "").strip()
        if summary_ai and summary_ai not in title:
            bullets.append(f"{title} — {summary_ai}")
        else:
            bullets.append(title)

    head = f"In the last {hours} hour{'s' if hours != 1 else ''}, top updates: "
    body = "\n".join(f"- {b}" for b in bullets)
    return head + "\n" + body

# ---------- optional remote summarizer (Gemini) ----------
# NOTE: This is intentionally generic. If you want to wire a real Gemini / VertexAI endpoint,
# add the proper endpoint and auth headers here. We keep this optional and resilient.
async def _call_remote_gemini(prompt: str, model: str = "gemini-1.0") -> Optional[str]:
    """
    Attempt to call a remote Gemini-like API. If httpx is unavailable or an exception occurs,
    return None so caller falls back to the local summarizer.
    """
    if not httpx:
        _LOG.debug("httpx not installed — skipping remote Gemini call.")
        return None

    key = getattr(settings, "GEMINI_API_KEY", None)
    if not key:
        _LOG.debug("No GEMINI_API_KEY set — skipping remote Gemini call.")
        return None

    # Example placeholder: user must replace with their real endpoint & payload if desired.
    # This function attempts a POST to an assumed endpoint and parses a 'text' field in JSON.
    endpoint = os.environ.get("GEMINI_API_ENDPOINT", "").strip()
    if not endpoint:
        # no configured endpoint — avoid guessing; let local summarizer handle it
        _LOG.debug("No GEMINI_API_ENDPOINT configured — skipping remote call.")
        return None

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "prompt": prompt, "max_tokens": 512}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(endpoint, json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
            # parse typical reply structure: try a few common shapes
            if isinstance(data, dict):
                # look for text-like keys
                for k in ("text", "content", "output", "summary"):
                    if k in data and isinstance(data[k], str):
                        return data[k].strip()
                # nested choices variant
                choices = data.get("choices")
                if choices and isinstance(choices, list) and choices[0].get("text"):
                    return choices[0]["text"].strip()
            return None
    except Exception as e:
        _LOG.warning("remote gemini call failed: %s", e)
        return None

# ---------- top-level summarize_daily ----------

async def summarize_daily(rows: List[Dict[str, Any]], hours: int = 24) -> str:
    """
    Produce a short summary string for the daily digest.
    Strategy:
     1) If remote Gemini is configured (GEMINI_API_KEY + GEMINI_API_ENDPOINT), attempt a remote call.
     2) If remote call fails or not configured, fall back to a local extractive summary.
    """
    # Defensive: ensure rows is a list
    rows = list(rows or [])
    if not rows:
        return ""

    # Build a short prompt (compact) for remote LLM if available
    bullet_excerpt = []
    for r in rows[:10]:
        t = r.get("title") or ""
        s = r.get("summary_ai") or ""
        bullet_excerpt.append(f"{t} — {s}" if s else t)
    prompt_body = (
        "You are a concise summarizer. Produce a short (2-4 sentence) summary of the following list "
        f"of changes from the last {hours} hours. Emphasize significance and group related items where possible.\n\n"
        + "\n".join(f"- {l}" for l in bullet_excerpt)
        + "\n\nSummary:"
    )

    # Try remote if available
    if gemini_is_active():
        remote = await _call_remote_gemini(prompt_body)
        if remote:
            # Keep it short: truncate to ~500 chars safely
            return remote.strip()

    # Fallback local
    return _local_summary_from_rows(rows, hours=hours, max_items=6)

# expose sync wrapper if someone imports non-async
def summarize_daily_sync(rows: List[Dict[str, Any]], hours: int = 24) -> str:
    return asyncio.get_event_loop().run_until_complete(summarize_daily(rows, hours=hours))
