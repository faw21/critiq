"""
critiq --web: launch a local HTML report server for review results.

Usage:
    critiq --web           # review staged changes, open report in browser
    critiq --web --port 9000  # custom port
"""

from __future__ import annotations

import html
import http.server
import threading
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from .reviewer import ReviewResult, Severity


# ── HTML template ─────────────────────────────────────────────────────────────

_SEVERITY_STYLE = {
    Severity.CRITICAL: ("critical", "#f44747", "#2d0d0d"),
    Severity.WARNING: ("warning", "#e5c07b", "#2a2000"),
    Severity.INFO: ("info", "#61afef", "#0d1e2d"),
    Severity.SUGGESTION: ("suggestion", "#a0a0a0", "#1a1a1a"),
}

_SEVERITY_ICON = {
    Severity.CRITICAL: "🚨",
    Severity.WARNING: "⚠️",
    Severity.INFO: "ℹ️",
    Severity.SUGGESTION: "💡",
}

_RATING_COLORS = {
    "✅ LGTM": "#98c379",
    "⚠️ Minor issues": "#e5c07b",
    "🚨 Needs work": "#f44747",
}


def _comment_card(comment) -> str:  # type: ignore[no-untyped-def]
    sev = comment.severity
    label, border_color, bg_color = _SEVERITY_STYLE.get(
        sev, ("info", "#61afef", "#0d1e2d")
    )
    icon = _SEVERITY_ICON.get(sev, "ℹ️")
    title_escaped = html.escape(comment.title)
    body_escaped = html.escape(comment.body).replace("\n", "<br>")
    location = ""
    if comment.file:
        loc_parts = [html.escape(comment.file)]
        if comment.line:
            loc_parts.append(html.escape(comment.line))
        location = f'<span class="location">📍 {" ".join(loc_parts)}</span>'
    category = (
        f'<span class="category">{html.escape(comment.category)}</span>'
        if comment.category
        else ""
    )

    return f"""
  <div class="card" style="border-left-color:{border_color};background:{bg_color}">
    <div class="card-header">
      <span class="badge" style="background:{border_color}">{icon} {label.upper()}</span>
      {category}
      {location}
    </div>
    <div class="card-title">{title_escaped}</div>
    <div class="card-body">{body_escaped}</div>
  </div>"""


def generate_html(result: ReviewResult, title: str = "critiq review") -> str:
    """Generate self-contained HTML report from a ReviewResult."""
    rating_color = _RATING_COLORS.get(result.overall_rating, "#e5c07b")
    total = len(result.comments)
    critical_n = sum(1 for c in result.comments if c.severity == Severity.CRITICAL)
    warning_n = sum(1 for c in result.comments if c.severity == Severity.WARNING)
    info_n = sum(1 for c in result.comments if c.severity in (Severity.INFO, Severity.SUGGESTION))

    cards_html = "\n".join(_comment_card(c) for c in result.comments) if result.comments else (
        '<div class="empty">✅ No issues found — code looks good!</div>'
    )

    summary_escaped = html.escape(result.summary) if result.summary else ""
    model_escaped = html.escape(result.provider_model) if result.provider_model else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(title)}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #1e2127;
      color: #abb2bf;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      min-height: 100vh;
    }}
    header {{
      background: #282c34;
      border-bottom: 1px solid #3e4451;
      padding: 20px 32px;
      display: flex;
      align-items: center;
      gap: 16px;
    }}
    .logo {{ font-size: 28px; font-weight: 700; color: #e06c75; letter-spacing: -1px; }}
    .logo span {{ color: #abb2bf; font-weight: 400; }}
    .rating {{
      margin-left: auto;
      font-size: 18px;
      font-weight: 600;
      color: {rating_color};
    }}
    .model {{ font-size: 12px; color: #5c6370; margin-top: 2px; }}
    main {{ max-width: 900px; margin: 32px auto; padding: 0 16px; }}
    .summary-bar {{
      background: #282c34;
      border: 1px solid #3e4451;
      border-radius: 8px;
      padding: 16px 20px;
      margin-bottom: 24px;
      display: flex;
      gap: 24px;
      align-items: center;
    }}
    .stat {{ text-align: center; }}
    .stat .num {{ font-size: 28px; font-weight: 700; }}
    .stat .label {{ font-size: 12px; color: #5c6370; text-transform: uppercase; }}
    .stat.crit .num {{ color: #f44747; }}
    .stat.warn .num {{ color: #e5c07b; }}
    .stat.info-s .num {{ color: #61afef; }}
    .summary-text {{ flex: 1; color: #abb2bf; font-size: 14px; padding-left: 16px; border-left: 1px solid #3e4451; }}
    .section-title {{
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: 1px;
      color: #5c6370;
      margin-bottom: 12px;
    }}
    .card {{
      border-left: 4px solid;
      border-radius: 6px;
      padding: 14px 16px;
      margin-bottom: 12px;
    }}
    .card-header {{
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 8px;
      flex-wrap: wrap;
    }}
    .badge {{
      font-size: 11px;
      font-weight: 700;
      padding: 2px 8px;
      border-radius: 3px;
      color: #1e2127;
      letter-spacing: 0.5px;
    }}
    .category {{
      font-size: 11px;
      color: #5c6370;
      background: #2c313a;
      padding: 2px 6px;
      border-radius: 3px;
    }}
    .location {{
      font-size: 12px;
      color: #5c6370;
      font-family: "SF Mono", "Fira Code", monospace;
    }}
    .card-title {{
      font-size: 15px;
      font-weight: 600;
      color: #e5c07b;
      margin-bottom: 6px;
    }}
    .card-body {{
      font-size: 13px;
      color: #abb2bf;
      line-height: 1.5;
    }}
    .empty {{
      text-align: center;
      padding: 48px;
      color: #98c379;
      font-size: 18px;
    }}
    footer {{
      text-align: center;
      padding: 24px;
      color: #3e4451;
      font-size: 12px;
    }}
    footer a {{ color: #61afef; text-decoration: none; }}
  </style>
</head>
<body>
  <header>
    <div>
      <div class="logo">critiq<span> review</span></div>
      {f'<div class="model">via {model_escaped}</div>' if model_escaped else ""}
    </div>
    <div class="rating">{html.escape(result.overall_rating)}</div>
  </header>
  <main>
    <div class="summary-bar">
      <div class="stat crit">
        <div class="num">{critical_n}</div>
        <div class="label">Critical</div>
      </div>
      <div class="stat warn">
        <div class="num">{warning_n}</div>
        <div class="label">Warnings</div>
      </div>
      <div class="stat info-s">
        <div class="num">{info_n}</div>
        <div class="label">Suggestions</div>
      </div>
      <div class="stat" style="margin-left:auto">
        <div class="num" style="color:#abb2bf">{total}</div>
        <div class="label">Total</div>
      </div>
      {f'<div class="summary-text">{summary_escaped}</div>' if summary_escaped else ""}
    </div>
    {f'<div class="section-title">Findings</div>' if result.comments else ""}
    {cards_html}
  </main>
  <footer>
    Generated by <a href="https://github.com/faw21/critiq">critiq</a>
    · <a href="https://pypi.org/project/critiq/">pip install critiq</a>
  </footer>
</body>
</html>"""


# ── Local server launcher ─────────────────────────────────────────────────────

def serve_report(result: ReviewResult, port: int = 8421, open_browser: bool = True) -> None:
    """Serve the HTML report on localhost and optionally open in browser.

    Blocks until Ctrl+C.  Emits a Rich status message.
    """
    from rich.console import Console

    console = Console()
    html_content = generate_html(result)
    encoded = html_content.encode("utf-8")

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, _format: str, *_args: object) -> None:  # suppress access logs
            pass

    server = http.server.HTTPServer(("127.0.0.1", port), _Handler)
    url = f"http://localhost:{port}"

    console.print(f"\n[bold green]critiq report serving at[/] [bold cyan]{url}[/]")
    console.print("[dim]Press Ctrl+C to stop.[/]")

    if open_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console.print("\n[dim]Server stopped.[/]")
    finally:
        server.server_close()


def save_html(result: ReviewResult, path: str | Path) -> Path:
    """Write HTML report to *path* and return the resolved Path."""
    dest = Path(path)
    dest.write_text(generate_html(result), encoding="utf-8")
    return dest
