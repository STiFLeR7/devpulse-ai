# backend/db_rest.py
from __future__ import annotations

import json
import asyncio
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlencode

import httpx

from app.settings import settings

# Timeouts
_DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0, read=20.0, write=10.0)


class SupabaseREST:
    """
    Minimal async PostgREST wrapper used by DevPulse backend.
    Methods:
      - select(table, params) -> list|dict
      - insert(table, payload, *, upsert=False, on_conflict=None, return_representation=True, params=None)
      - update(table, filters, payload, *, params=None)
      - delete(table, filters, *, params=None)
    Notes:
      - Do NOT pass 'upsert=true' in query params; set upsert=True to request Prefer: resolution=merge-duplicates.
      - on_conflict should be comma-separated column names (e.g. "origin_id") if using upsert behavior.
    """

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None) -> None:
        self.base_url = (base_url or settings.SUPABASE_URL or "").rstrip("/")
        if not self.base_url:
            raise RuntimeError("SUPABASE_URL not configured")
        # prefer JWT if available for privileged actions
        self.api_key = api_key or getattr(settings, "SUPABASE_JWT", None) or getattr(settings, "SUPABASE_KEY", None)

    def _auth_headers(self) -> Dict[str, str]:
        h: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            h["apikey"] = self.api_key
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, str]] = None,
        json_payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[httpx.Timeout] = None,
        retries: int = 0,
    ) -> httpx.Response:
        url = f"{self.base_url}/rest/v1/{path.lstrip('/')}"
        hdrs = self._auth_headers()
        if headers:
            hdrs.update(headers)

        timeout = timeout or _DEFAULT_TIMEOUT

        last_exc: Optional[Exception] = None
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            for attempt in range(retries + 1):
                try:
                    resp = await client.request(method, url, params=params, json=json_payload, headers=hdrs)
                    # don't raise here; caller will handle status codes
                    return resp
                except Exception as e:
                    last_exc = e
                    if attempt < retries:
                        await asyncio.sleep(0.2 * (attempt + 1))
                        continue
                    raise last_exc

    # -------------------- convenience --------------------

    async def select(self, table: str, params: Optional[Dict[str, str]] = None, *, timeout: float = 30.0) -> Any:
        """
        Simple select wrapper. `params` is a dict of PostgREST query parameters (e.g. {"select":"id", "limit":"1"}).
        """
        try:
            resp = await self._request("GET", table, params=params or {}, timeout=_DEFAULT_TIMEOUT)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            # include response JSON/text for easier debugging
            body = None
            try:
                body = resp.json()
            except Exception:
                body = resp.text if "resp" in locals() else str(e)
            raise httpx.HTTPStatusError(f"Select {table} failed: {resp.status_code} {body}", request=getattr(resp, "request", None), response=resp)
        except Exception:
            raise
        # try to parse JSON; PostgREST returns [] or rows
        try:
            return resp.json()
        except Exception:
            return resp.text

    async def insert(
        self,
        table: str,
        payload: Union[Dict[str, Any], List[Dict[str, Any]]],
        *,
        upsert: bool = False,
        on_conflict: Optional[str] = None,
        return_representation: bool = True,
        params: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
        retries: int = 0,
    ) -> Any:
        """
        Insert rows into a table.
        - payload: dict or list of dicts
        - upsert: if True, ask PostgREST to merge duplicates via Prefer: resolution=merge-duplicates
        - on_conflict: comma-separated column names passed as query param on_conflict=col1,col2
        - return_representation: controls Prefer: return=representation vs minimal
        """
        hdrs = headers.copy() if headers else {}
        prefers: List[str] = []
        if upsert:
            prefers.append("resolution=merge-duplicates")
        prefers.append(f"return={'representation' if return_representation else 'minimal'}")
        if prefers:
            hdrs["Prefer"] = ", ".join(prefers)

        params_final = params.copy() if params else {}
        if on_conflict:
            # on_conflict is accepted by PostgREST as a query param
            params_final["on_conflict"] = on_conflict

        try:
            resp = await self._request("POST", table, params=params_final, json_payload=payload, headers=hdrs, retries=retries)
            # if PostgREST returns 204 No Content for minimal returns, handle accordingly
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            body = None
            try:
                body = resp.json()
            except Exception:
                body = resp.text if "resp" in locals() else str(e)
            # propagate with clearer message
            raise httpx.HTTPStatusError(f"Insert {table} failed: {resp.status_code} {body}", request=getattr(resp, "request", None), response=resp)
        except Exception:
            raise

        try:
            # If representation returned, parse it; else return []
            if resp.status_code == 204 or not resp.content:
                return []
            return resp.json()
        except Exception:
            return resp.text

    async def update(
        self,
        table: str,
        filters: Dict[str, str],
        payload: Dict[str, Any],
        *,
        params: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
        return_representation: bool = True,
        retries: int = 0,
    ) -> Any:
        """
        Update rows matching filters.
        - filters: dict of PostgREST filter expressions, e.g. {"id": "eq.123"}
        - params: additional query params (e.g. "select": "*")
        - return_representation: prefer representation in Prefer header
        """
        hdrs = headers.copy() if headers else {}
        hdrs["Prefer"] = f"return={'representation' if return_representation else 'minimal'}"

        params_final = params.copy() if params else {}
        # merge filters into params_final (PostgREST uses querystring filters)
        params_final.update(filters or {})

        try:
            resp = await self._request("PATCH", table, params=params_final, json_payload=payload, headers=hdrs, retries=retries)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            body = None
            try:
                body = resp.json()
            except Exception:
                body = resp.text if "resp" in locals() else str(e)
            raise httpx.HTTPStatusError(f"Update {table} failed: {resp.status_code} {body}", request=getattr(resp, "request", None), response=resp)
        except Exception:
            raise

        try:
            if resp.status_code == 204 or not resp.content:
                return []
            return resp.json()
        except Exception:
            return resp.text

    async def delete(
        self,
        table: str,
        filters: Optional[Dict[str, str]] = None,
        *,
        params: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
        return_representation: bool = True,
        retries: int = 0,
    ) -> Any:
        """
        Delete rows matching filters.
        - filters: dict of PostgREST filter expressions, e.g. {"url": "ilike.https://example.com/%"}
        """
        hdrs = headers.copy() if headers else {}
        hdrs["Prefer"] = f"return={'representation' if return_representation else 'minimal'}"

        params_final = params.copy() if params else {}
        if filters:
            params_final.update(filters)

        try:
            resp = await self._request("DELETE", table, params=params_final, headers=hdrs, retries=retries)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            body = None
            try:
                body = resp.json()
            except Exception:
                body = resp.text if "resp" in locals() else str(e)
            raise httpx.HTTPStatusError(f"Delete {table} failed: {resp.status_code} {body}", request=getattr(resp, "request", None), response=resp)
        except Exception:
            raise

        try:
            if resp.status_code == 204 or not resp.content:
                return []
            return resp.json()
        except Exception:
            return resp.text

    # optional helper to call RPC endpoints
    async def rpc(
        self,
        fn: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, str]] = None,
        retries: int = 0,
    ) -> Any:
        hdrs = headers.copy() if headers else {}
        params_final = params.copy() if params else {}
        try:
            resp = await self._request("POST", f"rpc/{fn}", params=params_final, json_payload=payload or {}, headers=hdrs, retries=retries)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            body = None
            try:
                body = resp.json()
            except Exception:
                body = resp.text if "resp" in locals() else str(e)
            raise httpx.HTTPStatusError(f"RPC {fn} failed: {resp.status_code} {body}", request=getattr(resp, "request", None), response=resp)
        except Exception:
            raise

        try:
            return resp.json()
        except Exception:
            return resp.text
