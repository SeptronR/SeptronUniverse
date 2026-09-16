"""Tasks on the ``documents`` queue — populated by the phases (names ``documents.<task>`` route here via task_routes)."""

from app.tasks.celery_app import celery  # noqa: F401
