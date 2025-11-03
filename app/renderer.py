from datetime import datetime, timezone
from .settings import settings
from .crypto import sign_event

CSS = """
body{font-family:Inter,Segoe UI,Arial,sans-serif;line-height:1.45;color:#111;margin:0;padding:24px;background:#fafafa}
.card{background:#fff;border-radius:14px;box-shadow:0 1px 4px rgba(0,0,0,.06);padding:20px;margin:0 auto;max-width:920px}
h1{margin:0 0 8px 0;font-size:22px}
h2{font-size:16px;margin:16px 0 8px 0}
ul{margin:0 0 16px 20px;padding:0}
li{margin:6px 0}
a{color:#0a5fff;text-decoration:none}
.muted{color:#666;font-size:12px}
.footer{margin-top:20px;font-size:12px;color:#666}
.pill{display:inline-block;padding:2px 8px;border-radius:999px;background:#eef;font-size:12px;margin-left:6px}
"""

def _iso(dt):
    if isinstance(dt, str): return dt
    return dt.astimezone(timezone.utc).isoformat()

def _item_li(it: dict) -> str:
    extid = it["external_id"]
    payload = f"{extid}|{it['source']}"
    sig = sign_event(settings.BRIDGE_SIGNING_SECRET, payload)
    like = f'{settings.BASE_URL}/events/ping?source={it["source"]}&external_id={extid}&type=like&sig={sig}'
    dislike = f'{settings.BASE_URL}/events/ping?source={it["source"]}&external_id={extid}&type=dislike&sig={sig}'
    main = f'<a href="{settings.BASE_URL}/redirect?source={it["source"]}&external_id={extid}&to={it["url"]}">{it["title"]}</a>'
    if it.get("secondary_url"):
        main += f' <a href="{settings.BASE_URL}/redirect?source={it["source"]}&external_id={extid}&to={it["secondary_url"]}">(tag)</a>'
    ts = _iso(it["published_at"])
    return f'{main} <span style="color:#777;">({ts})</span> — <a href="{like}" style="text-decoration:none;">👍</a> <a href="{dislike}" style="text-decoration:none;">👎</a>'

def _section(title: str, items: list[dict]) -> str:
    if not items: return ""
    lis = "\n".join(f"<li style='margin:6px 0'>{_item_li(it)}</li>" for it in items)
    return f"<h2>{title}</h2>\n<ul>\n{lis}\n</ul>"

def render_html(items: list[dict]) -> str:
    now = datetime.now(timezone.utc).isoformat()
    by = {"github": [], "hf-model": [], "hf-dataset": [], "medium": []}
    for it in items:
        by.setdefault(it["source"], []).append(it)
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>devpulse-ai — Daily Digest</title>
  <style>{CSS}</style>
</head>
<body>
  <div class="card">
    <h1>devpulse-ai — Daily Digest <span class="pill">Phase-1</span></h1>
    <div class="muted">Generated at {now}</div>
    <hr style="border:none;border-top:1px solid #eee;margin:12px 0"/>
    {_section("Github", by.get("github", []))}
    {_section("Hugging Face — Models", by.get("hf-model", []))}
    {_section("Hugging Face — Datasets", by.get("hf-dataset", []))}
    {_section("Medium", by.get("medium", []))}
    <div class="footer">
      You received this because you subscribed to devpulse-ai. Like 👍 or Dislike 👎 links record feedback to improve ranking.
    </div>
  </div>
</body>
</html>"""
