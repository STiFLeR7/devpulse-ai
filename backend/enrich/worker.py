import asyncio
from backend.store_factory import get_store
from backend.enrich.pipeline import EnrichmentEngine
from backend.integrations.n8n_client import N8NClient
from app.settings import settings


async def process_batch(limit: int = 10):
    store = get_store()              # REST store (or PG later automatically)
    await store.init()               # no-op for REST, connect for PG

    engine = EnrichmentEngine(store)
    n8n = N8NClient(settings.N8N_WEBHOOK_URL)

    items = await engine.fetch_items_to_enrich(limit=limit)
    if not items:
        return

    for item in items:
        enriched = await engine.enrich(item)
        await store.upsert_enrichment(
            item_id=item["id"],
            summary_ai=enriched.summary,
            tags=enriched.tags,
            keywords=enriched.keywords,
            embedding=enriched.embedding,
            score=enriched.score,
            metadata=enriched.metadata,
        )
        await store.set_status(item["id"], "enriched")

        # fire digest refresh
        await store.refresh_digest()

        # route high signals to n8n
        if enriched.score >= settings.ALERT_SCORE_THRESHOLD:
            await n8n.send_signal({
                "title": item["title"],
                "url": item["url"],
                "tags": enriched.tags,
                "score": enriched.score,
                "summary": enriched.summary,
            })


async def main():
    await process_batch(limit=10)


if __name__ == "__main__":
    asyncio.run(main())
