# backend/ingest/hf.py
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
import httpx

from backend.store_factory import get_store

HF_API_BASE = "https://huggingface.co/api"

def _utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def _to_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    # HF returns ISO8601 with Z; datetime.fromisoformat can’t parse 'Z' pre-3.11; do a safe path
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
    """
    Pull recent models by lastModified (global). If you have an allowlist, use _models_by_ids instead.
    """
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
                # ignore 404s or private
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
    """
    Insert/update HF models into items table as kind='hf:model'.
    """
    store = get_store()
    await store.init()

    # Source row (dedup by kind+url)
    src_id = await store.upsert_source(
        kind="hf", name="huggingface-models", url="https://huggingface.co/models", weight=1.0
    )

    # Pick mode: allowlist exact IDs or recent-activity scan
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
        await store.insert_item(
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

    # Refresh digest/materialized views if any
    await store.refresh_digest()
    return inserted

async def ingest_hf_datasets(allow_ids: List[str], token: Optional[str], hours: int = 72) -> int:
    """
    Insert/update HF datasets into items table as kind='hf:dataset'.
    """
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
        await store.insert_item(
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

    await store.refresh_digest()
    return inserted

# ---- Optional: the read-only peek used by /ingest/hf/sync ----
async def hf_peek(models_allow: List[str], dsets_allow: List[str], token: Optional[str], hours: int, limit: int = 10) -> Dict[str, Any]:
    out: Dict[str, Any] = {"models": [], "datasets": []}
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
