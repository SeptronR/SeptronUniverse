"""Tasks on the ``reports`` queue — populated by the phases (names ``reports.<task>`` route here via task_routes)."""

from app.tasks.celery_app import celery  # noqa: F401
