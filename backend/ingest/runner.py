# backend/ingest/runner.py
import asyncio
from backend.db_rest import DB
from backend.store_rest import Store
from backend.ingest.core import Ingestor
from app.settings import settings


TARGET_REPOS = [
    "microsoft/onnxruntime",
    "google-deepmind/agent-lightning",
    "mistralai/mistral",
    "meta-llama/llama",
    "openai/whisper"
]


async def main():
    db = DB()
    store = Store(db)
    await store.init()

    ing = Ingestor(store, rate_qps=settings.RATE_QPS, concurrency=settings.MAX_CONCURRENCY)

    while True:
        for repo in TARGET_REPOS:
            try:
                await ing.ingest_github_events(repo, settings.GITHUB_TOKEN)
            except Exception as e:
                print(f"[ERR] {repo}: {e}")

        # refresh materialized digest for clean UI/API
        await store.refresh_digest()

        print("✅ cycle done… sleeping 60s")
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
