import httpx, re
from datetime import datetime, timezone
from typing import List
from .settings import settings

REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

def _utcnow():
    return datetime.now(timezone.utc)

async def fetch_github() -> list[dict]:
    if not settings.ENABLE_GITHUB:
        return []
    repos: List[str] = [r.strip() for r in (settings.GITHUB_REPOS or []) if REPO_RE.match(r.strip())]
    if not repos:
        return []
    headers = {"Accept": "application/vnd.github+json"}
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"

    items: list[dict] = []
    async with httpx.AsyncClient(timeout=30) as client:
        for repo in repos:
            owner, name = repo.split("/", 1)

            # Releases (preferred)
            try:
                r = await client.get(f"https://api.github.com/repos/{owner}/{name}/releases", headers=headers)
                if r.status_code == 200:
                    for rel in r.json()[:3]:
                        tag = rel.get("tag_name") or rel.get("name") or "release"
                        published = rel.get("published_at") or rel.get("created_at")
                        dt = _utcnow() if not published else datetime.fromisoformat(published.replace("Z","+00:00"))
                        items.append({
                            "source": "github",
                            "external_id": f"{repo}@{tag}",
                            "title": f"{repo}: {tag}",
                            "url": f"https://github.com/{repo}",
                            "secondary_url": rel.get("html_url"),
                            "published_at": dt,
                        })
            except Exception:
                pass

            # Tags (fallback/extra)
            try:
                r = await client.get(f"https://api.github.com/repos/{owner}/{name}/tags", headers=headers)
                if r.status_code == 200:
                    for t in r.json()[:2]:
                        tagname = t.get("name")
                        items.append({
                            "source": "github",
                            "external_id": f"{repo}@{tagname}",
                            "title": f"{repo}: {tagname} (tag)",
                            "url": f"https://github.com/{repo}",
                            "secondary_url": f"https://github.com/{repo}/releases/tag/{tagname}",
                            "published_at": _utcnow(),
                        })
            except Exception:
                pass
    return items
