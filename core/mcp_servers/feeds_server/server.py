from __future__ import annotations
import os
import sys
import json
import asyncio
from typing import Any, Iterable, List, Set
from datetime import datetime, timezone

from fastapi import FastAPI
import httpx
import feedparser
from email.utils import parsedate_to_datetime
from dotenv import load_dotenv

load_dotenv()  # read .env if present

# --------------------------- utils ---------------------------

def _csv(key: str) -> List[str]:
    raw = os.getenv(key, "") or ""
    return [x.strip() for x in raw.split(",") if x.strip()]

def _iso(s: str | None) -> datetime:
    if not s:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)

app = FastAPI(title="devpulse-ai Feeds Server", version="0.1.2")

@app.get("/")
async def index():
    return {
        "service": "devpulse-ai feeds",
        "routes": [
            "GET /health",
            "GET/POST /feeds/github",
            "GET/POST /feeds/hf/models",
            "GET/POST /feeds/hf/datasets",
            "GET/POST /feeds/medium",
        ],
    }

@app.get("/health")
async def health():
    return {"ok": True, "ts": datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M:%S")}

# --------------------------- GitHub ---------------------------

GITHUB_API = "https://api.github.com"

def _gh_headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json"}
    tok = os.getenv("GITHUB_TOKEN", "")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h

async def _maybe_backoff(r: httpx.Response):
    if r.status_code == 403 and r.headers.get("X-RateLimit-Remaining") == "0":
        reset = r.headers.get("X-RateLimit-Reset")
        try:
            now = int(datetime.now(timezone.utc).timestamp())
            delay = max(1, int(reset) - now) if reset else 1
        except Exception:
            delay = 1
        await asyncio.sleep(min(delay, 10))

async def _paginated(client: httpx.AsyncClient, url: str, params: dict | None = None, max_pages: int = 2) -> list:
    results = []
    page = 1
    headers = _gh_headers()
    while page <= max_pages:
        p = dict(params or {})
        p.setdefault("per_page", 100)
        p["page"] = page
        r = await client.get(url, headers=headers, params=p)
        await _maybe_backoff(r)
        if r.status_code == 404:
            break
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list) or not data:
            break
        results.extend(data)
        if len(data) < p["per_page"]:
            break
        page += 1
    return results

async def _list_org_repos(client: httpx.AsyncClient, org: str, limit: int) -> Set[str]:
    url = f"{GITHUB_API}/orgs/{org}/repos"
    data = await _paginated(client, url, params={"type": "public", "sort": "updated"}, max_pages=2)
    data.sort(key=lambda x: x.get("pushed_at") or x.get("updated_at") or "", reverse=True)
    return {f"{org}/{d['name']}" for d in data[:limit] if d.get("name")}

async def _list_user_repos(client: httpx.AsyncClient, user: str, limit: int) -> Set[str]:
    url = f"{GITHUB_API}/users/{user}/repos"
    data = await _paginated(client, url, params={"type": "public", "sort": "updated"}, max_pages=2)
    data.sort(key=lambda x: x.get("pushed_at") or x.get("updated_at") or "", reverse=True)
    return {f"{d['owner']['login']}/{d['name']}" for d in data[:limit] if d.get("name") and d.get("owner")}

async def _repos_from_watching(client: httpx.AsyncClient) -> Set[str]:
    url = f"{GITHUB_API}/user/subscriptions"
    data = await _paginated(client, url, max_pages=2)
    return {f"{d['owner']['login']}/{d['name']}" for d in data if d.get("owner") and d.get("name")}

async def _repos_from_starred(client: httpx.AsyncClient) -> Set[str]:
    url = f"{GITHUB_API}/user/starred"
    data = await _paginated(client, url, max_pages=2)
    return {f"{d['owner']['login']}/{d['name']}" for d in data if d.get("owner") and d.get("name")}

async def _list_following_accounts(client: httpx.AsyncClient) -> List[str]:
    url = f"{GITHUB_API}/user/following"
    data = await _paginated(client, url, max_pages=2)
    return [u["login"] for u in data if u.get("login")]

async def _latest_release_item(client: httpx.AsyncClient, repo: str, fallback_to_tags: bool) -> list[dict]:
    headers = _gh_headers()
    url = f"{GITHUB_API}/repos/{repo}/releases/latest"
    r = await client.get(url, headers=headers)
    if r.status_code == 404:
        if not fallback_to_tags:
            return []
        # fallback to latest tag
        t = await client.get(f"{GITHUB_API}/repos/{repo}/tags", headers=headers, params={"per_page": 1})
        await _maybe_backoff(t)
        if t.status_code == 404:
            return []
        t.raise_for_status()
        data = t.json()
        if not isinstance(data, list) or not data:
            return []
        tag = data[0]
        tag_name = tag.get("name") or "tag"
        ext_id = tag.get("commit", {}).get("sha") or tag_name
        return [{
            "source": "github",
            "type": "tag",
            "external_id": ext_id,
            "title": f"{repo}: {tag_name} (tag)",
            "url": f"https://github.com/{repo}/releases",
            "repo": repo,
            "published_at": datetime.now(timezone.utc).isoformat(),
            "raw": tag,
        }]
    await _maybe_backoff(r)
    r.raise_for_status()
    rel = r.json()
    external_id = str(rel.get("id"))
    title = rel.get("name") or rel.get("tag_name") or "release"
    published_at_str = rel.get("published_at") or rel.get("created_at")
    return [{
        "source": "github",
        "type": "release",
        "external_id": external_id,
        "title": f"{repo}: {title}",
        "url": rel.get("html_url") or rel.get("url"),
        "repo": repo,
        "published_at": _iso(published_at_str).isoformat(),
        "raw": rel,
    }]

@app.post("/feeds/github")
async def github_feed_post() -> dict:
    curated = _csv("GITHUB_REPOS")
    orgs = _csv("GITHUB_ORGS")
    users = _csv("GITHUB_USERS")
    use_watch = (os.getenv("GITHUB_USE_WATCHING", "false").lower() == "true")
    use_star = (os.getenv("GITHUB_USE_STARS", "false").lower() == "true")
    use_following = (os.getenv("GITHUB_USE_FOLLOWING", "false").lower() == "true")
    fallback_to_tags = (os.getenv("GITHUB_FALLBACK_TO_TAGS", "false").lower() == "true")
    try:
        discovery_limit = int(os.getenv("GITHUB_DISCOVERY_LIMIT", "30"))
    except ValueError:
        discovery_limit = 30

    repos: Set[str] = set(curated)
    async with httpx.AsyncClient(timeout=30.0) as client:
        if orgs:
            results = await asyncio.gather(*[_list_org_repos(client, o, discovery_limit) for o in orgs], return_exceptions=True)
            for r in results:
                if not isinstance(r, Exception):
                    repos |= r
        if users:
            results = await asyncio.gather(*[_list_user_repos(client, u, discovery_limit) for u in users], return_exceptions=True)
            for r in results:
                if not isinstance(r, Exception):
                    repos |= r
        if use_watch:
            try: repos |= await _repos_from_watching(client)
            except Exception: pass
        if use_star:
            try: repos |= await _repos_from_starred(client)
            except Exception: pass
        if use_following:
            try:
                accounts = await _list_following_accounts(client)
                results = await asyncio.gather(*[_list_user_repos(client, a, discovery_limit) for a in accounts], return_exceptions=True)
                for r in results:
                    if not isinstance(r, Exception):
                        repos |= r
            except Exception:
                pass

        sem = asyncio.Semaphore(8)
        async def _task(repo: str):
            async with sem:
                return await _latest_release_item(client, repo, fallback_to_tags)
        per_repo = await asyncio.gather(*[_task(r) for r in sorted(repos)], return_exceptions=True)

    items: list[dict[str, Any]] = []
    for r in per_repo:
        if isinstance(r, Exception):
            continue
        items.extend(r)
    return {"items": items}

@app.get("/feeds/github")
async def github_feed_get():
    return await github_feed_post()

# --------------------------- Hugging Face ---------------------------

def _hf_headers() -> dict[str, str]:
    hdr = {
        "Accept": "application/json",
        "User-Agent": "devpulse-ai/0.1 (+https://local) Python-httpx"
    }
    tok = os.getenv("HF_TOKEN", "")  # optional
    if tok:
        hdr["Authorization"] = f"Bearer {tok}"
    return hdr

async def _get_json_with_retries(client: httpx.AsyncClient, url: str, params: dict | None = None, max_retries: int = 3):
    attempt = 0
    while True:
        try:
            r = await client.get(url, headers=_hf_headers(), params=params)
            if r.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError("transient", request=r.request, response=r)
            try:
                return r.status_code, r.json(), None
            except Exception:
                return r.status_code, None, r.text
        except httpx.HTTPStatusError as e:
            attempt += 1
            if attempt > max_retries:
                body = None
                try: body = e.response.text
                except Exception: pass
                print(f"[HF] GET failed {url} status={getattr(e.response,'status_code',None)} body={str(body)[:300]}", file=sys.stderr)
                return getattr(e.response, "status_code", 0), None, body
            await asyncio.sleep(min(10.0, 0.5 * (2 ** (attempt - 1))))
        except Exception as e:
            attempt += 1
            if attempt > max_retries:
                print(f"[HF] GET exception {url}: {repr(e)}", file=sys.stderr)
                return 0, None, repr(e)
            await asyncio.sleep(min(10.0, 0.5 * (2 ** (attempt - 1))))

@app.post("/feeds/hf/models")
async def hf_models_post() -> dict:
    base = "https://huggingface.co/api/models"
    authors = _csv("HF_AUTHORS")
    tags = _csv("HF_MODEL_TAGS")
    try:
        limit = int(os.getenv("HF_LIMIT", "50"))
    except ValueError:
        limit = 50

    params_list = []
    if authors:
        for a in authors:
            params_list.append({"author": a, "sort": "last_modified", "direction": -1, "limit": limit})
    else:
        params_list.append({"sort": "last_modified", "direction": -1, "limit": limit})

    items: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for p in params_list:
            q = dict(p)
            if tags:
                q["tags"] = ",".join(tags)
            status, data, text = await _get_json_with_retries(client, base, params=q)
            if status != 200 or not isinstance(data, list):
                print(f"[HF models] Non-200 or bad JSON status={status} text={str(text)[:300]}", file=sys.stderr)
                continue
            for m in data:
                mid = m.get("modelId") or m.get("id")
                if not mid:
                    continue
                dt = m.get("lastModified") or m.get("createdAt")
                items.append({
                    "source": "hf-model",
                    "type": "model",
                    "external_id": mid,
                    "title": mid,
                    "url": f"https://huggingface.co/{mid}",
                    "repo": mid,
                    "published_at": _iso(dt).isoformat(),
                    "raw": m,
                })
    return {"items": items}

@app.get("/feeds/hf/models")
async def hf_models_get():
    return await hf_models_post()

@app.post("/feeds/hf/datasets")
async def hf_datasets_post() -> dict:
    base = "https://huggingface.co/api/datasets"
    authors = _csv("HF_AUTHORS")
    tags = _csv("HF_DATASET_TAGS")
    try:
        limit = int(os.getenv("HF_LIMIT", "50"))
    except ValueError:
        limit = 50

    params_list = []
    if authors:
        for a in authors:
            params_list.append({"author": a, "sort": "last_modified", "direction": -1, "limit": limit})
    else:
        params_list.append({"sort": "last_modified", "direction": -1, "limit": limit})

    items: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for p in params_list:
            q = dict(p)
            if tags:
                q["tags"] = ",".join(tags)
            status, data, text = await _get_json_with_retries(client, base, params=q)
            if status != 200 or not isinstance(data, list):
                print(f"[HF datasets] Non-200 or bad JSON status={status} text={str(text)[:300]}", file=sys.stderr)
                continue
            for d in data:
                did = d.get("id") or d.get("_id")
                if not did:
                    continue
                dt = d.get("lastModified") or d.get("createdAt")
                items.append({
                    "source": "hf-dataset",
                    "type": "dataset",
                    "external_id": did,
                    "title": did,
                    "url": f"https://huggingface.co/datasets/{did}",
                    "repo": did,
                    "published_at": _iso(dt).isoformat(),
                    "raw": d,
                })
    return {"items": items}

@app.get("/feeds/hf/datasets")
async def hf_datasets_get():
    return await hf_datasets_post()

# --------------------------- Medium ---------------------------

@app.post("/feeds/medium")
async def medium_feed_post() -> dict:
    feeds = _csv("MEDIUM_FEEDS")
    items: list[dict[str, Any]] = []
    for url in feeds:
        feed = feedparser.parse(url)
        for e in feed.entries[:20]:
            link = e.get("link")
            title = e.get("title") or "Medium Post"
            pub = None
            if getattr(e, "published", None):
                try:
                    pub = parsedate_to_datetime(e.published)
                except Exception:
                    pass
            if not pub and getattr(e, "updated", None):
                try:
                    pub = parsedate_to_datetime(e.updated)
                except Exception:
                    pass
            if not pub:
                pub = datetime.now(timezone.utc)
            ext_id = e.get("id") or link or f"{title}:{link}"
            items.append({
                "source": "medium",
                "type": "post",
                "external_id": ext_id,
                "title": title,
                "url": link,
                "repo": feed.feed.get("title", "medium"),
                "published_at": pub.isoformat(),
                "raw": {k: e.get(k) for k in e.keys()},
            })
    return {"items": items}

@app.get("/feeds/medium")
async def medium_feed_get():
    return await medium_feed_post()
# --------------------------- End ---------------------------