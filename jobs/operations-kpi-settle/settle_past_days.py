#!/usr/bin/env python3
"""Nightly settle of the Operations KPI dashboard's saved days.

Each night, at 01:30 Central (ninety minutes before the Daily Parts Shipped - GP email reads the dashboard), this job re-reads
every day from the Monday of yesterday's week through yesterday from BRAK. It does that through the dashboard's own explicit
refresh control on this host (POST /api/refresh), one day at a time, newest first, so every one of those days gets a fresh,
immutable saved copy. A correction made in BRAK after the dashboard's last automatic save of a day (for example a trailer
number fixed later) then shows up in the dashboard and in the email, and both agree with BRAK at that moment.

It never talks to BRAK itself and it sends no email: it only calls the dashboard on the same host.

The dashboard answers HTTP 200 with its cached copy, and saves nothing, when a refresh arrives within 15 seconds of another
refresh. So a 200 is not enough: a day counts as settled only when its saved copy is newer than the request.

Usage: settle_past_days.py [--dry-run] [--last-day YYYY-MM-DD]
  --dry-run    print the days that would be settled and stop; nothing is requested.
  --last-day   settle the week up to this day instead of yesterday (Central time), for a manual run.
Exit status: 0 every day settled, 1 at least one day not settled, 2 a bad setting or argument.
"""

import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

DEFAULT_BASE_URL = "http://127.0.0.1:5193"
BASE_URL_PATTERN = re.compile(r"^http://(127\.0\.0\.1|localhost):\d{2,5}/?$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# The dashboard refuses days before its recovered metric contract starts.
EARLIEST_SUPPORTED_DATE = datetime.date(2026, 9, 8)
# A saved copy counts as new when it was written no earlier than this long before the request started.
FRESH_SLACK_SECONDS = 5


class ConfigError(Exception):
    """A setting or argument that cannot be used."""


def log(event, **fields):
    record = {"ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "event": event}
    record.update(fields)
    print(json.dumps(record, separators=(",", ":")), flush=True)


def bounded_int(environ, name, default, low, high):
    text = environ.get(name, "").strip()
    if not text:
        return default
    try:
        value = int(text)
    except ValueError:
        raise ConfigError("%s must be a whole number" % name)
    if not low <= value <= high:
        raise ConfigError("%s must be between %d and %d" % (name, low, high))
    return value


def load_config(environ):
    base_url = environ.get("SETTLE_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
    if not BASE_URL_PATTERN.match(base_url):
        raise ConfigError("SETTLE_BASE_URL must be a local dashboard address such as http://127.0.0.1:5193")
    timezone_name = environ.get("SETTLE_TIMEZONE", "America/Chicago").strip() or "America/Chicago"
    try:
        ZoneInfo(timezone_name)
    except Exception:
        raise ConfigError("SETTLE_TIMEZONE is not a known time zone")
    return {
        "base_url": base_url.rstrip("/"),
        "timezone": timezone_name,
        "max_attempts": bounded_int(environ, "SETTLE_MAX_ATTEMPTS", 8, 1, 20),
        # The dashboard's cool-down is 15 seconds; retry only after it has passed.
        "retry_seconds": bounded_int(environ, "SETTLE_RETRY_SECONDS", 20, 16, 300),
        "request_timeout": bounded_int(environ, "SETTLE_REQUEST_TIMEOUT_SECONDS", 700, 60, 1200),
    }


def settle_days(now_utc, timezone_name, last_day=None):
    """Days to re-read: from the Monday of the last day's week through the last day, newest first.

    The last day is yesterday in the plant's time zone unless one is given."""
    if last_day is None:
        last_day = now_utc.astimezone(ZoneInfo(timezone_name)).date() - datetime.timedelta(days=1)
    monday = last_day - datetime.timedelta(days=last_day.weekday())
    return [last_day - datetime.timedelta(days=offset) for offset in range((last_day - monday).days + 1)]


def http(method, base_url, path, body=None, timeout=60):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json", "X-Operations-KPI-Action": "refresh"}
    request = urllib.request.Request(base_url + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def saved_copy(base_url, day):
    """The dashboard's latest saved copy of one day, or None when it has none or it cannot be read."""
    try:
        status, body = http("GET", base_url, "/api/snapshot?report_date=" + day.isoformat(), timeout=60)
    except OSError:
        return None
    if status != 200:
        return None
    try:
        snapshot = json.loads(body.decode("utf-8"))
        if snapshot.get("report_date") != day.isoformat():
            return None
        generated = datetime.datetime.fromisoformat(str(snapshot["generated_at"]))
        row = next(item for item in snapshot["daily"] if item.get("date") == day.isoformat())
    except (ValueError, KeyError, StopIteration, TypeError, AttributeError):
        return None
    if generated.tzinfo is None:
        return None
    return {"generated_at": generated, "shipped": row.get("parts_shipped"), "loaded": row.get("trailers_prepared"),
            "departed": row.get("trailers_shipped")}


def describe(copy):
    if copy is None:
        return None
    return {"generated_at": copy["generated_at"].isoformat(), "shipped": copy["shipped"], "loaded": copy["loaded"], "departed": copy["departed"]}


def settle_day(cfg, day, sleep=time.sleep):
    """Ask the dashboard to re-read one day until its saved copy is new. Returns {ok, attempts, before, after}."""
    before = saved_copy(cfg["base_url"], day)
    attempts = []
    for attempt in range(1, cfg["max_attempts"] + 1):
        started = datetime.datetime.now(datetime.timezone.utc)
        note = {"attempt": attempt}
        try:
            status, body = http("POST", cfg["base_url"], "/api/refresh", {"report_date": day.isoformat(), "force": True}, timeout=cfg["request_timeout"])
            note["http"] = status
            if status == 200:
                after = saved_copy(cfg["base_url"], day)
                if after is not None and after["generated_at"] >= started - datetime.timedelta(seconds=FRESH_SLACK_SECONDS):
                    note["new_copy_saved"] = True
                    attempts.append(note)
                    return {"ok": True, "attempts": attempts, "before": before, "after": after}
                # The dashboard answered from its cache (a refresh within 15 seconds of another one); nothing was saved.
                note["new_copy_saved"] = False
            else:
                note["error"] = body.decode("utf-8", "replace")[:200]
        except OSError as error:
            note["error"] = type(error).__name__ + ": " + str(error)[:160]
        attempts.append(note)
        if attempt < cfg["max_attempts"]:
            sleep(cfg["retry_seconds"])
    return {"ok": False, "attempts": attempts, "before": before, "after": None}


def run(cfg, now_utc, last_day=None, dry_run=False, sleep=time.sleep):
    days = [day for day in settle_days(now_utc, cfg["timezone"], last_day) if day >= EARLIEST_SUPPORTED_DATE]
    log("start", dry_run=dry_run, timezone=cfg["timezone"], days=[day.isoformat() for day in days])
    if dry_run:
        log("dry_run_done", days=len(days))
        return 0
    settled = []
    failed = []
    for day in days:
        result = settle_day(cfg, day, sleep)
        if result["ok"]:
            settled.append(day.isoformat())
            log("day_ok", day=day.isoformat(), attempts=len(result["attempts"]), before=describe(result["before"]), after=describe(result["after"]))
        else:
            failed.append(day.isoformat())
            log("day_failed", day=day.isoformat(), attempts=result["attempts"], before=describe(result["before"]))
    log("done", settled=len(settled), failed=len(failed), failed_days=failed)
    return 0 if not failed else 1


def main(argv=None, environ=None, now_utc=None, sleep=time.sleep):
    parser = argparse.ArgumentParser(description="Nightly settle of the Operations KPI dashboard's saved days.")
    parser.add_argument("--dry-run", action="store_true", help="print the days that would be settled and stop")
    parser.add_argument("--last-day", default="", help="settle the week up to this day (YYYY-MM-DD) instead of yesterday")
    args = parser.parse_args(argv)
    try:
        cfg = load_config(os.environ if environ is None else environ)
        last_day = None
        if args.last_day:
            if not DATE_PATTERN.match(args.last_day):
                raise ConfigError("--last-day must look like 2026-11-22")
            last_day = datetime.date.fromisoformat(args.last_day)
    except (ConfigError, ValueError) as error:
        log("failed", reason=str(error))
        return 2
    return run(cfg, now_utc or datetime.datetime.now(datetime.timezone.utc), last_day, args.dry_run, sleep)


if __name__ == "__main__":
    sys.exit(main())
