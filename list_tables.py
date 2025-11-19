import sqlite3, os, sys
db_path = os.path.join("n8n", "database.sqlite")
if not os.path.exists(db_path):
    print("DB not found:", db_path); sys.exit(2)
con = sqlite3.connect(db_path)
cur = con.cursor()
for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"):
    print(row[0])
con.close()
