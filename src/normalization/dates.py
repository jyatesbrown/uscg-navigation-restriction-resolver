from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

Validity = Literal["active", "upcoming", "expired", "unknown"]


def epoch_ms_to_dt(value: Any) -> datetime | None:
    """NAVCEN dates are epoch milliseconds (UTC). Anything else is treated as absent, never guessed."""
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z") if dt else None


def validity(start: datetime | None, end: datetime | None, at: datetime) -> Validity:
    if start is None and end is None:
        return "unknown"
    if end is not None and at > end:
        return "expired"
    if start is not None and at < start:
        return "upcoming"
    return "active"
