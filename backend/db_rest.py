# backend/db_rest.py
from typing import Any, Dict, List, Optional
import httpx
from app.settings import settings

JSON = Dict[str, Any]

class SupabaseREST:
    """
    Minimal client for Supabase PostgREST using the service role key.
    Uses HTTPS only (works even if Postgres TCP/DNS is blocked).
    """
    def __init__(self, base_url: str | None = None, service_key: str | None = None, timeout: float = 20.0):
        self.base = (base_url or settings.SUPABASE_URL).rstrip("/")
        self.key = service_key or settings.SUPABASE_SERVICE_ROLE
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        return {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def select(self, table: str, params: Dict[str, str] | None = None) -> List[JSON]:
        url = f"{self.base}/rest/v1/{table}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.get(url, headers=self._headers(), params=params or {})
            r.raise_for_status()
            return r.json()

    async def insert(self, table: str, rows: List[JSON], upsert: bool = False, on_conflict: Optional[str] = None) -> List[JSON]:
        url = f"{self.base}/rest/v1/{table}"
        headers = self._headers()
        if upsert:
            headers["Prefer"] = "resolution=merge-duplicates"
        params = {}
        if on_conflict:
            params["on_conflict"] = on_conflict
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(url, headers=headers, params=params, json=rows)
            r.raise_for_status()
            return r.json() if r.content else []

    async def update(self, table: str, match: Dict[str, str], patch: JSON) -> List[JSON]:
        url = f"{self.base}/rest/v1/{table}"
        params = match  # e.g., {"id":"eq.123"}
        headers = self._headers()
        headers["Prefer"] = "return=representation"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.patch(url, headers=headers, params=params, json=patch)
            r.raise_for_status()
            return r.json() if r.content else []

    async def rpc(self, fn: str, args: JSON | None = None) -> Any:
        url = f"{self.base}/rest/v1/rpc/{fn}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(url, headers=self._headers(), json=args or {})
            r.raise_for_status()
            return r.json() if r.content else None
