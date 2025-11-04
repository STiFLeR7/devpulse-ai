# backend/ingest/hf.py
from __future__ import annotations
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Iterable, Dict, Any, List, Optional
from huggingface_hub import HfApi
from app.settings import settings
from backend.store_factory import get_store

api = HfApi(token=settings.HF_TOKEN)

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _safe(s: Optional[str]) -> str:
    return s or ""

async def _upsert_items(rows: List[Dict[str, Any]]) -> int:
    store = get_store()
    await store.init()
    src_id = await store.upsert_source(
        kind="hf", name="huggingface", url="https://huggingface.co", weight=1.0
    )
    count = 0
    for r in rows:
        item_id = await store.insert_item(
            source_id=src_id,
            kind=r["kind"],                 # "hf:model" or "hf:dataset"
            origin_id=r["origin_id"],       # stable id + revision
            title=r["title"],
            url=r["url"],
            author=r.get("author"),
            summary_raw=r.get("summary_raw"),
            event_time=r["event_time"],
        )
        # enrichment is deferred to pipeline (Gemini), but add a mild prior score
        await store.upsert_enrichment(
            item_id=item_id,
            summary_ai=None,
            tags=r.get("tags", []),
            keywords=[],
            embedding=[],
            score=r.get("score", 0.0),
            metadata=r.get("metadata", {}),
        )
        count += 1
    await store.refresh_digest()
    return count

def _row_from_model(m) -> Dict[str, Any]:
    # HfApi list_models returns ModelInfo. Use lastModified & sha as revision marker
    last_mod = getattr(m, "lastModified", None) or getattr(m, "last_modified", None)
    dt = datetime.fromisoformat(last_mod.replace("Z", "+00:00")) if isinstance(last_mod, str) else _now_utc()
    model_id = m.id
    rev = (m.sha or "head")[:12] if hasattr(m, "sha") else "head"
    url = f"https://huggingface.co/{model_id}"
    card_tags = list(m.tags or [])
    title = f"🤗 {model_id} — {m.library_name or 'model'}"
    return {
        "kind": "hf:model",
        "origin_id": f"model:{model_id}:{rev}",
        "title": title,
        "url": url,
        "author": m.author or (model_id.split('/')[0] if '/' in model_id else None),
        "summary_raw": _safe(m.cardData.get("summary", "")) if getattr(m, "cardData", None) else "",
        "event_time": dt,
        "tags": card_tags,
        "score": 0.82 if "text-generation" in card_tags or "llm" in card_tags else 0.78,
        "metadata": {
            "pipeline_tag": getattr(m, "pipeline_tag", None),
            "likes": getattr(m, "likes", None),
            "downloads": getattr(m, "downloads", None),
        },
    }

def _row_from_dataset(d) -> Dict[str, Any]:
    last_mod = getattr(d, "lastModified", None) or getattr(d, "last_modified", None)
    dt = datetime.fromisoformat(last_mod.replace("Z", "+00:00")) if isinstance(last_mod, str) else _now_utc()
    ds_id = d.id
    rev = (d.sha or "head")[:12] if hasattr(d, "sha") else "head"
    url = f"https://huggingface.co/datasets/{ds_id}"
    title = f"📦 {ds_id} — dataset"
    return {
        "kind": "hf:dataset",
        "origin_id": f"dataset:{ds_id}:{rev}",
        "title": title,
        "url": url,
        "author": d.author or (ds_id.split('/')[0] if '/' in ds_id else None),
        "summary_raw": "",
        "event_time": dt,
        "tags": list(d.tags or []),
        "score": 0.80 if "image" in (d.tags or []) or "audio" in (d.tags or []) else 0.75,
        "metadata": {
            "likes": getattr(d, "likes", None),
            "downloads": getattr(d, "downloads", None),
        },
    }

async def ingest_hf_models(authors_or_ids: Iterable[str] | None = None, per_author_limit: int = 25) -> Dict[str, Any]:
    authors_or_ids = list(authors_or_ids or settings.HF_MODELS)
    rows: List[Dict[str, Any]] = []
    for author in authors_or_ids:
        try:
            infos = api.list_models(author=author, sort="lastModified", direction=-1, limit=per_author_limit)
            for m in infos:
                rows.append(_row_from_model(m))
        except Exception as e:
            # continue on individual failures
            rows.append({
                "kind": "log", "origin_id": f"err:model:{author}:{_now_utc().timestamp()}",
                "title": f"[warn] hf models fetch failed: {author}", "url": "", "event_time": _now_utc(),
                "summary_raw": str(e), "tags": [], "score": 0.0, "metadata": {}
            })
    # filter out log pseudo-rows from insert
    true_rows = [r for r in rows if r["kind"] != "log"]
    inserted = await _upsert_items(true_rows)
    return {"requested": authors_or_ids, "inserted": inserted}

async def ingest_hf_datasets(authors_or_ids: Iterable[str] | None = None, per_author_limit: int = 25) -> Dict[str, Any]:
    authors_or_ids = list(authors_or_ids or settings.HF_DATASETS)
    rows: List[Dict[str, Any]] = []
    for author in authors_or_ids:
        try:
            infos = api.list_datasets(author=author, sort="lastModified", direction=-1, limit=per_author_limit)
            for d in infos:
                rows.append(_row_from_dataset(d))
        except Exception as e:
            rows.append({
                "kind": "log", "origin_id": f"err:dataset:{author}:{_now_utc().timestamp()}",
                "title": f"[warn] hf datasets fetch failed: {author}", "url": "", "event_time": _now_utc(),
                "summary_raw": str(e), "tags": [], "score": 0.0, "metadata": {}
            })
    true_rows = [r for r in rows if r["kind"] != "log"]
    inserted = await _upsert_items(true_rows)
    return {"requested": authors_or_ids, "inserted": inserted}
