"""Plain-text helpers for channels that cannot render HTML (SMS / push / in-app summaries)."""

import html
import re

_BLOCK = re.compile(r"</(p|div|li|h[1-6])>|<br\s*/?>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def html_to_text(value: str | None, limit: int | None = None) -> str:
    """Strip tags (block ends become spaces), unescape entities, collapse whitespace; trim to ``limit`` with "…"."""
    text = _SPACE.sub(" ", html.unescape(_TAG.sub("", _BLOCK.sub(" ", value or "")))).strip()
    if limit is not None and len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text
