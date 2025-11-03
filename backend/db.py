# backend/db.py
import asyncpg, ssl
from urllib.parse import urlparse, unquote
from app.settings import settings

class DB:
    def __init__(self):
        self.pool = None

    async def connect(self):
        if self.pool: return
        url = urlparse(settings.SUPABASE_DB_URL)
        user = url.username or "postgres"
        password = unquote(url.password) if url.password else None
        host = url.hostname
        port = url.port or 6543
        database = (url.path or "/postgres").lstrip("/") or "postgres"

        ssl_ctx = ssl.create_default_context()

        self.pool = await asyncpg.create_pool(
            user=user, password=password, host=host, port=port, database=database,
            min_size=1, max_size=10, command_timeout=60, ssl=ssl_ctx,
            timeout=10.0,                   # connect timeout
            statement_cache_size=0          # avoids Windows oddities sometimes
        )
