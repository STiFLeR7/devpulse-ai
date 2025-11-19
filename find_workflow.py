import sqlite3, os, sys
db_path = os.path.join("n8n", "database.sqlite")
if not os.path.exists(db_path):
    print("DB not found:", db_path); sys.exit(2)
name_like = sys.argv[1] if len(sys.argv) > 1 else "%Daily Digest%"
con = sqlite3.connect(db_path)
cur = con.cursor()
# prefer workflow_entity, fallback to workflow
cur.execute("SELECT id,name,active FROM workflow_entity WHERE name LIKE ?", (name_like,))
rows = cur.fetchall()
tbl = "workflow_entity"
if not rows:
    cur.execute("SELECT id,name,active FROM workflow WHERE name LIKE ?", (name_like,))
    rows = cur.fetchall()
    tbl = "workflow" if rows else tbl
if not rows:
    print("No matching workflow found for", name_like); sys.exit(1)
for r in rows:
    print(tbl, r[0], r[1], r[2])
con.close()
