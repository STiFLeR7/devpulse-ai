import requests
print(requests.get("http://127.0.0.1:8000/ingest/run", timeout=60).json())
