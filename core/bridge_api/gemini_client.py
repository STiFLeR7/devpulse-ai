# core/bridge_api/gemini_client.py
from __future__ import annotations

from typing import Any, Dict, List
import asyncio
import json
import re

from app.settings import settings

_USE_GEMINI: bool = False
_ERR: str | None = None

try:
    import google.generativeai as genai  # type: ignore

    if settings.GEMINI_API_KEY and settings.GEMINI_API_KEY.strip():
        genai.configure(api_key=settings.GEMINI_API_KEY.strip())
        _USE_GEMINI = True
    else:
        _ERR = "GEMINI_API_KEY not set"
except Exception as e:  # pragma: no cover
    _ERR = f"gemini sdk import/config failed: {e!r}"


_SYSTEM_RANK = (
    "You are an AI/ML engineering news ranker. "
    "Given title and raw summary, return compact JSON with keys exactly:\n"
    "summary (<=40 words), tags (<=5 single-token lowercase), score (0..1 float).\n"
    "Bias toward LLMs, multimodal/VLMs, CUDA/inference/quantization, agents, KD/distillation, edge efficiency."
)


def _heuristic_score(title: str, raw: str) -> float:
    s = (title or "") + " " + (raw or "")
    s = s.lower()
    keys = [
        "quantization", "cuda", "llm", "agent", "distillation",
        "efficient", "inference", "vision", "bitsandbytes", "lora",
    ]
    hits = sum(k in s for k in keys)
    base = 0.72
    return min(base + 0.04 * hits, 0.94)


def _fallback(title: str, raw: str) -> Dict[str, Any]:
    return {
        "summary": (raw or title or "")[:220],
        "tags": [],
        "score": _heuristic_score(title, raw or ""),
        "_fallback": True,
        "_reason": _ERR or "no-sdk",
    }


def _parse_json_block(txt: str) -> Dict[str, Any]:
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        cleaned = re.sub(r",\s*}", "}", m.group(0))
        cleaned = re.sub(r",\s*]", "]", cleaned)
        try:
            return json.loads(cleaned)
        except Exception:
            return {}


async def summarize_rank(title: str, raw: str) -> Dict[str, Any]:
    """Summarize + tag + score a single item. Uses Gemini if available, else heuristic fallback."""
    if not _USE_GEMINI:
        return _fallback(title, raw)

    prompt = (
        f"{_SYSTEM_RANK}\n\n"
        f"TITLE:\n{title}\n\n"
        f"RAW:\n{raw}\n\n"
        "Return JSON only."
    )

    def _call():
        model = genai.GenerativeModel("gemini-1.5-flash")
        out = model.generate_content(prompt)
        return out.text or ""

    try:
        txt = await asyncio.to_thread(_call)
        data = _parse_json_block(txt)
        if not data:
            return _fallback(title, raw)

        summary = str(data.get("summary") or "")[:400]
        tags = data.get("tags") or []
        if isinstance(tags, str):
            import re as _re
            tags = [_t.strip().lower() for _t in _re.split(r"[,\s]+", tags) if _t.strip()]
        else:
            tags = [str(t).strip().lower() for t in tags if str(t).strip()]

        try:
            score = float(data.get("score"))
        except Exception:
            score = _heuristic_score(title, raw or "")

        return {"summary": summary, "tags": tags[:5], "score": score}
    except Exception as e:  # pragma: no cover
        global _ERR
        _ERR = f"gemini call failed: {e!r}"
        return _fallback(title, raw)


async def summarize_daily_brief(items: List[dict]) -> Dict[str, Any]:
    """
    Produce a short executive brief over a list of items.
    Returns: { "headline": str, "brief": str, "bullets": [str], "themes": [str] }
    Falls back to heuristic if Gemini is unavailable or errors.
    """
    if not items:
        return {
            "headline": "Quiet day",
            "brief": "No significant AI/ML updates detected in the selected window.",
            "bullets": [],
            "themes": [],
        }

    if not _USE_GEMINI:
        tops = [f"- {i.get('title','(no title)')}" for i in items[:3]]
        return {
            "headline": "AI/ML updates — quick scan",
            "brief": "Summaries generated without model (fallback heuristics).",
            "bullets": tops,
            "themes": ["fallback"],
        }

    # Build compact context (keep token usage tight)
    lines = []
    for i, it in enumerate(items[:30]):
        title = (it.get("title") or "")[:180]
        summ = (it.get("summary_ai") or "")[:300]
        score = it.get("score", 0)
        tags = ", ".join((it.get("tags") or [])[:5])
        lines.append(f"{i+1}. ({score}) {title}\n   {summ}\n   tags: {tags}")

    prompt = (
        "You are an AI/ML news editor for senior engineers. You will receive a list "
        "of top-ranked items (score 0..1) with summaries and tags from the last 24 hours. "
        "Write a concise executive brief:\n"
        "- headline: one line, 8-14 words\n"
        "- brief: 2-3 sentences capturing the gist\n"
        "- bullets: 3-6 bullets (<=18 words each), concrete and non-redundant\n"
        "- themes: 3-5 single-token or hyphenated tags summarizing trends\n"
        "Return STRICT JSON with keys: headline, brief, bullets, themes.\n\n"
        "ITEMS:\n" + "\n".join(lines)
    )

    def _call():
        model = genai.GenerativeModel("gemini-2.0-flash")
        out = model.generate_content(prompt)
        return out.text or ""

    try:
        txt = await asyncio.to_thread(_call)
        data = _parse_json_block(txt)
        if not data:
            return {
                "headline": "AI/ML daily digest",
                "brief": "Model returned non-JSON; falling back to heuristic list of top items.",
                "bullets": [f"- {it.get('title','(no title)')}" for it in items[:5]],
                "themes": ["parse-fallback"],
            }
        headline = str(data.get("headline") or "")[:140]
        brief = str(data.get("brief") or "")[:420]
        bullets = data.get("bullets") or []
        bullets = [str(b)[:140] for b in bullets][:6]
        themes = data.get("themes") or []
        themes = [str(t).lower().strip().replace(" ", "-") for t in themes][:5]
        return {"headline": headline, "brief": brief, "bullets": bullets, "themes": themes}
    except Exception as e:  # pragma: no cover
        return {
            "headline": "AI/ML daily digest",
            "brief": f"Gemini call failed; fallback applied. {e}",
            "bullets": [f"- {it.get('title','(no title)')}" for it in items[:5]],
            "themes": ["error-fallback"],
        }
