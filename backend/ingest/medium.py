# backend/ingest/medium.py
from __future__ import annotations

import os
import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import httpx

try:
    import feedparser  # pip install feedparser
except Exception:
    feedparser = None

from backend.store_factory import get_store

INGEST_TARGET = os.getenv("INGEST_TARGET", "v1")
LOG = logging.getLogger(__name__)
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0 Safari/537.36"
)
TIMEOUT = httpx.Timeout(20.0, connect=10.0, read=10.0, write=10.0)
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

def _dt_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _safe_event_time_from_feed(entry: Dict[str, Any]) -> Optional[datetime]:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            try:
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
    if not url:
        return url
    return url.split("?")[0].strip().rstrip("/")

def _mk_origin_id(url: str, published: Optional[datetime]) -> str:
    stamp = published.strftime("%Y%m%d%H%M%S") if published else "na"
    key = f"{_normalize_url(url)}::{stamp}"
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return f"medium:{h}"

def _clean_text(s: Optional[str]) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

async def _get_with_retries(client: httpx.AsyncClient, url: str, attempts: int = 3, backoff_base: float = 0.5) -> httpx.Response:
    last_exc = None
    for i in range(attempts):
        try:
            resp = await client.get(url, headers=HEADERS)
            resp.raise_for_status()
            return resp
        except Exception as e:
            last_exc = e
            wait = backoff_base * (2 ** i)
            LOG.debug("Fetch failed (%s), attempt %d/%d, retrying in %.2fs", e, i + 1, attempts, wait)
            await asyncio.sleep(wait)
    raise last_exc

async def _fetch_rss(url: str) -> Dict[str, Any]:
    if feedparser is None:
        return {"__error__": "feedparser package not installed"}

    async with httpx.AsyncClient(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True) as client:
        try:
            r = await _get_with_retries(client, url)
        except Exception as e:
            return {"__error__": f"fetch_failed: {e}", "feed": {}, "entries": [], "__src__": url}

        txt = r.text
        fp = feedparser.parse(txt)
        if getattr(fp, "entries", None):
            return {"feed": getattr(fp, "feed", {}), "entries": getattr(fp, "entries", []), "__raw__": f"len={len(txt)}", "__src__": url}

        try:
            m = re.search(
                r'<link[^>]+rel=["\']alternate["\'][^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]+href=["\']([^"\']+)["\']',
                txt, re.I
            )
            if m:
                rss_url = m.group(1)
                rss_url = urljoin(url, rss_url)
                try:
                    r2 = await _get_with_retries(client, rss_url)
                    fp2 = feedparser.parse(r2.text)
                    return {
                        "feed": getattr(fp2, "feed", {}),
                        "entries": getattr(fp2, "entries", []),
                        "__raw__": f"len={len(r2.text)} (discovered)",
                        "__src__": rss_url,
                    }
                except Exception as e:
                    LOG.debug("Discovered RSS fetch failed: %s", e)
                    return {"__error__": f"discovered_fetch_failed: {e}", "feed": {}, "entries": [], "__src__": rss_url}
        except Exception as e:
            LOG.debug("Discovery parse error: %s", e)

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
        author = e.get("author") or (e.get("authors")[0]["name"] if e.get("authors") else "")
        summary = _clean_text(e.get("summary") or e.get("description") or "")
        when = _safe_event_time_from_feed(e) or _now_utc()
        out.append(
            {
                "title": title,
                "url": link,
                "author": author,
                "summary": summary,
                "event_time": when,
                "origin_id": _mk_origin_id(link, when),
            }
        )
    out.sort(key=lambda x: x["event_time"], reverse=True)
    return out

@dataclass
class PeekResult:
    sample: List[Dict[str, Any]]
    diagnostics: List[Dict[str, Any]]

async def peek_medium(feeds: List[str], hours: int = 720, limit: int = 10) -> PeekResult:
    diags: List[Dict[str, Any]] = []
    samples: List[Dict[str, Any]] = []

    for f in feeds:
        rss_url = f if f.startswith("http") else f"https://medium.com/feed/@{f.strip().lstrip('@')}"
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
                    "__src__": rs.get("__src__"),
                }
            )
            samples.extend(posts[: max(0, int(limit))])
        except Exception as e:
            diags.append({"feed": f, "url": rss_url, "error": str(e)})

    samples = samples[: max(0, int(limit))]
    return PeekResult(sample=samples, diagnostics=diags)

async def ingest_medium_feeds(
    feeds: List[str],
    hours: int = 72,
    backfill: bool = False,
    limit: int | None = None,
    force_latest: bool = False,
    min_keep_per_feed: int = 3,
) -> int:
    store = get_store()
    await store.init()

    src_id = await store.upsert_source(
        kind="medium", name="medium-feeds", url="https://medium.com", weight=1.0
    )
    cutoff = _now_utc() - timedelta(hours=hours)
    inserted = 0

    for f in feeds:
        rss_url = f if f.startswith("http") else f"https://medium.com/feed/@{f.strip().lstrip('@')}"
        try:
            rs = await _fetch_rss(rss_url)
            posts = _posts_from_rss(rs) if "__error__" not in rs else []
        except Exception:
            posts = []

        kept = [p for p in posts if p["event_time"] >= cutoff]

        if not kept and force_latest and posts:
            kept = posts[: max(1, int(min_keep_per_feed))]

        if limit is not None:
            kept = kept[: max(0, int(limit))]

        for p in kept:
            try:
                # legacy insert
                item_id = await store.insert_item(
                    source_id=src_id,
                    kind="medium:post",
                    origin_id=p["origin_id"],
                    title=p["title"],
                    url=p["url"],
                    author=p.get("author") or "",
                    summary_raw=p.get("summary") or "",
                    event_time=p["event_time"],
                )
                inserted += 1

                # v2 upsert
                if INGEST_TARGET in ("v2", "both"):
                    try:
                        from backend.ingest.ingest_adapter import upsert_item_v2
                        item_v2 = {
                            "id": item_id,
                            "kind": "medium:post",
                            "title": p["title"],
                            "url": p["url"],
                            "domain": (p["url"].split("//")[-1].split("/")[0]) if p.get("url") else None,
                            "event_time": p["event_time"].isoformat() if p.get("event_time") else None,
                            "inferred_time": None,
                            "score": None,
                            "tags": None,
                            "summary_ai": p.get("summary") or "",
                            "raw_json": p,
                            "is_suspected_mock": False,
                            "source": "medium"
                        }
                        await upsert_item_v2(item_v2)
                    except Exception as e:
                        LOG.warning("ingest_adapter warning (medium): %s", e)

            except Exception as e:
                LOG.warning("insert_item failed for %s: %s", p.get("url"), e)

    try:
        await store.refresh_digest()
    except Exception as e:
        LOG.debug("refresh_digest failed: %s", e)

    return inserted
