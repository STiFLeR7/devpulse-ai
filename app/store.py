import sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).resolve().parents[1] / "devpulse.sqlite"

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS items(
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,
  external_id TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  secondary_url TEXT,
  published_at TEXT NOT NULL,
  score INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_items_source_pub ON items(source, published_at DESC);

CREATE TABLE IF NOT EXISTS feedback(
  id INTEGER PRIMARY KEY,
  external_id TEXT NOT NULL,
  etype TEXT NOT NULL,
  at TEXT NOT NULL DEFAULT (datetime('now')),
  meta TEXT
);
"""

@contextmanager
def _conn():
    con = sqlite3.connect(DB_PATH, isolation_level=None, timeout=30)
    con.execute("PRAGMA foreign_keys=ON;")
    try:
        yield con
    finally:
        con.close()

def init_db():
    with _conn() as con:
        for stmt in SCHEMA.strip().split(";"):
            s = stmt.strip()
            if s:
                con.execute(s)

def upsert_items(items: list[dict]) -> int:
    if not items:
        return 0
    q = """
    INSERT INTO items(source,external_id,title,url,secondary_url,published_at,score)
    VALUES(?,?,?,?,?,?,COALESCE(?,0))
    ON CONFLICT(external_id) DO UPDATE SET
      title=excluded.title,
      url=excluded.url,
      secondary_url=excluded.secondary_url,
      published_at=excluded.published_at;
    """
    rows = []
    for it in items:
        ts = it.get("published_at")
        if not isinstance(ts, str):
            ts = (ts or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        rows.append((
            it["source"], it["external_id"], it["title"], it["url"],
            it.get("secondary_url"), ts, it.get("score", 0)
        ))
    with _conn() as con:
        con.executemany(q, rows)
        cur = con.execute("SELECT changes();")
        # changes() counts updates too; return inserted/updated count which is fine
        return cur.fetchone()[0] or 0

def latest_items(limit: int = 200, sources: list[str] | None = None) -> list[dict]:
    with _conn() as con:
        if sources:
            q = "SELECT source,external_id,title,url,secondary_url,published_at,score FROM items WHERE source IN ({}) ORDER BY published_at DESC LIMIT ?".format(
                ",".join("?"*len(sources))
            )
            cur = con.execute(q, (*sources, limit))
        else:
            cur = con.execute("SELECT source,external_id,title,url,secondary_url,published_at,score FROM items ORDER BY published_at DESC LIMIT ?", (limit,))
        out = []
        for r in cur.fetchall():
            out.append({
                "source": r[0], "external_id": r[1], "title": r[2], "url": r[3],
                "secondary_url": r[4], "published_at": r[5], "score": r[6]
            })
        return out

def record_feedback(external_id: str, etype: str, meta: str | None = None) -> None:
    with _conn() as con:
        con.execute("INSERT INTO feedback(external_id, etype, meta) VALUES(?,?,?)", (external_id, etype, meta))
