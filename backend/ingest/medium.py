# backend/ingest/medium.py
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
import re
import html
import random

import httpx

try:
    import feedparser  # pip install feedparser
except Exception:
    feedparser = None  # we'll report a diagnostic if missing

from backend.store_factory import get_store

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0 Safari/537.36"
)

TIMEOUT = httpx.Timeout(15.0, connect=10.0, read=10.0, write=10.0)
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# ---------------- utils ----------------


def _dt_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _safe_event_time_from_feed(entry: Dict[str, Any]) -> Optional[datetime]:
    """
    Try multiple sources: published/updated/parsing hints.
    """
    # feedparser maps: published, published_parsed, updated, updated_parsed
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            try:
                # t is time.struct_time
                dt = datetime(*t[:6], tzinfo=timezone.utc)
                return dt
            except Exception:
                pass
    for key in ("published", "updated", "created"):
        raw = entry.get(key)
        if raw and isinstance(raw, str):
            try:
                from email.utils import parsedate_to_datetime

                dt = parsedate_to_datetime(raw)
                return _dt_utc(dt)
            except Exception:
                pass
    return None


def _normalize_url(url: str) -> str:
    # strip tracking/query parts and html fragments
    if not url:
        return url
    url = url.split("?")[0].split("#")[0].strip()
    return url


def _mk_origin_id(url: str, published: Optional[datetime]) -> str:
    # Stable unique id for upsert: url + yyyymmddHHMMSS (or na)
    stamp = published.strftime("%Y%m%d%H%M%S") if published else "na"
    # keep origin id short but unique-ish
    safe = re.sub(r"[^0-9A-Za-z\-_.:/]", "_", url)[:200]
    return f"medium:{safe}::{stamp}"


def _clean_text(s: Optional[str]) -> str:
    if not s:
        return ""
    # feedparser summary can include encoded entities or tags
    text = html.unescape(s)
    # strip html tags lightly
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ------------- fetch/parse -------------


async def _fetch_rss(url: str) -> Dict[str, Any]:
    """
    1) Try URL directly as RSS.
    2) If parsed entries == 0, GET HTML and auto-discover <link rel="alternate" type="application/rss+xml">,
       then fetch that RSS.
    3) Return diagnostics-friendly dict.
    """
    if feedparser is None:
        return {"__error__": "feedparser package not installed"}

    async with httpx.AsyncClient(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True) as client:
        try:
            r = await client.get(url)
            r.raise_for_status()
        except Exception as e:
            return {"__error__": f"fetch_failed: {e}", "__src__": url}

        txt = r.text
        fp = feedparser.parse(txt)
        if getattr(fp, "entries", None):
            return {"feed": fp.feed, "entries": fp.entries, "__raw__": f"len={len(txt)}", "__src__": url}

        # pass 2: discover RSS link from HTML <head>
        try:
            m = re.search(
                r'<link[^>]+rel=["\']alternate["\'][^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]+href=["\']([^"\']+)["\']',
                txt,
                re.I,
            )
            if m:
                rss_url = m.group(1)
                # make absolute if needed
                if rss_url.startswith("//"):
                    rss_url = "https:" + rss_url
                if rss_url.startswith("/"):
                    base = re.match(r"^https?://[^/]+", url)
                    if base:
                        rss_url = base.group(0) + rss_url
                try:
                    r2 = await client.get(rss_url)
                    r2.raise_for_status()
                    txt2 = r2.text
                    fp2 = feedparser.parse(txt2)
                    return {
                        "feed": getattr(fp2, "feed", {}),
                        "entries": getattr(fp2, "entries", []),
                        "__raw__": f"len={len(txt2)} (discovered)",
                        "__src__": rss_url,
                    }
                except Exception as e2:
                    return {"__error__": f"discovery_failed: {e2}", "__src__": rss_url}
        except Exception:
            pass

    return {"feed": {}, "entries": [], "__raw__": f"len={len(txt)} (no entries)", "__src__": url}


def _posts_from_rss(fp: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not fp or "entries" not in fp:
        return []

    out: List[Dict[str, Any]] = []
    for e in fp["entries"]:
        title = _clean_text(e.get("title") or "")
        link = _normalize_url(e.get("link") or "")
        if not title or not link:
            continue
        author = e.get("author") or (e.get("authors")[0]["name"] if e.get("authors") else None)
        summary = _clean_text(e.get("summary") or e.get("description") or "")
        when = _safe_event_time_from_feed(e) or _now_utc()

        out.append(
            {
                "title": title,
                "url": link,
                "author": author or "",
                "summary": summary,
                "event_time": when,
                "origin_id": _mk_origin_id(link, when),
            }
        )
    # reverse chrono
    out.sort(key=lambda x: x["event_time"], reverse=True)
    return out


# ------------- public API --------------

@dataclass
class PeekResult:
    sample: List[Dict[str, Any]]
    diagnostics: List[Dict[str, Any]]


async def peek_medium(feeds: List[str], hours: int = 720, limit: int = 10) -> PeekResult:
    """
    Fetch (without inserting) and return small samples + diagnostics.
    """
    diags: List[Dict[str, Any]] = []
    samples: List[Dict[str, Any]] = []

    for f in feeds:
        if f.startswith("http"):
            rss_url = f
        else:
            handle = f.replace("https://medium.com/", "").strip("/").lstrip("@")
            rss_url = f"https://medium.com/feed/@{handle}"

        try:
            rs = await _fetch_rss(rss_url)
            if "__error__" in rs:
                diags.append({"feed": f, "url": rss_url, "error": rs["__error__"]})
                continue
            posts = _posts_from_rss(rs)
            diags.append(
                {
                    "feed": f,
                    "url": rss_url,
                    "n_entries": len(rs.get("entries") or []),
                    "n_posts_parsed": len(posts),
                    "raw": rs.get("__raw__"),
                }
            )
            samples.extend(posts[: max(0, int(limit))])
        except Exception as e:
            diags.append({"feed": f, "url": rss_url, "error": str(e)})

    samples = samples[: max(0, int(limit))]
    return PeekResult(sample=samples, diagnostics=diags)


# ----- enrichment helpers (inlined to keep dependency small) -----


def _compute_tags_and_score(title: str, url: str, author: str, summary: str) -> (List[str], float, str):
    """
    Heuristic tags + baseline score for blog posts so they appear in digest.
    Returns (tags, score, short_summary).
    """
    tags: List[str] = ["Blog"]
    lu = (title + " " + (author or "") + " " + summary).lower()

    # source hints
    if "huggingface" in url or "huggingface" in author.lower():
        tags += ["HF"]
    if "openai.com" in url or "openai" in author.lower():
        tags += ["OpenAI"]
    if "ai.googleblog.com" in url or "google" in author.lower():
        tags += ["GoogleAI"]
    if "facebook" in url or "meta" in author.lower():
        tags += ["MetaAI"]

    # topic hints
    if any(k in lu for k in ["quantization", "int8", "int4", "w4a8", "gguf", "awq", "gptq"]):
        tags += ["Quantization", "EdgeAI"]
    if any(k in lu for k in ["gemma", "phi-3", "phi", "qwen", "qwen2", "llama", "openorca", "orca", "vicuna", "ultrachat", "omni"]):
        tags += ["LLM"]
    if any(k in lu for k in ["vision", "vlm", "multimodal", "image", "clip", "stable diffusion", "sd"]):
        tags += ["Multimodal"]

    # short heuristic summary: prioritize summary if long enough else title
    short_summary = (summary or title or "").strip()
    if len(short_summary) > 800:
        short_summary = short_summary[:800].rsplit(" ", 1)[0] + "…"

    # Base scoring strategy: give blogs a competitive floor so they show up in v_digest.
    # Keep numbers conservative to avoid flooding.
    base = 0.72
    # boost if it looks like an announcement
    if any(w in lu for w in ["announc", "introduc", "release", "launch", "now available", "available now"]):
        base += 0.06
    # boost for LLM / quantization signals
    if "llm" in " ".join(tags).lower() or "quantization" in " ".join(tags).lower():
        base += 0.03
    # final clamp
    score = float(min(max(base, 0.55), 0.97))

    # dedupe tags, preserve order
    seen = set()
    dedup = []
    for t in tags:
        if t not in seen:
            dedup.append(t)
            seen.add(t)

    return dedup, score, short_summary


async def ingest_medium_feeds(
    feeds: List[str],
    hours: int = 72,
    backfill: bool = False,  # accepted (keeps compat); hours drives cutoff
    limit: int | None = None,
    force_latest: bool = False,
    min_keep_per_feed: int = 3,
) -> int:
    """
    Insert recent Medium posts into items (upsert on origin_id) and immediately enrich them so
    they show up in the digest view without waiting for the enrichment pipeline.
    Returns number of attempted inserts.
    """
    store = get_store()
    await store.init()

    src_id = await store.upsert_source(
        kind="medium", name="medium-feeds", url="https://medium.com", weight=1.0
    )
    cutoff = _now_utc() - timedelta(hours=hours)
    inserted = 0
    diagnostics: List[Dict[str, Any]] = []

    for f in feeds:
        if f.startswith("http"):
            rss_url = f
        else:
            handle = f.replace("https://medium.com/", "").strip("/").lstrip("@")
            rss_url = f"https://medium.com/feed/@{handle}"

        try:
            rs = await _fetch_rss(rss_url)
            if "__error__" in rs:
                diagnostics.append({"feed": f, "url": rss_url, "error": rs["__error__"]})
                posts = []
            else:
                posts = _posts_from_rss(rs)
        except Exception as e:
            diagnostics.append({"feed": f, "url": rss_url, "error": str(e)})
            posts = []

        kept = [p for p in posts if p["event_time"] >= cutoff]

        if not kept and force_latest and posts:
            kept = posts[: max(1, int(min_keep_per_feed))]

        if limit is not None:
            kept = kept[: max(0, int(limit))]

        for p in kept:
            try:
                item_id = await store.insert_item(
                    source_id=src_id,
                    kind="medium:post",
                    origin_id=p["origin_id"],
                    title=p["title"],
                    url=p["url"],
                    author=p.get("author"),
                    summary_raw=p.get("summary"),
                    event_time=p["event_time"],
                )
                inserted += 1

                # immediate lightweight enrichment so blog posts appear in digest
                try:
                    tags, score, short_summary = _compute_tags_and_score(
                        p["title"], p["url"], p.get("author", "") or "", p.get("summary", "") or ""
                    )

                    await store.upsert_enrichment(
                        item_id=item_id,
                        summary_ai=(short_summary or p["title"])[:1200],
                        tags=tags,
                        keywords=[],
                        embedding=[],
                        score=score,
                        metadata={"source": "rss"},
                    )
                    await store.set_status(item_id, "enriched")
                except Exception:
                    # don't fail the whole process on enrichment problems
                    diagnostics.append({"feed": f, "url": rss_url, "warn": f"enrich_failed_for:{p['url']}"})
            except Exception as e:
                diagnostics.append({"feed": f, "url": rss_url, "error_insert": str(e)})

    # refresh digest MV so new items appear immediately
    try:
        await store.refresh_digest()
    except Exception:
        pass

    # Optionally: log diagnostics somewhere or return them.
    # For compatibility keep return as inserted count (old callers expect int).
    return inserted
