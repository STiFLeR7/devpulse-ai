# backend/store.py
from typing import List, Dict, Any, Optional, Sequence
from datetime import datetime
from backend.db import DB

class Store:
    def __init__(self, db: DB):
        self.db = db

    async def init(self):
        await self.db.connect()

    async def upsert_source(self, kind: str, name: str, url: str, weight: float = 1.0) -> int:
        q = """
        insert into sources(kind,name,url,weight)
        values($1,$2,$3,$4)
        on conflict(kind,url) do update set name=excluded.name, weight=excluded.weight
        returning id;
        """
        return await self.db.run_one(q, kind, name, url, weight)

    async def insert_item(
        self, *, source_id:int, kind:str, origin_id:str, title:str, url:str,
        author:Optional[str], summary_raw:Optional[str], event_time:Optional[datetime]
    ) -> int:
        q = """
        insert into items(source_id,kind,origin_id,title,url,author,summary_raw,event_time)
        values($1,$2,$3,$4,$5,$6,$7,$8)
        on conflict(kind,origin_id) do update set
          title=excluded.title, url=excluded.url, author=excluded.author,
          summary_raw=excluded.summary_raw, event_time=excluded.event_time
        returning id;
        """
        return await self.db.run_one(q, source_id, kind, origin_id, title, url, author, summary_raw, event_time)

    async def upsert_enrichment(
        self, item_id:int, *, summary_ai:str, tags:List[str], keywords:List[str],
        embedding:Sequence[float], score:float, metadata:Dict[str,Any]
    ):
        q = """
        insert into item_enriched(item_id,summary_ai,tags,keywords,embedding,score,metadata,updated_at)
        values($1,$2,$3,$4,$5,$6,$7,now())
        on conflict(item_id) do update set
          summary_ai=excluded.summary_ai, tags=excluded.tags, keywords=excluded.keywords,
          embedding=excluded.embedding, score=excluded.score, metadata=excluded.metadata, updated_at=now();
        """
        await self.db.exec(q, item_id, summary_ai, tags, keywords, embedding, score, metadata)

    async def set_status(self, item_id:int, status:str):
        await self.db.exec("update items set status=$2 where id=$1", item_id, status)

    async def refresh_digest(self):
        await self.db.exec("select refresh_mv_digest()")

    async def top_digest(self, limit:int=50, tags:Optional[List[str]]=None):
        base = "select * from mv_digest"
        params: list[Any] = []
        if tags:
            base += " where tags && $1::text[]"
            params.append(tags)
        base += f" order by score desc nulls last, event_time desc nulls last limit ${len(params)+1}"
        params.append(limit)
        return await self.db.run(base, *params)
