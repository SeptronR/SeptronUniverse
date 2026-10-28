"""Web locale packs — Prompts/39 §39.6 ``i18n_service`` (``i18n.web``).

Packs are the frontend build's ``public/locales/{lng}.json`` (also bundled in the API image at
``app/templates/locales``); institution vocabulary overrides (``i18n.overrides`` = ``{locale: {dotted.key: text}}``)
are merged over the pack. Unknown locales → 404; locales outside ``i18n.web_locales`` → 404.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.schemas.portals import LocalePackOut

_ROOT = Path(__file__).resolve().parents[4]
PACK_DIRS = (_ROOT / "frontend" / "public" / "locales", Path(__file__).resolve().parents[2] / "templates" / "locales")


@lru_cache(maxsize=8)
def pack(locale: str) -> dict[str, Any]:
    for d in PACK_DIRS:
        f = d / f"{locale}.json"
        if f.exists():
            return dict(json.loads(f.read_text(encoding="utf-8")))
    raise APIError(404, ErrorCode.NOT_FOUND, f"No language pack for {locale!r}")


def _set(tree: dict[str, Any], dotted: str, value: str) -> None:
    node = tree
    parts = dotted.split(".")
    for p in parts[:-1]:
        nxt = node.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            node[p] = nxt
        node = nxt
    node[parts[-1]] = value


async def locale_pack(db: AsyncSession, institution_id: Any, locale: str) -> LocalePackOut:
    allowed = ["en", "hi"]
    overrides: dict[str, str] = {}
    if institution_id is not None:
        rows = (
            await db.execute(
                text(
                    "SELECT key, value FROM institution_settings WHERE institution_id = :i AND category = 'i18n' "
                    "AND key IN ('web_locales', 'overrides') AND college_id IS NULL"
                ),
                {"i": institution_id},
            )
        ).all()
        for k, v in rows:
            if k == "web_locales" and isinstance(v, list):
                allowed = [str(x) for x in v]
            if k == "overrides" and isinstance(v, dict):
                overrides = {str(a): str(b) for a, b in (v.get(locale) or {}).items()}
    if locale not in allowed:
        raise APIError(404, ErrorCode.NOT_FOUND, f"Language {locale!r} is not offered")
    strings = json.loads(json.dumps(pack(locale)))
    for key, value in overrides.items():
        _set(strings, key, value)
    return LocalePackOut(locale=locale, strings=strings, overrides=overrides)
