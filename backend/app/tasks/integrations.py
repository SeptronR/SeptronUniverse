"""Tasks on the ``integrations`` queue — populated by the phases (names ``integrations.<task>`` route here via task_routes)."""

from app.tasks.celery_app import celery  # noqa: F401
