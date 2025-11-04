from __future__ import annotations
from typing import Dict, Any
from backend.store_factory import get_store
from app.settings import settings
from core.bridge_api import gemini_client as gc

# optional: n8n + AgentLightning hooks (safe no-ops if you haven't created them)
try:
    from backend.integrations.n8n_client import N8NClient
except Exception:
    N8NClient = None

try:
    from core.bridge_api.lightning_client import AgentLightning
except Exception:
    AgentLightning = None

# Gemini summarizer (fallbacks inside)
from core.bridge_api.gemini_client import summarize_rank


class EnrichmentEngine:
    def __init__(self, store=None):
        self.store = store or get_store()
        self.n8n = N8NClient() if N8NClient else None
        self.al = AgentLightning() if AgentLightning else None

    async def run_once(self, limit: int = 25) -> Dict[str, Any]:
        await self.store.init()
        rows = await self.store.fetch_unenriched(limit=limit)
        updated = 0
        alerted = 0
        for r in rows:
            title = r.get("title") or ""
            raw = r.get("summary_raw") or ""
            enriched = await summarize_rank(title, raw)
            score = float(enriched.get("score") or 0.0)

            await self.store.upsert_enrichment(
                item_id=r["id"],
                summary_ai=enriched.get("summary"),
                tags=enriched.get("tags", []),
                keywords=[],
                embedding=[],
                score=score,
                metadata={},
            )
            await self.store.set_status(r["id"], "enriched")
            updated += 1

            if score >= settings.ALERT_SCORE_THRESHOLD:
                payload = {
                    "title": title,
                    "url": r.get("url"),
                    "tags": enriched.get("tags", []),
                    "summary": enriched.get("summary", ""),
                    "score": score,
                }
                # fire-and-forget; ignore errors
                if self.n8n:
                    try:
                        await self.n8n.send_signal(payload)
                    except Exception:
                        pass
                if self.al:
                    try:
                        await self.al.trigger("devpulse_high_signal", payload)
                    except Exception:
                        pass
                alerted += 1

        await self.store.refresh_digest()
        return {"updated": updated, "alerted": alerted, "checked": len(rows), "using_gemini": bool(getattr(gc, "_USE_GEMINI", False))}
