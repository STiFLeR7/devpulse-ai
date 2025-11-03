# utils/scripts/ping_n8n.py
import asyncio
import httpx
from app.settings import settings
print(settings.N8N_WEBHOOK_URL)
async def main():
    payload = {
        "title": "🔥 DevPulse test signal",
        "url": "https://github.com/ai-edge/warp-quant",
        "tags": ["LLM", "EdgeAI"],
        "score": 0.91,
        "summary": "W4A8 adaptive quantization improves RTX 3050 inference by 3.1x"
    }
    async with httpx.AsyncClient(timeout=5) as client:
        r = await client.post(settings.N8N_WEBHOOK_URL, json=payload)
        print("status", r.status_code)

if __name__ == "__main__":
    asyncio.run(main())
