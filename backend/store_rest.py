# backend/store_rest.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence
from datetime import datetime, timezone, timedelta

from backend.db_rest import SupabaseREST

JSON = Dict[str, Any]


def _utc_iso(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc_iso_now_minus(hours: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=max(1, int(hours)))
    return dt.isoformat().replace("+00:00", "Z")


class StoreREST:
    def __init__(self, rest: SupabaseREST):
        self.rest = rest

    async def init(self):
        return

    # -------------------- sources --------------------
    async def upsert_source(self, kind: str, name: str, url: str, weight: float = 1.0) -> int:
        rows = await self.rest.insert(
            "sources",
            [{"kind": kind, "name": name, "url": url, "weight": weight}],
            upsert=True,
            on_conflict="kind,url",
            return_representation=True,
        )
        if rows and "id" in rows[0]:
            return rows[0]["id"]
        got = await self.rest.select(
            "sources",
            {"select": "id", "kind": f"eq.{kind}", "url": f"eq.{url}", "limit": "1"},
        )
        return got[0]["id"]

    # -------------------- items --------------------
    async def insert_item(
        self,
        *,
        source_id: int,
        kind: str,
        origin_id: str,
        title: str,
        url: str,
        author: Optional[str],
        summary_raw: Optional[str],
        event_time: Optional[datetime],
    ) -> int:
        payload = [
            {
                "source_id": source_id,
                "kind": kind,
                "origin_id": origin_id,
                "title": title,
                "url": url,
                "author": author,
                "summary_raw": summary_raw,
                "event_time": _utc_iso(event_time),
            }
        ]
        rows = await self.rest.insert(
            "items",
            payload,
            upsert=True,
            on_conflict="kind,origin_id",
            return_representation=True,
        )
        if rows and "id" in rows[0]:
            return rows[0]["id"]
        got = await self.rest.select(
            "items",
            {"select": "id", "kind": f"eq.{kind}", "origin_id": f"eq.{origin_id}", "limit": "1"},
        )
        return got[0]["id"]

    async def set_status(self, item_id: int, status: str):
        await self.rest.update("items", {"id": f"eq.{item_id}"}, {"status": status})

    async def mark_published(self, item_id: int):
        await self.set_status(item_id, "published")

    # -------------------- enrichment --------------------
    async def upsert_enrichment(
        self,
        item_id: int,
        *,
        summary_ai: str,
        tags: List[str],
        keywords: List[str],
        embedding: Sequence[float],
        score: float,
        metadata: Dict[str, Any],
    ):
        patch = {
            "item_id": item_id,
            "summary_ai": summary_ai,
            "tags": tags,
            "keywords": keywords,
            "score": float(score),
            "metadata": {**(metadata or {}), "embedding": list(embedding) if embedding else []},
            "updated_at": _utc_iso(datetime.utcnow()),
        }
        await self.rest.insert(
            "item_enriched",
            [patch],
            upsert=True,
            on_conflict="item_id",
            return_representation=False,
        )

    async def refresh_digest(self):
        try:
            await self.rest.rpc("refresh_mv_digest", {})
        except Exception:
            pass

    # -------------------- reads --------------------
    async def top_digest(self, limit: int = 50, tags: Optional[List[str]] = None, since_hours: Optional[int] = None):
        params = {
            "select": "id,kind,title,url,event_time,score,tags,summary_ai",
            "order": "score.desc,event_time.desc",
            "limit": str(limit),
        }
        if tags:
            params["tags"] = "ov.{" + ",".join(tags) + "}"
        if since_hours:
            from datetime import datetime, timedelta, timezone
            cutoff = datetime.now(timezone.utc) - timedelta(hours=int(since_hours))
            iso = cutoff.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            params["event_time"] = f"gte.{iso}"

        return await self.rest.select("v_digest", params)

    async def top_digest_since(
        self,
        since_hours: int = 24,
        limit: int = 50,
        tags: Optional[List[str]] = None,
    ):
        params: Dict[str, str] = {
            "select": "id,kind,title,url,event_time,score,tags,summary_ai",
            "order": "score.desc,event_time.desc",
            "limit": str(max(1, int(limit))),
            "event_time": f"gte.{_utc_iso_now_minus(since_hours)}",
        }
        if tags:
            params["tags"] = "ov.{" + ",".join(tags) + "}"
        return await self.rest.select("v_digest", params)

    async def fetch_unenriched(self, limit: int = 25, since_hours: int = 72):
        """
        Anti-join on item_enriched (left join + is null) so we catch anything not yet enriched,
        regardless of its 'status'. Also restrict to recent 'event_time' to avoid very old backlog.
        """
        params: Dict[str, str] = {
            # left join: item_enriched!left(id); then filter where item_enriched.id is null
            "select": "id,kind,title,url,author,summary_raw,event_time,source_id,status,created_at,item_enriched!left(id)",
            "order": "created_at.desc",
            "limit": str(max(1, int(limit))),
            "event_time": f"gte.{_utc_iso_now_minus(since_hours)}",
            "item_enriched.id": "is.null",
        }
        return await self.rest.select("items", params)
