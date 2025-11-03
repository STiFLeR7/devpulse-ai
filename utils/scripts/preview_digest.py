import webbrowser, requests

BASE = "http://127.0.0.1:8000"
try:
    requests.get(f"{BASE}/ingest/run", timeout=30)
except Exception:
    pass
webbrowser.open(f"{BASE}/digest/html")
