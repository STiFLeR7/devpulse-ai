from __future__ import annotations
import os
import json
import aiosqlite
from typing import Any, List, Dict
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "./devpulse.sqlite")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

class DB:
    def __init__(self, path: str | None = None):
        self.path = path or DB_PATH
        self.conn: aiosqlite.Connection | None = None

    async def init(self):
        first_time = not os.path.exists(self.path)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        if first_time:
            with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
                await self.conn.executescript(f.read())
            await self.conn.commit()

    async def upsert_items(self, items: List[Dict[str, Any]]) -> int:
        if not items:
            return 0
        q = """
        INSERT INTO items (source, external_id, title, url, repo, published_at, raw)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, external_id) DO UPDATE SET
            title=excluded.title,
            url=excluded.url,
            repo=excluded.repo,
            published_at=excluded.published_at,
            raw=excluded.raw
        """
        upserted = 0
        async with self.conn.execute("BEGIN"):
            for it in items:
                await self.conn.execute(q, (
                    it.get("source"),
                    it.get("external_id"),
                    it.get("title"),
                    it.get("url"),
                    it.get("repo"),
                    it.get("published_at"),
                    json.dumps(it.get("raw"), separators=(",", ":"), ensure_ascii=False),
                ))
                upserted += 1
        await self.conn.commit()
        return upserted

    async def log_run(self, meta: Dict[str, Any]):
        q = "INSERT INTO runs (started_at, finished_at, status, meta) VALUES (?, ?, ?, ?)"
        now = datetime.utcnow().isoformat() + "Z"
        await self.conn.execute(q, (now, now, "finished", json.dumps(meta, separators=(",", ":"), ensure_ascii=False)))
        await self.conn.commit()

    async def close(self):
        if self.conn:
            await self.conn.close()
