"""IC Markets MetaTrader server-wall-clock conversion utilities."""

from __future__ import annotations

from calendar import monthcalendar
from datetime import UTC, datetime, timedelta

from forex.errors import OperatorError


def _sunday(year: int, month: int, occurrence: int) -> int:
    sundays = [week[6] for week in monthcalendar(year, month) if week[6]]
    return sundays[occurrence - 1]


def server_utc_offset(value: datetime) -> timedelta:
    """Return IC Markets' New-York-close server offset for a historical date."""
    start = datetime(value.year, 3, _sunday(value.year, 3, 2), tzinfo=UTC)
    end = datetime(value.year, 11, _sunday(value.year, 11, 1), tzinfo=UTC)
    return timedelta(hours=3 if start <= value < end else 2)


def server_timestamp_to_utc(timestamp: float) -> datetime:
    """Interpret an epoch-like MT5 value as server wall time and normalize it to UTC."""
    server_time = datetime.fromtimestamp(timestamp, tz=UTC)
    return server_time - server_utc_offset(server_time)


def validate_live_server_timestamp(
    timestamp: float, now: datetime, tolerance: timedelta,
) -> None:
    """Reject a live MT5 clock that disagrees with the documented server schedule."""
    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise ValueError("server-clock reference time must be UTC-aware")
    encoded_server_time = datetime.fromtimestamp(timestamp, tz=UTC)
    expected = server_utc_offset(encoded_server_time)
    observed = encoded_server_time - now
    if abs(observed - expected) > tolerance:
        raise OperatorError(
            "MT5 server time disagrees with the IC Markets GMT+2/GMT+3 schedule: "
            f"observed offset {observed}, expected {expected} (tolerance {tolerance}). "
            "Confirm the VPS clock is synchronized and the configured server is IC Markets."
        )


def in_weekend(value: datetime, close_weekday: int, close_hour: int,
               open_weekday: int, open_hour: int) -> bool:
    """Classify an IC Markets weekend using standard-time UTC config as the baseline."""
    dst_shift_minutes = int((server_utc_offset(value) - timedelta(hours=2)).total_seconds() / 60)
    minute = value.weekday() * 1440 + value.hour * 60 + value.minute
    close = close_weekday * 1440 + close_hour * 60 - dst_shift_minutes
    opening = open_weekday * 1440 + open_hour * 60 - dst_shift_minutes
    if close <= opening:
        return close <= minute < opening
    return minute >= close or minute < opening
