import json
from pathlib import Path
import threading
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import operations_kpi_rollup.web as web
from operations_kpi_rollup.live import CURRENT_METHOD_VERSION
from operations_kpi_rollup.web import AppState, _is_private_address, create_server


FIXTURE = Path(__file__).parents[1] / "examples" / "2026-09-16.json"
LOADED_CHART_FIELDS = (
    "parts_loaded", "production_parts_loaded", "bv_parts_loaded", "service_parts_loaded",
    "unique_pieces_loaded", "carts_loaded", "production_carts_loaded",
    "bv_carts_loaded", "service_carts_loaded",
)


def request_json(url, method="GET", payload=None, headers=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(url, data=body, method=method, headers=headers or {})
    with urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read())


def with_loaded_chart(snapshot):
    report_date = datetime.fromisoformat(snapshot["report_date"]).date()
    history_start = datetime.fromisoformat(snapshot.get("scope", {}).get("history_start", "2026-09-08")).date()
    current = next(row for row in snapshot["daily"] if row["date"] == snapshot["report_date"])
    zero = {field: 0 for field in LOADED_CHART_FIELDS}
    values = {field: int(current.get(field, 0)) for field in LOADED_CHART_FIELDS}
    snapshot["chart_series"] = {"loaded": {
        "performance_model": {
            "effective_date": "2026-11-16",
            "baseline_start": "2026-09-08",
            "baseline_end": "2026-11-15",
            "baseline_completed_loading_days": 46,
            "baseline_net_loading_minutes": 34591.218,
            "baseline_carts_loaded": 4787,
            "baseline_pieces_loaded": 14214,
            "baseline_carts_per_hour": 8.3033,
            "baseline_pieces_per_hour": 24.6548,
            "target_gap_fraction": 0.25,
            "target_carts_per_hour": 9.2274,
            "target_pieces_per_hour": 27.4911,
            "goal_carts_per_hour": 12.0,
            "goal_pieces_per_hour": 36.0,
            "lunch_allowance_minutes": 30,
            "lunch_eligibility_span_minutes": 360,
            "partial_day_scoring": False,
        },
        "selected_day": {
            "first_cart_loaded_at": None,
            "last_cart_loaded_at": None,
            "load_span_minutes": 0.0,
            "lunch_allowance_minutes": 0.0,
            "net_loading_minutes": 0.0,
            "performance_scored": False,
            "carts_per_net_hour": None,
            "pieces_per_net_hour": None,
            "target_carts": None,
            "goal_carts": None,
            "target_pieces": None,
            "goal_pieces": None,
        },
        "hourly": [
            {
                "bucket": f"{report_date.isoformat()}T{hour:02d}:00:00",
                "is_partial": False,
                "data_available": True,
                "represented_day": True,
                "first_cart_loaded_at": None,
                "last_cart_loaded_at": None,
                "load_span_minutes": 0.0,
                "lunch_allowance_minutes": 0.0,
                "net_loading_minutes": 0.0,
                "performance_scored": False,
                **(values if hour == 8 else zero),
            }
            for hour in range(24)
        ],
        "weekly_13": [],
    }}
    report_week = report_date - timedelta(days=(report_date.weekday() + 1) % 7)
    for offset in range(12, -1, -1):
        week_start = report_week - timedelta(weeks=offset)
        full_end = week_start + timedelta(days=6)
        observed_end = min(full_end, report_date)
        observed_days = [week_start + timedelta(days=day) for day in range((observed_end - week_start).days + 1)]
        available_days = [day for day in observed_days if day >= history_start]
        represented_days = [day for day in available_days if day.weekday() < 5 or day == report_date]
        partial = observed_end < full_end
        if partial:
            parts_total = int(current.get("parts_loaded", 0))
            carts_total = int(current.get("carts_loaded", 0))
        else:
            parts_total = len(represented_days) * 100
            carts_total = len(represented_days) * 40
        snapshot["chart_series"]["loaded"]["weekly_13"].append({
            "bucket": week_start.isoformat(),
            "bucket_end": observed_end.isoformat(),
            "is_partial": partial,
            "data_available": bool(available_days),
            "represented_days": len(represented_days),
            "performance_days": 0,
            "performance_comparable": False,
            "net_loading_minutes": 0.0,
            "parts_loaded_total": parts_total,
            "carts_loaded_total": carts_total,
            "average_parts_loaded": round(parts_total / len(represented_days), 1) if represented_days else None,
            "average_carts_loaded": round(carts_total / len(represented_days), 1) if represented_days else None,
            "carts_per_net_hour": None,
            "pieces_per_net_hour": None,
            "average_target_carts": None,
            "average_goal_carts": None,
            "average_target_pieces": None,
            "average_goal_pieces": None,
        })
    loaded_weeks = snapshot["chart_series"]["loaded"]["weekly_13"]
    staged_carts = int(current.get("staged_carts", 0))
    staged_pieces = int(current.get("staged_pieces", 0))
    paint_carts = int(current.get("paint_carts", 0))
    paint_pieces = int(current.get("paint_pieces_processed", 0))
    repaint_numerator = int(current.get("paint_fty_repaint_count", 0))
    repaint_denominator = int(current.get("paint_fty_total", 0))
    finesse_numerator = int(current.get("finesse_repair_count", 0)) + int(current.get("paint_fty_repair_count", 0))
    finesse_denominator = int(current.get("finesse_rejected_count", 0)) + int(current.get("reject_fty_rejected_count", 0))

    def hourly_counts(metric, fields, values, value_hour=8):
        return [
            {
                "bucket": f"{report_date.isoformat()}T{hour:02d}:00:00",
                "is_partial": False,
                "data_available": True,
                "represented_day": True,
                **{field: value if hour == value_hour else 0 for field, value in zip(fields, values)},
            }
            for hour in range(24)
        ]

    def count_weeks(cart_value, piece_value, painted=False):
        rows = []
        for loaded_week in loaded_weeks:
            represented = int(loaded_week["represented_days"])
            row = {
                "bucket": loaded_week["bucket"],
                "bucket_end": loaded_week["bucket_end"],
                "is_partial": loaded_week["is_partial"],
                "data_available": loaded_week["data_available"],
                "represented_days": represented,
                "carts_total": cart_value * represented,
                "pieces_total": piece_value * represented,
                "average_carts": float(cart_value) if represented else None,
                "average_pieces": float(piece_value) if represented else None,
            }
            if painted:
                comparable = bool(represented and not loaded_week["is_partial"])
                row.update({
                    "performance_days": represented,
                    "performance_comparable": comparable,
                    "net_activity_minutes": 600.0 * represented,
                    "carts_per_net_hour": round(cart_value / 10.0, 1) if represented else None,
                    "pieces_per_net_hour": round(piece_value / 10.0, 1) if represented else None,
                    "average_target_carts": 89.7 if comparable else None,
                    "average_goal_carts": 100.0 if comparable else None,
                    "average_target_pieces": 268.8 if comparable else None,
                    "average_goal_pieces": 300.0 if comparable else None,
                })
            rows.append(row)
        return rows

    def quality_weeks(numerator, denominator):
        rows = []
        for loaded_week in loaded_weeks:
            represented = int(loaded_week["represented_days"])
            total_numerator = numerator * represented
            total_denominator = denominator * represented
            rows.append({
                "bucket": loaded_week["bucket"],
                "bucket_end": loaded_week["bucket_end"],
                "is_partial": loaded_week["is_partial"],
                "data_available": loaded_week["data_available"],
                "represented_days": represented,
                "quality_numerator": total_numerator,
                "quality_denominator": total_denominator,
                "rate_percent": round(total_numerator * 100 / total_denominator, 4) if total_denominator else None,
            })
        return rows

    snapshot["chart_series"].update({
        "staged": {
            "performance_model": {
                "baseline_represented_days": 53,
                "baseline_staged_carts": 7,
                "baseline_staged_pieces": 7,
                "baseline_carts_per_snapshot": 0.1321,
                "baseline_pieces_per_snapshot": 0.1321,
                "target_gap_fraction": 0.25,
                "target_carts": 3.0991,
                "target_pieces": 9.0991,
                "goal_carts": 12.0,
                "goal_pieces": 36.0,
                "direction": "at_or_above",
            },
            "selected_day": {"staged_carts": staged_carts, "staged_pieces": staged_pieces},
            "hourly": hourly_counts("staged", ("staged_carts", "staged_pieces"), (staged_carts, staged_pieces), 23),
            "weekly_13": count_weeks(staged_carts, staged_pieces),
        },
        "painted": {
            "performance_model": {
                "baseline_completed_painting_days": 46,
                "baseline_net_painting_minutes": 31482.434,
                "baseline_carts_painted": 4529,
                "baseline_pieces_painted": 13560,
                "baseline_carts_per_hour": 8.6315,
                "baseline_pieces_per_hour": 25.843,
                "target_gap_fraction": 0.25,
                "target_carts_per_hour": 8.9736,
                "target_pieces_per_hour": 26.8822,
                "goal_carts_per_hour": 10.0,
                "goal_pieces_per_hour": 30.0,
            },
            "selected_day": {
                "first_activity_at": f"{report_date.isoformat()}T08:00:00",
                "last_activity_at": f"{report_date.isoformat()}T18:30:00",
                "activity_span_minutes": 630.0,
                "lunch_allowance_minutes": 30.0,
                "net_activity_minutes": 600.0,
                "performance_scored": True,
                "carts_per_net_hour": round(paint_carts / 10.0, 1),
                "pieces_per_net_hour": round(paint_pieces / 10.0, 1),
                "target_carts": 89.7,
                "goal_carts": 100.0,
                "target_pieces": 268.8,
                "goal_pieces": 300.0,
            },
            "hourly": hourly_counts("painted", ("paint_carts", "paint_pieces_processed"), (paint_carts, paint_pieces)),
            "weekly_13": count_weeks(paint_carts, paint_pieces, painted=True),
        },
        "repaint": {
            "performance_model": {
                "baseline_numerator": 975,
                "baseline_denominator": 12446,
                "baseline_percent": 7.8338,
                "target_gap_fraction": 0.25,
                "target_percent": 6.8754,
                "goal_percent": 4.0,
                "direction": "at_or_below",
                "weighted_rate": True,
            },
            "selected_day": {},
            "hourly": hourly_counts("repaint", ("quality_numerator", "quality_denominator"), (repaint_numerator, repaint_denominator)),
            "weekly_13": quality_weeks(repaint_numerator, repaint_denominator),
        },
        "finesse": {
            "performance_model": {
                "baseline_numerator": 1034,
                "baseline_denominator": 2527,
                "baseline_percent": 40.9181,
                "target_gap_fraction": 0.25,
                "target_percent": 53.1886,
                "goal_percent": 90.0,
                "direction": "at_or_above",
                "weighted_rate": True,
            },
            "selected_day": {},
            "hourly": hourly_counts("finesse", ("quality_numerator", "quality_denominator"), (finesse_numerator, finesse_denominator)),
            "weekly_13": quality_weeks(finesse_numerator, finesse_denominator),
        },
    })
    for metric in ("repaint", "finesse"):
        for row in snapshot["chart_series"][metric]["hourly"]:
            denominator = row["quality_denominator"]
            row["rate_percent"] = round(row["quality_numerator"] * 100 / denominator, 4) if denominator else None
    return snapshot


def snapshot_for(report_date):
    snapshot = json.loads(FIXTURE.read_text(encoding="utf-8"))
    date_text = report_date.isoformat()
    snapshot["report_date"] = date_text
    snapshot["generated_at"] = datetime.now(ZoneInfo("America/Indiana/Indianapolis")).isoformat(timespec="seconds")
    snapshot["daily"][-1]["date"] = date_text
    snapshot["scope"]["method_version"] = CURRENT_METHOD_VERSION
    return with_loaded_chart(snapshot)


def test_fixture_wallboard_serves_and_persists_refresh(tmp_path, monkeypatch):
    monkeypatch.setenv("KPI_MIN_REFRESH_SECONDS", "0")
    state = AppState("fixture", tmp_path / "snapshots", FIXTURE)
    server = create_server("127.0.0.1", 0, state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, health = request_json(base + "/api/health")
        assert status == 200
        assert health["status"] == "ok"
        assert health["mode"] == "fixture"
        assert health["refresh_boundary"] == "fixture-only"
        assert health["refresh_in_progress"] is False
        assert health["next_auto_refresh_at"] is None
        assert datetime.fromisoformat(health["server_time"]).tzinfo is not None
        # The pages follow the server's day, not their own computer's clock.
        assert health["business_date"] == datetime.fromisoformat(health["server_time"]).date().isoformat()
        assert health["business_timezone"] == "America/Chicago"

        status, snapshot = request_json(base + "/api/snapshot")
        assert status == 200
        assert snapshot["report_date"] == "2026-09-16"

        status, dated_snapshot = request_json(base + "/api/snapshot?report_date=2026-09-16")
        assert status == 200
        assert dated_snapshot["report_date"] == "2026-09-16"

        status, refreshed = request_json(
            base + "/api/refresh",
            method="POST",
            payload={"report_date": "2026-09-16", "force": True},
            headers={"Content-Type": "application/json", "X-Operations-KPI-Action": "refresh"},
        )
        assert status == 200
        assert refreshed["report_date"] == "2026-09-16"
        assert (tmp_path / "snapshots" / "latest.json").is_file()
        assert len(list((tmp_path / "snapshots").glob("2026-09-16__*.json"))) == 1

        with urlopen(base + "/", timeout=5) as response:
            html = response.read().decode("utf-8")
            assert response.status == 200
            assert "Operations KPI Rollup" in html
            assert "Load selected day" in html
            assert "Previous" in html
            assert "Today" in html
            assert "Next" in html
            assert 'id="report-range"' in html
            assert "refresh-key" not in html
            assert "0.35.0-chart-refinements-r1" in html
            assert 'id="refresh-countdown"' in html
            assert 'id="cards"' in html
            assert 'id="metric-chart-panel"' in html
            assert 'id="metric-chart-content"' in html
            assert "Decision-use boundary" not in html
            assert 'class="method-banner"' not in html
            assert 'id="scope-label"' not in html
            assert 'id="throughput-chart"' not in html
            assert 'id="quality-chart"' not in html
            assert 'id="daily-table"' not in html
            assert 'id="period-table"' not in html
            assert 'id="defect-table"' not in html
            assert 'id="shipping-chart"' not in html
            assert 'id="painter-panel"' not in html
            assert 'id="quality-notes"' not in html
            assert 'id="attention-items"' not in html

        with urlopen(base + "/app.js", timeout=5) as response:
            javascript = response.read().decode("utf-8")
            assert response.status == 200
            assert "production_parts_loaded" in javascript
            assert "bv_parts_loaded" in javascript
            assert "service_parts_loaded" in javascript
            assert "n71_6164_parts_loaded" not in javascript
            assert "production_carts_loaded" in javascript
            assert "bv_carts_loaded" in javascript
            assert "service_carts_loaded" in javascript
            assert "n71_6164_carts_loaded" not in javascript
            assert "production_paint_carts" in javascript
            assert "bv_paint_carts" in javascript
            assert "service_paint_carts" in javascript
            assert "n71_6164_paint_carts" not in javascript
            assert "production_paint_pieces_processed" in javascript
            assert "bv_paint_pieces_processed" in javascript
            assert "service_paint_pieces_processed" in javascript
            assert "n71_6164_paint_pieces_processed" not in javascript
            assert "unique_pieces_loaded" in javascript
            assert "unique_pieces_processed" in javascript
            assert "splitMetricCard('Carts / Pieces loaded', current.parts_loaded" in javascript
            assert "labelNode.append(text('Carts / Pieces staged'))" in javascript
            assert "splitMetricCard('Carts / Pieces painted', current.paint_pieces_processed" in javascript
            assert "compactOptionalInteger(splitTotal(rows[0]))" in javascript
            assert "uniqueDetails(snapshot.chart_series?.loaded?.selected_day, current.unique_pieces_loaded)" in javascript
            assert "metric-split-total" in javascript
            assert "values.push(`${integer(row.n71)} N71-6164`)" not in javascript
            assert "stagedMetricCard(current.staged_carts, current.staged_pieces" in javascript
            assert "`${compactOptionalInteger(carts)} Carts / ${compactOptionalInteger(pieces)} Pieces`" in javascript
            assert "compactOptionalInteger(row.production)" in javascript
            assert "scope-label" not in javascript
            assert "Finesse detail unavailable" in javascript
            assert "dualYieldCard('PPY (Paint Process Yield)'" in javascript
            assert "dualYieldCard('FTY (First Time Yield)'" in javascript
            assert "metric.details.forEach" in javascript
            assert "'Repaint' : 'Repaints'" in javascript
            assert "`${integer(current.reject_ppy_pending_count)} Pending`" in javascript
            assert "`${integer(current.reject_fty_pending_count)} Pending`" in javascript
            assert "'Repaint %'" in javascript
            assert "'Finesse Effectiveness'" in javascript
            assert "ratio(finesseRepair, finesseRejected)" in javascript
            assert "Repaired / ${integer(finesseRejected)} Rejected" in javascript
            assert "finesse_rejected_count" in javascript
            assert "paint_fty_repair_count" in javascript
            assert "reject_fty_rejected_count" in javascript
            assert "FUKA Repaired" in javascript
            assert "Fairings Repaired" in javascript
            assert "Bumpers Repaired" in javascript
            assert "other_paint_fty_repair_count" in javascript and "otherRepaired" in javascript
            assert "Other Repaired" in javascript
            assert "current.ppy_repaint_count" in javascript
            assert "reject_ppy_approved" in javascript
            assert "reject_fty_approved" in javascript
            assert "yieldRatio(metric.numerator, metric.denominator)" in javascript
            assert "inspectionYieldCard(" in javascript
            assert "receiving_bumper_approved" in javascript
            assert "receiving_fairing_approved" in javascript
            assert "final_fuka_approved" in javascript
            assert "final_bumper_approved" in javascript
            assert "final_fairing_approved" in javascript
            assert "trailerCountCard(current.trailers_prepared, current.trailers_shipped, [" in javascript
            assert "Departed = DriverLog TimeOut departures" in javascript
            assert "{label:'Bumper racks', value:current.bumper_racks_shipped}" in javascript
            assert "{label:'FUKA racks', value:current.fuka_racks_shipped}" in javascript
            assert "{label:'Fairing racks', value:current.fairing_racks_shipped}" in javascript
            assert "optionalInteger(metric.value)" in javascript
            assert "return values.join(' / ')" not in javascript
            assert "shippedPieceDetail(snapshot)" in javascript
            assert "`${integer(counts.fuka)} FUKA`" in javascript
            assert "`${integer(counts.bumpers)} Bumpers`" in javascript
            assert "`${integer(counts.n71)} N71-6164`" in javascript
            assert "`${integer(counts.fairings)} Fairings`" in javascript
            assert "if (counts.other) details.push(`${integer(counts.other)} Other`)" in javascript
            assert "'FUKA':palette.teal" in javascript
            assert "'Fairings':palette.blue" in javascript
            assert "'Bumpers':palette.red" in javascript
            assert "'N71-6164':palette.amber" in javascript
            assert "shipping-legend" in javascript
            assert "repaintLineSetDetail(current)" in javascript
            assert "`${integer(row.fuka_paint_fty_repaint_count)} FUKA`" in javascript
            assert "`${integer(row.bumper_paint_fty_repaint_count)} Bumpers`" in javascript
            assert "`${integer(row.fairing_paint_fty_repaint_count)} Fairings`" in javascript
            assert "provisional · not standard OEE" in javascript
            assert "N33 / Chassis Fairing · dated by last assembled piece" in javascript
            assert "N71-6171 · AssembledDate" in javascript
            assert "mic_complete_assy_sets" in javascript
            assert "painted_complete_assy_sets" in javascript
            assert "mic_assembled_bumper_count" in javascript
            assert "painted_assembled_bumper_count" in javascript
            assert "metric-detail-list" in javascript
            assert "metric-detail-row" in javascript
            assert "First Decisions" in javascript
            assert "by receive stamp" not in javascript
            assert "by final stamp" not in javascript
            assert "rangeLabel(snapshot.daily)" in javascript
            assert "WALLBOARD_POLL_MS = 30 * 1000" in javascript
            assert "HEALTH_POLL_MS = 5 * 1000" in javascript
            assert "COUNTDOWN_TICK_MS = 1000" in javascript
            assert "health.next_auto_refresh_at" in javascript
            assert "health.server_time" in javascript
            assert "serverClockOffsetMs" in javascript
            assert "Auto refresh in ${minutes}:${seconds}" in javascript
            assert javascript.index("['Pieces shipped'") > javascript.index("['Assembled bumpers'")
            assert javascript.index("splitMetricCard('Carts / Pieces loaded'") < javascript.index("container.append(stagedMetricCard(")
            assert javascript.index("container.append(stagedMetricCard(") < javascript.index("splitMetricCard('Carts / Pieces painted'")
            assert javascript.index("splitMetricCard('Carts / Pieces painted'") < javascript.index("'Repaint %'")
            assert javascript.index("'Repaint %'") < javascript.index("'Finesse Effectiveness'")
            assert javascript.index("['Pieces shipped'") < javascript.index("container.append(trailerCountCard(")
            assert "loadCachedReport(businessToday(), true)" in javascript
            assert "const loadedToday = await loadCachedReport(today);" in javascript
            assert "if (!loadedToday) await loadLatest();" in javascript
            assert "refreshReport(businessToday(), true)" not in javascript
            assert "refreshReport(localDateISO(), true)" not in javascript
            assert "X-Operations-KPI-Refresh-Key" not in javascript
            assert "sessionStorage" not in javascript
            assert "renderLoadedCharts(snapshot)" in javascript
            assert "renderStagedCharts(snapshot)" in javascript
            assert "renderPaintedCharts(snapshot)" in javascript
            assert "renderQualityCharts(snapshot, 'repaint'" in javascript
            assert "renderQualityCharts(snapshot, 'finesse'" in javascript
            assert "12-cart / 36-piece minimum goals" in javascript
            assert "Scheduled demand stays hidden until GP-only scope is proven." in javascript
            assert "Scheduled-demand comparison is hidden until its source can be proven GP-paint-only." in javascript
            assert "against a 4% goal; lower is better" in javascript
            assert "against a 90% goal; higher is better" in javascript
            assert "not enabled in this first layout pilot" not in javascript
            assert "renderLoadedLineChart" in javascript
            assert "options.chartType === 'bar'" in javascript
            assert "class:'loaded-bar'" in javascript
            assert "class:'loaded-value-label'" in javascript
            assert "class:'loaded-scale-label'" in javascript
            assert "loadedWholeNumberScaleMaximum" in javascript
            assert "formatValue:wholeNumber" in javascript
            assert "formatValue:percentagePoint" in javascript
            assert "valueLabel.append(text(formatValue(value)))" in javascript
            assert "Daily weighted average" in javascript
            assert "13-week weighted average" in javascript
            assert "metric === 'finesse' ? '13-week avg' : 'Daily avg'" in javascript
            assert "targetAssessmentLabel" in javascript
            assert "value:periodAverage === null ? 'No Data' : decimal(periodAverage)" in javascript
            assert "value:latest ? decimal(latest[options.averageField]) : 'No Data'" in javascript
            assert javascript.count("chartType:'bar'") == 10  # eight existing weekly/Pareto bar charts plus the assembly hourly and 13-week bars
            assert "line:!barChart" in javascript
            assert "loadedLinearTrend" in javascript
            assert "13-week daily averages" in javascript
            assert "loadedTileSummaryTable" not in javascript
            assert "Loaded tile summary · selected report day" not in javascript
            assert "loadedHourlySummary" in javascript
            assert javascript.count("hourlySummary:{label:") == 2
            assert "Day total" in javascript
            assert "Peak hour" in javascript
            assert "Active hours" not in javascript
            assert "Net loading time" in javascript
            assert "Actual rate" in javascript
            assert "Interim target" in javascript
            assert "Long-term goal" in javascript
            assert "loadedPerformanceContract" not in javascript
            assert "Loaded performance contract" not in javascript
            assert "Loaded baseline, interim target, and long-term goal rates" not in javascript
            assert "loadedWeeklyReferenceModel" in javascript
            assert "netLoadingMinutes / 60 / performanceDays" in javascript
            assert "value:weeklyReference.targetCarts" in javascript
            assert "value:weeklyReference.goalPieces" in javascript
            assert "field:'average_target_carts'" not in javascript
            assert "field:'average_goal_pieces'" not in javascript
            assert "Net-time interim target" in javascript
            assert "Net-time long-term goal" in javascript
            assert javascript.count("value:performance.model.target_") == 8
            assert javascript.count("value:performance.model.goal_") == 4
            assert "class:'loaded-reference-line'" in javascript
            assert javascript.count("spanFullWidth:true") == 15
            assert "loaded-reference-line-full-width" in javascript
            assert "points = [left + ',' + y(referencePoints[0].value)]" in javascript
            assert "points.push((width - right) + ',' + y(referencePoints[referencePoints.length - 1].value))" in javascript
            assert "horizontal 13-week average-day reference" in javascript
            assert "Horizontal target and goal lines use one " in javascript
            assert "The reference updates only when the 13-week window rolls." in javascript
            assert "Target and goal lines span the historical plot using values from fully comparable weeks" not in javascript
            assert "Target and goal segments appear only on fully comparable weeks" not in javascript
            assert "loadedWeeklySummary" in javascript
            assert "options.omitNull" in javascript
            assert "omitNull:true, verticalLabels:true, chartType:'bar'" in javascript
            assert javascript.count("verticalLabels:true, showTick:() => true") == 8  # six existing charts plus the two assembly charts
            assert "Unavailable weeks before the September 8 history boundary are omitted, not zero." in javascript
            assert "field:'unique_pieces_loaded'" not in javascript
            assert "Hourly · selected report day" in javascript
            assert "selectMetricChart" in javascript
            render_body = javascript.split("function render(snapshot) {", 1)[1].split("\n}", 1)[0]
            assert "renderCards(snapshot);" in render_body
            assert "renderMetricCharts(snapshot);" in render_body
            assert "renderDaily(snapshot)" not in render_body
            assert "renderPeriods(snapshot)" not in render_body
            assert "renderDefects(snapshot)" not in render_body
            assert "renderShipping(snapshot)" not in render_body
            assert "renderPainters(snapshot)" not in render_body
            assert "renderNotes(snapshot)" not in render_body

        with urlopen(base + "/styles.css", timeout=5) as response:
            styles = response.read().decode("utf-8")
            assert response.status == 200
            assert ".split-count-card{container-type:inline-size}" in styles
            assert ".method-banner" not in styles
            assert ".metric-split-row{display:grid;grid-template-columns:auto minmax(0,1fr);gap:.2rem" in styles
            assert ".metric-card .metric-split-value{margin:0;font-size:min(6cqw,.7rem)" in styles
            assert "letter-spacing:-.025em;white-space:nowrap" in styles
            assert ".metric-detail-list{display:grid" in styles
            assert "font-size:min(7.5cqw,1.75rem)" in styles
            assert "font-size:min(7.5cqw,2.2rem)" in styles
            assert ".dual-yield-grid{display:grid;grid-template-columns:1fr 1fr" in styles
            assert ".dual-yield-value" in styles
            assert ".dual-yield-details{display:grid" in styles
            assert "white-space:nowrap" in styles
            assert ".header-status .refresh-countdown" in styles
            assert ".metric-card .metric-detail-row" in styles
            assert ".shipping-legend{" in styles
            assert "font-variant-numeric:tabular-nums" in styles
            assert ".cards{display:grid;grid-template-columns:repeat(5,minmax(0,1fr))" in styles
            assert "body.wallboard .cards{grid-template-columns:repeat(5,minmax(0,1fr))}" in styles
            assert ".inspection-detail-row{display:grid;grid-template-columns:minmax(0,1fr) auto" in styles
            assert ".metric-card .inspection-detail-counts{grid-column:1/-1;justify-self:end" in styles
            assert ".trailer-count-card{grid-column:span 1}" in styles
            assert ".trailer-rack-list{display:grid" in styles
            assert ".metric-card.selectable-card" in styles
            assert ".loaded-chart-grid{display:grid;grid-template-columns:1fr 1fr" in styles
            assert ".loaded-chart-grid.single-chart-grid{grid-template-columns:minmax(0,1fr)}" in styles
            assert ".loaded-chart-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr))" in styles
            assert ".loaded-summary-table-wrap" not in styles
            assert ".loaded-performance-contract" not in styles
            assert ".loaded-summary-table" not in styles
            assert ".loaded-axis-label,.loaded-scale-label{font-variant-numeric:tabular-nums}" in styles
            assert ".loaded-value-label{" in styles
            assert ".loaded-value-label-miss{" in styles
            assert ".loaded-reference-label{" in styles
            assert ".chart-placeholder" in styles
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_live_refresh_uses_private_lan_boundary_without_browser_key(tmp_path, monkeypatch):
    monkeypatch.setenv("KPI_MIN_REFRESH_SECONDS", "0")
    source = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source["scope"]["method_version"] = CURRENT_METHOD_VERSION
    with_loaded_chart(source)
    monkeypatch.setattr(web, "refresh_live_snapshot", lambda report_date: source)
    state = AppState("live", tmp_path / "snapshots", FIXTURE)
    server = create_server("127.0.0.1", 0, state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, refreshed = request_json(
            base + "/api/refresh",
            method="POST",
            payload={"report_date": source["report_date"], "force": True},
            headers={"Content-Type": "application/json", "X-Operations-KPI-Action": "refresh"},
        )
        assert status == 200
        assert refreshed["report_date"] == source["report_date"]
        status, health = request_json(base + "/api/health")
        assert status == 200
        assert health["refresh_boundary"] == "private-lan-bounded"
        assert health["last_refresh_source"] == "live-query"
        assert health["last_query_duration_seconds"] is not None
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_refresh_private_address_boundary():
    assert _is_private_address("127.0.0.1")
    assert _is_private_address("192.168.7.137")
    assert _is_private_address("::ffff:192.168.7.137")
    assert not _is_private_address("8.8.8.8")
    assert not _is_private_address("not-an-address")


def test_historical_refresh_reuses_newest_immutable_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("KPI_MIN_REFRESH_SECONDS", "0")
    source = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source["scope"]["method_version"] = CURRENT_METHOD_VERSION
    with_loaded_chart(source)
    report_date = datetime.fromisoformat(source["report_date"]).date()
    calls = []

    def fake_refresh(requested_date):
        calls.append(requested_date)
        return json.loads(json.dumps(source))

    monkeypatch.setattr(web, "refresh_live_snapshot", fake_refresh)
    state = AppState("live", tmp_path / "snapshots")

    first = state.refresh(report_date, force=True)
    second = state.refresh(report_date)

    assert first == second
    assert calls == [report_date]
    assert len(list((tmp_path / "snapshots").glob("2026-09-16__*.json"))) == 1
    assert state.health()["last_refresh_source"] == "historical-cache"


def test_current_day_refresh_is_deduplicated_inside_freshness_window(tmp_path, monkeypatch):
    monkeypatch.setenv("KPI_MIN_REFRESH_SECONDS", "0")
    monkeypatch.setenv("KPI_REFRESH_FRESHNESS_SECONDS", "600")
    state = AppState("live", tmp_path / "snapshots")
    today = state._today()
    source = snapshot_for(today)
    calls = []

    def fake_refresh(requested_date):
        calls.append(requested_date)
        return json.loads(json.dumps(source))

    monkeypatch.setattr(web, "refresh_live_snapshot", fake_refresh)

    first = state.refresh(today, force=True)
    second = state.refresh(today)

    assert first == second
    assert calls == [today]
    health = state.health()
    assert health["last_refresh_source"] == "fresh-cache"
    assert health["refresh_freshness_seconds"] == 600
    next_refresh = datetime.fromisoformat(health["next_auto_refresh_at"])
    generated_at = datetime.fromisoformat(first["generated_at"])
    assert (next_refresh - generated_at).total_seconds() == 600


def test_historical_cache_is_recovered_after_a_newer_current_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("KPI_MIN_REFRESH_SECONDS", "0")
    snapshot_dir = tmp_path / "snapshots"
    historical = json.loads(FIXTURE.read_text(encoding="utf-8"))
    legacy_method = historical["scope"]["method_version"]
    monkeypatch.setattr(web, "CURRENT_METHOD_VERSION", legacy_method)
    historical_date = datetime.fromisoformat(historical["report_date"]).date()
    first_state = AppState("live", snapshot_dir)
    today = first_state._today()
    current = snapshot_for(today)
    current["scope"]["method_version"] = legacy_method

    def first_refresh(requested_date):
        source = historical if requested_date == historical_date else current
        return json.loads(json.dumps(source))

    monkeypatch.setattr(web, "refresh_live_snapshot", first_refresh)
    first_state.refresh(historical_date, force=True)
    first_state.refresh(today, force=True)

    second_state = AppState("live", snapshot_dir)

    def unexpected_refresh(_requested_date):
        raise AssertionError("historical cache should avoid a live query")

    monkeypatch.setattr(web, "refresh_live_snapshot", unexpected_refresh)
    recovered = second_state.refresh(historical_date)

    assert recovered["report_date"] == historical_date.isoformat()
    assert second_state.health()["last_refresh_source"] == "historical-cache"


def test_stale_current_snapshot_runs_the_live_query(tmp_path, monkeypatch):
    monkeypatch.setenv("KPI_MIN_REFRESH_SECONDS", "0")
    monkeypatch.setenv("KPI_REFRESH_FRESHNESS_SECONDS", "600")
    state = AppState("live", tmp_path / "snapshots")
    today = state._today()
    stale = snapshot_for(today)
    stale["generated_at"] = (
        datetime.now(ZoneInfo("America/Indiana/Indianapolis")) - timedelta(minutes=20)
    ).isoformat(timespec="seconds")
    fresh = snapshot_for(today)
    responses = [stale, fresh]
    calls = []

    def fake_refresh(requested_date):
        calls.append(requested_date)
        return json.loads(json.dumps(responses.pop(0)))

    monkeypatch.setattr(web, "refresh_live_snapshot", fake_refresh)
    state.refresh(today, force=True)
    state.refresh(today)

    assert calls == [today, today]
    assert state.health()["last_refresh_source"] == "live-query"


def test_live_state_runs_one_server_owned_initial_refresh(tmp_path, monkeypatch):
    state = AppState("live", tmp_path / "snapshots", FIXTURE)
    called = threading.Event()
    calls = []

    def fake_refresh(report_date, force=False):
        calls.append((report_date, force))
        called.set()
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    monkeypatch.setattr(state, "refresh", fake_refresh)
    state.start_auto_refresh()
    try:
        assert called.wait(timeout=2)
        assert calls == [(state._today(), False)]
        assert state.health()["auto_refresh_running"] is True
    finally:
        state.stop_auto_refresh()


def test_wallboard_tiles_lead_with_carts_and_pieces_and_list_unique_figures_below():
    script = (Path(__file__).resolve().parents[1] / "src" / "operations_kpi_rollup" / "web" / "app.js").read_text(encoding="utf-8")
    assert "function splitTotal(row) {" in script and "function uniqueDetails(day, uniqueParts) {" in script
    assert "function splitMetricCard(label, total, rows, color, extraDetails = []) {" in script
    assert "Carts / " in script and "compactOptionalInteger(splitTotal(rows[0]))" in script and " Pieces" in script
    assert " Total / " not in script
    # unique parts (each part once however often it looped) first, unique colors last; the old Unique Pieces wording is gone
    assert "' Unique Pieces'" not in script and "day.unique_parts" not in script
    order = [script.index("' Unique Parts'"), script.index("' Unique Colors'")]
    assert order == sorted(order)
    assert "uniqueDetails(snapshot.chart_series?.loaded?.selected_day, current.unique_pieces_loaded)" in script
    assert "uniqueDetails(snapshot.chart_series?.painted?.selected_day, current.unique_pieces_processed)" in script
    assert "uniqueDetails(snapshot.chart_series?.staged?.selected_day, current.staged_pieces)" in script


def test_wallboard_tiles_are_five_across_and_three_down_in_the_requested_order():
    root = Path(__file__).resolve().parents[1] / "src" / "operations_kpi_rollup" / "web"
    script = (root / "app.js").read_text(encoding="utf-8")
    labels = [
        "Carts / Pieces loaded", "Carts / Pieces staged", "Carts / Pieces painted", "Repaint %", "Process time",
        "Finesse Effectiveness", "PPY (Paint Process Yield)", "FTY (First Time Yield)", "Complete assy sets", "Assembled bumpers",
        "Receiving FTY", "Final FTY", "Preliminary OEE", "Pieces shipped", "Trailers",
    ]
    expected = "const tileOrder = [" + ", ".join("'" + label + "'" for label in labels) + "];"
    flattened = " ".join(part.strip() for part in script[script.index("const tileOrder = ["):script.index("];", script.index("const tileOrder = [")) + 2].split("\n"))
    assert flattened == expected
    assert len(labels) == 15 and len(set(labels)) == 15
    styles = (root / "styles.css").read_text(encoding="utf-8")
    assert "repeat(7," not in styles.split("@media")[0]
    assert styles.count("repeat(5,minmax(0,1fr))") == 2


def test_hourly_summary_counts_hours_at_target_once_a_target_exists():
    script = (Path(__file__).resolve().parents[1] / "src" / "operations_kpi_rollup" / "web" / "app.js").read_text(encoding="utf-8")
    assert "label:'Hours at target'" in script and "function yieldMarkText(value) {" in script
    assert "yieldHourlySummary(rows, metric, {target:targetMark, goal:goalMark})" in script
    assert "label:'Target / goal', value:'Not set'" in script  # still the fallback when no target is configured
