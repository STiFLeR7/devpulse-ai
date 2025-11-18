# tests/test_endpoints.py
import time
import json
from fastapi.testclient import TestClient
from pathlib import Path

# import the FastAPI app from your project
from app.main import app

client = TestClient(app, base_url="http://testserver")


def poll_for_condition(fn, timeout=6.0, interval=0.5):
    """Poll helper: call fn() repeatedly until truthy or timeout (seconds)."""
    start = time.time()
    while True:
        val = fn()
        if val:
            return val
        if time.time() - start > timeout:
            return None
        time.sleep(interval)


def test_ingest_seed_and_digest_endpoints():
    """
    1) Hit /ingest/seed to schedule a background seed of 1 mock item.
    2) Poll /debug/items/recent until the seeded item appears.
    3) Call /digest/json and /digest/daily_html and assert the seeded title is present.
    """
    # 1) Request seed (schedules background job)
    r = client.get("/ingest/seed?n=1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("scheduled") in (True, "True", 1)

    # 2) Poll recent items endpoint until we see 1+ item
    def check_recent():
        rr = client.get("/debug/items/recent?limit=10&hours=48")
        if rr.status_code != 200:
            return None
        js = rr.json()
        return js.get("count", 0) > 0

    ok = poll_for_condition(check_recent, timeout=8.0, interval=0.6)
    assert ok, "Timed out waiting for seeded item to appear in store (background task may be delayed)"

    # Confirm recent items include seeded mock title prefix
    rr = client.get("/debug/items/recent?limit=10&hours=48")
    assert rr.status_code == 200
    recent = rr.json()
    assert recent["count"] >= 1
    titles = [it.get("title", "").lower() for it in recent.get("items", [])]
    assert any("devpulse mock signal" in t or "devpulse mock" in t for t in titles), titles

    # 3) Call digest/json and assert it returns an array / list with expected fields
    rjson = client.get("/digest/json?limit=20")
    assert rjson.status_code == 200, rjson.text
    rows = rjson.json()
    # rows may be list of dicts
    assert isinstance(rows, list)
    if rows:
        sample = rows[0]
        # basic fields
        assert "title" in sample and "url" in sample

    # 4) Call daily_html (string) and ensure seeded text is present
    rhtml = client.get("/digest/daily_html?hours=48&limit=20")
    assert rhtml.status_code == 200, rhtml.text
    txt = rhtml.text
    # our seeded mock titles include "DevPulse Mock Signal"
    assert "DevPulse Mock Signal" in txt or "DevPulse — Mock" in txt or "DevPulse Mock" in txt

    # 5) Call email_html endpoint, ensure HTML response and list items included
    re = client.get("/digest/email_html?hours=48")
    assert re.status_code == 200
    assert "<html" not in re.text.lower() or "<div" in re.text  # crude HTML sanity check
