# analyze_supabase_csvs.py (FIXED)
import pandas as pd
import re
import pathlib
from datetime import datetime, timezone

FILES = {
    "items": "items_rows.csv",
    "item_enriched": "item_enriched_rows.csv",
    "sources": "sources_rows.csv",
    "v_digest": "v_digest_rows.csv"
}

dfs = {}
for k, fname in FILES.items():
    p = pathlib.Path(fname)
    if p.exists():
        try:
            dfs[k] = pd.read_csv(p, dtype=str)
        except Exception as e:
            print(f"Error reading {fname}: {e}")
            dfs[k] = pd.read_csv(p, encoding='utf-8', dtype=str, engine='python')
    else:
        print(f"[WARN] {fname} not found in cwd.")
        dfs[k] = None

items = dfs['items']
if items is None:
    print("No items CSV found — place items_rows.csv in this folder and re-run.")
    raise SystemExit(1)

# detect columns (case-insensitive)
cols = {c.lower(): c for c in items.columns}
def colname(key):
    return cols.get(key.lower())

id_col = colname('id') or colname('item_id') or list(items.columns)[0]
url_col = colname('url') or colname('link') or colname('html_url')
title_col = colname('title') or colname('name')
event_col = colname('event_time') or colname('published_at') or colname('created_at') or colname('time')
score_col = colname('score')
tags_col = colname('tags')
summary_col = colname('summary_ai') or colname('summary')

print("\n=== Files loaded ===")
for k in FILES:
    df = dfs[k]
    print(f" {k}: {'found, rows='+str(len(df)) if df is not None else 'missing'}")

print("\n=== Main columns detected (in items_rows.csv) ===")
print(f" id_col: {id_col}")
print(f" title_col: {title_col}")
print(f" url_col: {url_col}")
print(f" event_col: {event_col}")
print(f" score_col: {score_col}")
print(f" tags_col: {tags_col}")
print(f" summary_col: {summary_col}")

total = len(items)
print(f"\nTotal items rows: {total}")

# safe series getters
def series_or_empty(df, col):
    if df is None or col is None: return pd.Series([None]*len(df))
    return df[col]

event_series = series_or_empty(items, event_col)
null_event_count = int(event_series.isna().sum() + (event_series == '').sum())
print(f"Rows with event_time NULL/empty: {null_event_count}")

present_ts = items[~(event_series.isna() | (event_series == ''))] if event_col else items.iloc[0:0]
null_ts = items[(event_series.isna() | (event_series == ''))] if event_col else items

print(f"Rows with event_time present: {len(present_ts)}")
if len(present_ts):
    # choose safe display columns that do exist
    display_cols = [c for c in [id_col, title_col, url_col, event_col, score_col] if c is not None]
    print("Sample present event_time (first 5 rows):")
    print(present_ts[display_cols].head(5).to_string(index=False))
else:
    print("Sample present event_time: <none>")

print("\nSample rows with NULL event_time (first 5):")
display_cols_null = [c for c in [id_col, title_col, url_col, event_col, score_col] if c is not None]
print(null_ts[display_cols_null].head(5).to_string(index=False))

# domain analysis
def extract_domain(url):
    try:
        if not isinstance(url, str): return ""
        m = re.search(r"https?://([^/]+)", url)
        return (m.group(1).lower() if m else "")
    except:
        return ""
items['__domain__'] = items[url_col].astype(str).apply(extract_domain) if url_col else ""
domain_counts = items['__domain__'].value_counts().head(20)
print("\nTop domains (by row count):")
print(domain_counts.to_string())

# suspected mocks
mock_domains = ["example.com", "localhost"]
def is_mock_row(r):
    u = str(r.get(url_col,"") or "")
    t = str(r.get(title_col,"") or "")
    if any(d in u.lower() for d in mock_domains): return True
    if re.search(r'mock|demo|sample', t, re.I): return True
    return False

items['__is_mock__'] = items.apply(is_mock_row, axis=1)
mock_rows = items[items['__is_mock__']]
print(f"\nSuspected mock/demo rows: {len(mock_rows)}")
if len(mock_rows):
    cols_show = [c for c in [id_col, title_col, url_col, event_col, score_col] if c is not None]
    print(mock_rows[cols_show].head(10).to_string(index=False))

# tags frequency
if tags_col:
    def split_tags(s):
        if pd.isna(s) or s=='': return []
        if "\\n" in s:
            parts = [x for x in s.replace("\\n","\n").split("\n") if x]
        else:
            parts = [x for x in str(s).split(",") if x]
        parts = [re.sub(r'^\d+:\s*','',x).strip() for x in parts]
        return [p for p in parts if p]
    items['__tags_list__'] = items[tags_col].apply(split_tags)
    exploded = items.explode('__tags_list__')
    tag_counts = exploded['__tags_list__'].value_counts().head(30)
    print("\nTop tags (sample):")
    print(tag_counts.to_string())
else:
    print("\nNo tags column detected or empty.")

# DATE inference
date_pattern_v = re.compile(r'v?([12]\d{3})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])')
date_pattern_iso = re.compile(r'([12]\d{3})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])')
date_pattern_compact = re.compile(r'([12]\d{3})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])')

inferred = []
for idx, row in items.iterrows():
    if event_col and row.get(event_col) and str(row.get(event_col)).strip():
        continue
    text = " ".join([str(row.get(title_col,"") or ""), str(row.get(url_col,"") or ""), str(row.get(summary_col,"") or "")])
    m = date_pattern_v.search(text) or date_pattern_iso.search(text) or date_pattern_compact.search(text)
    if m:
        yyyy, mm, dd = m.group(1), m.group(2), m.group(3)
        iso = f"{yyyy}-{mm}-{dd}T00:00:00Z"
        inferred.append({
            "id": row.get(id_col),
            "title": row.get(title_col),
            "url": row.get(url_col),
            "inferred_date": iso,
            "match_text": m.group(0)
        })

print(f"\nInferred dates from title/url/summary for NULL event_time rows: {len(inferred)}")
if len(inferred):
    print("Sample inferences (first 10):")
    for s in inferred[:10]:
        print(f" id={s['id']}, inferred={s['inferred_date']}, match={s['match_text']}, title={str(s['title'])[:80]}")

# Build backfill SQL
backfill_sql_lines = []
for s in inferred:
    id_val = s['id']
    dt = s['inferred_date']
    backfill_sql_lines.append(f"UPDATE digest_items SET event_time = '{dt}' WHERE id = {id_val};")

bf_sql_path = pathlib.Path("backfill_updates.sql")
bf_sql_path.write_text("\n".join(backfill_sql_lines), encoding="utf-8")
print(f"\nWrote backfill SQL for {len(backfill_sql_lines)} rows to {bf_sql_path}")

suspected_path = pathlib.Path("suspected_mocks.csv")
if len(mock_rows):
    mock_rows.to_csv(suspected_path, index=False)
    print(f"Wrote suspected mock rows to {suspected_path}")
else:
    print("No suspected mock rows to write.")

# recommended SQL (soft-flag or delete)
if len(mock_rows):
    ids = [str(i) for i in mock_rows[id_col].tolist()]
    print("\n-- Recommended actions for mock rows --")
    print("ALTER TABLE digest_items ADD COLUMN IF NOT EXISTS is_suspected_mock boolean DEFAULT FALSE;")
    print("UPDATE digest_items SET is_suspected_mock = TRUE WHERE id IN (" + ",".join(ids) + ");")
    print("\nDELETE FROM digest_items WHERE id IN (" + ",".join(ids) + ");")
else:
    print("\nNo mock rows found; no delete SQL printed.")

print("\n=== SUMMARY ===")
print(f"Total items: {total}")
print(f"Null event_time: {null_event_count}")
print(f"Suspected mock rows: {len(mock_rows)}")
print(f"Inferred event_time candidates: {len(inferred)}")
print(f"Backfill SQL written: {len(backfill_sql_lines)} rows")
print("Files written (if any): backfill_updates.sql, suspected_mocks.csv")
print("Next steps: review suspected_mocks.csv; run backfill_updates.sql in Supabase SQL editor if you trust inferences.")
