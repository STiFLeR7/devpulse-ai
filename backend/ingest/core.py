# backend/ingest/core.py

import asyncio
import httpx
from datetime import datetime
from aiolimiter import AsyncLimiter

from backend.store_rest import Store


class Ingestor:
    def __init__(self, store: Store, rate_qps: float = 5.0, concurrency: int = 10):
        self.store = store
        self.client = httpx.AsyncClient(timeout=30)
        self.rate = AsyncLimiter(max_rate=rate_qps, time_period=1)
        self.sem = asyncio.Semaphore(concurrency)

    async def fetch_json(self, url: str, headers=None):
        async with self.rate, self.sem:
            r = await self.client.get(url, headers=headers)
            r.raise_for_status()
            return r.json()

    async def ingest_github_events(self, repo: str, token: str):
        url = f"https://api.github.com/repos/{repo}/commits"
        headers = {"Authorization": f"Bearer {token}"}

        # Ensure source row exists
        source_id = await self.store.upsert_source("github", repo, f"https://github.com/{repo}")

        data = await self.fetch_json(url, headers=headers)

        for commit in data:
            sha = commit["sha"]
            info = commit["commit"]
            msg = info["message"]
            author = info.get("author", {}).get("name")
            ts = info.get("author", {}).get("date")

            item_id = await self.store.insert_item(
                source_id=source_id,
                kind="github",
                origin_id=f"{repo}@{sha}",
                title=msg.split("\n")[0],
                url=f"https://github.com/{repo}/commit/{sha}",
                author=author,
                summary_raw=msg,
                event_time=datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
            )

            # Mark as "new" — enrichment worker will pick up
            # No status change here; default is already new

        return True

    async def close(self):
        await self.client.aclose()
