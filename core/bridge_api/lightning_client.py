# core/bridge_api/lightning_client.py
from __future__ import annotations
from typing import Dict, Any, Optional
import httpx
from app.settings import settings

base_env = getattr(settings, "AGENTLIGHTNING_URL", None)
key_env  = getattr(settings, "AGENTLIGHTNING_KEY", None)

class AgentLightning:
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None, timeout: float = 10.0):
        self.base = base_url or settings.AGENTLIGHTNING_URL or ""
        self.key = api_key or settings.AGENTLIGHTNING_KEY or ""
        self.timeout = timeout

    async def trigger(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.base:
            return {"skipped": True, "reason": "no AgentLightning URL configured"}
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        url = f"{self.base.rstrip('/')}/actions/{action}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            return r.json()
