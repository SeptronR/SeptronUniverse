"""Calendar — ``calendar_events`` / ``calendar_feed_tokens`` of section 24 (Prompts/25 §25.3).

Both tables were mapped earlier and are re-exported here: ``CalendarEvent`` by Phase 14 (``app/models/exams.py`` —
the exam date-sheet publishes its rows with ``source_type='exam_paper'``) and ``CalendarFeedToken`` by Phase 10
(``app/models/timetable.py`` — one live token per user; the Phase 25 personal feed and the Phase 10 timetable feed
share it, so a new token from either screen revokes the other's).
"""

from app.models.exams import CalendarEvent
from app.models.timetable import CalendarFeedToken

__all__ = ["CalendarEvent", "CalendarFeedToken"]
