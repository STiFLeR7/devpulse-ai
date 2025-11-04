# backend/store_factory.py
from app.settings import settings

def get_store():
    use_rest = settings.FORCE_SUPABASE_REST or not settings.SUPABASE_DB_URL
    if use_rest:
        from backend.db_rest import SupabaseREST
        from backend.store_rest import StoreREST
        return StoreREST(SupabaseREST())
    else:
        from backend.db import DB
        from backend.store import Store
        return Store(DB())
