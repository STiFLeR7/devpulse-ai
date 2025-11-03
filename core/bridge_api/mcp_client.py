from __future__ import annotations
import os
from typing import Any
import httpx
from dotenv import load_dotenv

load_dotenv()

FEEDS_URL = os.getenv("FEEDS_SERVER_URL", "http://127.0.0.1:9001")

class MCPClient:
    def __init__(self, base: str | None = None):
        self.base = base or FEEDS_URL
        self.client = httpx.AsyncClient(timeout=60.0)

    async def close(self):
        await self.client.aclose()

    async def github(self) -> list[dict[str, Any]]:
        r = await self.client.post(f"{self.base}/feeds/github")
        r.raise_for_status()
        return r.json().get("items", [])

    async def hf_models(self) -> list[dict[str, Any]]:
        r = await self.client.post(f"{self.base}/feeds/hf/models")
        r.raise_for_status()
        return r.json().get("items", [])

    async def hf_datasets(self) -> list[dict[str, Any]]:
        r = await self.client.post(f"{self.base}/feeds/hf/datasets")
        r.raise_for_status()
        return r.json().get("items", [])

    async def medium(self) -> list[dict[str, Any]]:
        r = await self.client.post(f"{self.base}/feeds/medium")
        r.raise_for_status()
        return r.json().get("items", [])
# --------------------------- End ---------------------------