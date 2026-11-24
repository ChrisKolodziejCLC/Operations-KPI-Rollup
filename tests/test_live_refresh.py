"""Live refresh: the normal wallboard view and the drill-down page follow the plant's current day by themselves (v0.47.1).

Before v0.47.1 only the wallboard view (?wallboard=1) re-read the saved snapshot. The normal view and the drill-down loaded it once and
showed a countdown to the SERVER's refresh, so what was on screen stayed as loaded until someone reloaded the page."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src/operations_kpi_rollup/web"
DRILL = ROOT / "src/operations_kpi_rollup/drilldown_web"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def function_source(text: str, name: str) -> str:
    match = re.search(r"^(async )?function " + re.escape(name) + r"\(", text, re.M)
    assert match, name
    start = match.start()
    depth = 0
    for index in range(text.index("{", match.end()), len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    raise AssertionError("unterminated function " + name)


def run_node(script: str) -> dict:
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


WALLBOARD_PRELUDE = """
const STALE_AFTER_MS = 25 * 60 * 1000;
let followToday = true, liveRefreshBusy = false, wallboardMode = false, refreshInProgress = false;
let activeSnapshot = null, serverClockOffsetMs = 0, today = '2026-11-23';
const NOW = Date.parse('2026-11-24T02:00:00Z');
Date.now = () => NOW;
const node = {textContent: '', stale: null, classList: {toggle: (name, on) => { node.stale = Boolean(on); }}};
const $ = (selector) => (selector === '#generated-at' ? node : null);
const snapshotStamp = (value) => 'S(' + value + ')';
const fullDateLabel = (value) => 'D(' + value + ')';
const businessToday = () => today;
const calls = {api: [], render: [], status: []};
let apiImpl = async () => { throw new Error('api not stubbed'); };
const api = (path) => { calls.api.push(path); return apiImpl(path); };
const render = (snapshot) => { calls.render.push(snapshot.generated_at); activeSnapshot = snapshot; };
const setStatus = (message) => { calls.status.push(message); };
const reset = () => { calls.api.length = 0; calls.render.length = 0; calls.status.length = 0; followToday = true; wallboardMode = false; refreshInProgress = false; liveRefreshBusy = false; today = '2026-11-23'; serverClockOffsetMs = 0; };
const OLD = {report_date: '2026-11-23', generated_at: '2026-11-23T19:29:03-06:00'};
const NEW = {report_date: '2026-11-23', generated_at: '2026-11-23T19:40:11-06:00'};
"""

WALLBOARD_SCENARIOS = """
(async () => {
  const out = {};
  const snap = () => ({api: calls.api.slice(), render: calls.render.slice(), status: calls.status.slice(), busy: liveRefreshBusy});
  reset(); activeSnapshot = OLD; apiImpl = async () => NEW; await refreshLiveView(); out.newer = snap();
  reset(); activeSnapshot = NEW; apiImpl = async () => NEW; await refreshLiveView(); out.same = snap();
  reset(); activeSnapshot = OLD; followToday = false; apiImpl = async () => NEW; await refreshLiveView(); out.not_following = snap();
  reset(); activeSnapshot = OLD; wallboardMode = true; apiImpl = async () => NEW; await refreshLiveView(); out.wallboard_mode = snap();
  reset(); activeSnapshot = OLD; refreshInProgress = true; apiImpl = async () => NEW; await refreshLiveView(); out.user_load_running = snap();
  reset(); activeSnapshot = OLD; apiImpl = async () => { throw new Error('boom'); }; await refreshLiveView(); out.failed = snap();
  apiImpl = async () => NEW; await refreshLiveView(); out.after_failure = snap();
  reset(); activeSnapshot = OLD; apiImpl = async () => { followToday = false; return NEW; }; await refreshLiveView(); out.navigated_away = snap();
  reset(); activeSnapshot = OLD; let release; apiImpl = () => new Promise((resolve) => { release = () => resolve(NEW); });
  const first = refreshLiveView(); const second = refreshLiveView(); release(); await first; await second; out.concurrent = snap();
  reset(); today = '2026-11-24'; activeSnapshot = {report_date: '2026-11-23', generated_at: '2026-11-23T23:59:00-06:00'};
  apiImpl = async () => ({report_date: '2026-11-24', generated_at: '2026-11-23T23:59:00-06:00'}); await refreshLiveView(); out.rollover = snap();
  const fresh = (generated, report) => { activeSnapshot = {report_date: report || '2026-11-23', generated_at: generated}; renderFreshness(); return {text: node.textContent, stale: node.stale}; };
  reset(); out.fresh_10 = fresh('2026-11-23T19:50:00-06:00');
  out.stale_30 = fresh('2026-11-23T19:30:00-06:00');
  out.past_day = fresh('2026-11-22T10:00:00-06:00', '2026-11-22');
  serverClockOffsetMs = 3 * 60 * 1000; out.offset_counts = fresh('2026-11-23T19:37:00-06:00');
  console.log(JSON.stringify(out));
})();
"""


def wallboard_run() -> dict:
    app = read(WEB / "app.js")
    return run_node(WALLBOARD_PRELUDE + function_source(app, "renderFreshness") + "\n" + function_source(app, "refreshLiveView") + "\n" + WALLBOARD_SCENARIOS)


@needs_node
def test_the_normal_wallboard_view_renders_a_newer_saved_snapshot_and_only_then():
    out = wallboard_run()
    assert out["newer"]["api"] == ["/api/snapshot?report_date=2026-11-23"]
    assert out["newer"]["render"] == ["2026-11-23T19:40:11-06:00"]
    assert len(out["newer"]["status"]) == 1 and "updated automatically" in out["newer"]["status"][0]
    assert out["same"]["api"] and out["same"]["render"] == [] and out["same"]["status"] == []
    assert out["rollover"]["api"] == ["/api/snapshot?report_date=2026-11-24"] and out["rollover"]["render"] == ["2026-11-23T23:59:00-06:00"]


@needs_node
def test_the_live_poll_stays_out_of_the_way_of_the_viewer():
    out = wallboard_run()
    for name in ("not_following", "wallboard_mode", "user_load_running"):
        assert out[name]["api"] == [] and out[name]["render"] == [], name
    assert out["navigated_away"]["api"] and out["navigated_away"]["render"] == [], "a day picked while the fetch was running must not be overwritten"
    assert len(out["concurrent"]["api"]) == 1, "an overlapping poll must be skipped"
    assert out["failed"]["render"] == [] and out["failed"]["status"] == [] and out["failed"]["busy"] is False
    assert out["after_failure"]["render"] == ["2026-11-23T19:40:11-06:00"], "one failed poll must not stop the next one"


@needs_node
def test_the_snapshot_stamp_warns_when_todays_data_is_older_than_25_minutes():
    out = wallboard_run()
    assert out["fresh_10"] == {"text": "Snapshot S(2026-11-23T19:50:00-06:00)", "stale": False}
    assert out["stale_30"]["stale"] is True and out["stale_30"]["text"].endswith(" · 30 min old")
    assert out["past_day"]["stale"] is False and "min old" not in out["past_day"]["text"]
    assert out["offset_counts"]["stale"] is True and out["offset_counts"]["text"].endswith(" · 26 min old"), "the server clock offset must be applied"


def test_the_normal_wallboard_view_is_wired_to_poll_and_the_wallboard_poll_is_unchanged():
    app = read(WEB / "app.js")
    assert "const loadedToday = await loadCachedReport(today);\n    if (!loadedToday) await loadLatest();\n    setInterval(refreshLiveView, WALLBOARD_POLL_MS);" in app
    assert "setInterval(() => loadCachedReport(businessToday(), true), WALLBOARD_POLL_MS);" in app
    assert "wallboardMode = wallboard;" in app
    assert "followToday = reportDate === businessToday();" in app
    assert "followToday = $('#date-input').value === businessToday();" in app
    health = function_source(app, "applyHealth")
    assert "refreshLiveView();" in health and "health.generated_at" in health and "health.report_date === businessToday()" in health
    assert "renderFreshness();" in function_source(app, "render") and "renderFreshness();" in function_source(app, "renderRefreshCountdown")
    assert "#generated-at.stale" in read(WEB / "styles.css")
    live = function_source(app, "refreshLiveView")
    assert "/api/refresh" not in live and "POST" not in live, "the live poll only reads the saved snapshot"


DRILL_PRELUDE = """
const STALE_AFTER_MS = 25 * 60 * 1000;
let busy = false, liveBusy = false, followToday = true, activeSnapshot = null, today = '2026-11-23';
const NOW = Date.parse('2026-11-24T02:00:00Z');
Date.now = () => NOW;
const node = {textContent: '', stale: null, classList: {toggle: (name, on) => { node.stale = Boolean(on); }}};
const $ = (selector) => (selector === '#generated-at' ? node : null);
const snapshotStamp = (value) => 'S(' + value + ')';
const dateLabel = (value) => 'D(' + value + ')';
const businessToday = () => today;
const calls = {clock: 0, fetch: [], render: [], status: [], refresh: 0};
let fetchImpl = async () => { throw new Error('fetch not stubbed'); };
const loadBusinessClock = async () => { calls.clock += 1; };
const fetchJson = (url) => { calls.fetch.push(url); return fetchImpl(url); };
const renderWithNames = async (snapshot) => { calls.render.push(snapshot.generated_at); activeSnapshot = snapshot; };
const requestRefresh = async () => { calls.refresh += 1; };
const setStatus = (message) => { calls.status.push(message); };
const reset = () => { calls.clock = 0; calls.refresh = 0; calls.fetch.length = 0; calls.render.length = 0; calls.status.length = 0; busy = false; liveBusy = false; followToday = true; today = '2026-11-23'; };
const OLD = {report_date: '2026-11-23', generated_at: '2026-11-23T19:29:03-06:00'};
const NEW = {report_date: '2026-11-23', generated_at: '2026-11-23T19:40:11-06:00'};
const notFound = () => { const error = new Error('No drill-down snapshot'); error.notFound = true; return error; };
"""

DRILL_SCENARIOS = """
(async () => {
  const out = {};
  const snap = () => ({clock: calls.clock, fetch: calls.fetch.slice(), render: calls.render.slice(), status: calls.status.slice(), refresh: calls.refresh, busy: liveBusy});
  reset(); activeSnapshot = OLD; fetchImpl = async () => NEW; await pollLive(); out.newer = snap();
  reset(); activeSnapshot = NEW; fetchImpl = async () => NEW; await pollLive(); out.same = snap();
  reset(); activeSnapshot = OLD; fetchImpl = async () => { throw notFound(); }; await pollLive(); out.missing = snap();
  reset(); activeSnapshot = OLD; busy = true; fetchImpl = async () => NEW; await pollLive(); out.busy = snap();
  reset(); activeSnapshot = OLD; followToday = false; fetchImpl = async () => NEW; await pollLive(); out.not_following = snap();
  reset(); activeSnapshot = OLD; fetchImpl = async () => { busy = true; return NEW; }; await pollLive(); out.user_started_a_load = snap();
  reset(); activeSnapshot = OLD; fetchImpl = async () => { throw new Error('boom'); }; await pollLive(); out.failed = snap();
  const fresh = (generated) => { activeSnapshot = {report_date: '2026-11-23', generated_at: generated}; renderFreshness(); return {text: node.textContent, stale: node.stale}; };
  out.fresh_10 = fresh('2026-11-23T19:50:00-06:00');
  out.stale_30 = fresh('2026-11-23T19:30:00-06:00');
  console.log(JSON.stringify(out));
})();
"""


def drill_run() -> dict:
    app = read(DRILL / "app.js")
    return run_node(DRILL_PRELUDE + function_source(app, "renderFreshness") + "\n" + function_source(app, "pollLive") + "\n" + DRILL_SCENARIOS)


@needs_node
def test_the_drilldown_page_renders_a_newer_saved_snapshot_and_never_builds_one():
    out = drill_run()
    assert out["newer"]["clock"] == 1 and out["newer"]["fetch"] == ["/api/drilldown/snapshot?report_date=2026-11-23"]
    assert out["newer"]["render"] == ["2026-11-23T19:40:11-06:00"] and "updated automatically" in out["newer"]["status"][0]
    assert out["same"]["render"] == [] and out["same"]["status"] == []
    assert out["missing"]["render"] == [] and out["missing"]["refresh"] == 0, "a missing copy is never built by the poll"
    for name in ("busy", "not_following"):
        assert out[name]["fetch"] == [] and out[name]["render"] == [], name
    assert out["user_started_a_load"]["render"] == [], "a load the viewer started while the poll was reading must win"
    assert out["failed"]["render"] == [] and out["failed"]["busy"] is False and out["failed"]["refresh"] == 0


@needs_node
def test_the_drilldown_stamp_warns_when_todays_data_is_older_than_25_minutes():
    out = drill_run()
    assert out["fresh_10"] == {"text": "Generated S(2026-11-23T19:50:00-06:00)", "stale": False}
    assert out["stale_30"]["stale"] is True and out["stale_30"]["text"].endswith(" · 30 min old")


def test_the_drilldown_page_is_wired_to_poll_without_building_anything():
    app = read(DRILL / "app.js")
    start = function_source(app, "start")
    assert "setInterval(pollLive, LIVE_POLL_MS);" in start and "setInterval(renderFreshness, 10 * 1000);" in start
    assert "followToday = reportDate === businessToday();" in function_source(app, "loadDate")
    assert "renderFreshness();" in function_source(app, "render")
    poll = function_source(app, "pollLive")
    assert "requestRefresh" not in poll and "POST" not in poll and "force" not in poll
    assert "#generated-at.stale" in read(DRILL / "styles.css")
