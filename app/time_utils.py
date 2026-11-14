from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.settings import settings


def local_today() -> date:
    """Return today's date in the configured application timezone."""
    return datetime.now(ZoneInfo(settings.TIMEZONE)).date()
