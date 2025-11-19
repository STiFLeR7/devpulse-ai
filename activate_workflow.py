import sqlite3, os, sys
db_path = os.path.join("n8n", "database.sqlite")
if not os.path.exists(db_path):
    print("DB not found:", db_path); sys.exit(2)
name_like = sys.argv[1] if len(sys.argv) > 1 else "%Daily Digest%"
con = sqlite3.connect(db_path)
cur = con.cursor()
cur.execute("SELECT id FROM workflow_entity WHERE name LIKE ?", (name_like,))
rows = cur.fetchall()
tbl = "workflow_entity"
if not rows:
    cur.execute("SELECT id FROM workflow WHERE name LIKE ?", (name_like,))
    rows = cur.fetchall()
    tbl = "workflow" if rows else tbl
if not rows:
    print("No matching workflow found for", name_like); sys.exit(1)
for (wid,) in rows:
    print("Activating", wid, "in table", tbl)
    cur.execute(f"UPDATE {tbl} SET active=1 WHERE id=?", (wid,))
con.commit()
print("Done. Updated", len(rows), "row(s).")
con.close()
