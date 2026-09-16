"""``@register_pack("IN")`` registry — docs/Regulatory_Pack_IN.md.

``get_pack(code)`` falls back to ``GENERIC``. Packs are plain modules importing this registry; ``app/core/packs/__init__``
imports them so the registry is complete at import time.
"""

from collections.abc import Callable

from app.core.packs.base import RegulatoryPack

PACKS: dict[str, RegulatoryPack] = {}


def register_pack(code: str) -> Callable[[Callable[[], RegulatoryPack]], Callable[[], RegulatoryPack]]:
    def deco(factory: Callable[[], RegulatoryPack]) -> Callable[[], RegulatoryPack]:
        pack = factory()
        assert pack.code == code, f"pack code mismatch: {pack.code} != {code}"
        assert code not in PACKS, f"duplicate pack {code}"
        PACKS[code] = pack
        return factory

    return deco


def get_pack(code: str | None) -> RegulatoryPack:
    return PACKS.get((code or "GENERIC").upper()) or PACKS["GENERIC"]


def pack_codes() -> list[str]:
    return sorted(PACKS)
