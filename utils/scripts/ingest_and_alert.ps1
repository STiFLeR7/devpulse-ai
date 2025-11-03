# 1) call your app's ingest endpoint to pull fresh GitHub items
Invoke-RestMethod -Uri "http://127.0.0.1:8000/ingest/run" -Method GET

# 2) open the digest HTML (optional)
Start-Process "http://127.0.0.1:8000/digest/html"

# 3) push high-signal items to n8n
python -m utils.scripts.notify_latest_to_n8n
