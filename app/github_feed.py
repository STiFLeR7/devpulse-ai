# app/github_feed.py
from __future__ import annotations

from typing import Dict, List, Optional
import os
import datetime as dt

import httpx

# ---- Public API -------------------------------------------------------------

def aggregate_all(
    repos: List[str],
    *,
    github_token: Optional[str] = None,
    per_repo_limit: int = 20,
    timeout_s: float = 12.0,
) -> List[Dict]:
    """
    Aggregate latest GitHub items (releases + recent tags) for the given repos.

    Returns a list of dicts shaped for store.upsert_items():
      {
        "source": "github",
        "external_id": "<stable id>",
        "title": "<repo>: <name> (tag|release)",
        "url": "<human html url>",
        "secondary_url": "<api/archive/url or None>",
        "author": "<login or org>",
        "created_at": "YYYY-MM-DDTHH:MM:SSZ",
        "raw_json": {...}  # original payload
      }
    """
    if not repos:
        return []

    token = github_token or os.getenv("GITHUB_TOKEN") or None
    headers = _build_headers(token)

    items: List[Dict] = []
    with httpx.Client(headers=headers, timeout=timeout_s) as client:
        for full in repos:
            owner_repo = full.strip().strip("/")
            if not owner_repo or "/" not in owner_repo:
                continue

            # 1) Releases (preferred)
            rels = _fetch_releases(client, owner_repo, per_repo_limit)
            items.extend([_release_to_item(owner_repo, r) for r in rels])

            # 2) Tags (fallback/supplement) — only keep tags that don't already exist by tag_name
            existing_tag_names = {r.get("tag_name") for r in rels if isinstance(r, dict)}
            tags = _fetch_recent_tags_with_dates(client, owner_repo, per_repo_limit)
            for t in tags:
                if t["name"] in existing_tag_names:
                    continue
                items.append(_tag_to_item(owner_repo, t))

    # sort newest first by created_at
    def _parse_ts(x: Dict) -> float:
        ts = x.get("created_at") or ""
        try:
            # Expecting RFC3339-like timestamps; normalize any missing 'Z'
            if ts.endswith("Z"):
                return dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").timestamp()
            # Try common formats
            return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0.0

    items.sort(key=_parse_ts, reverse=True)
    return items


# ---- GitHub fetchers --------------------------------------------------------

API_BASE = "https://api.github.com"

def _build_headers(token: Optional[str]) -> Dict[str, str]:
    h = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "devpulse-ai/ingestor",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _fetch_releases(client: httpx.Client, owner_repo: str, limit: int) -> List[Dict]:
    url = f"{API_BASE}/repos/{owner_repo}/releases"
    # Includes both published and pre-releases; GitHub returns newest first
    resp = client.get(url, params={"per_page": min(limit, 100)})
    if resp.status_code >= 400:
        return []
    data = resp.json()
    if not isinstance(data, list):
        return []
    return data[:limit]


def _fetch_recent_tags_with_dates(client: httpx.Client, owner_repo: str, limit: int) -> List[Dict]:
    """
    GitHub /tags doesn't include time. We fetch commit dates for each tag's commit SHA.
    Returns items like: {name, commit_sha, commit_date, html_url}
    """
    tags_url = f"{API_BASE}/repos/{owner_repo}/tags"
    r = client.get(tags_url, params={"per_page": min(limit, 100)})
    if r.status_code >= 400:
        return []

    tags = r.json()
    if not isinstance(tags, list):
        return []

    results: List[Dict] = []
    for t in tags[:limit]:
        name = t.get("name")
        commit = (t.get("commit") or {})
        sha = commit.get("sha")
        if not (name and sha):
            continue

        commit_date = _commit_date(client, owner_repo, sha)
        results.append({
            "name": name,
            "commit_sha": sha,
            "commit_date": commit_date,  # may be None
            "html_url": f"https://github.com/{owner_repo}/releases/tag/{name}",
            "zipball_url": f"https://api.github.com/repos/{owner_repo}/zipball/{name}",
            "tarball_url": f"https://api.github.com/repos/{owner_repo}/tarball/{name}",
        })

    # Most-recent first by commit_date (None goes last)
    def _k(x: Dict) -> str:
        return x.get("commit_date") or ""

    results.sort(key=_k, reverse=True)
    return results


def _commit_date(client: httpx.Client, owner_repo: str, sha: str) -> Optional[str]:
    url = f"{API_BASE}/repos/{owner_repo}/commits/{sha}"
    rr = client.get(url)
    if rr.status_code >= 400:
        return None
    j = rr.json()
    # Prefer committer date; fallback to author
    try:
        date = (
            (((j.get("commit") or {}).get("committer") or {}).get("date"))
            or (((j.get("commit") or {}).get("author") or {}).get("date"))
        )
        return date  # already ISO 8601
    except Exception:
        return None


# ---- Mappers ----------------------------------------------------------------

def _release_to_item(owner_repo: str, r: Dict) -> Dict:
    rid = r.get("id")  # stable numeric id for release
    tag = r.get("tag_name")
    name = r.get("name") or tag or "release"
    html = r.get("html_url") or f"https://github.com/{owner_repo}/releases"
    author_login = ((r.get("author") or {}).get("login")) or owner_repo.split("/")[0]
    published_at = r.get("published_at") or r.get("created_at")  # prefer published_at

    title = f"{owner_repo}: {name} (release)"
    secondary_url = r.get("tarball_url") or r.get("zipball_url")

    return {
        "source": "github",
        "external_id": f"gh_release_{owner_repo}_{rid or tag or name}",
        "title": title,
        "url": html,
        "secondary_url": secondary_url,
        "author": author_login,
        "created_at": _normalize_ts(published_at),
        "raw_json": r,
    }


def _tag_to_item(owner_repo: str, t: Dict) -> Dict:
    name = t.get("name") or "tag"
    html = t.get("html_url") or f"https://github.com/{owner_repo}/releases/tag/{name}"
    author_login = owner_repo.split("/")[0]
    created_at = t.get("commit_date")

    title = f"{owner_repo}: {name} (tag)"
    secondary_url = t.get("tarball_url") or t.get("zipball_url")

    return {
        "source": "github",
        "external_id": f"gh_tag_{owner_repo}_{name}",
        "title": title,
        "url": html,
        "secondary_url": secondary_url,
        "author": author_login,
        "created_at": _normalize_ts(created_at),
        "raw_json": t,
    }


def _normalize_ts(ts: Optional[str]) -> str:
    """
    Normalize various ISO formats to 'YYYY-MM-DDTHH:MM:SSZ'.
    If missing, use current UTC as a conservative default to avoid DB errors.
    """
    if not ts:
        return dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        if ts.endswith("Z"):
            # Already Zulu format
            dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
            return ts
        # Parse generic ISO and emit Z
        d = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return d.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
