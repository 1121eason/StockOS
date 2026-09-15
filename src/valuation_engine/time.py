from datetime import UTC, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal

ET = ZoneInfo("America/New_York")


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must include timezone")
    return value.astimezone(UTC)


def now() -> datetime:
    return datetime.now(UTC)


@lru_cache(maxsize=256)
def sessions(start: str, end: str):  # type: ignore[no-untyped-def]
    return mcal.get_calendar("NASDAQ").schedule(start_date=start, end_date=end)


def calculate_next_tradable_timestamp(value: datetime) -> datetime:
    """Next regular-session OPEN at/after availability; conservative even intraday."""
    value = aware(value)
    day = value.astimezone(ET).date()
    schedule = sessions(str(day), str(day + timedelta(days=14)))
    for opening in schedule["market_open"]:
        result = opening.to_pydatetime()
        if result >= value:
            return result.astimezone(ET)
    raise ValueError("Calendar contains no eligible session")
