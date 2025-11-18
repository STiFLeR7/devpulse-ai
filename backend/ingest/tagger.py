# backend/ingest/tagger.py
from typing import List
import re

CATEGORY_KEYWORDS = {
    "AI": ["ai", "artificial intelligence", "machine learning", "deep learning", "neural network", "transformer", "llm"],
    "HF": ["huggingface", "hugging face", "hf.co", "🤗", "model hub"],
    "Research": ["paper", "arxiv", "study", "experiment", "methodology", "evaluation", "results", "we propose"],
    "Blog": ["blog", "personal", "opinion", "tutorial", "how to", "guide"],
    "Tooling": ["cli", "tool", "library", "package", "pip", "npm"],
    "Tutorial": ["tutorial", "how to", "step by step", "guide", "walkthrough"],
}

def tag_from_text(title: str, content: str, top_n=3) -> List[str]:
    text = f"{title}\n{content}".lower()
    scores = {}
    for tag, kws in CATEGORY_KEYWORDS.items():
        s = 0
        for kw in kws:
            if kw in text: s += 1
        if s > 0:
            scores[tag] = s
    # return tags sorted by score
    sorted_tags = sorted(scores.keys(), key=lambda t: scores[t], reverse=True)
    return sorted_tags[:top_n]
