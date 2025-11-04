from __future__ import annotations
import httpx
from datetime import datetime, timezone
from typing import Iterable, Optional
from backend.store_factory import get_store

GITHUB_API = "https://api.github.com"

def _ts(dt: str | None):
    if not dt:
        return None
    try:
        return datetime.fromisoformat(dt.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None

async def _upsert_release(repo: str, rel: dict):
    store = get_store()
    await store.init()
    src_id = await store.upsert_source("github", repo, f"https://github.com/{repo}", 1.0)

    origin_id = f"release:{rel.get('id')}"
    title = f"🔖 {repo} — {rel.get('tag_name', 'release')}"
    url = rel.get("html_url") or f"https://github.com/{repo}/releases"
    summary_raw = rel.get("name") or rel.get("body") or ""
    event_time = _ts(rel.get("published_at") or rel.get("created_at"))

    item_id = await store.insert_item(
        source_id=src_id, kind="github:release", origin_id=origin_id,
        title=title, url=url, author=repo.split("/")[0], summary_raw=summary_raw, event_time=event_time
    )
    await store.upsert_enrichment(
        item_id=item_id,
        summary_ai=summary_raw[:600],
        tags=["GitHub","Release"],
        keywords=[rel.get("tag_name","")],
        embedding=[],
        score=0.85,
        metadata={"repo": repo, "type": "release"},
    )
    await store.set_status(item_id, "enriched")

async def _upsert_tag(repo: str, tag: dict):
    store = get_store()
    await store.init()
    src_id = await store.upsert_source("github", repo, f"https://github.com/{repo}", 1.0)

    name = tag.get("name") or tag.get("ref") or "tag"
    origin_id = f"tag:{name}"
    title = f"🏷️ {repo} — Tag {name}"
    url = f"https://github.com/{repo}/releases/tag/{name}"
    event_time = None

    item_id = await store.insert_item(
        source_id=src_id, kind="github:tag", origin_id=origin_id,
        title=title, url=url, author=repo.split("/")[0], summary_raw="", event_time=event_time
    )
    await store.upsert_enrichment(
        item_id=item_id,
        summary_ai=f"New tag {name} in {repo}.",
        tags=["GitHub","Tag"],
        keywords=[name],
        embedding=[],
        score=0.78,
        metadata={"repo": repo, "type": "tag"},
    )
    await store.set_status(item_id, "enriched")

async def ingest_github_repos(repos: Iterable[str], token: Optional[str] = None, per_repo_limit: int = 3):
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(timeout=25) as client:
        for repo in repos or []:
            try:
                r = await client.get(f"{GITHUB_API}/repos/{repo}/releases", headers=headers, params={"per_page": per_repo_limit})
                if r.status_code == 200:
                    for rel in r.json()[:per_repo_limit]:
                        await _upsert_release(repo, rel)
            except Exception:
                pass

            try:
                r = await client.get(f"{GITHUB_API}/repos/{repo}/tags", headers=headers, params={"per_page": per_repo_limit})
                if r.status_code == 200:
                    for tag in r.json()[:per_repo_limit]:
                        await _upsert_tag(repo, tag)
            except Exception:
                pass

    store = get_store()
    await store.init()
    await store.refresh_digest()
