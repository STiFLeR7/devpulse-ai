# backend/store_factory.py
from app.settings import settings

def get_store():
    """
    Returns a store bound either to Supabase REST (default while sockets/DNS are blocked)
    or to direct Postgres (asyncpg) if SUPABASE_DB_URL is set and FORCE_SUPABASE_REST is false.
    """
    use_rest = getattr(settings, "FORCE_SUPABASE_REST", True) or not getattr(settings, "SUPABASE_DB_URL", None)

    if use_rest:
        from backend.db_rest import SupabaseREST
        from backend.store_rest import StoreREST
        return StoreREST(SupabaseREST())
    else:
        from backend.db import DB
        from backend.store import Store
        return Store(DB())
