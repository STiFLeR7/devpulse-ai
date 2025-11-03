from __future__ import annotations
import os
from datetime import datetime, timezone
from fastapi import FastAPI, Query
from pydantic import BaseModel
from typing import Any, Dict, List
from dotenv import load_dotenv

from core.bridge_api.mcp_client import MCPClient
from core.storage.db import DB

load_dotenv()

app = FastAPI(title="devpulse-ai Bridge API", version="0.1.2")

@app.get("/")
async def index():
    return {"service": "devpulse-ai bridge", "routes": ["GET /health", "POST /trigger/daily?dry_run=true|false"]}

@app.get("/health")
async def health():
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}

def _rank(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def score(it):
        try:
            dt = datetime.fromisoformat(it["published_at"].replace("Z", "+00:00"))
        except Exception:
            dt = datetime.now(timezone.utc)
        return dt.timestamp()
    return sorted(items, key=score, reverse=True)

def _digest(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    sections: Dict[str, List[Dict[str, Any]]] = {}
    for it in items:
        sections.setdefault(it["source"], []).append({
            "title": it["title"],
            "url": it["url"],
            "repo": it.get("repo"),
            "published_at": it["published_at"],
        })
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sections": [{"section": k, "items": v} for k, v in sections.items()],
    }

class TriggerResponse(BaseModel):
    counts: dict
    digest: dict

@app.post("/trigger/daily")
async def trigger_daily(dry_run: bool = Query(default=True)) -> TriggerResponse:
    db = DB()
    await db.init()
    client = MCPClient()
    try:
        gh  = await client.github()
        hfm = await client.hf_models()
        hfd = await client.hf_datasets()
        md  = await client.medium()
        fetched = gh + hfm + hfd + md

        upserted = await db.upsert_items(fetched)
        ranked = _rank(fetched)
        digest = _digest(ranked)

        if not dry_run:
            await db.log_run(meta={"fetched": len(fetched), "upserted": upserted})
        return TriggerResponse(counts={"fetched": len(fetched), "upserted": upserted}, digest=digest)
    finally:
        await client.close()
        await db.close()
