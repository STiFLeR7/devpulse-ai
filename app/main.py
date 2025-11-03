from fastapi import FastAPI, Query, HTTPException, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, PlainTextResponse
from typing import Optional
from urllib.parse import urlparse
from datetime import datetime, timezone

from .settings import settings
from .crypto import verify_event
from .store import init_db, upsert_items, latest_items, record_feedback
from .github_feed import aggregate_all

app = FastAPI(title="devpulse-ai")

@app.on_event("startup")
def _startup():
    init_db()

@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    return "ok"

@app.get("/ingest/run", response_class=JSONResponse)
async def ingest_now():
    items = await aggregate_all()
    n = upsert_items(items)
    return {"inserted_or_updated": n, "total_seen": len(items)}

@app.get("/digest/json", response_class=JSONResponse)
def digest_json(limit: int = 200):
    return latest_items(limit=limit)

from .renderer import render_html

@app.get("/digest/html", response_class=HTMLResponse)
def digest_html(limit: int = 200):
    items = latest_items(limit=limit)
    # If empty, do a lazy ingest to avoid blank screen
    if not items:
        # Lazy: try to populate once
        import asyncio
        items = asyncio.run(aggregate_all())
        upsert_items(items)
        items = latest_items(limit=limit)
    return HTMLResponse(render_html(items))

def _is_allowed_redirect(url: str) -> bool:
    # allow github, huggingface, medium
    host = urlparse(url).netloc.lower()
    return any(host.endswith(h) for h in ["github.com", "huggingface.co", "medium.com"])

@app.get("/redirect")
def outbound_redirect(source: str, external_id: str, to: str):
    if not _is_allowed_redirect(to):
        raise HTTPException(status_code=400, detail="blocked host")
    return RedirectResponse(to, status_code=302)

@app.get("/events/ping")
def events_ping(
    source: str,
    external_id: str,
    type: str = Query(..., pattern="^(like|dislike)$"),
    sig: Optional[str] = None,
):
    if not sig:
        raise HTTPException(status_code=400, detail="missing signature")
    payload = f"{external_id}|{source}"
    if not verify_event(settings.BRIDGE_SIGNING_SECRET, payload, sig):
        raise HTTPException(status_code=403, detail="invalid signature")
    record_feedback(external_id, type)
    # Redirect back to digest for smooth UX
    return RedirectResponse(url=f"{settings.BASE_URL}/digest/html", status_code=302)
