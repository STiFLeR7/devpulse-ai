# backend/ingest/medium.py
from __future__ import annotations
from datetime import datetime, timezone
from typing import Iterable, Dict, Any, List
import feedparser

from app.settings import settings
from backend.store_factory import get_store


def _parse_dt(entry) -> datetime:
    """
    Convert feedparser entry time to UTC. Tries published_parsed, then updated_parsed, else now().
    """
    t = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if t:
        try:
            return datetime(*t[:6], tzinfo=timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc)


async def ingest_medium(feeds: Iterable[str] | None = None, limit_per_feed: int = 15) -> Dict[str, Any]:
    """
    Ingest latest Medium posts from a list of RSS feed URLs.
    """
    feeds = list(feeds or settings.MEDIUM_FEEDS)
    store = get_store()
    await store.init()

    inserted = 0
    for url in feeds:
        parsed = feedparser.parse(url)

        # one source per feed (title falls back to URL)
        src_title = parsed.feed.get("title", url) if getattr(parsed, "feed", None) else url
        src_id = await store.upsert_source(kind="medium", name=src_title, url=url, weight=0.9)

        entries: List[Any] = list(getattr(parsed, "entries", []))[:limit_per_feed]
        for e in entries:
            origin = e.get("id") or e.get("link")
            if not origin:
                continue

            title = e.get("title") or "Medium post"
            link = e.get("link") or url
            author = e.get("author") or src_title
            summary_raw = (e.get("summary") or "")[:2000]
            ts = _parse_dt(e)

            item_id = await store.insert_item(
                source_id=src_id,
                kind="medium:post",
                origin_id=f"medium:{origin}",
                title=title,
                url=link,
                author=author,
                summary_raw=summary_raw,
                event_time=ts,
            )
            # Base prior; your enrichment pipeline (Gemini) will rescore/retag
            await store.upsert_enrichment(
                item_id=item_id,
                summary_ai=None,
                tags=["Medium", "Blog"],
                keywords=[],
                embedding=[],
                score=0.76,
                metadata={"feed": url},
            )
            await store.set_status(item_id, "enriched")
            inserted += 1

    await store.refresh_digest()
    return {"feeds": feeds, "inserted": inserted}


# ---- Compatibility alias (your app imported this name) ----
async def ingest_medium_feeds(feeds: Iterable[str] | None = None, limit_per_feed: int = 15):
    return await ingest_medium(feeds=feeds, limit_per_feed=limit_per_feed)
