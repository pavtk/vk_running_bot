from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.bot.handlers.stats_utils import group_reports_by_week


def test_group_reports_by_week_counts_runs_and_numbers_event_weeks():
    rows = [
        (datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc), Decimal('5.5')),
        (datetime(2026, 1, 7, 8, 0, tzinfo=timezone.utc), Decimal('2.0')),
        (datetime(2026, 1, 12, 8, 0, tzinfo=timezone.utc), Decimal('3.25')),
        (datetime(2026, 1, 20, 8, 0, tzinfo=timezone.utc), Decimal('4.0')),
    ]

    result = group_reports_by_week(rows, event_starts_on=datetime(2026, 1, 5).date(), through_date=datetime(2026, 1, 20).date())

    assert result == [
        (1, Decimal('7.50'), 2),
        (2, Decimal('3.25'), 1),
        (3, Decimal('4.00'), 1),
    ]


def test_group_reports_by_week_includes_weeks_without_runs():
    result = group_reports_by_week(
        [(datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc), Decimal('5.5'))],
        event_starts_on=datetime(2026, 1, 5).date(),
        through_date=datetime(2026, 1, 20).date(),
    )

    assert result == [
        (1, Decimal('5.50'), 1),
        (2, Decimal('0.00'), 0),
        (3, Decimal('0.00'), 0),
    ]


def test_group_reports_by_week_returns_empty_before_event_starts():
    assert group_reports_by_week(
        [],
        event_starts_on=datetime(2026, 1, 5).date(),
        through_date=datetime(2026, 1, 4).date(),
    ) == []


def test_midweek_start_ends_first_week_on_sunday_in_configured_timezone():
    moscow = ZoneInfo("Europe/Moscow")
    rows = [
        (datetime(2026, 1, 11, 20, 59, tzinfo=timezone.utc), Decimal("4.0")),
        (datetime(2026, 1, 11, 21, 0, tzinfo=timezone.utc), Decimal("5.0")),
        (datetime(2026, 1, 18, 20, 59, tzinfo=timezone.utc), Decimal("6.0")),
    ]

    result = group_reports_by_week(
        rows,
        event_starts_on=datetime(2026, 1, 7).date(),
        through_date=datetime(2026, 1, 18).date(),
        report_timezone=moscow,
    )

    assert result == [
        (1, Decimal("4.00"), 1),
        (2, Decimal("11.00"), 2),
    ]
