"""Regulatory packs registry (IN, GENERIC). Importing the package registers every pack."""

from app.core.packs import generic_pack, in_pack  # noqa: F401
from app.core.packs.registry import PACKS, get_pack, pack_codes, register_pack

__all__ = ["PACKS", "get_pack", "pack_codes", "register_pack"]
