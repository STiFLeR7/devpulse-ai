# backend/store_rest.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence
from datetime import datetime, timezone

from backend.db_rest import SupabaseREST

JSON = Dict[str, Any]


def _utc_iso(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class StoreREST:
    def __init__(self, rest: SupabaseREST):
        self.rest = rest

    async def init(self):
        # REST path needs no warmup; keep for interface compatibility
        return

    # ------------------------------- sources -------------------------------

    async def upsert_source(self, kind: str, name: str, url: str, weight: float = 1.0) -> int:
        """
        INSERT ... ON CONFLICT (kind,url) DO UPDATE, return id.
        """
        rows = await self.rest.insert(
            "sources",
            [{"kind": kind, "name": name, "url": url, "weight": weight}],
            upsert=True,
            on_conflict="kind,url",
            return_representation=True,
        )
        if rows and "id" in rows[0]:
            return rows[0]["id"]

        # Fallback read if backend skipped representation
        got = await self.rest.select(
            "sources",
            {"select": "id", "kind": f"eq.{kind}", "url": f"eq.{url}", "limit": "1"},
        )
        return got[0]["id"]

    # -------------------------------- items --------------------------------

    async def insert_item(
        self,
        *,
        source_id: int,
        kind: str,
        origin_id: str,
        title: Optional[str],
        url: Optional[str],
        author: Optional[str],
        summary_raw: Optional[str],
        event_time: Optional[datetime],
    ) -> int:
        """
        Upsert item uniquely by (kind, origin_id) and return id.
        """
        payload = [{
            "source_id": source_id,
            "kind": kind,
            "origin_id": origin_id,
            "title": title,
            "url": url,
            "author": author,
            "summary_raw": summary_raw,
            "event_time": _utc_iso(event_time),
        }]
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

    # ----------------------------- enrichment ------------------------------

    async def upsert_enrichment(
        self,
        item_id: int,
        *,
        summary_ai: Optional[str],
        tags: List[str],
        keywords: List[str],
        embedding: Sequence[float],
        score: float,
        metadata: Dict[str, Any],
    ):
        """
        Upsert into item_enriched by unique(item_id).
        Keep 'embedding' in its own column (jsonb) per schema; metadata stays separate.
        """
        patch = {
            "item_id": item_id,
            "summary_ai": summary_ai,
            "tags": tags or [],
            "keywords": keywords or [],
            "embedding": list(embedding) if embedding else [],
            "score": float(score),
            "metadata": metadata or {},
            "updated_at": _utc_iso(datetime.now(timezone.utc)),
        }
        await self.rest.insert(
            "item_enriched",
            [patch],
            upsert=True,
            on_conflict="item_id",
            return_representation=False,
        )

    # ------------------------------- digest --------------------------------

    async def refresh_digest(self):
        """
        Call optional RPC to refresh a materialized view. If not present, ignore.
        """
        try:
            await self.rest.rpc("refresh_mv_digest", {})
        except Exception:
            # OK if the function isn't defined (dev mode or plain view)
            pass

    async def top_digest(self, limit: int = 50, tags: Optional[List[str]] = None):
        """
        Read from v_digest with optional tag overlap filter.
        """
        params: Dict[str, str] = {
            "select": "id,kind,title,url,event_time,score,tags,summary_ai",
            "order": "score.desc,event_time.desc",
            "limit": str(max(1, int(limit))),
        }
        if tags:
            # PostgREST array overlap: tags=ov.{tag1,tag2}
            params["tags"] = "ov.{" + ",".join(tags) + "}"
        return await self.rest.select("v_digest", params)

    # -------------------------- enrichment picking -------------------------

    async def fetch_unenriched(self, limit: int = 25, score_floor: float = 0.80):
        limit = max(1, int(limit))

        # Pull a larger recent window and filter in app (simplifies PostgREST filters)
        params = {
            "select": "id,title,url,summary_raw,event_time,status,item_enriched!left(summary_ai,score)",
            "order": "created_at.desc",
            "limit": "200",
        }
        rows = await self.rest.select("items", params)

        need: list[dict] = []
        for r in rows:
            rel = r.get("item_enriched")
            has_row = isinstance(rel, dict)
            summary_ai = (rel or {}).get("summary_ai") if has_row else None
            score = (rel or {}).get("score") if has_row else None
            needs = (
                (not has_row) or
                (summary_ai is None or str(summary_ai).strip() == "") or
                (score is None or float(score) < float(score_floor)) or
                (r.get("status") != "enriched")
            )
            if needs:
                need.append({
                    "id": r["id"],
                    "title": r.get("title"),
                    "url": r.get("url"),
                    "summary_raw": r.get("summary_raw") or "",
                    "event_time": r.get("event_time"),
                    "status": r.get("status"),
                })
            if len(need) >= limit:
                break
        return need

