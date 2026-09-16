"""Institution timezone / locale / currency helpers — docs/Technical_Architecture.md §2.

Timestamps are stored in UTC; academic dates are interpreted in the institution timezone; money is INTEGER paise.
"""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

DEFAULT_TZ = "Asia/Kolkata"
DEFAULT_LOCALE = "en-IN"
DEFAULT_CURRENCY = "INR"


def institution_tz(institution: object | None) -> ZoneInfo:
    name = getattr(institution, "timezone", None) or DEFAULT_TZ
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 - unknown zone name in settings falls back to the default
        return ZoneInfo(DEFAULT_TZ)


def now_utc() -> datetime:
    return datetime.now(UTC)


def today_for(institution: object | None) -> date:
    """Today's date in the institution's timezone (academic dates are institution-local)."""
    return datetime.now(institution_tz(institution)).date()


def to_local(dt: datetime, institution: object | None) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(institution_tz(institution))


def local_day_bounds(day: date, institution: object | None) -> tuple[datetime, datetime]:
    """UTC [start, end) of a local calendar day — for querying TIMESTAMPTZ columns by institution date."""
    tz = institution_tz(institution)
    start = datetime(day.year, day.month, day.day, tzinfo=tz)
    end = datetime(day.year, day.month, day.day, 23, 59, 59, 999999, tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


def paise_to_display(paise: int, currency: str = DEFAULT_CURRENCY, locale: str = DEFAULT_LOCALE) -> str:
    """Format paise as a currency string using Indian digit grouping for en-IN (12,34,567.00)."""
    rupees, p = divmod(abs(int(paise)), 100)
    sign = "-" if paise < 0 else ""
    s = str(rupees)
    if locale.endswith("-IN") and len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups + [tail])
    elif len(s) > 3:
        s = f"{rupees:,}"
    symbol = {"INR": "₹"}.get(currency, currency + " ")
    return f"{sign}{symbol}{s}.{p:02d}"
