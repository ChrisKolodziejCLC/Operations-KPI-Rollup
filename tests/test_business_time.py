"""The service has one business clock: the plant's Central day, owned by the server and followed by the pages."""

from datetime import date, datetime, timezone
from pathlib import Path
import re

import pytest

from operations_kpi_rollup.business_time import (
    DEFAULT_BUSINESS_TIMEZONE,
    business_clock_fields,
    business_now,
    business_timezone_name,
    business_today,
)
from operations_kpi_rollup.web import AppState

ROOT = Path(__file__).parents[1]
SRC = ROOT / "src" / "operations_kpi_rollup"
FIXTURE = ROOT / "examples" / "2026-09-16.json"
EASTERN = "America/Indiana/Indianapolis"


@pytest.fixture(autouse=True)
def clean_zone(monkeypatch):
    monkeypatch.delenv("KPI_TIMEZONE", raising=False)


def test_the_business_zone_defaults_to_the_plants_central_zone(monkeypatch):
    assert DEFAULT_BUSINESS_TIMEZONE == "America/Chicago"
    assert business_timezone_name() == "America/Chicago"
    monkeypatch.setenv("KPI_TIMEZONE", "   ")
    assert business_timezone_name() == "America/Chicago"


def test_an_explicit_setting_wins(monkeypatch):
    monkeypatch.setenv("KPI_TIMEZONE", EASTERN)
    assert business_timezone_name() == EASTERN


def test_the_day_follows_the_named_zone_not_the_viewer(monkeypatch):
    # 05:30 UTC on 11-24 is 23:30 Central on 11-23 but already 00:30 Eastern on 11-24.
    moment = datetime(2026, 11, 24, 5, 30, tzinfo=timezone.utc)
    assert business_today(moment) == date(2026, 11, 23)
    monkeypatch.setenv("KPI_TIMEZONE", EASTERN)
    assert business_today(moment) == date(2026, 11, 24)


def test_the_day_flips_at_midnight_central(monkeypatch):
    before = datetime(2026, 11, 24, 5, 59, 59, tzinfo=timezone.utc)
    after = datetime(2026, 11, 24, 6, 0, 0, tzinfo=timezone.utc)
    assert business_today(before) == date(2026, 11, 23)
    assert business_today(after) == date(2026, 11, 24)


def test_daylight_saving_follows_the_named_zone():
    winter = business_now(datetime(2026, 11, 24, 18, 0, tzinfo=timezone.utc))
    summer = business_now(datetime(2026, 7, 14, 18, 0, tzinfo=timezone.utc))
    assert winter.utcoffset().total_seconds() == -6 * 3600
    assert summer.utcoffset().total_seconds() == -5 * 3600


def test_clock_fields_are_what_the_pages_read():
    fields = business_clock_fields(datetime(2026, 11, 24, 16, 30, 5, tzinfo=timezone.utc))
    assert fields == {
        "business_date": "2026-11-24",
        "business_timezone": "America/Chicago",
        "server_time": "2026-11-24T10:30:05-06:00",
    }


def test_a_moment_without_a_zone_is_refused():
    with pytest.raises(ValueError):
        business_now(datetime(2026, 11, 24, 10, 0))


def test_health_reports_the_servers_day_for_both_pages(tmp_path, monkeypatch):
    state = AppState("fixture", tmp_path / "snapshots", FIXTURE)
    health = state.health()
    assert health["business_timezone"] == "America/Chicago"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", health["business_date"])
    assert health["business_date"] == datetime.fromisoformat(health["server_time"]).date().isoformat()
    assert datetime.fromisoformat(health["server_time"]).utcoffset().total_seconds() in (-6 * 3600, -5 * 3600)

    monkeypatch.setenv("KPI_TIMEZONE", EASTERN)
    assert state.health()["business_timezone"] == EASTERN


def test_no_module_keeps_its_own_eastern_default():
    offenders = [path.name for path in sorted(SRC.glob("*.py")) if "Indianapolis" in path.read_text(encoding="utf-8")]
    assert offenders == []


def test_the_service_unit_names_the_central_zone():
    unit = (ROOT / "deploy" / "operations-kpi-rollup.service").read_text(encoding="utf-8")
    assert "Environment=KPI_TIMEZONE=America/Chicago" in unit
    assert "Indianapolis" not in unit


def test_both_pages_ask_the_server_for_today_and_show_times_in_the_plant_zone():
    wallboard = (SRC / "web" / "app.js").read_text(encoding="utf-8")
    drilldown = (SRC / "drilldown_web" / "app.js").read_text(encoding="utf-8")
    for script in (wallboard, drilldown):
        # The only no-argument read of the viewer's own date is the fallback inside businessToday().
        assert script.count("localDateISO()") == 1
        assert "const businessToday = () => businessDate || localDateISO();" in script
        assert "health.business_date" in script and "health.business_timezone" in script
        assert "timeZone: businessTimeZone" in script and "timeZoneName: 'short'" in script
        assert "new Date(snapshot.generated_at).toLocaleString()" not in script
    assert wallboard.index("await loadHealth();\n  const today = businessToday();") > 0
    assert "async function loadBusinessClock()" in drilldown
    start = drilldown[drilldown.index("async function start()"):]
    assert start.index("await loadBusinessClock();") < start.index("businessToday()")
    for handler in ("$('#next-day')", "$('#today')"):
        block = drilldown[drilldown.index(handler):]
        assert block[:200].count("async () =>") == 1 and "await loadBusinessClock();" in block[:260]
