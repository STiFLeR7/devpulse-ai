# backend/ingest/hf.py
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
import httpx

from backend.store_factory import get_store

INGEST_TARGET = os.getenv("INGEST_TARGET", "v1")
HF_API_BASE = "https://huggingface.co/api"

def _utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def _to_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s).astimezone(timezone.utc)
    except Exception:
        return None

async def _get_json(client: httpx.AsyncClient, url: str, token: Optional[str]) -> Any:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = await client.get(url, headers=headers)
    r.raise_for_status()
    return r.json()

async def _recent_models(token: Optional[str], hours: int, limit: int = 200) -> List[Dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    params = f"sort=lastModified&direction=-1&limit={limit}"
    url = f"{HF_API_BASE}/models?{params}"

    async with httpx.AsyncClient(timeout=30) as client:
        js = await _get_json(client, url, token)
        out = []
        for m in js:
            dt = _to_dt(m.get("lastModified"))
            if dt and dt >= cutoff:
                out.append(m)
        return out

async def _recent_datasets(token: Optional[str], hours: int, limit: int = 200) -> List[Dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    params = f"sort=lastModified&direction=-1&limit={limit}"
    url = f"{HF_API_BASE}/datasets?{params}"

    async with httpx.AsyncClient(timeout=30) as client:
        js = await _get_json(client, url, token)
        out = []
        for d in js:
            dt = _to_dt(d.get("lastModified"))
            if dt and dt >= cutoff:
                out.append(d)
        return out

async def _models_by_ids(ids: List[str], token: Optional[str]) -> List[Dict[str, Any]]:
    out = []
    async with httpx.AsyncClient(timeout=30) as client:
        for mid in ids:
            url = f"{HF_API_BASE}/models/{mid}"
            try:
                js = await _get_json(client, url, token)
                out.append(js)
            except httpx.HTTPStatusError:
                continue
    return out

async def _datasets_by_ids(ids: List[str], token: Optional[str]) -> List[Dict[str, Any]]:
    out = []
    async with httpx.AsyncClient(timeout=30) as client:
        for did in ids:
            url = f"{HF_API_BASE}/datasets/{did}"
            try:
                js = await _get_json(client, url, token)
                out.append(js)
            except httpx.HTTPStatusError:
                continue
    return out

async def ingest_hf_models(allow_ids: List[str], token: Optional[str], hours: int = 72) -> int:
    store = get_store()
    await store.init()

    src_id = await store.upsert_source(
        kind="hf", name="huggingface-models", url="https://huggingface.co/models", weight=1.0
    )

    if allow_ids:
        models = await _models_by_ids(allow_ids, token)
    else:
        models = await _recent_models(token, hours=hours, limit=200)

    inserted = 0
    for m in models:
        mid = m.get("id")
        if not mid:
            continue
        url = f"https://huggingface.co/{mid}"
        title = f"🤗 HF Model — {mid}"
        last = _to_dt(m.get("lastModified")) or datetime.now(timezone.utc)
        origin = f"model:{mid}"
        # legacy insert
        item_id = await store.insert_item(
            source_id=src_id,
            kind="hf:model",
            origin_id=origin,
            title=title,
            url=url,
            author=None,
            summary_raw=m.get("pipeline_tag") or "",
            event_time=last,
        )
        inserted += 1

        # v2 upsert
        if INGEST_TARGET in ("v2", "both"):
            try:
                from backend.ingest.ingest_adapter import upsert_item_v2
                item_v2 = {
                    "id": item_id,
                    "kind": "hf:model",
                    "title": title,
                    "url": url,
                    "domain": (url.split("//")[-1].split("/")[0]) if url else None,
                    "event_time": last.isoformat() if last else None,
                    "inferred_time": None,
                    "score": None,
                    "tags": None,
                    "summary_ai": m.get("pipeline_tag") or "",
                    "raw_json": m,
                    "is_suspected_mock": False,
                    "source": "hf"
                }
                await upsert_item_v2(item_v2)
            except Exception as e:
                print("ingest_adapter warning (hf model):", e)

    await store.refresh_digest()
    return inserted

async def ingest_hf_datasets(allow_ids: List[str], token: Optional[str], hours: int = 72) -> int:
    store = get_store()
    await store.init()

    src_id = await store.upsert_source(
        kind="hf", name="huggingface-datasets", url="https://huggingface.co/datasets", weight=1.0
    )

    if allow_ids:
        dsets = await _datasets_by_ids(allow_ids, token)
    else:
        dsets = await _recent_datasets(token, hours=hours, limit=200)

    inserted = 0
    for d in dsets:
        did = d.get("id")
        if not did:
            continue
        url = f"https://huggingface.co/datasets/{did}"
        title = f"📚 HF Dataset — {did}"
        last = _to_dt(d.get("lastModified")) or datetime.now(timezone.utc)
        origin = f"dataset:{did}"
        # legacy insert
        item_id = await store.insert_item(
            source_id=src_id,
            kind="hf:dataset",
            origin_id=origin,
            title=title,
            url=url,
            author=None,
            summary_raw=d.get("cardData", {}).get("language", "") if isinstance(d.get("cardData"), dict) else "",
            event_time=last,
        )
        inserted += 1

        # v2 upsert
        if INGEST_TARGET in ("v2", "both"):
            try:
                from backend.ingest.ingest_adapter import upsert_item_v2
                item_v2 = {
                    "id": item_id,
                    "kind": "hf:dataset",
                    "title": title,
                    "url": url,
                    "domain": (url.split("//")[-1].split("/")[0]) if url else None,
                    "event_time": last.isoformat() if last else None,
                    "inferred_time": None,
                    "score": None,
                    "tags": None,
                    "summary_ai": d.get("cardData", {}).get("language", "") if isinstance(d.get("cardData"), dict) else "",
                    "raw_json": d,
                    "is_suspected_mock": False,
                    "source": "hf"
                }
                await upsert_item_v2(item_v2)
            except Exception as e:
                print("ingest_adapter warning (hf dataset):", e)

    await store.refresh_digest()
    return inserted

# hf_peek unchanged (no v2 writes)
async def hf_peek(models_allow: List[str], dsets_allow: List[str], token: Optional[str], hours: int, limit: int = 10):
    out = {"models": [], "datasets": []}
    try:
        if models_allow:
            ms = await _models_by_ids(models_allow, token)
        else:
            ms = await _recent_models(token, hours=hours, limit=limit)
        out["models"] = [{"id": m.get("id"), "lastModified": m.get("lastModified")} for m in ms[:limit]]
    except Exception as e:
        out["models_error"] = str(e)
    try:
        if dsets_allow:
            ds = await _datasets_by_ids(dsets_allow, token)
        else:
            ds = await _recent_datasets(token, hours=hours, limit=limit)
        out["datasets"] = [{"id": d.get("id"), "lastModified": d.get("lastModified")} for d in ds[:limit]]
    except Exception as e:
        out["datasets_error"] = str(e)
    return out
