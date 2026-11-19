#!/usr/bin/env python3
"""Daily Parts Shipped - GP.

Takes the shipped count, trailers loaded and trailers departed for each day of the week from the Operations KPI dashboard's saved days
(so the email always agrees with the dashboard), builds the email, checks the numbers, and sends it through the FlowForge Alerts mailer.
Replaces the Windows service on CLC07-OPS002. The older way (the BRAK procedure dbo.usp_QPTS_SendWeeklyShippedCountEmail plus two read-only
trailer queries) is still here behind --source sql, for a manual run if the dashboard is down.

  python3 shipped_count_email.py             live run (the seven recipients)
  python3 shipped_count_email.py --dry-run   read and check the numbers, send nothing
  python3 shipped_count_email.py --test      one test email to the test recipient only
  python3 shipped_count_email.py --source sql   (with any of the above) read BRAK directly instead of the dashboard

Configuration comes from the environment (job.env). The dashboard source needs no password; --source sql uses the systemd credential shipped-count-sql.
"""
import argparse
import datetime
import http.client
import json
import os
import re
import sys
import time
import traceback
from html import escape
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+'-]+@creativeliquidcoatings\.com$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RETRY_WAITS = (60, 120)
SUBJECT_PREFIX_FOR_NOTICES = "[FlowForge] "
SUBJECT = "Daily Parts Shipped - GP"
DEFAULT_DASHBOARD_URL = "http://127.0.0.1:5193"
DASHBOARD_URL_PATTERN = re.compile(r"^http://(127\.0\.0\.1|localhost):\d{2,5}/?$")
# The dashboard's day follows its own clock (KPI_TIMEZONE, Eastern). A saved day counts as a whole day only if it was saved at or after
# 23:00 dashboard time on that day (its last automatic save is about 23:50) or later (someone refreshed that day afterwards).
DASHBOARD_TIMEZONE = "America/Indiana/Indianapolis"
DAY_COMPLETE_FROM_HOUR = 23
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
SUMMARY_LEAD = "FlowForge shipped count summary for"
COLUMN_LABELS = ("Ship Date", "Day", "Shipped Count", "Trailers Loaded", "Trailers Departed")
HEAD_STYLE = "padding:6px 10px;border:1px solid #cccccc;background:#f2f2f2;"
CELL_STYLE = "padding:6px 10px;border:1px solid #cccccc;"
FOOTNOTE = ("Trailers Loaded is the number of different trailers the shipped parts went out on that day (service parts are not counted). "
            "Trailers Departed is the number of trailers the drivers logged as leaving that day.")
FOOTNOTE_DASHBOARD = "These are the Operations KPI dashboard's saved numbers for each day, so this email matches the dashboard. " + FOOTNOTE

# The trailer counts use the same definitions as the Operations KPI wallboard (its "Loaded" and "Departed" trailers):
#   loaded   = distinct (ship date, ship trailer) pairs on dbo.[EDI Data Table], service parts left out, blank trailer left out;
#   departed = dbo.DriverLog rows by the date of TimeOut with a non-blank TrailerID.
# Read only: two SELECTs, no temp tables, READ UNCOMMITTED like the shipped-count procedure.
TRAILER_SQL = """SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;
DECLARE @FirstDay datetime2(0) = CONVERT(datetime2(0), '@FIRST@', 23);
DECLARE @DayAfterLast datetime2(0) = DATEADD(day, 1, CONVERT(datetime2(0), '@LAST@', 23));
SELECT CONVERT(varchar(10), t.report_date, 23) AS report_date, COUNT_BIG(*) AS trailers_loaded
FROM (
    SELECT CONVERT(date, e.ship_date) AS report_date, LTRIM(RTRIM(e.ship_trailer)) AS trailer_id
    FROM dbo.[EDI Data Table] AS e
    WHERE e.ship_date >= @FirstDay
      AND e.ship_date < @DayAfterLast
      AND ISNULL(e.Model, N'') <> N'Service'
      AND NULLIF(LTRIM(RTRIM(e.ship_trailer)), N'') IS NOT NULL
    GROUP BY CONVERT(date, e.ship_date), LTRIM(RTRIM(e.ship_trailer))
) AS t
GROUP BY t.report_date
ORDER BY t.report_date;
SELECT CONVERT(varchar(10), x.report_date, 23) AS report_date, COUNT_BIG(*) AS trailers_departed
FROM (
    SELECT CONVERT(date, d.TimeOut) AS report_date
    FROM dbo.DriverLog AS d
    WHERE d.TimeOut >= @FirstDay
      AND d.TimeOut < @DayAfterLast
      AND NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(255), d.TrailerID))), N'') IS NOT NULL
) AS x
GROUP BY x.report_date
ORDER BY x.report_date;
"""


class PermanentError(Exception):
    """A problem a retry cannot fix (bad data, refused request)."""


class TransientError(Exception):
    """A problem that may pass (SQL or mailer not reachable)."""


def log(event, **fields):
    record = {"ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "event": event}
    record.update(fields)
    print(json.dumps(record, default=str), flush=True)


def split_addresses(value):
    return [item.strip() for item in re.split(r"[;,]", value or "") if item.strip()]


def validate_addresses(addresses, label):
    if not addresses:
        raise PermanentError(label + " is empty")
    for address in addresses:
        if not EMAIL_PATTERN.match(address):
            raise PermanentError(label + " has an address outside creativeliquidcoatings.com or with unsafe characters: " + address[:80])
    return addresses


def load_config(environ, need_sql=True):
    def need(name):
        value = environ.get(name, "").strip()
        if not value:
            raise PermanentError("missing setting " + name)
        return value

    def sql_setting(name):
        return need(name) if need_sql else environ.get(name, "").strip()

    dashboard_url = environ.get("SHIPPED_COUNT_DASHBOARD_URL", "").strip() or DEFAULT_DASHBOARD_URL
    if not DASHBOARD_URL_PATTERN.match(dashboard_url):
        raise PermanentError("SHIPPED_COUNT_DASHBOARD_URL must be a loopback address such as " + DEFAULT_DASHBOARD_URL)
    host, instance = sql_setting("SHIPPED_COUNT_SERVER_HOST"), sql_setting("SHIPPED_COUNT_SERVER_INSTANCE")
    return {
        "server": host + "\\" + instance if host and instance else "",
        "database": sql_setting("SHIPPED_COUNT_DATABASE"),
        "user": sql_setting("SHIPPED_COUNT_USER"),
        "dashboard_url": dashboard_url.rstrip("/"),
        "recipients": validate_addresses(split_addresses(need("SHIPPED_COUNT_RECIPIENTS")), "SHIPPED_COUNT_RECIPIENTS"),
        "test_recipient": validate_addresses(split_addresses(need("SHIPPED_COUNT_TEST_RECIPIENT")), "SHIPPED_COUNT_TEST_RECIPIENT")[:1],
        "failure_recipient": validate_addresses(split_addresses(need("SHIPPED_COUNT_FAILURE_RECIPIENT")), "SHIPPED_COUNT_FAILURE_RECIPIENT")[:1],
        "mailer_url": need("SHIPPED_COUNT_MAILER_URL"),
        "sender": need("SHIPPED_COUNT_SENDER"),
        "timezone": environ.get("SHIPPED_COUNT_TIMEZONE", "America/Chicago").strip() or "America/Chicago",
    }


def read_password(environ):
    directory = environ.get("CREDENTIALS_DIRECTORY", "")
    if not directory:
        raise PermanentError("no systemd credentials directory (run the job through its service)")
    with open(os.path.join(directory, "shipped-count-sql"), "rb") as handle:
        password = handle.read().decode("utf-8").strip()
    if not password:
        raise PermanentError("the SQL credential is empty")
    return password


def expected_report_date(now_utc, timezone_name):
    local = now_utc.astimezone(ZoneInfo(timezone_name))
    return (local.date() - datetime.timedelta(days=1)).isoformat()


def run_sql(cfg, password, sql, label):
    import odbc_min  # imported here so the checks below can be tested without the ODBC library
    try:
        connection = odbc_min.Connection(odbc_min.build_connection_string(cfg["server"], cfg["database"], cfg["user"], password))
    except odbc_min.OdbcError as error:
        raise TransientError("SQL connect: " + str(error)[:300])
    try:
        return connection.run_batch(sql)
    except odbc_min.OdbcError as error:
        raise TransientError("SQL %s: %s" % (label, str(error)[:300]))
    finally:
        connection.close()


def run_procedure(cfg, password, recipients, report_date_override):
    sql = "SET NOCOUNT ON; EXEC dbo.usp_QPTS_SendWeeklyShippedCountEmail @Recipients = N'" + ";".join(recipients) + "'"
    if report_date_override:
        if not DATE_PATTERN.match(report_date_override):
            raise PermanentError("the report date must look like 2026-11-18")
        sql += ", @ReportDateOverride = '" + report_date_override + "'"
    sql += ";"
    return run_sql(cfg, password, sql, "procedure")


def trailer_sql(first_day, last_day):
    for value in (first_day, last_day):
        if not DATE_PATTERN.match(value or ""):
            raise PermanentError("the trailer dates must look like 2026-11-18")
    return TRAILER_SQL.replace("@FIRST@", first_day).replace("@LAST@", last_day)


def run_trailer_counts(cfg, password, days):
    return run_sql(cfg, password, trailer_sql(days[0], days[-1]), "trailer counts")


def parse_trailer_counts(result_sets, days):
    """Turn the two trailer result sets into {date: (loaded, departed)}; a day with no rows counts as zero."""
    if len(result_sets) != 2:
        raise PermanentError("the trailer query returned %d result sets, expected 2" % len(result_sets))
    counts = {day: [0, 0] for day in days}
    for index, rows in enumerate(result_sets):
        for row in rows:
            if len(row) < 2 or row[0] not in counts:
                raise PermanentError("the trailer query returned a day outside the week: " + str(row[:1])[:40])
            try:
                value = int(row[1])
            except (TypeError, ValueError):
                raise PermanentError("the trailer counts are not numbers")
            if value < 0:
                raise PermanentError("a trailer count is negative")
            counts[row[0]][index] = value
    return {day: (pair[0], pair[1]) for day, pair in counts.items()}


def merge_rows(daily, trailers):
    """One dict per day: date, day name, shipped count, trailers loaded, trailers departed."""
    rows = []
    for item in daily:
        loaded, departed = trailers[item[0]]
        rows.append({"date": item[0], "day": item[1], "shipped": int(item[2]), "loaded": loaded, "departed": departed})
    return rows


def week_days(report_date):
    """The ISO dates from the Monday of the week that contains report_date through report_date."""
    last = datetime.date.fromisoformat(report_date)
    first = last - datetime.timedelta(days=last.weekday())
    return [(first + datetime.timedelta(days=offset)).isoformat() for offset in range((last - first).days + 1)]


def http_get(base_url, path, timeout=30):
    parts = urlparse(base_url)
    try:
        connection = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=timeout)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()
    except (OSError, http.client.HTTPException) as error:
        raise TransientError("the KPI dashboard is not reachable: " + str(error)[:200])


def fetch_dashboard_day(base_url, day):
    """The dashboard's saved snapshot for one day. A plain read: it never makes the dashboard refresh or save anything."""
    status, body = http_get(base_url, "/api/snapshot?report_date=" + day)
    if status == 404:
        raise PermanentError("the KPI dashboard has no saved day for " + day)
    if status != 200:
        raise TransientError("the KPI dashboard answered HTTP %d for %s" % (status, day))
    try:
        return json.loads(body.decode("utf-8"))
    except ValueError:
        raise TransientError("the KPI dashboard answered with something that is not JSON for " + day)


def day_from_snapshot(snapshot, day):
    """One day's numbers from the dashboard's saved snapshot, after checking that it really is that whole day."""
    if not isinstance(snapshot, dict) or snapshot.get("report_date") != day:
        raise PermanentError("the KPI dashboard answered for a different day than " + day)
    zone = ZoneInfo(DASHBOARD_TIMEZONE)
    try:
        saved_at = datetime.datetime.fromisoformat(str(snapshot.get("generated_at")))
    except ValueError:
        raise PermanentError("the KPI dashboard's saved %s has no readable save time" % day)
    if saved_at.tzinfo is None:
        saved_at = saved_at.replace(tzinfo=zone)
    day_date = datetime.date.fromisoformat(day)
    day_complete = datetime.datetime.combine(day_date, datetime.time(DAY_COMPLETE_FROM_HOUR), tzinfo=zone)
    if saved_at < day_complete:
        raise PermanentError("the KPI dashboard's saved %s was taken at %s, before that day was over"
                             % (day, saved_at.astimezone(zone).strftime("%Y-%m-%d %H:%M")))
    row = next((item for item in snapshot.get("daily") or [] if isinstance(item, dict) and item.get("date") == day), None)
    if row is None:
        raise PermanentError("the KPI dashboard's saved %s has no row for that day" % day)
    values = {}
    for name, key in (("shipped", "parts_shipped"), ("loaded", "trailers_prepared"), ("departed", "trailers_shipped")):
        value = row.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise PermanentError("the KPI dashboard's %s for %s is not a whole number" % (key, day))
        values[name] = value
    return {"date": day, "day": DAY_NAMES[day_date.weekday()], "saved_at": str(snapshot["generated_at"]),
            "shipped": values["shipped"], "loaded": values["loaded"], "departed": values["departed"]}


def dashboard_week(cfg, report_date):
    """(summary, rows) for the week up to report_date, straight from the dashboard's saved days."""
    rows = [day_from_snapshot(fetch_dashboard_day(cfg["dashboard_url"], day), day) for day in week_days(report_date)]
    summary = {"report_date": report_date, "previous_day_count": rows[-1]["shipped"],
               "week_total_count": sum(row["shipped"] for row in rows), "subject": SUBJECT}
    return summary, rows


def check_result(result_sets, expected_date, skip_date_guard):
    """Validate what the procedure returned and return (summary dict, daily rows)."""
    if len(result_sets) < 2 or not result_sets[-1]:
        raise PermanentError("the procedure did not return the expected summary row")
    daily = result_sets[0]
    row = result_sets[-1][0]
    if len(row) < 7:
        raise PermanentError("the summary row has " + str(len(row)) + " columns, expected 7")
    summary = {
        "report_date": row[0], "previous_day_count": row[1], "week_total_count": row[2], "subject": row[3],
        "recipients": row[4], "source_object": row[5],
    }
    if not summary["subject"] or "\n" in summary["subject"] or "\r" in summary["subject"]:
        raise PermanentError("the procedure returned no usable subject")
    if not DATE_PATTERN.match(summary["report_date"] or ""):
        raise PermanentError("the procedure returned no report date")
    try:
        daily_total = sum(int(item[2]) for item in daily)
        total = int(summary["week_total_count"])
        int(summary["previous_day_count"])
    except (ValueError, IndexError):
        raise PermanentError("the shipped counts are not numbers")
    if daily_total != total:
        raise PermanentError("the daily rows add up to %d but the week total says %d" % (daily_total, total))
    if not skip_date_guard and summary["report_date"] != expected_date:
        raise PermanentError("the report date is %s but yesterday is %s (check the clocks on BRAK and GP-AI01)" % (summary["report_date"], expected_date))
    return summary, daily


def us_date(iso):
    return datetime.datetime.strptime(iso, "%Y-%m-%d").strftime("%m/%d/%Y")


def week_totals(summary, rows):
    return int(summary["week_total_count"]), sum(row["loaded"] for row in rows), sum(row["departed"] for row in rows)


def build_html(summary, rows, footnote=FOOTNOTE):
    """The email body: the same look as the old procedure email, with the two trailer columns added."""
    shipped_total, loaded_total, departed_total = week_totals(summary, rows)

    def cell(value, extra=""):
        return '<td style="%s%s">%s</td>' % (CELL_STYLE, extra, escape(str(value)))

    right = "text-align:right;"
    lines = [
        '<html><body style="font-family:Segoe UI, Arial, sans-serif;font-size:12pt;">',
        "<p>%s <strong>%s</strong>.</p>" % (SUMMARY_LEAD, escape(us_date(summary["report_date"]))),
        "<p><strong>Previous day shipped count:</strong> %s</p>" % escape(str(summary["previous_day_count"])),
        "<p><strong>Week-to-date grand total:</strong> %s</p>" % escape(str(summary["week_total_count"])),
        "<p><strong>Week-to-date breakdown</strong> (week containing the reported ship date):</p>",
        '<table style="border-collapse:collapse;">',
        "<tr>" + "".join('<th style="%s">%s</th>' % (HEAD_STYLE, escape(label)) for label in COLUMN_LABELS) + "</tr>",
    ]
    for row in rows:
        lines.append("<tr>" + cell(us_date(row["date"])) + cell(row["day"]) + cell(row["shipped"], right)
                     + cell(row["loaded"], right) + cell(row["departed"], right) + "</tr>")
    total_style = "background:#f2f2f2;font-weight:bold;"
    lines.append('<tr><td colspan="2" style="%s%s">Week Total</td>' % (CELL_STYLE, total_style)
                 + "".join(cell(value, total_style + right) for value in (shipped_total, loaded_total, departed_total)) + "</tr>")
    lines.append("</table>")
    lines.append('<p style="font-size:9pt;color:#666666;">%s</p>' % escape(footnote))
    lines.append("</body></html>")
    return "".join(lines)


def build_text(summary, rows, footnote=FOOTNOTE):
    shipped_total, loaded_total, departed_total = week_totals(summary, rows)
    lines = [
        "%s %s." % (SUMMARY_LEAD, us_date(summary["report_date"])), "",
        "Previous day shipped count: %s" % summary["previous_day_count"], "",
        "Week-to-date grand total: %s" % summary["week_total_count"], "",
        "Week-to-date breakdown (week containing the reported ship date):", "",
        "\t".join(COLUMN_LABELS),
    ]
    for row in rows:
        lines.append("\t".join((us_date(row["date"]), row["day"], str(row["shipped"]), str(row["loaded"]), str(row["departed"]))))
    lines.append("Week Total\t\t%d\t%d\t%d" % (shipped_total, loaded_total, departed_total))
    lines += ["", footnote]
    return "\r\n".join(lines) + "\r\n"


def post_to_mailer(cfg, payload):
    parts = urlparse(cfg["mailer_url"])
    body = json.dumps(payload).encode("utf-8")
    try:
        connection = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=60)
        try:
            connection.request("POST", "/api/send", body=body, headers={"Content-Type": "application/json", "Content-Length": str(len(body))})
            response = connection.getresponse()
            raw = response.read().decode("utf-8", "replace")
        finally:
            connection.close()
    except (OSError, http.client.HTTPException) as error:
        raise TransientError("mailer not reachable: " + str(error)[:200])
    if response.status == 200:
        try:
            return json.loads(raw or "{}")
        except ValueError:
            raise TransientError("mailer answered 200 with an unreadable body")
    if 500 <= response.status < 600:
        raise TransientError("mailer HTTP %d: %s" % (response.status, raw[:200]))
    raise PermanentError("mailer refused the message, HTTP %d: %s" % (response.status, raw[:300]))


def mail_payload(cfg, key, subject, html_body, text_body, recipients, template):
    return {"IdempotencyKey": key[:200], "SenderIdentity": cfg["sender"], "To": list(recipients), "Cc": [], "Bcc": [],
            "Subject": subject, "PlainTextBody": text_body, "HtmlBody": html_body, "TemplateName": template,
            "TemplateVersion": "1", "CorrelationId": key[:200]}


def with_test_banner(html_body):
    banner = ('<p style="padding:8px 10px;background:#fff4ce;border:1px solid #e0c36a;"><strong>Test from the server.</strong> '
              'This is a one-time test of the server job that replaces the Windows service. The usual recipients did not receive it.</p>')
    index = html_body.find(">", html_body.lower().find("<body"))
    return html_body[:index + 1] + banner + html_body[index + 1:] if index > 0 else banner + html_body


def failure_notice(cfg, message, expected_date):
    html_body = ("<p>The Daily Parts Shipped - GP email for <strong>%s</strong> did not go out.</p><p>%s</p>"
                 "<p>The server job will try again at its next scheduled time. To send it now, run: sudo systemctl start clc-shipped-count-email.service</p>"
                 "<p>This notice went only to you.</p>") % (us_date(expected_date), message.replace("&", "&amp;").replace("<", "&lt;"))
    text_body = ("The Daily Parts Shipped - GP email for %s did not go out.\r\n\r\n%s\r\n\r\nThe server job will try again at its next scheduled time. "
                 "To send it now, run: sudo systemctl start clc-shipped-count-email.service\r\n\r\nThis notice went only to you.\r\n") % (us_date(expected_date), message)
    key = "daily-parts-shipped-gp:failure:%s:%d" % (expected_date, int(time.time() // 3600))
    return mail_payload(cfg, key, SUBJECT_PREFIX_FOR_NOTICES + "Daily Parts Shipped - GP did not go out", html_body, text_body,
                        cfg["failure_recipient"], "daily-parts-shipped-failure")


def attempt(cfg, password, mode, report_date_override, now_utc, source="dashboard"):
    expected = expected_report_date(now_utc, cfg["timezone"])
    live = mode == "live"
    recipients = cfg["recipients"] if live else cfg["test_recipient"]
    if source == "dashboard":
        report_date = report_date_override or expected
        if not DATE_PATTERN.match(report_date):
            raise PermanentError("the report date must look like 2026-11-18")
        summary, rows = dashboard_week(cfg, report_date)
        footnote = FOOTNOTE_DASHBOARD
        log("dashboard_ok", report_date=summary["report_date"], previous_day=summary["previous_day_count"], week_total=summary["week_total_count"],
            days=len(rows), subject=summary["subject"], mode=mode, columns="date,shipped,loaded,departed,dashboard_saved_at",
            table=[[row["date"], row["shipped"], row["loaded"], row["departed"], row["saved_at"]] for row in rows])
    else:
        result_sets = run_procedure(cfg, password, cfg["recipients"], report_date_override)
        summary, daily = check_result(result_sets, expected, bool(report_date_override))
        log("procedure_ok", report_date=summary["report_date"], previous_day=summary["previous_day_count"], week_total=summary["week_total_count"],
            days=len(daily), subject=summary["subject"], mode=mode)
        days = [item[0] for item in daily]
        rows = merge_rows(daily, parse_trailer_counts(run_trailer_counts(cfg, password, days), days))
        footnote = FOOTNOTE
        log("trailers_ok", table=[[row["date"], row["shipped"], row["loaded"], row["departed"]] for row in rows], columns="date,shipped,loaded,departed")
    html_body = build_html(summary, rows, footnote)
    text_body = build_text(summary, rows, footnote)
    if mode == "dry-run":
        log("dry_run_done", would_send_to=len(cfg["recipients"]), body_chars=len(html_body))
        return summary
    subject = summary["subject"]
    if mode == "test":
        subject = subject + " (TEST from the server)"
        html_body = with_test_banner(html_body)
        key = "daily-parts-shipped-gp:test:%d" % int(time.time())
    else:
        key = "daily-parts-shipped-gp:" + summary["report_date"]
    response = post_to_mailer(cfg, mail_payload(cfg, key, subject, html_body, text_body, recipients, "daily-parts-shipped"))
    log("mail_accepted", mode=mode, recipients=len(recipients), provider_message_id=response.get("ProviderMessageId"), idempotency_key=key)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--test", action="store_true")
    parser.add_argument("--report-date", default="", help="YYYY-MM-DD; with --dry-run or --test only")
    parser.add_argument("--source", choices=("dashboard", "sql"), default="dashboard",
                        help="dashboard (default): the KPI dashboard's saved days; sql: read BRAK directly")
    args = parser.parse_args(argv)
    mode = "dry-run" if args.dry_run else "test" if args.test else "live"
    log("start", mode=mode, source=args.source, report_date_override=args.report_date or None)
    if args.report_date and mode == "live":
        log("failed", reason="--report-date is only for --dry-run or --test; a live run always reports yesterday")
        return 2
    try:
        cfg = load_config(os.environ, need_sql=args.source == "sql")
        password = read_password(os.environ) if args.source == "sql" else ""
    except PermanentError as error:
        log("failed", reason=str(error))
        return 1
    last_error = "unknown"
    for number in range(len(RETRY_WAITS) + 1):
        try:
            attempt(cfg, password, mode, args.report_date, datetime.datetime.now(datetime.timezone.utc), args.source)
            log("done", mode=mode, attempts=number + 1)
            return 0
        except TransientError as error:
            last_error = str(error)
            log("attempt_failed", attempt=number + 1, transient=True, reason=last_error)
            if number < len(RETRY_WAITS):
                time.sleep(RETRY_WAITS[number])
        except PermanentError as error:
            last_error = str(error)
            log("attempt_failed", attempt=number + 1, transient=False, reason=last_error)
            break
        except Exception as error:  # a defect: record it, do not hide it
            last_error = "unexpected error: " + type(error).__name__ + ": " + str(error)[:200]
            log("attempt_failed", attempt=number + 1, transient=False, reason=last_error, trace=traceback.format_exc()[-600:])
            break
    if mode == "live":
        try:
            post_to_mailer(cfg, failure_notice(cfg, last_error, expected_report_date(datetime.datetime.now(datetime.timezone.utc), cfg["timezone"])))
            log("failure_notice_sent", to=cfg["failure_recipient"][0])
        except (TransientError, PermanentError) as error:
            log("failure_notice_not_sent", reason=str(error))
    log("failed", mode=mode, reason=last_error)
    return 1


if __name__ == "__main__":
    sys.exit(main())
