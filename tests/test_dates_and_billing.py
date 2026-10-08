from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.billing import EVENT_NAME, billing_decision
from src.normalization.dates import epoch_ms_to_dt, validity

AT = datetime(2026, 10, 8, 12, tzinfo=UTC)
D = lambda d: datetime(2026, 10, d, tzinfo=UTC)  # noqa: E731


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (D(1), D(20), "active"),
        (D(9), D(20), "upcoming"),
        (D(1), D(5), "expired"),
        (None, None, "unknown"),
        (D(1), None, "active"),
        (None, D(5), "expired"),
    ],
)
def test_validity(start, end, expected):
    assert validity(start, end, AT) == expected


@pytest.mark.parametrize("raw", [None, 0, -5, "2026-10-01", True])
def test_dates_never_guessed(raw):
    assert epoch_ms_to_dt(raw) is None


def test_epoch_ms_is_utc():
    assert epoch_ms_to_dt(1732665600000) == datetime(2024, 11, 27, tzinfo=UTC)


@pytest.mark.parametrize(
    ("status", "matched", "billable"),
    [
        ("success", 0, True),
        ("success", 4, True),
        ("partial", 2, True),
        ("partial", 0, False),
        ("source_unavailable", 0, False),
        ("invalid_input", 0, False),
    ],
)
def test_billing(status, matched, billable):
    b = billing_decision(status, matched)
    assert b.billable is billable
    assert b.event_name == (EVENT_NAME if billable else None)
