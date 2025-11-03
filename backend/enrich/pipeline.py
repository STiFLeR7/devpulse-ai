# backend/enrich/pipeline.py

import asyncio
import httpx
import math
from datetime import datetime, timezone
from sentence_transformers import SentenceTransformer

from app.settings import settings
from backend.store_rest import Store


class EnrichmentEngine:
    def __init__(self, store: Store):
        self.store = store
        self.client = httpx.AsyncClient(timeout=40)
        self.embed_model = SentenceTransformer(settings.HF_EMBED_MODEL if hasattr(settings, "HF_EMBED_MODEL") else "sentence-transformers/all-MiniLM-L6-v2")

    async def summarize(self, title: str, text: str, url: str):
        prompt = f"""
You are an AI technical analyst.
Condense and categorize the content into structured JSON:

Input:
Title: {title}
URL: {url}
Text: {text}

Output JSON fields:
- summary (max 80 words, technical, signal-focused)
- tags (5-8 tags, broad research/tech categories: LLM, Vision, CUDA, Quantization, KD, Agents, Systems, Infra)
- keywords (8–12 concise technical tokens)
"""
        endpoint = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{getattr(settings, 'GEMINI_MODEL_SUMMARY', 'gemini-1.5-pro')}"
            f":generateContent?key={settings.GEMINI_API_KEY}"
        )
        body = {"contents": [{"parts": [{"text": prompt}]}]}

        r = await self.client.post(endpoint, json=body)
        r.raise_for_status()
        text_out = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        try:
            out = eval(text_out)
        except Exception:
            out = {"summary": text_out, "tags": [], "keywords": []}
        return out["summary"], out.get("tags", []), out.get("keywords", [])

    async def embed(self, text: str):
        try:
            return self.embed_model.encode(text).tolist()
        except Exception:
            return self.embed_model.encode(text).tolist()

    def score_item(self, *, tags, keywords, event_time, src_weight):
        now = datetime.now(timezone.utc)
        hours = (now - event_time).total_seconds() / 3600 if event_time else 0
        decay = math.exp(-math.log(2) * hours / float(getattr(settings, "SCORE_DECAY_HALFLIFE_HRS", 48.0)))
        richness = min(1.0, (len(tags) + len(keywords)) / 20)
        score = (0.55 * decay) + (0.35 * (src_weight or 1.0)) + (0.10 * richness)
        return round(score, 4)
