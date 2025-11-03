# backend/integrations/n8n_client.py
import httpx, hmac, hashlib
from typing import Dict, Any
from app.settings import settings

def _sign(payload: Dict[str, Any]) -> str:
    # deterministic compact canonicalization
    import json
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hmac.new(settings.N8N_SHARED_SECRET.encode(), body, hashlib.sha256).hexdigest()

class N8NClient:
    def __init__(self, webhook_url: str | None = None, timeout_s: float = 5.0):
        self.webhook_url = webhook_url or settings.N8N_WEBHOOK_URL
        self.timeout_s = timeout_s

    async def post_signal(self, payload: Dict[str, Any]) -> None:
        sig = _sign(payload)
        headers = {
            "x-devpulse-key": settings.N8N_SHARED_SECRET,
            "x-devpulse-signature": sig,
            "content-type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                await client.post(self.webhook_url, json=payload, headers=headers)
        except Exception:
            # plug your logger here if you want
            pass
