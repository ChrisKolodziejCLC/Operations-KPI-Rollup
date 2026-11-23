import contextlib
import datetime
import io
import json
import os
import socket
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

JOB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "jobs", "operations-kpi-settle")
sys.path.insert(0, JOB_DIR)
import settle_past_days as settle

UTC = datetime.timezone.utc
OLD = "2026-11-20T23:55:00-06:00"


def utc(year, month, day, hour, minute):
    return datetime.datetime(year, month, day, hour, minute, tzinfo=UTC)


class FakeDashboard:
    """Stands in for the dashboard: saved copies per day, the explicit refresh control and its 15 second cool-down."""

    def __init__(self, days, loaded_after=None, no_op_first=None, fail_days=()):
        self.copies = {day: {"generated_at": OLD, "shipped": 400, "loaded": 10, "departed": 5} for day in days}
        self.loaded_after = loaded_after or {}
        self.no_op_remaining = dict(no_op_first or {})
        self.fail_days = set(fail_days)
        self.calls = []
        self.bad_headers = 0
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def _handler(self):
        state = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, payload):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _snapshot(self, day):
                copy = state.copies[day]
                return {"report_date": day, "generated_at": copy["generated_at"],
                        "daily": [{"date": day, "parts_shipped": copy["shipped"], "trailers_prepared": copy["loaded"], "trailers_shipped": copy["departed"]}]}

            def do_GET(self):
                parsed = urlparse(self.path)
                day = parse_qs(parsed.query).get("report_date", [""])[0]
                if parsed.path == "/api/snapshot" and day in state.copies:
                    return self._send(200, self._snapshot(day))
                return self._send(404, {"error": "no saved day"})

            def do_POST(self):
                if self.path != "/api/refresh":
                    return self._send(404, {})
                if self.headers.get("X-Operations-KPI-Action") != "refresh":
                    state.bad_headers += 1
                    return self._send(403, {"error": "missing action header"})
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
                day = payload.get("report_date")
                state.calls.append((day, payload.get("force")))
                if day in state.fail_days:
                    return self._send(400, {"error": "RefreshError: Please wait 14 seconds before refreshing again."})
                if state.no_op_remaining.get(day, 0) > 0:
                    # a refresh within 15 seconds of another one: HTTP 200 with the cached copy, nothing saved
                    state.no_op_remaining[day] -= 1
                    return self._send(200, self._snapshot(day))
                copy = state.copies.setdefault(day, {"shipped": 0, "loaded": 0, "departed": 0})
                copy["generated_at"] = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-6))).isoformat()
                copy["loaded"] = state.loaded_after.get(day, copy["loaded"])
                return self._send(200, self._snapshot(day))

        return Handler

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def config(url, **overrides):
    environ = {"SETTLE_BASE_URL": url}
    environ.update(overrides)
    return settle.load_config(environ)


def events(text):
    return [json.loads(line) for line in text.splitlines() if line.startswith("{")]


def run_job(cfg, now_utc, **kwargs):
    sleeps = []
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = settle.run(cfg, now_utc, sleep=sleeps.append, **kwargs)
    return code, events(out.getvalue()), sleeps


class PlanTests(unittest.TestCase):
    def test_tuesday_early_morning_settles_only_monday(self):
        # 01:30 Central on Tuesday 2026-11-24 is 07:30 UTC
        self.assertEqual(settle.settle_days(utc(2026, 11, 24, 7, 30), "America/Chicago"), [datetime.date(2026, 11, 23)])

    def test_monday_early_morning_settles_the_whole_previous_week_newest_first(self):
        days = settle.settle_days(utc(2026, 11, 23, 7, 30), "America/Chicago")
        self.assertEqual([day.isoformat() for day in days], ["2026-11-22", "2026-11-21", "2026-11-20", "2026-11-19", "2026-11-18", "2026-11-17", "2026-11-16"])

    def test_midweek_settles_monday_through_yesterday(self):
        days = settle.settle_days(utc(2026, 11, 25, 7, 30), "America/Chicago")
        self.assertEqual([day.isoformat() for day in days], ["2026-11-24", "2026-11-23"])

    def test_yesterday_follows_central_time_not_utc(self):
        # 04:30 UTC on Tuesday is still Monday 22:30 Central, so yesterday is Sunday
        self.assertEqual(settle.settle_days(utc(2026, 11, 24, 4, 30), "America/Chicago")[0], datetime.date(2026, 11, 22))

    def test_summer_time(self):
        # 01:30 CDT on Tuesday 2026-07-07 is 06:30 UTC
        self.assertEqual(settle.settle_days(utc(2026, 7, 7, 6, 30), "America/Chicago"), [datetime.date(2026, 7, 6)])

    def test_last_day_override(self):
        days = settle.settle_days(utc(2026, 11, 24, 7, 30), "America/Chicago", datetime.date(2026, 11, 19))
        self.assertEqual([day.isoformat() for day in days], ["2026-11-19", "2026-11-18", "2026-11-17", "2026-11-16"])


class ConfigTests(unittest.TestCase):
    def test_defaults(self):
        cfg = settle.load_config({})
        self.assertEqual(cfg["base_url"], "http://127.0.0.1:5193")
        self.assertEqual(cfg["timezone"], "America/Chicago")
        self.assertEqual((cfg["max_attempts"], cfg["retry_seconds"]), (8, 20))

    def test_only_a_local_dashboard_is_allowed(self):
        for bad in ("http://example.com:5193", "https://127.0.0.1:5193", "http://192.168.7.137:5193", "http://127.0.0.1"):
            with self.assertRaises(settle.ConfigError):
                settle.load_config({"SETTLE_BASE_URL": bad})

    def test_retry_wait_must_clear_the_dashboards_cool_down(self):
        with self.assertRaises(settle.ConfigError):
            settle.load_config({"SETTLE_RETRY_SECONDS": "10"})

    def test_bounds_and_time_zone(self):
        for name, value in (("SETTLE_MAX_ATTEMPTS", "0"), ("SETTLE_MAX_ATTEMPTS", "x"), ("SETTLE_REQUEST_TIMEOUT_SECONDS", "5"), ("SETTLE_TIMEZONE", "Mars/Olympus")):
            with self.assertRaises(settle.ConfigError):
                settle.load_config({name: value})


class RunTests(unittest.TestCase):
    NOW = utc(2026, 11, 24, 7, 30)

    def test_settles_the_day_and_reports_the_change(self):
        with FakeDashboard(["2026-11-23"], loaded_after={"2026-11-23": 11}) as dash:
            code, evs, sleeps = run_job(config(dash.url), self.NOW)
            self.assertEqual(code, 0)
            self.assertEqual(sleeps, [])
            self.assertEqual(dash.calls, [("2026-11-23", True)])
            self.assertEqual(dash.bad_headers, 0)
        names = [event["event"] for event in evs]
        self.assertEqual(names, ["start", "day_ok", "done"])
        ok = evs[1]
        self.assertEqual((ok["before"]["loaded"], ok["after"]["loaded"]), (10, 11))
        self.assertEqual(evs[2]["settled"], 1)

    def test_whole_week_newest_first(self):
        days = ["2026-11-%02d" % n for n in range(16, 23)]
        with FakeDashboard(days) as dash:
            code, evs, _ = run_job(config(dash.url), utc(2026, 11, 23, 7, 30))
            self.assertEqual(code, 0)
            self.assertEqual([call[0] for call in dash.calls], list(reversed(days)))

    def test_a_cached_answer_is_not_counted_as_settled(self):
        # the first request lands within the 15 second cool-down: HTTP 200, old copy, nothing saved
        with FakeDashboard(["2026-11-23"], no_op_first={"2026-11-23": 2}, loaded_after={"2026-11-23": 11}) as dash:
            code, evs, sleeps = run_job(config(dash.url), self.NOW)
            self.assertEqual(code, 0)
            self.assertEqual(len(dash.calls), 3)
        ok = [event for event in evs if event["event"] == "day_ok"][0]
        self.assertEqual(ok["attempts"], 3)
        self.assertEqual(sleeps, [20, 20])

    def test_a_day_that_keeps_failing_does_not_stop_the_others(self):
        days = ["2026-11-22", "2026-11-21", "2026-11-20", "2026-11-19", "2026-11-18", "2026-11-17", "2026-11-16"]
        with FakeDashboard(days, fail_days={"2026-11-21"}) as dash:
            code, evs, sleeps = run_job(config(dash.url, SETTLE_MAX_ATTEMPTS="3"), utc(2026, 11, 23, 7, 30))
            self.assertEqual(code, 1)
            self.assertEqual(len([call for call in dash.calls if call[0] == "2026-11-21"]), 3)
        failed = [event for event in evs if event["event"] == "day_failed"]
        self.assertEqual([event["day"] for event in failed], ["2026-11-21"])
        self.assertIn("Please wait", failed[0]["attempts"][-1]["error"])
        done = evs[-1]
        self.assertEqual((done["settled"], done["failed"], done["failed_days"]), (6, 1, ["2026-11-21"]))
        self.assertEqual(sleeps, [20, 20])

    def test_dry_run_requests_nothing(self):
        with FakeDashboard(["2026-11-23"]) as dash:
            code, evs, _ = run_job(config(dash.url), self.NOW, dry_run=True)
            self.assertEqual(code, 0)
            self.assertEqual(dash.calls, [])
        self.assertEqual([event["event"] for event in evs], ["start", "dry_run_done"])

    def test_dashboard_not_reachable_fails_without_crashing(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            closed_port = probe.getsockname()[1]
        code, evs, sleeps = run_job(config("http://127.0.0.1:%d" % closed_port, SETTLE_MAX_ATTEMPTS="2", SETTLE_REQUEST_TIMEOUT_SECONDS="60"), self.NOW)
        self.assertEqual(code, 1)
        self.assertEqual(sleeps, [20])
        self.assertTrue([event for event in evs if event["event"] == "day_failed"][0]["attempts"][0]["error"])

    def test_a_day_without_an_earlier_copy_is_settled_too(self):
        with FakeDashboard([]) as dash:
            code, evs, _ = run_job(config(dash.url), self.NOW)
            self.assertEqual(code, 0)
        self.assertIsNone([event for event in evs if event["event"] == "day_ok"][0]["before"])

    def test_days_before_the_dashboards_first_supported_date_are_skipped(self):
        with FakeDashboard([]) as dash:
            code, evs, _ = run_job(config(dash.url), self.NOW, last_day=datetime.date(2026, 9, 6))
            self.assertEqual(code, 0)
            self.assertEqual(dash.calls, [])
        self.assertEqual(evs[0]["days"], [])


class MainTests(unittest.TestCase):
    def test_bad_arguments_and_settings_exit_with_2(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(settle.main(["--last-day", "yesterday"], environ={}), 2)
            self.assertEqual(settle.main([], environ={"SETTLE_BASE_URL": "http://example.com:5193"}), 2)
        self.assertEqual([event["event"] for event in events(out.getvalue())], ["failed", "failed"])

    def test_main_dry_run(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(settle.main(["--dry-run", "--last-day", "2026-11-18"], environ={}), 0)
        self.assertEqual(events(out.getvalue())[0]["days"], ["2026-11-18", "2026-11-17", "2026-11-16"])


class BoundaryTests(unittest.TestCase):
    def test_it_only_talks_to_the_local_dashboard_and_sends_no_mail(self):
        source = open(os.path.join(JOB_DIR, "settle_past_days.py"), encoding="utf-8").read()
        for word in ("smtplib", "sendmail", "5096", "pyodbc", "sqlcmd", "brak.eliteenterprisesinc", "sqlexpress"):
            self.assertNotIn(word, source.lower())

    def test_units(self):
        timer = open(os.path.join(JOB_DIR, "deploy", "operations-kpi-settle.timer"), encoding="utf-8").read()
        service = open(os.path.join(JOB_DIR, "deploy", "operations-kpi-settle.service"), encoding="utf-8").read()
        self.assertIn("OnCalendar=*-*-* 01:30:00 America/Chicago", timer)
        self.assertIn("Persistent=true", timer)
        for line in ("Type=oneshot", "DynamicUser=yes", "IPAddressDeny=any", "IPAddressAllow=127.0.0.1", "SETTLE_TIMEZONE=America/Chicago", "ProtectSystem=strict"):
            self.assertIn(line, service)


if __name__ == "__main__":
    unittest.main()
