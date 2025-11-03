from html import escape
from datetime import datetime
from typing import Iterable, Mapping, Any, Optional


def _fmt(ts: str) -> str:
    if not ts:
        return ""
    try:
        ts2 = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(ts2).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ts


def render_html(
    items: Iterable[Mapping[str, Any]],
    title: str = "Daily Dev Pulse",
    phase_label: Optional[str] = None,
    **_: Any,  # absorb unexpected kwargs to stay forwards/backwards compatible
) -> str:
    items = list(items)

    # If a phase label is passed (from settings), prefix it into the title.
    if phase_label:
        title = f"{phase_label} · {title}"

    if not items:
        return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{escape(title)}</title>
<style>
body{{font-family:ui-sans-serif,system-ui; margin:24px;}}
.hdr{{font-size:20px;font-weight:700;margin-bottom:8px}}
.meta{{color:#6b7280;font-size:12px}}
.card{{border:1px solid #e5e7eb;border-radius:12px;padding:16px;margin:12px 0}}
a{{text-decoration:none}}
a:hover{{text-decoration:underline}}
.badge{{display:inline-block;padding:2px 8px;border:1px solid #e5e7eb;border-radius:999px;font-size:11px;color:#374151;margin-left:8px}}
</style>
</head>
<body>
<div class="hdr">{escape(title)}</div>
<p>No items yet. Hit <code>/ingest/run</code> and refresh.</p>
<div class="meta">Powered by devpulse-ai</div>
</body></html>"""

    cards = []
    for it in items:
        _title = escape(it.get("title", ""))
        _url = escape(it.get("url", ""))
        _src = escape(it.get("source", "github"))
        _created = _fmt(it.get("created_at") or "")
        _disc = _fmt(it.get("discovered_at") or "")
        _score = float(it.get("rank_score") or 0.0)

        sec = it.get("secondary_url")
        sec_html = (
            f' &middot; <a href="{escape(sec)}" target="_blank" rel="noopener">secondary</a>'
            if sec else ""
        )

        cards.append(
            f"""
<div class="card">
  <div><a href="{_url}" target="_blank" rel="noopener">{_title}</a></div>
  <div class="meta">{_created} → {_disc}
     <span class="badge">{_src}</span>
     <span class="badge">score {_score:.2f}</span>{sec_html}
  </div>
</div>"""
        )

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{escape(title)}</title>
<style>
body{{font-family:ui-sans-serif,system-ui; margin:24px;}}
.hdr{{font-size:20px;font-weight:700;margin-bottom:8px}}
.meta{{color:#6b7280;font-size:12px}}
.card{{border:1px solid #e5e7eb;border-radius:12px;padding:16px;margin:12px 0}}
a{{text-decoration:none}}
a:hover{{text-decoration:underline}}
.badge{{display:inline-block;padding:2px 8px;border:1px solid #e5e7eb;border-radius:999px;font-size:11px;color:#374151;margin-left:8px}}
</style>
</head>
<body>
<div class="hdr">{escape(title)}</div>
{''.join(cards)}
<div class="meta">Powered by devpulse-ai</div>
</body></html>"""
