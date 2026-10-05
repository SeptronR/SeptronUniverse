"""Imports every model module so Alembic autogenerate and the drift check see the full metadata.

Phases append their module here (``from app.models import <module>  # noqa: F401``).
"""

from app.models import academic, communication, curriculum, hr, platform, saas  # noqa: F401

__all__ = ["academic", "communication", "curriculum", "hr", "platform", "saas"]
