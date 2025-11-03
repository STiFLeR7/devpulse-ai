import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

# --- Config ---
DB_PATH = Path(os.getenv("DB_PATH", "./devpulse.sqlite"))
SCHEMA_PATH = Path("./core/storage/schema.sql")


# --- Internal helpers ---
def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    # sensible pragmas for single-writer / multi-reader local use
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    return con


def _apply_schema(con: sqlite3.Connection) -> None:
    if SCHEMA_PATH.exists():
        with SCHEMA_PATH.open("r", encoding="utf-8") as f:
            con.executescript(f.read())
    else:
        # Minimal fallback if schema.sql is missing (keeps you unblocked)
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY,
                source TEXT NOT NULL DEFAULT 'github',
                external_id TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                secondary_url TEXT,
                created_at TEXT NOT NULL,
                discovered_at TEXT NOT NULL DEFAULT (datetime('now')),
                metadata_json TEXT DEFAULT '{}',
                is_new INTEGER NOT NULL DEFAULT 1,
                rank_score REAL DEFAULT 0
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_items_source_external
                ON items(source, external_id);
            CREATE INDEX IF NOT EXISTS idx_items_external_id ON items(external_id);
            CREATE INDEX IF NOT EXISTS idx_items_created_at ON items(created_at);
            CREATE INDEX IF NOT EXISTS idx_items_discovered_at ON items(discovered_at);
            CREATE INDEX IF NOT EXISTS idx_items_source_created ON items(source, created_at);

            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY,
                item_id INTEGER NOT NULL,
                action TEXT NOT NULL, -- e.g., 'like','dismiss','open','share'
                note TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
            );
            """
        )

    # Optional view that matches our Python access pattern
    con.executescript(
        """
        DROP VIEW IF EXISTS latest_items;
        CREATE VIEW latest_items AS
        SELECT
            id,
            source,
            external_id,
            title,
            url,
            COALESCE(secondary_url, '') AS secondary_url,
            created_at,
            discovered_at,
            COALESCE(metadata_json,'{}') AS metadata_json,
            COALESCE(is_new,0) AS is_new,
            COALESCE(rank_score,0.0) AS rank_score
        FROM items;
        """
    )


# --- Public API used by the app ---
def init_db() -> None:
    """
    Idempotent DB bootstrap. Safe to call at app startup.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as con:
        _apply_schema(con)


def latest_items(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Fetch newest items by discovered_at (fallback to created_at).
    Only uses columns that exist in your current schema.
    """
    q = """
    SELECT
        id,
        source,
        external_id,
        title,
        url,
        COALESCE(secondary_url, '') AS secondary_url,
        created_at,
        discovered_at,
        COALESCE(metadata_json,'{}') AS metadata_json,
        COALESCE(is_new,0) AS is_new,
        COALESCE(rank_score,0.0) AS rank_score
    FROM items
    ORDER BY datetime(discovered_at) DESC, datetime(created_at) DESC
    LIMIT ?
    """
    with _connect() as con:
        rows = con.execute(q, (int(limit),)).fetchall()
        return [dict(r) for r in rows]


def upsert_items(items: Iterable[Dict[str, Any]]) -> int:
    """
    Upsert items compatible with the current schema.

    Required keys per item:
      - source, external_id, title, url, created_at
    Optional:
      - secondary_url, discovered_at, metadata_json, is_new, rank_score
    """
    rows: List[Dict[str, Any]] = []
    for it in items:
        rows.append(
            {
                "source": it.get("source", "github"),
                "external_id": it["external_id"],
                "title": it["title"],
                "url": it["url"],
                "secondary_url": it.get("secondary_url"),
                "created_at": it["created_at"],
                "discovered_at": it.get("discovered_at"),
                "metadata_json": it.get("metadata_json", "{}"),
                "is_new": it.get("is_new", 1),
                "rank_score": it.get("rank_score", 0.0),
            }
        )

    q = """
    INSERT INTO items (
        source, external_id, title, url, secondary_url,
        created_at, discovered_at, metadata_json, is_new, rank_score
    ) VALUES (
        :source, :external_id, :title, :url, :secondary_url,
        :created_at, COALESCE(:discovered_at, datetime('now')),
        COALESCE(:metadata_json, '{}'),
        COALESCE(:is_new, 1),
        COALESCE(:rank_score, 0.0)
    )
    ON CONFLICT(source, external_id) DO UPDATE SET
        title=excluded.title,
        url=excluded.url,
        secondary_url=excluded.secondary_url,
        created_at=excluded.created_at,
        discovered_at=excluded.discovered_at,
        metadata_json=excluded.metadata_json,
        is_new=excluded.is_new,
        rank_score=excluded.rank_score
    """
    with _connect() as con:
        con.executemany(q, rows)
        # total_changes includes updates; good enough as "affected"
        return con.total_changes


def record_feedback(item_id: int, action: str, note: Optional[str] = "") -> int:
    """
    Attach lightweight user feedback to an item.
    """
    q = "INSERT INTO feedback (item_id, action, note) VALUES (?, ?, ?)"
    with _connect() as con:
        cur = con.execute(q, (item_id, action, note or ""))
        return cur.lastrowid
