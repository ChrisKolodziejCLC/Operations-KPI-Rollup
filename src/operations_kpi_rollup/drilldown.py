"""Standard wallboard drill-down: painter, repaint, and Finesse detail.

Chris Kolodziej directed on 2026-11-18 that this detail be a standard view on
GP-AI01 instead of an identity-gated surface. The aggregate wallboard contract
(/api/snapshot) is unchanged and still contains no named people or part rows.
This module owns a separate snapshot, validated by the reviewed detail contract
in `restricted.py`, that is served only under /drilldown and /api/drilldown/*.
The drill-down can be disabled without a redeploy with KPI_DRILLDOWN_ENABLED=0.
"""

from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from .assembly_details import assembly_details_section, unavailable_section as assembly_details_unavailable
from .odbc import execute_assembly_details, execute_standard_drilldown
from .restricted import build_restricted_snapshot, validate_restricted_snapshot
from .restricted_web import RestrictedRefreshError, RestrictedState


DRILLDOWN_VERSION = "0.38.0-chart-clarity"
_DISABLED_VALUES = {"0", "false", "no", "off"}


class DrilldownRefreshError(RestrictedRefreshError):
    """Raised for bounded, user-presentable drill-down refresh problems."""


def _assembly_details_pinned() -> bool:
    return bool(os.environ.get("KPI_ASSEMBLY_DETAILS_PROCEDURE_HASH", "").strip())


def _assembly_details_for_snapshot(report_date: date) -> Optional[Dict[str, Any]]:
    """Assembly counts are optional: an unset hash means the feature is not deployed; a failure never blocks the drill-down."""
    if not _assembly_details_pinned():
        return None
    try:
        return assembly_details_section(execute_assembly_details(report_date), report_date)
    except Exception as error:  # noqa: BLE001 - the rest of the drill-down must keep working
        return assembly_details_unavailable("The assembly-details procedure could not be read (" + error.__class__.__name__ + ").")


class DrilldownState(RestrictedState):
    LABEL = "drill-down"
    MODE_ENV = "KPI_DRILLDOWN_DATA_MODE"
    FRESHNESS_ENV = "KPI_DRILLDOWN_REFRESH_FRESHNESS_SECONDS"
    AUTO_REFRESH_ENV = "KPI_DRILLDOWN_AUTO_REFRESH_SECONDS"
    MIN_REFRESH_ENV = "KPI_DRILLDOWN_MIN_REFRESH_SECONDS"
    SERVICE_NAME = "operations-kpi-rollup-drilldown"
    REFRESH_BOUNDARY = "standard-wallboard-view"
    THREAD_NAME = "operations-kpi-drilldown-refresh"
    LOG_EVENT = "drilldown-auto-refresh-error"

    def __init__(self, mode: str, snapshot_dir: Path, fixture_path: Optional[Path] = None) -> None:
        # Stagger this process's first drill-down query behind the wallboard's
        # own startup refresh so a restart never runs both heavy queries at once.
        self.initial_delay_seconds = self._bounded_seconds(
            "KPI_DRILLDOWN_INITIAL_DELAY_SECONDS", 20.0, 0.0, 600.0
        )
        super().__init__(mode, snapshot_dir, fixture_path)

    def snapshot(self, report_date: Optional[date] = None) -> Optional[Dict[str, Any]]:
        """A saved day written before the assembly counts existed is treated as not saved once the procedure is pinned.

        The page then builds that day on demand, exactly as it does for a day with no saved copy, so the Assembly production
        panel fills in without anyone pressing Refresh. A failed build still stores an assembly section (marked unavailable),
        so a day is never rebuilt in a loop, and the older saved files stay on disk untouched."""
        snapshot = super().snapshot(report_date)
        if report_date is not None and snapshot is not None and "assembly" not in snapshot and _assembly_details_pinned():
            return None
        return snapshot

    def _fetch_live(self, report_date: date) -> Dict[str, Any]:
        snapshot = build_restricted_snapshot(report_date, execute_standard_drilldown(report_date))
        assembly = _assembly_details_for_snapshot(report_date)
        if assembly is not None:
            snapshot["assembly"] = assembly
            validate_restricted_snapshot(snapshot)
        return snapshot

    def _incompatible_snapshot(self, path: Path, exc: BaseException) -> None:
        # Cache files from an older contract (for example the named v1 snapshots) are discarded
        # instead of disabling the drill-down. Fixtures are never touched.
        if path.parent != self.snapshot_dir:
            raise exc
        discarded = 0
        for candidate in list(self.snapshot_dir.glob("*.json")):
            try:
                self._read_snapshot(candidate)
            except (ValueError, OSError):
                candidate.unlink(missing_ok=True)
                discarded += 1
        print(
            json.dumps(
                {"event": "drilldown-incompatible-snapshots-discarded", "files": discarded, "error": f"{type(exc).__name__}: {str(exc)[:160]}"},
                separators=(",", ":"),
            ),
            flush=True,
        )

    def _auto_refresh_loop(self) -> None:
        if self.initial_delay_seconds and self._auto_refresh_stop.wait(self.initial_delay_seconds):
            return
        super()._auto_refresh_loop()


def drilldown_enabled() -> bool:
    return os.environ.get("KPI_DRILLDOWN_ENABLED", "1").strip().lower() not in _DISABLED_VALUES


def create_drilldown_state(wallboard_mode: str, wallboard_snapshot_dir: Path) -> Optional[DrilldownState]:
    """Build the drill-down state, or return None when it is disabled.

    Fixture mode needs an explicit fixture path; without one the drill-down
    stays off so local previews never surface empty pages.
    """

    if not drilldown_enabled():
        return None
    mode = os.environ.get("KPI_DRILLDOWN_DATA_MODE", wallboard_mode).strip().lower()
    configured_dir = os.environ.get("KPI_DRILLDOWN_SNAPSHOT_DIR", "").strip()
    snapshot_dir = Path(configured_dir) if configured_dir else wallboard_snapshot_dir / "drilldown"
    fixture_value = os.environ.get("KPI_DRILLDOWN_FIXTURE_PATH", "").strip()
    fixture_path = Path(fixture_value) if fixture_value else None
    if mode == "fixture" and fixture_path is None:
        return None
    return DrilldownState(mode, snapshot_dir, fixture_path)


def disabled_event(error: BaseException) -> str:
    return json.dumps(
        {"event": "drilldown-disabled", "error": f"{type(error).__name__}: {str(error)[:240]}"},
        separators=(",", ":"),
    )
