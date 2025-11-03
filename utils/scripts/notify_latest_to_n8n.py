import os
import json
import math
import httpx
from datetime import datetime, timezone
from typing import Dict, Any, List

# reuse your local app settings + store (SQLite)
from app.settings import settings  # uses .env
from app.store import latest_items  # reads from devpulse.sqlite


def recency_score(iso: str | None, halflife_hours: float = 24.0) -> float:
    """
    Exponential decay by recency. 1.0 if now; ~0.5 after halflife_hours.
    """
    if not iso:
        return 0.0
    try:
        # SQLite timestamps are "YYYY-MM-DD HH:MM:SS"
        if "T" in iso:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(iso, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return 0.0

    now = datetime.now(timezone.utc)
    hours = (now - dt).total_seconds() / 3600.0
    return math.exp(-math.log(2) * (hours / halflife_hours))


def build_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    # minimal fields; tags empty for now (Phase-1)
    title = row.get("title") or "(no title)"
    url = row.get("url") or ""
    discovered = row.get("discovered_at") or row.get("created_at")

    score = recency_score(discovered, halflife_hours=24.0)
    payload = {
        "idempotency_key": f"{row.get('source','github')}::{row.get('external_id','')}",
        "source": row.get("source", "github"),
        "title": title,
        "url": url,
        "tags": [],                  # add later from enrichment
        "score": round(float(score), 4),
        "summary": title,            # placeholder; Phase-2 enrichment will fill real summary
    }
    return payload


async def main():
    n8n_url = os.getenv("N8N_WEBHOOK_URL", "http://localhost:5678/webhook/devpulse/new-signal")
    threshold = float(os.getenv("ALERT_SCORE_THRESHOLD", "0.80"))

    rows: List[Dict[str, Any]] = latest_items(limit=settings.digest_limit)
    if not rows:
        print("no items found; run /ingest/run first")
        return

    # sort newest first by discovered_at/created_at (already ordered by latest_items)
    selected = []
    for r in rows:
        p = build_payload(r)
        if p["score"] >= threshold:
            selected.append(p)

    print(f"selected {len(selected)} items (≥ {threshold}) for alerting")

    async with httpx.AsyncClient(timeout=5.0) as client:
        for p in selected:
            try:
                r = await client.post(n8n_url, json=p)
                print("=>", p["title"][:80], r.status_code)
            except Exception as e:
                print("post error:", e)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
