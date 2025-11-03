import asyncio
import httpx
import os

BRIDGE = os.getenv("BRIDGE_API_URL", "http://127.0.0.1:8000")

async def main():
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(f"{BRIDGE}/trigger/daily", params={"dry_run": True})
        r.raise_for_status()
        data = r.json()
        digest = data.get("digest", {})
        for sec in digest.get("sections", []):
            print(f"=== {sec['section'].upper()} ===")
            for it in sec.get("items", [])[:10]:
                print(f"- {it['title']}  ({it['published_at']})")
                print(f"  {it['url']}")
        print("\nCounts:", data.get("counts"))

if __name__ == "__main__":
    asyncio.run(main())
