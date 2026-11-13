from collections import defaultdict
from datetime import date, datetime, timezone, tzinfo
from decimal import Decimal


def group_reports_by_week(
    rows: list[tuple[datetime, Decimal]],
    event_starts_on: date,
    through_date: date,
    report_timezone: tzinfo = timezone.utc,
) -> list[tuple[int, Decimal, int]]:
    """Group reports into a partial first calendar week and Monday-Sunday weeks."""
    if through_date < event_starts_on:
        return []

    first_week_days = 7 - event_starts_on.weekday()

    def week_number_for(day: date) -> int:
        days_since_start = (day - event_starts_on).days
        if days_since_start < first_week_days:
            return 1
        return (days_since_start - first_week_days) // 7 + 2

    elapsed_weeks = week_number_for(through_date)
    by_week: dict[int, tuple[Decimal, int]] = defaultdict(lambda: (Decimal("0"), 0))
    for created_at, distance in rows:
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        report_date = created_at.astimezone(report_timezone).date()
        if report_date < event_starts_on or report_date > through_date:
            continue
        week_number = week_number_for(report_date)
        total, run_count = by_week[week_number]
        by_week[week_number] = (total + distance, run_count + 1)

    return [
        (
            week_number,
            by_week[week_number][0].quantize(Decimal("0.01")),
            by_week[week_number][1],
        )
        for week_number in range(1, elapsed_weeks + 1)
    ]
