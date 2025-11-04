# app/main.py
from __future__ import annotations

from fastapi import FastAPI, Query, BackgroundTasks, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    PlainTextResponse,
    Response,
    FileResponse,
)
from typing import List, Optional
from datetime import datetime, timezone, timedelta
from pathlib import Path
import uuid
import random
import os

from backend.store_factory import get_store
from app.settings import settings

# -------------------- assets & template helpers --------------------
FAVICON_PATH = "utils/assets/favicon.ico"

def _load_template() -> str:
    p = Path("utils/html_templates/email.html")
    if p.exists():
        return p.read_text(encoding="utf-8")
    # fallback minimal template if file is missing
    return """<!doctype html><html><body style="font-family:Inter,Arial,sans-serif">
      <h2>DevPulse — Daily Digest ({{DATE}})</h2>
      <table width="100%" cellpadding="0" cellspacing="0">{{ROWS}}</table>
      <div style="margin-top:12px;font-size:12px;color:#999">Powered by DevPulse-AI · Supabase · n8n</div>
    </body></html>"""

TPL = _load_template()

def render_html_digest(rows):
    items_html = "\n".join(
        f"""<tr>
              <td style="padding:8px 12px;">
                <div style="font-weight:600;">
                  <a href="{r.get('url','')}" target="_blank" style="text-decoration:none;color:#0b57d0;">
                    {r.get('title','(no title)')}
                  </a>
                </div>
                <div style="font-size:12px;color:#666;">
                  score: {r.get('score','-')} · {", ".join(r.get('tags') or [])}
                </div>
                <div style="font-size:13px;margin-top:6px;color:#222;">
                  {r.get('summary_ai','')}
                </div>
              </td>
            </tr>"""
        for r in rows
    )
    today = datetime.now().strftime("%a, %d %b %Y")
    return TPL.replace("{{DATE}}", today).replace("{{ROWS}}", items_html)

_QUOTES = [
    "Perseverance is not a long race; it is many short races one after another.",
    "The secret of getting ahead is getting started.",
    "Tiny gains daily beat bursts of genius.",
    "Stay curious. Ship often.",
]

def render_email_html(rows, hours: int):
    quote = random.choice(_QUOTES)
    items = "".join(
        f"<li style='margin-bottom:8px'><a href='{r.get('url','')}' target='_blank'>{r.get('title','(no title)')}</a>"
        f" — <em>{r.get('summary_ai','')}</em> <strong>[score={r.get('score','-')}]</strong></li>"
        for r in rows
    )
    return f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:700px;margin:auto">
      <h1 style="margin:0 0 8px">DevPulse — Last {hours}h</h1>
      <p style="color:#666;margin:0 0 16px">{quote}</p>
      <hr style="border:0;border-top:1px solid #eee;margin:16px 0"/>
      <ul style="padding-left:20px">{items or '<li>No high-signal items in this window.</li>'}</ul>
      <hr style="border:0;border-top:1px solid #eee;margin:16px 0"/>
      <p style="font-size:12px;color:#999">Powered by DevPulse-AI · Supabase · n8n</p>
    </div>
    """

# -------------------- app --------------------
app = FastAPI(title="DevPulse-AI API")
store = get_store()

@app.get("/favicon.ico")
async def favicon():
    if os.path.exists(FAVICON_PATH):
        return FileResponse(FAVICON_PATH, media_type="image/x-icon")
    return Response(status_code=204)

@app.on_event("startup")
async def startup():
    await store.init()

@app.get("/")
async def root():
    return RedirectResponse(url="/digest/html")

@app.get("/debug/gemini")
async def debug_gemini():
    try:
        from core.bridge_api import gemini_client as gc
        return {
            "use_gemini": bool(getattr(gc, "_USE_GEMINI", False)),
            "error": getattr(gc, "_ERR", None),
            "has_key": bool(settings.GEMINI_API_KEY),
        }
    except Exception as e:
        return {"use_gemini": False, "error": str(e), "has_key": bool(settings.GEMINI_API_KEY)}

# -------------------- digest endpoints --------------------
@app.get("/digest/json")
async def digest_json(limit: int = 50, tags: Optional[List[str]] = Query(None)):
    rows = await store.top_digest(limit=limit, tags=tags)
    return JSONResponse(rows)

@app.get("/digest/html", response_class=HTMLResponse)
async def digest_html(limit: int = 50, tags: Optional[List[str]] = Query(None)):
    try:
        rows = await store.top_digest(limit=limit, tags=tags)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"digest fetch failed: {e}")
    return HTMLResponse(render_html_digest(rows))

@app.get("/digest/email_html", response_class=HTMLResponse)
async def digest_email_html(hours: int = 24, tags: Optional[List[str]] = Query(None)):
    rows = await store.top_digest(limit=100, tags=tags)
    return HTMLResponse(render_email_html(rows, hours))

@app.get("/digest/rss", response_class=PlainTextResponse)
async def digest_rss(limit: int = 50, tags: Optional[List[str]] = Query(None)):
    rows = await store.top_digest(limit=limit, tags=tags)
    items = "".join(
        f"<item><title>{r['title']}</title><link>{r['url']}</link>"
        f"<description>{r.get('summary_ai','')}</description></item>"
        for r in rows
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<rss version="2.0"><channel><title>DevPulse</title>{items}</channel></rss>'
    )

@app.get("/digest/jsonl", response_class=PlainTextResponse)
async def digest_jsonl(limit: int = 50, tags: Optional[List[str]] = Query(None)):
    import json
    rows = await store.top_digest(limit=limit, tags=tags)
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)

# -------------------- mock seeding for quick UI testing --------------------
async def _ensure_source():
    s = get_store()
    await s.init()
    return await s.upsert_source(
        kind="github", name="devpulse-mock", url="https://github.com/devpulse/mock", weight=1.0
    )

async def _seed_n_items(n: int = 1):
    s = get_store()
    await s.init()
    src_id = await _ensure_source()

    base_time = datetime.now(timezone.utc)
    for i in range(n):
        ts = base_time - timedelta(minutes=i)
        origin = f"mock-{uuid.uuid4().hex[:8]}-{i}"
        title = f"🔥 DevPulse Mock Signal — Quantization speedup #{i+1}"
        url = f"https://example.com/devpulse-mock-{i+1}"
        item_id = await s.insert_item(
            source_id=src_id,
            kind="github:repo",
            origin_id=origin,
            title=title,
            url=url,
            author="devpulse",
            summary_raw="Mock raw summary to validate pipeline.",
            event_time=ts,
        )
        score = round(random.uniform(0.75, 0.97), 2)
        await s.upsert_enrichment(
            item_id=item_id,
            summary_ai="W4A8 adaptive quantization improves RTX 3050 inference.",
            tags=["LLM", "EdgeAI", "Quantization"],
            keywords=["W4A8", "adaptive", "RTX3050"],
            embedding=[],
            score=score,
            metadata={},
        )
        await s.set_status(item_id, "enriched")

    await s.refresh_digest()

@app.api_route("/ingest/seed", methods=["GET", "POST"])
async def ingest_seed(request: Request, background: BackgroundTasks, n: int = 1):
    background.add_task(_seed_n_items, n=max(1, int(n)))
    return {"scheduled": True, "count": max(1, int(n))}

@app.api_route("/ingest/run", methods=["GET", "POST"])
async def ingest_run(request: Request, background: BackgroundTasks):
    background.add_task(_seed_n_items, n=1)
    return {"scheduled": True, "mode": "mock"}

# -------------------- real ingestion & enrichment --------------------
@app.api_route("/enrich/run", methods=["GET", "POST"])
async def enrich_run(background: BackgroundTasks, limit: int = 25):
    from backend.enrich.pipeline import EnrichmentEngine  # lazy import
    engine = EnrichmentEngine()
    result = await engine.run_once(limit=limit)
    return {"ok": True, **result}

@app.api_route("/ingest/github/batch", methods=["GET", "POST"])
async def ingest_github_batch(background: BackgroundTasks):
    from backend.ingest.github import ingest_github_repos  # lazy import
    repos = settings.GITHUB_REPOS
    background.add_task(ingest_github_repos, repos, settings.GITHUB_TOKEN, 3)
    return {"scheduled": True, "repos": repos}

@app.api_route("/ingest/hf/batch", methods=["GET", "POST"])
async def ingest_hf_batch(background: BackgroundTasks):
    from backend.ingest.hf import ingest_hf_models, ingest_hf_datasets  # lazy import
    models = settings.HF_MODELS
    dsets = settings.HF_DATASETS
    background.add_task(ingest_hf_models, models, settings.HF_TOKEN)
    background.add_task(ingest_hf_datasets, dsets, settings.HF_TOKEN)
    return {"scheduled": True, "models": models, "datasets": dsets}

@app.api_route("/ingest/medium/batch", methods=["GET", "POST"])
async def ingest_medium_batch(background: BackgroundTasks):
    from backend.ingest.medium import ingest_medium_feeds  # lazy import (alias)
    feeds = settings.MEDIUM_FEEDS
    background.add_task(ingest_medium_feeds, feeds)
    return {"scheduled": True, "feeds": feeds}

# -------------------- Supabase connectivity debug --------------------
@app.get("/debug/supabase")
async def debug_supabase():
    from backend.db_rest import SupabaseREST
    client = SupabaseREST()
    try:
        rows = await client.select("v_digest", {"select": "id", "limit": "1"})
        return {
            "ok": True,
            "url": settings.SUPABASE_URL,
            "has_key": bool(settings.SUPABASE_JWT),
            "sample": rows,
        }
    except Exception as e:
        return {
            "ok": False,
            "url": settings.SUPABASE_URL,
            "has_key": bool(settings.SUPABASE_JWT),
            "error": str(e),
        }
