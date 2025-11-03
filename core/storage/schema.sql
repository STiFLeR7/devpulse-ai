-- core/storage/schema.sql

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
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('like','dislike')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Recreate view to match latest columns
DROP VIEW IF EXISTS latest_items;
CREATE VIEW latest_items AS
SELECT
    id, source, external_id, title, url, secondary_url,
    created_at, discovered_at, metadata_json, is_new, rank_score
FROM items
ORDER BY datetime(discovered_at) DESC, datetime(created_at) DESC;
