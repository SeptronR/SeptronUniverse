"""Tasks on the ``notifications`` queue — populated by the phases (names ``notifications.<task>`` route here via task_routes)."""

from app.tasks.celery_app import celery  # noqa: F401
