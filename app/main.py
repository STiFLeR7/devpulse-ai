# app/main.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional
import os
import random
import uuid

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)

from app.settings import settings
from backend.store_factory import get_store

# Optional summarizer (Gemini). Keep imports lazy-safe.
try:
    from core.bridge_api.gemini_client import summarize_daily, gemini_is_active
except Exception:  # pragma: no cover
    summarize_daily = None

    def gemini_is_active() -> bool:
        return False

# ---------- App + globals ----------
app = FastAPI(title="DevPulse-AI API")
store = get_store()

FAVICON_PATH = "utils/assets/favicon.ico"
TPL_PATH = Path("utils/html_templates/email.html")
TPL = TPL_PATH.read_text(encoding="utf-8") if TPL_PATH.exists() else """\
<!doctype html><meta charset="utf-8">
<title>DevPulse — Daily Digest</title>
<body style="font-family:Inter,Arial,sans-serif;max-width:820px;margin:32px auto;line-height:1.45">
  <h1 style="margin:0 0 4px">DevPulse — Daily Digest</h1>
  <div style="color:#666;margin-bottom:18px">{{DATE}}</div>
  <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse">{{ROWS}}</table>
</body>"""

_QUOTES = [
    "Perseverance is not a long race; it is many short races one after another.",
    "The secret of getting ahead is getting started.",
    "Tiny gains daily beat bursts of genius.",
    "Stay curious. Ship often.",
]


# ---------- helpers ----------
def render_html_digest(rows: List[dict]) -> str:
    items_html = "\n".join(
        f"""<tr>
              <td style="padding:10px 12px;border-bottom:1px solid #eee">
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


def render_email_html(rows: List[dict], hours: int) -> str:
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


def _utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# ---------- lifecycle ----------
@app.on_event("startup")
async def startup() -> None:
    await store.init()


# ---------- basics ----------
@app.get("/")
async def root():
    return RedirectResponse(url="/digest/html")


@app.get("/favicon.ico")
async def favicon():
    if os.path.exists(FAVICON_PATH):
        return FileResponse(FAVICON_PATH, media_type="image/x-icon")
    return Response(status_code=204)


# ---------- digest views ----------
@app.get("/digest/json")
async def digest_json(limit: int = 50, tags: Optional[List[str]] = Query(None)):
    rows = await store.top_digest(limit=limit, tags=tags)
    return JSONResponse(rows)


@app.get("/digest/html", response_class=HTMLResponse)
async def digest_html(limit: int = 50, tags: Optional[List[str]] = Query(None)):
    rows = await store.top_digest(limit=limit, tags=tags)
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


@app.get("/digest/daily_html", response_class=HTMLResponse)
async def daily_html(
    hours: int = 24,
    limit: int = 40,
    tags: Optional[List[str]] = Query(None),
):
    rows = await store.top_digest(limit=limit, tags=tags, since_hours=hours)
    summary = ""
    try:
        if summarize_daily and gemini_is_active():
            summary = await summarize_daily(rows, hours=hours)
    except Exception:
        summary = ""
    head = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:820px;margin:20px auto 10px;">
      <h2 style="margin:0 0 6px">DevPulse — Daily Digest</h2>
      <div style="color:#666;margin-bottom:12px">{datetime.now().strftime('%a, %d %b %Y')}</div>
      <div style="padding:12px;border:1px solid #eee;border-radius:8px;background:#fafafa">{summary or "No significant AI/ML updates detected in the selected window."}</div>
    </div>
    """
    return HTMLResponse(head + render_html_digest(rows))


# ---------- mock seeding (for dev UI tests) ----------
async def _ensure_source() -> int:
    s = get_store()
    await s.init()
    return await s.upsert_source(
        kind="github", name="devpulse-mock", url="https://github.com/devpulse/mock", weight=1.0
    )


async def _seed_n_items(n: int = 1) -> None:
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


# ---------- real ingestion batch ----------
@app.api_route("/ingest/github/batch", methods=["GET", "POST"])
async def ingest_github_batch(background: BackgroundTasks):
    from backend.ingest.github import ingest_github_repos

    repos = settings.GITHUB_REPOS
    background.add_task(ingest_github_repos, repos, settings.GITHUB_TOKEN, 3)
    return {"scheduled": True, "repos": repos}


@app.api_route("/ingest/hf/batch", methods=["GET", "POST"])
async def ingest_hf_batch(background: BackgroundTasks):
    from backend.ingest.hf import ingest_hf_datasets, ingest_hf_models

    models = settings.HF_MODELS
    dsets = settings.HF_DATASETS
    background.add_task(ingest_hf_models, models, settings.HF_TOKEN)
    background.add_task(ingest_hf_datasets, dsets, settings.HF_TOKEN)
    return {"scheduled": True, "models": models, "datasets": dsets}


@app.post("/ingest/hf/sync")
async def ingest_hf_sync(hours: int = 720, backfill: bool = True, limit_peek: int = 10):  # 30 days
    """
    Blocking version for debugging/backfill. Returns inserted counts & a small sample.
    """
    try:
        from backend.ingest.hf import ingest_hf_models, ingest_hf_datasets, hf_peek    # add hf_peek (below)
        models = settings.HF_MODELS
        dsets = settings.HF_DATASETS

        peek = await hf_peek(models, dsets, token=settings.HF_TOKEN, hours=hours, limit=limit_peek)

        m = await ingest_hf_models(models, settings.HF_TOKEN, hours=hours) if backfill else 0
        d = await ingest_hf_datasets(dsets, settings.HF_TOKEN, hours=hours) if backfill else 0

        rows = await store.top_digest(limit=5)
        return {"inserted_models": m, "inserted_datasets": d, "peek": peek, "sample_top5": rows}
    except Exception as e:
        # surface the real reason for 500s
        return JSONResponse({"error": str(e)}, status_code=500)


@app.api_route("/ingest/medium/batch", methods=["GET", "POST"])
async def ingest_medium_batch(background: BackgroundTasks):
    from backend.ingest.medium import ingest_medium_feeds

    feeds = settings.MEDIUM_FEEDS
    background.add_task(ingest_medium_feeds, feeds)
    return {"scheduled": True, "feeds": feeds}


@app.post("/ingest/medium/sync")
async def ingest_medium_sync(
    hours: int = 720,
    backfill: bool = True,
    force_latest: bool = True,
    min_keep_per_feed: int = 3,
    limit: int | None = None,
):
    from backend.ingest.medium import ingest_medium_feeds
    feeds = settings.MEDIUM_FEEDS
    ins = await ingest_medium_feeds(
        feeds,
        hours=hours,
        backfill=backfill,
        limit=limit,
        force_latest=force_latest,
        min_keep_per_feed=min_keep_per_feed,
    )
    rows = await store.top_digest(limit=5)
    return {"inserted_posts": ins, "sample_top5": rows}


@app.get("/debug/medium/peek")
async def debug_medium_peek(hours: int = 720, limit: int = 10):
    from backend.ingest.medium import peek_medium
    feeds = settings.MEDIUM_FEEDS
    res = await peek_medium(feeds, hours=hours, limit=limit)
    # Return compact titles to prove parsing is working
    sample_titles = [
        {"title": p["title"], "url": p["url"], "event_time": p["event_time"].isoformat()}
        for p in res.sample
    ]
    return {
        "ok": True,
        "feeds": feeds,
        "peek": {
            "sample": sample_titles,
            "diagnostics": res.diagnostics,
        },
    }

# ---------- enrichment ----------
@app.api_route("/enrich/run", methods=["GET", "POST"])
async def enrich_run(background: BackgroundTasks, limit: int = 25):
    from backend.enrich.pipeline import EnrichmentEngine

    engine = EnrichmentEngine()
    result = await engine.run_once(limit=limit)
    ok = result.get("checked", 0) >= 0
    result["ok"] = ok
    return result


# ---------- debug ----------
@app.get("/debug/gemini")
async def debug_gemini():
    try:
        active = gemini_is_active() if summarize_daily else False
        return {"use_gemini": active, "error": None, "has_key": bool(settings.GEMINI_API_KEY)}
    except Exception as e:
        return {"use_gemini": False, "error": str(e), "has_key": bool(settings.GEMINI_API_KEY)}

@app.get("/debug/gemini/test")
async def debug_gemini_test():
    try:
        import google.generativeai as genai
        if not settings.GEMINI_API_KEY:
            return {"ok": False, "error": "GEMINI_API_KEY missing"}

        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.0-flash")
        r = model.generate_content("Return exactly: PING", safety_settings=None)
        text = (r.text or "").strip()
        return {"ok": text == "PING", "got": text}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/debug/supabase")
async def debug_supabase():
    from backend.db_rest import SupabaseREST

    client = SupabaseREST()
    try:
        rows = await client.select("v_digest", {"select": "id", "limit": "1"})
        return {"ok": True, "url": settings.SUPABASE_URL, "has_key": bool(settings.SUPABASE_JWT), "sample": rows}
    except Exception as e:
        return {"ok": False, "url": settings.SUPABASE_URL, "has_key": bool(settings.SUPABASE_JWT), "error": str(e)}


@app.get("/debug/items/recent")
async def debug_items_recent(limit: int = 50, hours: int = 48):
    from backend.db_rest import SupabaseREST

    rest = SupabaseREST()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours))
    try:
        rows = await rest.select(
            "items",
            {
                "select": "id,kind,title,url,author,event_time,status,created_at",
                "event_time": f"gte.{_utc_iso(cutoff)}",
                "order": "event_time.desc,created_at.desc",
                "limit": str(limit),
            },
        )
        return {"count": len(rows), "items": rows}
    except Exception as e:
        raise HTTPException(500, f"recent fetch failed: {e}")


@app.get("/debug/items/unenriched")
async def debug_items_unenriched(limit: int = 50, hours: int = 72):
    """
    Items in time window that have no corresponding row in item_enriched.
    """
    from backend.db_rest import SupabaseREST

    rest = SupabaseREST()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours))

    # fetch recent items
    recent = await rest.select(
        "items",
        {
            "select": "id,kind,title,url,author,event_time,status,created_at",
            "event_time": f"gte.{_utc_iso(cutoff)}",
            "order": "event_time.desc,created_at.desc",
            "limit": str(limit * 3),
        },
    )
    if not recent:
        return {"count": 0, "items": []}

    ids = [str(r["id"]) for r in recent]

    # enriched mapping
    chunk = ",".join(ids[:1000])
    enriched = await rest.select(
        "item_enriched",
        {"select": "item_id", "item_id": f"in.({chunk})", "limit": str(len(ids))},
    )
    enriched_ids = {str(r["item_id"]) for r in enriched}

    out = [r for r in recent if str(r["id"]) not in enriched_ids]
    return {"count": len(out[:limit]), "items": out[:limit]}


# ---------- admin ----------
@app.post("/admin/cleanup/mocks")
async def admin_cleanup_mocks(hard: bool = False):
    """
    Delete seeded mock rows by URL prefix. item_enriched will be removed via ON DELETE CASCADE.
    """
    from backend.db_rest import SupabaseREST

    rest = SupabaseREST()
    try:
        deleted = await rest.delete("items", {"url": "ilike.https://example.com/devpulse-mock%"})
        return {"deleted_items": len(deleted), "deleted_enriched": "via cascade"}
    except Exception as e:
        raise HTTPException(500, f"cleanup failed: {e}")
