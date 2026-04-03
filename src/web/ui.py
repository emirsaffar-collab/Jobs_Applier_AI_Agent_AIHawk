"""
Web UI for AIHawk Resume Builder.

The HTML, CSS, and JavaScript live in separate, editable files:
  - src/web/templates/index.html  (page structure)
  - src/web/static/style.css      (all styling)
  - src/web/static/app.js         (all client-side logic)

get_html() reads those files and assembles a single self-contained HTML
response so the FastAPI backend can serve them inline without a static-file
server.
"""

from pathlib import Path

_HERE = Path(__file__).parent

_TEMPLATE = _HERE / "templates" / "index.html"
_CSS = _HERE / "static" / "style.css"
_JS = _HERE / "static" / "app.js"


def get_html() -> str:
    """Assemble and return the complete HTML page for the web UI.

    CSS and JavaScript are loaded from their own files so they can be
    edited independently with full IDE/linter support.  The assembled
    output is byte-for-byte identical to the old monolithic _HTML constant.
    """
    template = _TEMPLATE.read_text(encoding="utf-8")
    css = _CSS.read_text(encoding="utf-8")
    js = _JS.read_text(encoding="utf-8")
    return template.replace("{CSS_PLACEHOLDER}", css).replace("{JS_PLACEHOLDER}", js)
