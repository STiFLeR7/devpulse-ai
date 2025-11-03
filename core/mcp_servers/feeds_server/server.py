# Optional MCP stub – pulls and upserts
import asyncio
from app.github_feed import aggregate_all
from app.store import upsert_items

async def run_once():
    items = await aggregate_all()
    upsert_items(items)

if __name__ == "__main__":
    asyncio.run(run_once())
