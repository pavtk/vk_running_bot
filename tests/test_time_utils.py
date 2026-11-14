from datetime import datetime, timezone

from app import time_utils
from app.database.service import (
    event_is_registration_available,
    event_is_report_available,
)


def test_local_today_uses_configured_timezone(monkeypatch):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            current = cls(2026, 11, 14, 21, 30, tzinfo=timezone.utc)
            return current.astimezone(tz) if tz else current

    monkeypatch.setattr(time_utils, "datetime", FrozenDateTime)
    monkeypatch.setattr(time_utils.settings, "TIMEZONE", "Europe/Moscow")

    assert time_utils.local_today().isoformat() == "2026-11-15"


def test_event_availability_defaults_to_configured_local_date(monkeypatch):
    monkeypatch.setattr(
        "app.database.service.local_today",
        lambda: datetime(2026, 11, 15).date(),
    )

    assert event_is_registration_available(
        starts_on=datetime(2026, 11, 14).date(),
        ends_on=datetime(2026, 11, 15).date(),
        registration_open=True,
    )
    assert event_is_report_available(
        starts_on=datetime(2026, 11, 14).date(),
        ends_on=datetime(2026, 11, 15).date(),
        registration_open=False,
    )
