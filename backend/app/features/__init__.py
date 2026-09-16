"""Imports every phase's feature-key module so ``FEATURE_REGISTRY`` is complete at import time.

Core keys live in ``app/core/features.py``. Each phase adds ``from app.features import <module>  # noqa: F401``.
"""

from app.core.features import FEATURE_REGISTRY  # noqa: F401  (core keys)

__all__ = ["FEATURE_REGISTRY"]
