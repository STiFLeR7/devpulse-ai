from supabase import create_client, Client
from dotenv import load_dotenv
import os
from datetime import datetime, timezone

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def main():
    # 1) ensure a source exists
    src = {
        "kind": "github",
        "name": "devpulse-mock",
        "url": "https://github.com/devpulse/mock",
        "weight": 1.0,
    }
    supabase.table("sources").upsert(src, on_conflict="kind,url").execute()
    src_id = supabase.table("sources").select("id").eq("kind", "github").eq("url", src["url"]).limit(1).single().execute().data["id"]

    # 2) insert/update one item
    now = datetime.now(timezone.utc).isoformat()
    item = {
        "source_id": src_id,
        "kind": "github:repo",
        "origin_id": f"mock-{int(datetime.now().timestamp())}",
        "title": "🔥 DevPulse Mock Signal — Quantization speedup",
        "url": "https://example.com/devpulse-mock",
        "author": "devpulse",
        "summary_raw": "Mock raw summary to validate pipeline.",
        "event_time": now,
        "status": "new",
    }
    item_res = supabase.table("items").upsert(item, on_conflict="kind,origin_id").execute()
    # fetch id (upsert may or may not return row depending on settings)
    it = supabase.table("items").select("id").eq("kind","github:repo").eq("origin_id", item["origin_id"]).single().execute().data
    item_id = it["id"]

    # 3) add enrichment with a high score (so n8n IF > 0.8 passes)
    enrich = {
        "item_id": item_id,
        "summary_ai": "W4A8 adaptive quantization improves RTX 3050 inference by 3.1x.",
        "tags": ["LLM","EdgeAI","Quantization"],
        "keywords": ["W4A8","adaptive","RTX3050"],
        "embedding": [],  # store later via pgvector RPC
        "score": 0.91,
        "metadata": {},
        "updated_at": now,
    }
    supabase.table("item_enriched").upsert(enrich, on_conflict="item_id").execute()

    # 4) mark enriched and refresh digest view (RPC is a no-op if you kept it simple)
    supabase.table("items").update({"status": "enriched"}).eq("id", item_id).execute()
    try:
        supabase.rpc("refresh_mv_digest", {}).execute()
    except Exception:
        pass

    print("Seeded item_id:", item_id)

if __name__ == "__main__":
    main()
