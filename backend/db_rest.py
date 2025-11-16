from __future__ import annotations

import httpx
from app.settings import settings


class SupabaseREST:
    """
    Minimal async REST client for Supabase/PostgREST.
    """

    def __init__(self) -> None:
        self.base = settings.SUPABASE_URL.rstrip("/") + "/rest/v1"
        self.headers = {
            "apikey": settings.SUPABASE_JWT,
            "Authorization": f"Bearer {settings.SUPABASE_JWT}",
        }

    # ---- CRUD ----
    async def select(self, table: str, params: dict):
        async with httpx.AsyncClient(timeout=30) as s:
            r = await s.get(f"{self.base}/{table}", params=params, headers=self.headers)
            r.raise_for_status()
            return r.json()

    async def insert(
        self,
        table: str,
        rows,
        *,
        upsert: bool = False,
        on_conflict: str | None = None,
        return_representation: bool = True,
    ):
        headers = dict(self.headers)
        if return_representation:
            headers["Prefer"] = "return=representation"
        if upsert:
            headers["Prefer"] = headers.get("Prefer", "") + ",resolution=merge-duplicates"
        params = {}
        if on_conflict:
            params["on_conflict"] = on_conflict
        async with httpx.AsyncClient(timeout=30) as s:
            r = await s.post(f"{self.base}/{table}", params=params, headers=headers, json=rows)
            r.raise_for_status()
            return r.json() if return_representation else []

    async def update(self, table: str, filters: dict, patch: dict):
        async with httpx.AsyncClient(timeout=30) as s:
            r = await s.patch(f"{self.base}/{table}", params=filters, headers=self.headers, json=patch)
            r.raise_for_status()

            # Some updates return 204 No Content
            if not r.content or r.status_code == 204:
                return []

            try:
                return r.json()
            except Exception:
                return []


    async def delete(self, table: str, filters: dict):
        # Example: filters={"url": "ilike.https://example.com/devpulse-mock%"}
        headers = dict(self.headers)
        headers["Prefer"] = "return=representation"
        async with httpx.AsyncClient(timeout=30) as s:
            r = await s.delete(f"{self.base}/{table}", params=filters, headers=headers)
            r.raise_for_status()
            return r.json()

    # ---- RPC ----
    async def rpc(self, fn: str, args: dict):
        async with httpx.AsyncClient(timeout=60) as s:
            r = await s.post(f"{self.base}/rpc/{fn}", headers=self.headers, json=args)
            r.raise_for_status()
            return r.json()
