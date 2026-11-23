"""One business clock for the whole service.

The numbers on the wallboard, the drill-down and the emailed report are the plant's: BRAK, the
rollup procedure and the Daily Parts Shipped email all use Central days. This module names that
zone once (KPI_TIMEZONE, default America/Chicago, an IANA name so daylight saving follows BRAK)
and answers "what day is it?" for the server, the refresh loop and the pages (through /api/health).
Nothing here reads the host operating-system clock zone (GP-AI01 runs on UTC) or a viewer's clock.
"""

from __future__ import annotations

from datetime import date, datetime
import os
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

DEFAULT_BUSINESS_TIMEZONE = "America/Chicago"
TIMEZONE_ENVIRONMENT = "KPI_TIMEZONE"


def business_timezone_name() -> str:
    """The configured business zone name; an unset or blank setting means the plant's Central zone."""

    configured = os.environ.get(TIMEZONE_ENVIRONMENT, "").strip()
    return configured or DEFAULT_BUSINESS_TIMEZONE


def business_zone() -> ZoneInfo:
    return ZoneInfo(business_timezone_name())


def business_now(moment: Optional[datetime] = None) -> datetime:
    """The current instant in the business zone (an aware moment can be passed in, for tests)."""

    zone = business_zone()
    if moment is None:
        return datetime.now(zone)
    if moment.tzinfo is None:
        raise ValueError("A business-clock moment must carry a time zone.")
    return moment.astimezone(zone)


def business_today(moment: Optional[datetime] = None) -> date:
    return business_now(moment).date()


def business_clock_fields(moment: Optional[datetime] = None) -> Dict[str, Any]:
    """Fields every health endpoint reports so a page can follow the server's day instead of its own clock."""

    now = business_now(moment)
    return {
        "business_date": now.date().isoformat(),
        "business_timezone": business_timezone_name(),
        "server_time": now.isoformat(timespec="seconds"),
    }
