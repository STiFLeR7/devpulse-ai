# Aggregator for all sources (GitHub + HF + Medium)
import httpx, feedparser
from datetime import datetime, timezone
from .settings import settings

from .github_items import fetch_github

def _ts(x: str | None):
    if not x:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(x.replace("Z","+00:00"))

async def fetch_hf() -> list[dict]:
    if not settings.ENABLE_HF:
        return []
    items: list[dict] = []
    async with httpx.AsyncClient(timeout=30) as client:
        # Models
        try:
            r = await client.get(
                "https://huggingface.co/api/models",
                params={"sort": "lastModified", "direction": "-1", "limit": settings.HF_MODELS_LIMIT},
            )
            if r.status_code == 200:
                for m in r.json():
                    repo_id = m.get("modelId") or m.get("id")
                    if repo_id:
                        items.append({
                            "source": "hf-model",
                            "external_id": f"hf:model:{repo_id}",
                            "title": f"{repo_id} (model)",
                            "url": f"https://huggingface.co/{repo_id}",
                            "secondary_url": None,
                            "published_at": _ts(m.get("lastModified")),
                        })
        except Exception:
            pass

        # Datasets
        try:
            r = await client.get(
                "https://huggingface.co/api/datasets",
                params={"sort": "lastModified", "direction": "-1", "limit": settings.HF_DATASETS_LIMIT},
            )
            if r.status_code == 200:
                for d in r.json():
                    ds_id = d.get("id")
                    if ds_id:
                        items.append({
                            "source": "hf-dataset",
                            "external_id": f"hf:dataset:{ds_id}",
                            "title": f"{ds_id} (dataset)",
                            "url": f"https://huggingface.co/datasets/{ds_id}",
                            "secondary_url": None,
                            "published_at": _ts(d.get("lastModified")),
                        })
        except Exception:
            pass
    return items

def _parse_dt(entry):
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    if t:
        return datetime(*t[:6], tzinfo=timezone.utc)
    return datetime.now(timezone.utc)

def fetch_medium_sync() -> list[dict]:
    if not (settings.ENABLE_MEDIUM and settings.MEDIUM_FEEDS):
        return []
    items: list[dict] = []
    for feed_url in settings.MEDIUM_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for e in feed.entries[:12]:
                eid = e.get("id") or e.get("link")
                title = e.get("title", "Medium")
                link = e.get("link")
                if not (eid and link): 
                    continue
                items.append({
                    "source": "medium",
                    "external_id": f"medium:{eid}",
                    "title": title,
                    "url": link,
                    "secondary_url": None,
                    "published_at": _parse_dt(e),
                })
        except Exception:
            continue
    return items

async def aggregate_all() -> list[dict]:
    out: list[dict] = []
    out.extend(await fetch_github())
    out.extend(await fetch_hf())
    out.extend(fetch_medium_sync())
    # Deduplicate by external_id (keep newest)
    seen = {}
    for it in sorted(out, key=lambda x: str(x["published_at"]), reverse=True):
        seen.setdefault(it["external_id"], it)
    return list(seen.values())
