# backend/ingest/runner.py
"""
Simple ingestion runner wrapper.

Usage:
  python -m backend.ingest.runner --once --debug

Environment variables:
  INGEST_TARGET           = v1 | v2 | both   (default: v1)
  INGEST_GITHUB_REPOS     = comma separated list like "pytorch/pytorch,huggingface/transformers"
  GITHUB_TOKEN            = optional personal/access token for GitHub
  INGEST_HF_TOKEN         = optional HuggingFace token
  INGEST_MEDIUM_FEEDS     = comma separated Medium handles or feed URLs
  SUPABASE_URL            = postgres://... (Postgres connection string for v2 writes)
"""
import os
import asyncio
import argparse
import traceback
from typing import List

# dynamic imports so runner doesn't fail if modules change
async def run_github(repos: List[str], token: str):
    try:
        from backend.ingest import github
    except Exception as e:
        print("github module import failed:", e)
        return 0
    try:
        await github.ingest_github_repos(repos, token, per_repo_limit=5)
        print("github ingestion finished")
        return 1
    except Exception:
        print("github ingestion error:")
        traceback.print_exc()
        return 0

async def run_hf(allow_ids: List[str], token: str, hours: int = 72):
    try:
        from backend.ingest import hf
    except Exception as e:
        print("hf module import failed:", e)
        return 0
    try:
        # if allow_ids provided, pass them; else fetch recent
        if allow_ids:
            res = await hf.ingest_hf_models(allow_ids, token, hours=hours)
            print(f"hf models inserted: {res}")
        else:
            res = await hf.ingest_hf_models([], token, hours=hours)
            print(f"hf models inserted (recent): {res}")
        return 1
    except Exception:
        print("hf ingestion error:")
        traceback.print_exc()
        return 0

async def run_medium(feeds: List[str], hours: int = 72, limit: int | None = None):
    try:
        from backend.ingest import medium
    except Exception as e:
        print("medium module import failed:", e)
        return 0
    try:
        res = await medium.ingest_medium_feeds(feeds, hours=hours, limit=limit or None)
        print(f"medium inserted: {res}")
        return 1
    except Exception:
        print("medium ingestion error:")
        traceback.print_exc()
        return 0

async def main_once(args):
    # read env for configuration
    repos_env = os.getenv("INGEST_GITHUB_REPOS", "").strip()
    hf_allow = os.getenv("INGEST_HF_IDS", "").strip()
    medium_env = os.getenv("INGEST_MEDIUM_FEEDS", "").strip()

    github_repos = [r.strip() for r in repos_env.split(",") if r.strip()]
    hf_ids = [r.strip() for r in hf_allow.split(",") if r.strip()]
    medium_feeds = [r.strip() for r in medium_env.split(",") if r.strip()]

    github_token = os.getenv("GITHUB_TOKEN", "") or os.getenv("INGEST_GITHUB_TOKEN", "")
    hf_token = os.getenv("INGEST_HF_TOKEN", "") or os.getenv("HF_TOKEN", "")

    tasks = []
    # run in sequence to avoid bursting APIs; keep concurrent if you prefer
    if github_repos:
        print("Starting GitHub ingestion for:", github_repos)
        await run_github(github_repos, github_token)
    else:
        print("No GITHUB_REPOS provided; skipping GitHub ingestion.")

    # HF
    print("Starting HuggingFace ingestion (recent models)...")
    await run_hf(hf_ids, hf_token, hours=int(os.getenv("INGEST_HOURS", "72")))

    # Medium
    if medium_feeds:
        print("Starting Medium ingestion for:", medium_feeds)
        await run_medium(medium_feeds, hours=int(os.getenv("INGEST_HOURS", "72")))
    else:
        print("No medium feeds provided; skipping Medium ingestion.")

    print("Runner: all tasks finished.")

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true", help="Run once and exit")
    p.add_argument("--debug", action="store_true", help="Debug/verbose")
    return p.parse_args()

if __name__ == "__main__":
    args = parse_args()
    if args.debug:
        print("Runner starting (debug mode). INGEST_TARGET:", os.getenv("INGEST_TARGET"))
    if args.once:
        asyncio.run(main_once(args))
    else:
        # simple loop: run every N seconds (useful for local testing)
        interval = int(os.getenv("INGEST_LOOP_SECONDS", "3600"))
        async def loop_runner():
            while True:
                await main_once(args)
                print(f"Sleeping {interval}s before next ingestion cycle...")
                await asyncio.sleep(interval)
        asyncio.run(loop_runner())
