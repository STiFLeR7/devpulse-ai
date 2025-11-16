# backend/enrich/pipeline.py
from __future__ import annotations

from typing import Dict, Any, List
import asyncio

from app.settings import settings
from backend.store_factory import get_store

# Optional n8n notifier (guarded)
try:
    from backend.integrations.n8n_client import N8NClient  # type: ignore
except Exception:
    N8NClient = None  # type: ignore


class EnrichmentEngine:
    """
    Pull 'new' items, summarize+score with Gemini (fallback heuristics),
    upsert into item_enriched, flip status->'enriched', and optionally
    send high-signal alerts to n8n.
    """

    def __init__(self):
        self.store = get_store()
        self.n8n = N8NClient() if N8NClient else None
        self.threshold = float(settings.ALERT_SCORE_THRESHOLD or 0.80)

    async def _enrich_item(self, it: Dict[str, Any]) -> Dict[str, Any]:
        from core.bridge_api.gemini_client import summarize_rank

        title = it.get("title") or ""
        raw = it.get("summary_raw") or title
        res = await summarize_rank(title, raw)

        # normalize + guard
        summary_ai = str(res.get("summary") or "")[:1000]
        tags = [str(t).strip().lower() for t in (res.get("tags") or []) if str(t).strip()]
        score = float(res.get("score") or 0.0)
        keywords: List[str] = []

        return {
            "summary_ai": summary_ai,
            "tags": tags[:8],
            "keywords": keywords,
            "embedding": [],
            "score": score,
            "metadata": {},
        }

    async def run_once(self, limit: int = 25) -> Dict[str, Any]:
        await self.store.init()

        items = await self.store.fetch_unenriched(limit=limit)
        if not items:
            return {"updated": 0, "alerted": 0, "checked": 0, "using_gemini": True}

        updated = 0
        alerted = 0

        for it in items:
            enriched = await self._enrich_item(it)
            await self.store.upsert_enrichment(
                item_id=it["id"],
                summary_ai=enriched["summary_ai"],
                tags=enriched["tags"],
                keywords=enriched["keywords"],
                embedding=enriched["embedding"],
                score=enriched["score"],
                metadata=enriched["metadata"],
            )
            await self.store.set_status(it["id"], "enriched")
            updated += 1

            # high-signal alert
            if self.n8n and enriched["score"] >= self.threshold:
                try:
                    await self.n8n.send_signal(
                        title=it.get("title") or "(no title)",
                        url=it.get("url") or "",
                        score=enriched["score"],
                        tags=enriched["tags"],
                        summary=enriched["summary_ai"],
                    )
                    alerted += 1
                except Exception:
                    # don't fail the whole batch on notifier error
                    pass

        # refresh the digest view/materialized view if present
        try:
            await self.store.refresh_digest()
        except Exception:
            pass

        return {"updated": updated, "alerted": alerted, "checked": len(items), "using_gemini": True}
