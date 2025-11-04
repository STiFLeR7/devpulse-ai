# backend/db_rest.py
from typing import Any, Dict, List, Optional
import httpx
from app.settings import settings

JSON = Dict[str, Any]


class SupabaseREST:
    """
    Minimal PostgREST client using the Supabase key (service role preferred).
    Sends both `apikey` and `Authorization: Bearer ...` as required.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        jwt_key: Optional[str] = None,
        timeout: float = 20.0,
    ):
        self.base = (base_url or settings.SUPABASE_URL).rstrip("/")
        self.key = (jwt_key or settings.SUPABASE_JWT).strip()
        if not self.key:
            raise RuntimeError(
                "Supabase key missing. Set SUPABASE_SERVICE_ROLE or SUPABASE_KEY in .env"
            )
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        return {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def select(self, table: str, params: Optional[Dict[str, str]] = None) -> List[JSON]:
        url = f"{self.base}/rest/v1/{table}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.get(url, headers=self._headers(), params=params or {})
            r.raise_for_status()
            return r.json()

    async def insert(
        self,
        table: str,
        rows: List[JSON],
        *,
        upsert: bool = False,
        on_conflict: Optional[str] = None,
        return_representation: bool = True,
    ) -> List[JSON]:
        url = f"{self.base}/rest/v1/{table}"
        headers = self._headers()
        params: Dict[str, str] = {}
        if upsert:
            headers["Prefer"] = "resolution=merge-duplicates"
        if return_representation:
            headers["Prefer"] = headers.get("Prefer", "") + (
                ("," if "Prefer" in headers else "") + "return=representation"
            )
        if on_conflict:
            params["on_conflict"] = on_conflict
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(url, headers=headers, params=params, json=rows)
            r.raise_for_status()
            return r.json() if r.content else []

    async def update(
        self, table: str, match: Dict[str, str], patch: JSON, return_representation: bool = False
    ) -> List[JSON]:
        url = f"{self.base}/rest/v1/{table}"
        headers = self._headers()
        if return_representation:
            headers["Prefer"] = "return=representation"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.patch(url, headers=headers, params=match, json=patch)
            r.raise_for_status()
            return r.json() if r.content else []

    async def rpc(self, fn: str, args: Optional[JSON] = None) -> Any:
        url = f"{self.base}/rest/v1/rpc/{fn}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(url, headers=self._headers(), json=args or {})
            r.raise_for_status()
            return r.json() if r.content else None
