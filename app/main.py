# app/main.py
from __future__ import annotations

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from typing import Any, Dict, List

from .settings import settings
from .store import init_db, upsert_items, latest_items, record_feedback
from .renderer import render_html
from .github_feed import aggregate_all as aggregate_github

app = FastAPI(title="devpulse-ai")

# --- lifecycle ----------------------------------------------------------------

@app.on_event("startup")
def on_startup():
    init_db()

# --- helpers ------------------------------------------------------------------

def _aggregate_all_sources() -> List[Dict[str, Any]]:
    """
    Aggregate all enabled sources (currently GitHub only; HF/Medium can be added later).
    """
    items: List[Dict[str, Any]] = []

    # ---- GitHub ----
    repos = settings.github_repos  # List[str] parsed in settings
    if repos:
        gh_items = aggregate_github(
            repos,
            github_token=settings.github_token,
            per_repo_limit=settings.github_per_repo_limit,
            timeout_s=12.0,
        )
        items.extend(gh_items)

    # Future: Hugging Face, Medium, etc. (merge here)

    return items

# --- routes -------------------------------------------------------------------

@app.get("/", response_class=RedirectResponse)
def root() -> RedirectResponse:
    # Quality-of-life: send to digest page
    return RedirectResponse(url="/digest/html", status_code=302)

@app.get("/healthz", response_class=PlainTextResponse)
def healthz() -> str:
    return "ok"

@app.get("/ingest/run", response_class=PlainTextResponse)
async def ingest_now() -> str:
    # Pull from all sources and persist
    items = _aggregate_all_sources()
    n = upsert_items(items)
    return f"ingested={n}"

@app.get("/digest/html", response_class=HTMLResponse)
def digest_html() -> HTMLResponse:
    items = latest_items(limit=settings.digest_limit)
    html = render_html(items, phase_label=settings.phase_label)
    return HTMLResponse(html)

@app.get("/redirect")
def redirect(source: str, external_id: str, to: str) -> Response:
    # (Optional) could record click here
    return RedirectResponse(url=to, status_code=302)

@app.get("/events/ping", response_class=PlainTextResponse)
def events_ping(source: str, external_id: str, type: str) -> str:
    """
    Record user feedback: type in {"like","dislike"}.
    """
    ok = record_feedback(source=source, external_id=external_id, kind=type)
    if not ok:
        raise HTTPException(status_code=400, detail="failed to record feedback")
    return "ok"
