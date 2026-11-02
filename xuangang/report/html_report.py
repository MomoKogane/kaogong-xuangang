"""生成自包含 HTML 报告（单文件，无外部请求）。"""

from __future__ import annotations

import html
import json
from pathlib import Path

from .common import payload

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "web" / "report.html"


def write_html(result, path: Path, profile=None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = payload(result)
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    text = text.replace("</", "<\\/").replace("<!--", "<\\!--")
    title = f"考公选岗报告 {result.profile.target_year if result.profile else ''}".strip()
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    output = template.replace("__TITLE__", html.escape(title)).replace("__DATA__", text)
    path.write_text(output, encoding="utf-8")
    return path
