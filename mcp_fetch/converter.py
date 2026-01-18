from __future__ import annotations

from markdownify import markdownify as _markdownify


def html_to_markdown(html: str) -> str:
    return _markdownify(
        html or "",
        heading_style="ATX",
        bullets="-",
    )
