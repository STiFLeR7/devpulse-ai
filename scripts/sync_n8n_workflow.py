#!/usr/bin/env python3
"""
Robust n8n workflow sync script.

Usage:
  export N8N_URL="http://127.0.0.1:5678"
  export N8N_USER="admin"
  export N8N_PASS="your_password"
  python scripts/sync_n8n_workflow.py path/to/workflow.json
"""
import os
import sys
import json
import base64
from pathlib import Path

try:
    import requests
except Exception:
    print("Please `pip install requests` and re-run.")
    sys.exit(2)


N8N_URL = os.getenv("N8N_URL", "http://127.0.0.1:5678").rstrip("/")
API_BASE = os.getenv("N8N_API_BASE", "/api")  # default to /api; adjust if your n8n uses /rest
API_BASE = API_BASE.rstrip("/")
LIST_URL = f"{N8N_URL}{API_BASE}/workflows"
USERNAME = os.getenv("N8N_USER", "admin")
PASSWORD = os.getenv("N8N_PASS", "")


def auth_headers():
    token = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


def load_workflow(path):
    raw = Path(path).read_text(encoding="utf-8")
    return json.loads(raw)


def pretty_response(resp):
    print(f"> HTTP {resp.status_code} {resp.reason}")
    text = resp.text or ""
    if len(text) > 4000:
        print(text[:4000] + "\n... (truncated)")
    else:
        print(text)


def find_workflow_id(name):
    resp = requests.get(LIST_URL, headers=auth_headers(), timeout=10)
    if resp.status_code != 200:
        print("Failed to list workflows:")
        pretty_response(resp)
        resp.raise_for_status()
    # older/newer n8n may nest list under 'data' or return array directly
    try:
        body = resp.json()
    except Exception:
        print("List response is not JSON:")
        pretty_response(resp)
        raise
    if isinstance(body, dict) and "data" in body:
        workflows = body["data"]
    elif isinstance(body, list):
        workflows = body
    else:
        workflows = []
    for wf in workflows:
        if wf.get("name") == name:
            return wf.get("id") or wf.get("workflow_id") or wf.get("uuid")
    return None


def create_workflow(payload):
    url = LIST_URL
    resp = requests.post(url, headers=auth_headers(), json=payload, timeout=15)
    if resp.status_code not in (200, 201):
        print("Create failed:")
        pretty_response(resp)
        resp.raise_for_status()
    try:
        return resp.json().get("id") or resp.json().get("data", {}).get("id")
    except Exception:
        return None


def update_workflow(wf_id, payload):
    url = f"{LIST_URL}/{wf_id}"
    resp = requests.patch(url, headers=auth_headers(), json=payload, timeout=15)
    if resp.status_code not in (200, 201):
        print("Update failed:")
        pretty_response(resp)
        resp.raise_for_status()
    try:
        return resp.json().get("id") or resp.json().get("data", {}).get("id")
    except Exception:
        return None


def main():
    if len(sys.argv) != 2:
        print("Usage: python sync_n8n_workflow.py workflow.json")
        sys.exit(1)

    wf_file = sys.argv[1]
    if not Path(wf_file).exists():
        print("Workflow file not found:", wf_file)
        sys.exit(2)

    data = load_workflow(wf_file)
    name = data.get("name") or Path(wf_file).stem
    print("Syncing workflow:", name)
    print("Using N8N_URL:", LIST_URL)
    wf_id = None
    try:
        wf_id = find_workflow_id(name)
    except Exception as e:
        print("Could not list workflows:", e)
        sys.exit(3)

    payload = {
        "name": data.get("name"),
        "nodes": data.get("nodes", []),
        "connections": data.get("connections", {}),
        "settings": data.get("settings", {}),
        "active": data.get("active", False),
        # keep credentials empty; they must be configured in UI; including them here can be unsafe
    }

    try:
        if wf_id:
            print(f"Workflow exists. Updating ID={wf_id}")
            update_workflow(wf_id, payload)
        else:
            print("Workflow does not exist. Creating new...")
            wf_id = create_workflow(payload)
    except Exception as e:
        print("Create/Update failed:", e)
        sys.exit(4)

    print(f"Successfully synced workflow ID={wf_id}")


if __name__ == "__main__":
    main()
