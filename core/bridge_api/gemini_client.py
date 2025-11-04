# core/bridge_api/gemini_client.py
from __future__ import annotations
from typing import Dict, Any
import json, re, asyncio
from app.settings import settings

_USE_GEMINI = False
_ERR: str | None = None

try:
    import google.generativeai as genai
    if settings.GEMINI_API_KEY and settings.GEMINI_API_KEY.strip():
        genai.configure(api_key=settings.GEMINI_API_KEY.strip())
        _USE_GEMINI = True
    else:
        _ERR = "GEMINI_API_KEY not set"
except Exception as e:
    _ERR = f"gemini sdk import/config failed: {e!r}"


_SYSTEM = (
    "You are an AI/ML engineering news ranker. "
    "Given title and raw summary, return compact JSON with keys exactly:\n"
    "summary (<=40 words), tags (<=5 single-token lowercase), score (0..1 float).\n"
    "Bias toward LLMs, multimodal/VLMs, CUDA/inference/quantization, agents, KD/distillation, edge efficiency."
)

def _heuristic_score(title: str, raw: str) -> float:
    s = (title + " " + raw).lower()
    keys = ["quantization","cuda","llm","agent","distillation","efficient","inference","vision","bitsandbytes","lora"]
    hits = sum(k in s for k in keys)
    base = 0.72
    return min(base + 0.04 * hits, 0.94)

def _fallback(title: str, raw: str) -> Dict[str, Any]:
    return {
        "summary": (raw or title)[:220],
        "tags": [],
        "score": _heuristic_score(title, raw or ""),
        "_fallback": True,
        "_reason": _ERR or "no-sdk",
    }

def _parse_json_block(txt: str) -> Dict[str, Any]:
    # extract first JSON object from free-form text
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        # light repair: remove trailing commas etc.
        cleaned = re.sub(r",\s*}", "}", m.group(0))
        cleaned = re.sub(r",\s*]", "]", cleaned)
        try:
            return json.loads(cleaned)
        except Exception:
            return {}

async def summarize_rank(title: str, raw: str) -> Dict[str, Any]:
    # Fast path: no Gemini available
    if not _USE_GEMINI:
        return _fallback(title, raw)

    prompt = (
        f"{_SYSTEM}\n\n"
        f"TITLE:\n{title}\n\n"
        f"RAW:\n{raw}\n\n"
        "Return JSON only."
    )

    # The SDK call is sync; run it in a thread to avoid blocking.
    def _call():
        model = genai.GenerativeModel("gemini-1.5-flash")
        out = model.generate_content(prompt)
        return out.text or ""

    try:
        txt = await asyncio.to_thread(_call)
        data = _parse_json_block(txt)
        if not data:
            # guard rails: fallback if model returns non-JSON
            return _fallback(title, raw)

        # normalize fields
        summary = str(data.get("summary") or "")[:400]
        tags = data.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip().lower() for t in re.split(r"[,\s]+", tags) if t.strip()]
        else:
            tags = [str(t).strip().lower() for t in tags if str(t).strip()]

        try:
            score = float(data.get("score"))
        except Exception:
            score = _heuristic_score(title, raw or "")

        return {"summary": summary, "tags": tags[:5], "score": score}
    except Exception as e:
        # network/quota/etc. → graceful degrade
        global _ERR
        _ERR = f"gemini call failed: {e!r}"
        return _fallback(title, raw)
