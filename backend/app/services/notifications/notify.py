"""``notify_event`` for services (the implementation lives in ``app/core/notifications/notify.py`` so the workflow
engine in ``app/core`` can use it without importing the services layer)."""

from app.core.notifications.notify import notify_event

__all__ = ["notify_event"]
