"""Imports every model module so Alembic autogenerate and the drift check see the full metadata.

Phases append their module here (``from app.models import <module>  # noqa: F401``).
"""

from app.models import academic, admissions, communication, curriculum, hr, platform, saas, students  # noqa: F401

__all__ = ["academic", "admissions", "communication", "curriculum", "hr", "platform", "saas", "students"]
