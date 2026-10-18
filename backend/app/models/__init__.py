"""Imports every model module so Alembic autogenerate and the drift check see the full metadata.

Phases append their module here (``from app.models import <module>  # noqa: F401``).
"""

from app.models import (  # noqa: F401
    academic,
    attendance,
    admissions,
    communication,
    curriculum,
    hr,
    offerings,
    platform,
    registration,
    saas,
    students,
    timetable,
)

__all__ = [
    "academic",
    "attendance",
    "admissions",
    "communication",
    "curriculum",
    "hr",
    "offerings",
    "platform",
    "registration",
    "saas",
    "students",
    "timetable",
]
