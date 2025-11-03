# backend/store_rest.py
from typing import Any, Dict, List, Optional, Sequence
from datetime import datetime
from backend.db_rest import SupabaseREST

JSON = Dict[str, Any]

class StoreREST:
    def __init__(self, rest: SupabaseREST):
        self.rest = rest

    async def init(self):
        return  # no-op

    # ---------- sources ----------
    async def upsert_source(self, kind: str, name: str, url: str, weight: float = 1.0) -> int:
        rows = await self.rest.insert(
            "sources",
            [{"kind": kind, "name": name, "url": url, "weight": weight}],
            upsert=True,
            on_conflict="kind,url",
        )
        # On upsert, PostgREST may return empty; fetch id:
        if rows and "id" in rows[0]:
            return rows[0]["id"]
        # fallback: select existing
        got = await self.rest.select("sources", {"kind": f"eq.{kind}", "url": f"eq.{url}"})
        return got[0]["id"]

    # ---------- items ----------
    async def insert_item(
        self, *, source_id:int, kind:str, origin_id:str, title:str, url:str,
        author:Optional[str], summary_raw:Optional[str], event_time:Optional[datetime]
    ) -> int:
        payload = [{
            "source_id": source_id, "kind": kind, "origin_id": origin_id,
            "title": title, "url": url, "author": author,
            "summary_raw": summary_raw,
            "event_time": event_time.isoformat() if event_time else None
        }]
        rows = await self.rest.insert("items", payload, upsert=True, on_conflict="kind,origin_id")
        if rows and "id" in rows[0]:
            return rows[0]["id"]
        got = await self.rest.select("items", {"kind": f"eq.{kind}", "origin_id": f"eq.{origin_id}"})
        return got[0]["id"]

    async def upsert_enrichment(
        self, item_id:int, *, summary_ai:str, tags:List[str], keywords:List[str],
        embedding:Sequence[float], score:float, metadata:Dict[str,Any]
    ):
        # PostgREST doesn't accept vector type directly; store as float[] or use RPC.
        # If your column is vector, create an RPC to set it. For now, store metadata['embedding'].
        patch = {
            "summary_ai": summary_ai,
            "tags": tags,
            "keywords": keywords,
            "score": score,
            "metadata": {**metadata, "embedding": embedding},
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
        await self.rest.insert(
            "item_enriched",
            [{"item_id": item_id, **patch}],
            upsert=True,
            on_conflict="item_id",
        )

    async def set_status(self, item_id:int, status:str):
        await self.rest.update("items", {"id": f"eq.{item_id}"}, {"status": status})

    async def mark_published(self, item_id:int):
        await self.set_status(item_id, "published")

    async def refresh_digest(self):
        # Exposed as RPC in your migrations
        await self.rest.rpc("refresh_mv_digest", {})

    async def top_digest(self, limit:int=50, tags:Optional[List[str]]=None):
        params = {"select": "*", "order": "score.desc,event_time.desc", "limit": str(limit)}
        if tags:
            # PostgREST overlap operator on text[]:  tags=ov.{LLM,CUDA}
            params["tags"] = "ov.{" + ",".join(tags) + "}"
        return await self.rest.select("mv_digest", params)
