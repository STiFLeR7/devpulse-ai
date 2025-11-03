# app/main.py
from fastapi import FastAPI, Query, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from typing import List, Optional
from datetime import datetime, timezone

from backend.store_factory import get_store
from app.settings import settings

# simple renderer (keep yours if you already have one)
def render_html_digest(rows):
    items = "".join(
        f"<li><a href='{r.get('url','')}' target='_blank'>{r.get('title','(no title)')}</a> "
        f"[score={r.get('score','-')}]</li>"
        for r in rows
    )
    return f"<h2>DevPulse Digest</h2><ul>{items}</ul>"

app = FastAPI(title="DevPulse-AI API")
store = get_store()

@app.on_event("startup")
async def startup():
    await store.init()

@app.get("/")
async def root():
    # convenience: open digest
    return RedirectResponse(url="/digest/html")

@app.get("/digest/json")
async def digest_json(limit:int=50, tags: Optional[List[str]] = Query(None)):
    rows = await store.top_digest(limit=limit, tags=tags)
    return JSONResponse(rows)

@app.get("/digest/html", response_class=HTMLResponse)
async def digest_html(limit:int=50, tags: Optional[List[str]] = Query(None)):
    rows = await store.top_digest(limit=limit, tags=tags)
    return HTMLResponse(render_html_digest(rows))

@app.get("/healthz")
async def healthz():
    mode = "rest"
    return {"ok": True, "mode": mode}

# --------- quick mock ingest to validate end-to-end ----------
async def _ingest_once_mock():
    # This writes a high-score item so your n8n email fires.
    s = get_store()
    await s.init()
    src_id = await s.upsert_source(
        kind="github", name="devpulse-mock", url="https://github.com/devpulse/mock", weight=1.0
    )
    now = datetime.now(timezone.utc)
    origin = f"mock-{int(now.timestamp())}"
    item_id = await s.insert_item(
        source_id=src_id, kind="github:repo", origin_id=origin,
        title="🔥 DevPulse Mock Signal — Quantization speedup",
        url="https://example.com/devpulse-mock",
        author="devpulse",
        summary_raw="Mock raw summary to validate pipeline.",
        event_time=now,
    )
    await s.upsert_enrichment(
        item_id=item_id,
        summary_ai="W4A8 adaptive quantization improves RTX 3050 inference by 3.1x.",
        tags=["LLM","EdgeAI","Quantization"],
        keywords=["W4A8","adaptive","RTX3050"],
        embedding=[],  # stored in metadata in REST mode
        score=0.91,    # > 0.8 so your n8n IF passes
        metadata={},
    )
    await s.set_status(item_id, "enriched")
    await s.refresh_digest()

@app.post("/ingest/run")
async def ingest_run(background: BackgroundTasks):
    background.add_task(_ingest_once_mock)
    return {"scheduled": True, "mode": "mock"}
