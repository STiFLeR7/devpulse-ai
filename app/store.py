# app/store.py
"""
Phase-2 bridge: app layer uses Supabase backend store.
SQLite code removed; this file now delegates to backend/store.py
"""

from backend.db_rest import DB
from backend.store import Store


db = DB()
store = Store(db)


async def init_db():
    await store.init()


async def latest_items(limit: int):
    rows = await store.top_digest(limit=limit)
    return [dict(x) for x in rows]


async def record_feedback(source: str, external_id: str, kind: str) -> bool:
    # TODO: store in separate supabase table later
    print(f"[feedback] {source} {external_id} = {kind}")
    return True
