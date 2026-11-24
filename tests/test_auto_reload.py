"""Auto reload: open pages reload themselves once when the service reports a newer version (v0.47.2).

Before v0.47.2 a page that was already open (a plant wallboard, a normal view, the drill-down) kept running the script it was loaded with until
someone reloaded it, so a fix reached a screen only after a manual reload. Every health reply now carries the running version and each page
compares it with the version it came with."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
from pathlib import Path
from urllib.request import urlopen

import pytest

from operations_kpi_rollup import __version__
from operations_kpi_rollup.web import AppState, Handler, create_server
from test_assembly_details import EXAMPLE, _drilldown_state

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


def test_every_version_string_matches_the_package_version():
    assert re.search(r'^version = "' + re.escape(__version__) + '"$', read(ROOT / "pyproject.toml"), re.M)
    assert Handler.server_version == "OperationsKPI/" + __version__
    for app in (WEB / "app.js", DRILL / "app.js"):
        assert "const PAGE_VERSION = '" + __version__ + "';" in read(app), app
    index = read(WEB / "index.html")
    assert '/app.js?v=' + __version__ + '"' in index and '/styles.css?v=' + __version__ + '"' in index
    drill = read(DRILL / "index.html")
    assert '/drilldown/app.js?v=' + __version__ + '"' in drill and '/drilldown/styles.css?v=' + __version__ + '"' in drill
    assert "<span>" + __version__ + "</span>" in drill
    assert "Version " + __version__ + " " in read(ROOT / "README.md")


def test_both_health_endpoints_report_the_running_version(tmp_path):
    state = AppState("fixture", tmp_path / "snapshots", EXAMPLE)
    server = create_server("127.0.0.1", 0, state, _drilldown_state(tmp_path))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        for path in ("/api/health", "/api/drilldown/health"):
            with urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=10) as response:
                payload = json.loads(response.read())
                assert response.headers["Server"].startswith("OperationsKPI/" + __version__), path
            assert payload["app_version"] == __version__, path
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


PRELUDE = """
const PAGE_VERSION = '1.0.0';
let versionReloadPending = false;
let currentHref = 'http://kpi.example/?wallboard=1';
const calls = {status: [], timers: [], replaced: []};
const setStatus = (message) => { calls.status.push(message); };
const setTimeout = (fn, delay) => { calls.timers.push({fn: fn, delay: delay}); return calls.timers.length; };
const location = {get href() { return currentHref; }, replace: (url) => { calls.replaced.push(url); }};
Math.random = () => 0.5;
"""

SCENARIOS = """
const snap = () => ({status: calls.status.slice(), timers: calls.timers.map((timer) => timer.delay), replaced: calls.replaced.slice(), pending: versionReloadPending});
const reset = (href) => { calls.status.length = 0; calls.timers.length = 0; calls.replaced.length = 0; versionReloadPending = false; currentHref = href || 'http://kpi.example/?wallboard=1'; };
const out = {};
reset(); checkAppVersion({app_version: '1.0.0'}); out.same = snap();
reset(); checkAppVersion({}); checkAppVersion(null); checkAppVersion({app_version: 5}); checkAppVersion({app_version: ''}); out.missing = snap();
reset(); checkAppVersion({app_version: '1.0.1'}); out.newer = snap(); calls.timers[0].fn(); out.newer_replaced = calls.replaced.slice();
reset(); checkAppVersion({app_version: '1.0.1'}); checkAppVersion({app_version: '1.0.1'}); out.twice_while_pending = snap();
reset('http://kpi.example/?wallboard=1&v=1.0.1'); checkAppVersion({app_version: '1.0.1'}); out.already_reloaded = snap();
reset('http://kpi.example/?wallboard=1&v=1.0.1'); checkAppVersion({app_version: '1.0.2'}); calls.timers[0].fn(); out.next_version = snap();
reset('http://kpi.example/drilldown/'); checkAppVersion({app_version: '1.0.1'}); calls.timers[0].fn(); out.drilldown_url = snap();
reset('http://kpi.example/'); checkAppVersion({app_version: '0.9.0'}); calls.timers[0].fn(); out.older_server = snap();
console.log(JSON.stringify(out));
"""


def reload_run(app: Path) -> dict:
    source = function_source(read(app), "checkAppVersion")
    return run_node("(function () {\n" + PRELUDE + source + "\n" + SCENARIOS + "\n})();")


@needs_node
@pytest.mark.parametrize("app", [WEB / "app.js", DRILL / "app.js"], ids=["wallboard", "drilldown"])
def test_a_page_reloads_once_for_each_other_version_and_never_loops(app):
    out = reload_run(app)
    for name in ("same", "missing"):
        assert out[name]["status"] == [] and out[name]["timers"] == [] and out[name]["replaced"] == [], name
    newer = out["newer"]
    assert len(newer["status"]) == 1 and "1.0.1" in newer["status"][0] and newer["pending"] is True and newer["replaced"] == []
    assert len(newer["timers"]) == 1 and 1000 <= newer["timers"][0] <= 10000, "a random 1 to 10 second delay"
    assert out["newer_replaced"] == ["http://kpi.example/?wallboard=1&v=1.0.1"], "a wallboard keeps ?wallboard=1"
    assert len(out["twice_while_pending"]["timers"]) == 1 and len(out["twice_while_pending"]["status"]) == 1
    assert out["already_reloaded"]["timers"] == [] and out["already_reloaded"]["status"] == [], "the same tab must not reload twice for one version"
    assert out["next_version"]["replaced"] == ["http://kpi.example/?wallboard=1&v=1.0.2"], "a newer version replaces v and does not duplicate it"
    assert out["drilldown_url"]["replaced"] == ["http://kpi.example/drilldown/?v=1.0.1"]
    assert out["older_server"]["replaced"] == ["http://kpi.example/?v=0.9.0"], "a rollback to an older version reloads too, once"


def test_the_reload_guard_uses_no_browser_storage():
    for app in (WEB / "app.js", DRILL / "app.js"):
        source = function_source(read(app), "checkAppVersion")
        assert "sessionStorage" not in source and "localStorage" not in source and "document.cookie" not in source, app
    assert "sessionStorage" not in read(WEB / "app.js"), "the public wallboard script keeps its no-storage rule"


def test_each_page_checks_the_version_on_every_health_read():
    wallboard = read(WEB / "app.js")
    assert "checkAppVersion(health);" in function_source(wallboard, "applyHealth")
    drill = function_source(read(DRILL / "app.js"), "loadBusinessClock")
    assert "checkAppVersion(health);" in drill and drill.index("checkAppVersion(health);") < drill.index("business_date")