import datetime
import os
import re
import sys
import unittest

JOB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "jobs", "daily-parts-shipped-email")
sys.path.insert(0, JOB_DIR)
import shipped_count_email as job

PAGE = '<html><body style="x"><p>FlowForge shipped count summary for <strong>11/18/2026</strong>.</p><table><tr><td>1</td></tr></table></body></html>'
DAILY = [["2026-11-16", "Monday", "407"], ["2026-11-17", "Tuesday", "301"], ["2026-11-18", "Wednesday", "528"]]
DAYS = [item[0] for item in DAILY]


def sets(report_date="2026-11-18", total="1236", subject="Daily Parts Shipped - GP"):
    # The procedure's own email text is still the seventh column but the job does not use it any more.
    return [DAILY, [[report_date, "528", total, subject, "a@creativeliquidcoatings.com", "dbo.[EDI Data Table]", "<html></html>"]]]


def trailer_sets(loaded=(("2026-11-16", "11"), ("2026-11-17", "5"), ("2026-11-18", "9")),
                 departed=(("2026-11-16", "5"), ("2026-11-17", "6"), ("2026-11-18", "6"))):
    return [[list(item) for item in loaded], [list(item) for item in departed]]


def sample_rows():
    return job.merge_rows(DAILY, job.parse_trailer_counts(trailer_sets(), DAYS))


class ConfigTests(unittest.TestCase):
    ENV = {"SHIPPED_COUNT_SERVER_HOST": "brak.example", "SHIPPED_COUNT_SERVER_INSTANCE": "SQLEXPRESS", "SHIPPED_COUNT_DATABASE": "db", "SHIPPED_COUNT_USER": "u",
           "SHIPPED_COUNT_RECIPIENTS": "antoniatodd@creativeliquidcoatings.com, chriskolodziej@creativeliquidcoatings.com;zabdiventura@creativeliquidcoatings.com",
           "SHIPPED_COUNT_TEST_RECIPIENT": "chriskolodziej@creativeliquidcoatings.com", "SHIPPED_COUNT_FAILURE_RECIPIENT": "chriskolodziej@creativeliquidcoatings.com",
           "SHIPPED_COUNT_MAILER_URL": "http://127.0.0.1:5096", "SHIPPED_COUNT_SENDER": "flowforge-alerts@creativeliquidcoatings.com"}

    def test_recipients_split_on_comma_and_semicolon(self):
        cfg = job.load_config(self.ENV)
        self.assertEqual(len(cfg["recipients"]), 3)
        self.assertEqual(cfg["server"], "brak.example\\SQLEXPRESS")
        self.assertEqual(cfg["timezone"], "America/Chicago")

    def test_outside_domain_is_refused(self):
        env = dict(self.ENV, SHIPPED_COUNT_RECIPIENTS="x@example.com")
        with self.assertRaises(job.PermanentError):
            job.load_config(env)

    def test_unsafe_address_is_refused(self):
        env = dict(self.ENV, SHIPPED_COUNT_RECIPIENTS="a'; DROP TABLE x;--@creativeliquidcoatings.com")
        with self.assertRaises(job.PermanentError):
            job.load_config(env)

    def test_missing_setting_is_refused(self):
        env = dict(self.ENV)
        del env["SHIPPED_COUNT_USER"]
        with self.assertRaises(job.PermanentError):
            job.load_config(env)

    def test_the_dashboard_address_defaults_to_the_local_one(self):
        self.assertEqual(job.load_config(self.ENV)["dashboard_url"], "http://127.0.0.1:5193")
        env = dict(self.ENV, SHIPPED_COUNT_DASHBOARD_URL="http://localhost:5193/")
        self.assertEqual(job.load_config(env)["dashboard_url"], "http://localhost:5193")

    def test_a_dashboard_address_off_this_machine_is_refused(self):
        for bad in ("http://192.168.7.137:5193", "https://127.0.0.1:5193", "http://127.0.0.1.evil.example:5193", "http://127.0.0.1"):
            with self.assertRaises(job.PermanentError):
                job.load_config(dict(self.ENV, SHIPPED_COUNT_DASHBOARD_URL=bad))

    def test_the_sql_settings_are_only_needed_for_the_sql_source(self):
        env = {key: value for key, value in self.ENV.items() if "SERVER" not in key and key not in ("SHIPPED_COUNT_DATABASE", "SHIPPED_COUNT_USER")}
        job.load_config(env, need_sql=False)
        with self.assertRaises(job.PermanentError):
            job.load_config(env)


class CheckTests(unittest.TestCase):
    def test_good_result(self):
        summary, daily = job.check_result(sets(), "2026-11-18", False)
        self.assertEqual(summary["week_total_count"], "1236")
        self.assertEqual(len(daily), 3)

    def test_wrong_day_is_refused(self):
        with self.assertRaises(job.PermanentError):
            job.check_result(sets(), "2026-11-19", False)

    def test_wrong_day_allowed_for_an_explicit_override(self):
        job.check_result(sets(), "2026-11-19", True)

    def test_total_mismatch_is_refused(self):
        with self.assertRaises(job.PermanentError):
            job.check_result(sets(total="1237"), "2026-11-18", False)

    def test_missing_summary_is_refused(self):
        with self.assertRaises(job.PermanentError):
            job.check_result([DAILY], "2026-11-18", False)

    def test_short_summary_row_is_refused(self):
        with self.assertRaises(job.PermanentError):
            job.check_result([DAILY, [["2026-11-18", "528", "1236"]]], "2026-11-18", False)

    def test_multiline_subject_is_refused(self):
        with self.assertRaises(job.PermanentError):
            job.check_result(sets(subject="a\nBcc: x"), "2026-11-18", False)


class TrailerQueryTests(unittest.TestCase):
    def test_dates_are_filled_in(self):
        sql = job.trailer_sql("2026-11-16", "2026-11-18")
        self.assertIn("'2026-11-16'", sql)
        self.assertIn("'2026-11-18'", sql)
        self.assertNotIn("@FIRST@", sql)
        self.assertNotIn("@LAST@", sql)

    def test_a_bad_date_is_refused(self):
        for bad in ("2026-11-16'; DROP TABLE x;--", "11/16/2026", "", None):
            with self.assertRaises(job.PermanentError):
                job.trailer_sql(bad, "2026-11-18")
            with self.assertRaises(job.PermanentError):
                job.trailer_sql("2026-11-16", bad)

    def test_it_uses_the_wallboard_definitions(self):
        sql = job.trailer_sql("2026-11-16", "2026-11-18")
        for piece in ("FROM dbo.[EDI Data Table] AS e", "ISNULL(e.Model, N'') <> N'Service'",
                      "NULLIF(LTRIM(RTRIM(e.ship_trailer)), N'') IS NOT NULL",
                      "GROUP BY CONVERT(date, e.ship_date), LTRIM(RTRIM(e.ship_trailer))",
                      "FROM dbo.DriverLog AS d", "d.TimeOut >= @FirstDay",
                      "NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(255), d.TrailerID))), N'') IS NOT NULL"):
            self.assertIn(piece, sql)

    def test_it_only_reads(self):
        sql = job.trailer_sql("2026-11-16", "2026-11-18").upper()
        for word in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "EXEC", "TRUNCATE", "MERGE", "GRANT", "INTO #"):
            self.assertIsNone(re.search(r"\b" + re.escape(word) + r"\b", sql), word)
        self.assertEqual(sql.count("SELECT"), 4)  # two queries, each with one inner query
        self.assertIn("READ UNCOMMITTED", sql)


class TrailerCountTests(unittest.TestCase):
    def test_counts_line_up_with_the_days(self):
        counts = job.parse_trailer_counts(trailer_sets(), DAYS)
        self.assertEqual(counts["2026-11-16"], (11, 5))
        self.assertEqual(counts["2026-11-17"], (5, 6))
        self.assertEqual(counts["2026-11-18"], (9, 6))

    def test_a_day_without_rows_counts_as_zero(self):
        counts = job.parse_trailer_counts(trailer_sets(loaded=(("2026-11-17", "5"),), departed=()), DAYS)
        self.assertEqual(counts["2026-11-16"], (0, 0))
        self.assertEqual(counts["2026-11-17"], (5, 0))

    def test_a_day_outside_the_week_is_refused(self):
        with self.assertRaises(job.PermanentError):
            job.parse_trailer_counts(trailer_sets(loaded=(("2026-11-23", "5"),)), DAYS)

    def test_text_instead_of_a_number_is_refused(self):
        with self.assertRaises(job.PermanentError):
            job.parse_trailer_counts(trailer_sets(departed=(("2026-11-16", "x"),)), DAYS)

    def test_a_negative_count_is_refused(self):
        with self.assertRaises(job.PermanentError):
            job.parse_trailer_counts(trailer_sets(loaded=(("2026-11-16", "-1"),)), DAYS)

    def test_the_wrong_number_of_result_sets_is_refused(self):
        with self.assertRaises(job.PermanentError):
            job.parse_trailer_counts(trailer_sets()[:1], DAYS)
        with self.assertRaises(job.PermanentError):
            job.parse_trailer_counts(trailer_sets() + [[]], DAYS)

    def test_rows_carry_all_five_values(self):
        rows = sample_rows()
        self.assertEqual(rows[1], {"date": "2026-11-17", "day": "Tuesday", "shipped": 301, "loaded": 5, "departed": 6})


class FormatTests(unittest.TestCase):
    def test_expected_date_is_yesterday_in_chicago(self):
        # 2026-11-20 09:00 UTC is 03:00 in Chicago on 11-20, so yesterday is 11-19.
        now = datetime.datetime(2026, 11, 20, 9, 0, tzinfo=datetime.timezone.utc)
        self.assertEqual(job.expected_report_date(now, "America/Chicago"), "2026-11-19")
        # 2026-11-20 05:30 UTC is still 11-19 in Chicago, so yesterday is 11-18.
        now = datetime.datetime(2026, 11, 20, 5, 30, tzinfo=datetime.timezone.utc)
        self.assertEqual(job.expected_report_date(now, "America/Chicago"), "2026-11-18")

    def test_html_says_flowforge_and_has_the_trailer_columns(self):
        summary, _ = job.check_result(sets(), "2026-11-18", False)
        page = job.build_html(summary, sample_rows())
        self.assertIn("FlowForge shipped count summary for <strong>11/18/2026</strong>.", page)
        self.assertNotIn("QPTS", page)
        for label in ("Ship Date", "Day", "Shipped Count", "Trailers Loaded", "Trailers Departed"):
            self.assertIn(">" + label + "</th>", page)
        self.assertEqual(page.count("<th "), 5)
        self.assertIn("<strong>Previous day shipped count:</strong> 528</p>", page)
        self.assertIn("<strong>Week-to-date grand total:</strong> 1236</p>", page)

    def test_html_rows_and_week_totals(self):
        summary, _ = job.check_result(sets(), "2026-11-18", False)
        page = job.build_html(summary, sample_rows())
        cells = re.findall(r"<td[^>]*>([^<]*)</td>", page)
        self.assertEqual(cells[:5], ["11/16/2026", "Monday", "407", "11", "5"])
        self.assertEqual(cells[5:10], ["11/17/2026", "Tuesday", "301", "5", "6"])
        self.assertEqual(cells[10:15], ["11/18/2026", "Wednesday", "528", "9", "6"])
        self.assertEqual(cells[15:], ["Week Total", "1236", "25", "17"])
        self.assertIn('colspan="2"', page)

    def test_html_keeps_the_old_look(self):
        summary, _ = job.check_result(sets(), "2026-11-18", False)
        page = job.build_html(summary, sample_rows())
        self.assertTrue(page.startswith('<html><body style="font-family:Segoe UI, Arial, sans-serif;font-size:12pt;">'))
        self.assertIn('<table style="border-collapse:collapse;">', page)
        self.assertIn("padding:6px 10px;border:1px solid #cccccc;background:#f2f2f2;", page)
        self.assertTrue(page.endswith("</body></html>"))

    def test_html_escapes_what_it_prints(self):
        summary, _ = job.check_result(sets(), "2026-11-18", False)
        rows = sample_rows()
        rows[0]["day"] = "<b>Monday</b>"
        page = job.build_html(summary, rows)
        self.assertNotIn("<b>Monday", page)
        self.assertIn("&lt;b&gt;Monday", page)

    def test_text_body_matches_the_email_shape(self):
        summary, _ = job.check_result(sets(), "2026-11-18", False)
        text = job.build_text(summary, sample_rows())
        self.assertIn("FlowForge shipped count summary for 11/18/2026.", text)
        self.assertNotIn("QPTS", text)
        self.assertIn("Previous day shipped count: 528", text)
        self.assertIn("Ship Date\tDay\tShipped Count\tTrailers Loaded\tTrailers Departed", text)
        self.assertIn("11/16/2026\tMonday\t407\t11\t5", text)
        self.assertIn("Week Total\t\t1236\t25\t17", text)

    def test_payload_has_the_mailer_fields(self):
        cfg = job.load_config(ConfigTests.ENV)
        payload = job.mail_payload(cfg, "k" * 300, "Daily Parts Shipped - GP", "<p>x</p>", "x", cfg["recipients"], "t")
        self.assertEqual(len(payload["IdempotencyKey"]), 200)
        self.assertEqual(payload["SenderIdentity"], "flowforge-alerts@creativeliquidcoatings.com")
        self.assertEqual(payload["To"], cfg["recipients"])
        self.assertTrue(payload["Subject"].startswith("Daily Parts Shipped"))

    def test_test_banner_goes_inside_the_body(self):
        marked = job.with_test_banner(PAGE)
        self.assertTrue(marked.index("Test from the server") > marked.index("<body"))
        self.assertTrue(marked.index("Test from the server") < marked.index("FlowForge shipped count summary"))

    def test_failure_notice_goes_to_the_failure_recipient_with_an_allowed_prefix(self):
        cfg = job.load_config(ConfigTests.ENV)
        payload = job.failure_notice(cfg, "boom <b>", "2026-11-18")
        self.assertEqual(payload["To"], cfg["failure_recipient"])
        self.assertTrue(payload["Subject"].startswith("[FlowForge] "))
        self.assertNotIn("<b>", payload["HtmlBody"])


class AttemptTests(unittest.TestCase):
    """The whole run with the two database calls and the mailer replaced."""

    def run_attempt(self, mode, trailers=None):
        cfg = job.load_config(ConfigTests.ENV)
        sent = []
        originals = (job.run_procedure, job.run_trailer_counts, job.post_to_mailer)
        job.run_procedure = lambda *args: sets()
        job.run_trailer_counts = lambda *args: trailers if trailers is not None else trailer_sets()
        job.post_to_mailer = lambda config, payload: sent.append(payload) or {"ProviderMessageId": "m1"}
        try:
            now = datetime.datetime(2026, 11, 19, 9, 0, tzinfo=datetime.timezone.utc)
            job.attempt(cfg, "pw", mode, "", now, source="sql")
        finally:
            job.run_procedure, job.run_trailer_counts, job.post_to_mailer = originals
        return sent

    def test_live_run_sends_the_new_body_to_everyone(self):
        sent = self.run_attempt("live")
        self.assertEqual(len(sent), 1)
        self.assertEqual(len(sent[0]["To"]), 3)
        self.assertIn("Trailers Departed", sent[0]["HtmlBody"])
        self.assertIn("Week Total\t\t1236\t25\t17", sent[0]["PlainTextBody"])
        self.assertEqual(sent[0]["Subject"], "Daily Parts Shipped - GP")
        self.assertEqual(sent[0]["IdempotencyKey"], "daily-parts-shipped-gp:2026-11-18")

    def test_test_run_goes_to_the_test_recipient_only_and_is_marked(self):
        sent = self.run_attempt("test")
        self.assertEqual(sent[0]["To"], ["chriskolodziej@creativeliquidcoatings.com"])
        self.assertTrue(sent[0]["Subject"].endswith("(TEST from the server)"))
        self.assertIn("Test from the server", sent[0]["HtmlBody"])

    def test_dry_run_sends_nothing(self):
        self.assertEqual(self.run_attempt("dry-run"), [])

    def test_a_bad_trailer_answer_stops_the_send(self):
        with self.assertRaises(job.PermanentError):
            self.run_attempt("live", trailers=trailer_sets()[:1])


def saved_day(day, shipped, loaded, departed, saved_at=None):
    """What the dashboard's /api/snapshot?report_date=<day> returns, cut down to what the job reads.
    By default it is the nightly settle job's copy: saved at 01:30 Central, after that day was over."""
    after = (datetime.date.fromisoformat(day) + datetime.timedelta(days=1)).isoformat()
    return {"report_date": day, "generated_at": saved_at or after + "T01:30:12-06:00", "schema_version": 1,
            "daily": [{"date": day, "parts_shipped": shipped, "trailers_prepared": loaded, "trailers_shipped": departed}]}


# What the dashboard shows for the week: the saved Wednesday says 8 loaded (the tile Chris pasted), the saved Monday says 10.
SAVED = {"2026-11-16": saved_day("2026-11-16", 407, 10, 5), "2026-11-17": saved_day("2026-11-17", 301, 5, 6, "2026-11-19T10:58:00-05:00"),
         "2026-11-18": saved_day("2026-11-18", 528, 8, 6)}


class WeekDaysTests(unittest.TestCase):
    def test_a_thursday_report_date_gives_monday_to_thursday(self):
        self.assertEqual(job.week_days("2026-11-19"), ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19"])

    def test_a_sunday_report_date_gives_the_whole_week(self):
        self.assertEqual(job.week_days("2026-11-22"), ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20", "2026-11-21", "2026-11-22"])

    def test_a_monday_report_date_gives_just_that_monday(self):
        self.assertEqual(job.week_days("2026-11-16"), ["2026-11-16"])


class DashboardDayTests(unittest.TestCase):
    def test_the_numbers_come_straight_from_the_saved_day(self):
        row = job.day_from_snapshot(SAVED["2026-11-18"], "2026-11-18")
        self.assertEqual((row["day"], row["shipped"], row["loaded"], row["departed"]), ("Wednesday", 528, 8, 6))
        self.assertEqual(row["saved_at"], "2026-11-19T01:30:12-06:00")

    def test_a_day_saved_later_is_fine(self):
        row = job.day_from_snapshot(SAVED["2026-11-17"], "2026-11-17")
        self.assertEqual(row["loaded"], 5)

    def test_an_answer_for_another_day_is_refused(self):
        with self.assertRaises(job.PermanentError):
            job.day_from_snapshot(SAVED["2026-11-17"], "2026-11-18")

    def test_a_day_saved_before_it_was_over_is_refused(self):
        early = saved_day("2026-11-18", 300, 4, 3, "2026-11-18T15:10:00-05:00")
        with self.assertRaises(job.PermanentError) as caught:
            job.day_from_snapshot(early, "2026-11-18")
        self.assertIn("before that day was over", str(caught.exception))

    def test_the_cutoff_is_the_end_of_the_central_day(self):
        # Saved at 23:30 Central on the day itself (00:30 Eastern the next morning): the day was not over yet.
        with self.assertRaises(job.PermanentError) as caught:
            job.day_from_snapshot(saved_day("2026-11-18", 1, 1, 1, "2026-11-18T23:30:00-06:00"), "2026-11-18")
        self.assertIn("before that day was over", str(caught.exception))
        self.assertIn("Central", str(caught.exception))
        with self.assertRaises(job.PermanentError):
            job.day_from_snapshot(saved_day("2026-11-18", 1, 1, 1, "2026-11-19T00:30:00-05:00"), "2026-11-18")  # 23:30 Central
        # Exactly midnight Central, and anything after it, is a finished day.
        job.day_from_snapshot(saved_day("2026-11-18", 1, 1, 1, "2026-11-19T00:00:00-06:00"), "2026-11-18")
        job.day_from_snapshot(saved_day("2026-11-18", 1, 1, 1, "2026-11-19T01:00:00-05:00"), "2026-11-18")  # 00:00 Central
        job.day_from_snapshot(saved_day("2026-11-18", 1, 1, 1, "2026-11-19T01:30:12-06:00"), "2026-11-18")

    def test_the_old_eastern_rule_no_longer_decides(self):
        # 23:54 Eastern on the day (22:54 Central) used to be good enough; it is not any more.
        with self.assertRaises(job.PermanentError):
            job.day_from_snapshot(saved_day("2026-11-18", 1, 1, 1, "2026-11-18T23:54:42-05:00"), "2026-11-18")
        self.assertEqual(job.DASHBOARD_TIMEZONE, "America/Chicago")
        with open(os.path.join(JOB_DIR, "shipped_count_email.py"), encoding="utf-8") as source:
            self.assertNotIn("Indianapolis", source.read())

    def test_the_footnote_names_the_central_day(self):
        self.assertIn("Each day is the plant's Central day, 12:00 AM through 11:59 PM.", job.FOOTNOTE)
        self.assertIn(job.FOOTNOTE, job.FOOTNOTE_DASHBOARD)

    def test_a_save_time_without_a_zone_counts_as_dashboard_time(self):
        job.day_from_snapshot(saved_day("2026-11-18", 1, 1, 1, "2026-11-19T01:30:12"), "2026-11-18")
        with self.assertRaises(job.PermanentError):
            job.day_from_snapshot(saved_day("2026-11-18", 1, 1, 1, "2026-11-18T23:54:42"), "2026-11-18")
        with self.assertRaises(job.PermanentError):
            job.day_from_snapshot(saved_day("2026-11-18", 1, 1, 1, "2026-11-18T09:00:00"), "2026-11-18")

    def test_an_unreadable_save_time_is_refused(self):
        with self.assertRaises(job.PermanentError):
            job.day_from_snapshot(saved_day("2026-11-18", 1, 1, 1, "last night"), "2026-11-18")

    def test_a_missing_row_is_refused(self):
        snapshot = saved_day("2026-11-18", 1, 1, 1)
        snapshot["daily"] = []
        with self.assertRaises(job.PermanentError):
            job.day_from_snapshot(snapshot, "2026-11-18")

    def test_numbers_that_are_not_whole_numbers_are_refused(self):
        for bad in (None, -1, 2.5, "7", True):
            for key in ("parts_shipped", "trailers_prepared", "trailers_shipped"):
                snapshot = saved_day("2026-11-18", 528, 8, 6)
                snapshot["daily"][0][key] = bad
                with self.assertRaises(job.PermanentError):
                    job.day_from_snapshot(snapshot, "2026-11-18")


class DashboardFetchTests(unittest.TestCase):
    def fetch_with(self, status, body):
        original = job.http_get
        job.http_get = lambda base, path, timeout=30: (status, body)
        try:
            return job.fetch_dashboard_day("http://127.0.0.1:5193", "2026-11-18")
        finally:
            job.http_get = original

    def test_it_asks_for_the_saved_day_and_only_reads(self):
        seen = []
        original = job.http_get
        job.http_get = lambda base, path, timeout=30: seen.append((base, path)) or (200, b'{"report_date": "2026-11-18"}')
        try:
            job.fetch_dashboard_day("http://127.0.0.1:5193", "2026-11-18")
        finally:
            job.http_get = original
        self.assertEqual(seen, [("http://127.0.0.1:5193", "/api/snapshot?report_date=2026-11-18")])

    def test_a_missing_day_is_a_permanent_problem(self):
        with self.assertRaises(job.PermanentError):
            self.fetch_with(404, b"")

    def test_a_server_error_or_junk_is_worth_retrying(self):
        with self.assertRaises(job.TransientError):
            self.fetch_with(500, b"")
        with self.assertRaises(job.TransientError):
            self.fetch_with(200, b"<html>")

    def test_an_unreachable_dashboard_is_worth_retrying(self):
        with self.assertRaises(job.TransientError):
            job.http_get("http://127.0.0.1:1", "/api/snapshot?report_date=2026-11-18", timeout=2)


class DashboardAttemptTests(unittest.TestCase):
    """The whole run from the dashboard's saved days, with the dashboard and the mailer replaced."""

    def run_attempt(self, mode, saved=None, report_date=""):
        cfg = job.load_config(ConfigTests.ENV)
        saved = SAVED if saved is None else saved
        sent = []
        originals = (job.fetch_dashboard_day, job.post_to_mailer, job.run_procedure)

        def fetch(base, day):
            if day not in saved:
                raise job.PermanentError("the KPI dashboard has no saved day for " + day)
            return saved[day]
        job.fetch_dashboard_day = fetch
        job.post_to_mailer = lambda config, payload: sent.append(payload) or {"ProviderMessageId": "m1"}
        job.run_procedure = lambda *args: self.fail("the dashboard source must not touch BRAK")
        try:
            now = datetime.datetime(2026, 11, 19, 9, 0, tzinfo=datetime.timezone.utc)  # 03:00 in Chicago, so yesterday is 11-18
            job.attempt(cfg, "", mode, report_date, now)
        finally:
            job.fetch_dashboard_day, job.post_to_mailer, job.run_procedure = originals
        return sent

    def test_live_run_sends_the_dashboards_numbers_to_everyone(self):
        sent = self.run_attempt("live")
        self.assertEqual(len(sent), 1)
        self.assertEqual(len(sent[0]["To"]), 3)
        self.assertEqual(sent[0]["Subject"], "Daily Parts Shipped - GP")
        self.assertEqual(sent[0]["IdempotencyKey"], "daily-parts-shipped-gp:2026-11-18")
        cells = re.findall(r"<td[^>]*>([^<]*)</td>", sent[0]["HtmlBody"])
        self.assertEqual(cells[:5], ["11/16/2026", "Monday", "407", "10", "5"])
        self.assertEqual(cells[10:15], ["11/18/2026", "Wednesday", "528", "8", "6"])
        self.assertEqual(cells[15:], ["Week Total", "1236", "23", "17"])
        self.assertIn("Previous day shipped count:</strong> 528", sent[0]["HtmlBody"])
        self.assertIn("Week-to-date grand total:</strong> 1236", sent[0]["HtmlBody"])
        self.assertIn("saved numbers", sent[0]["HtmlBody"])
        self.assertIn("Week Total\t\t1236\t23\t17", sent[0]["PlainTextBody"])

    def test_the_email_shows_what_the_dashboard_shows_not_a_live_recount(self):
        # Wednesday's saved Loaded is 8 even though a live count today says 9: the email follows the dashboard.
        sent = self.run_attempt("live")
        self.assertIn(">8</td>", sent[0]["HtmlBody"])
        self.assertNotIn(">9</td>", sent[0]["HtmlBody"])

    def test_test_run_goes_to_the_test_recipient_only_and_is_marked(self):
        sent = self.run_attempt("test")
        self.assertEqual(sent[0]["To"], ["chriskolodziej@creativeliquidcoatings.com"])
        self.assertTrue(sent[0]["Subject"].endswith("(TEST from the server)"))
        self.assertIn("Test from the server", sent[0]["HtmlBody"])

    def test_dry_run_sends_nothing(self):
        self.assertEqual(self.run_attempt("dry-run"), [])

    def test_a_missing_saved_day_stops_the_send(self):
        saved = dict(SAVED)
        del saved["2026-11-17"]
        with self.assertRaises(job.PermanentError):
            self.run_attempt("live", saved=saved)

    def test_a_partial_day_stops_the_send(self):
        saved = dict(SAVED)
        saved["2026-11-18"] = saved_day("2026-11-18", 200, 3, 2, "2026-11-18T14:00:00-05:00")
        with self.assertRaises(job.PermanentError):
            self.run_attempt("live", saved=saved)

    def test_a_report_date_override_is_used_for_checks(self):
        saved = {"2026-11-16": saved_day("2026-11-16", 407, 10, 5), "2026-11-17": SAVED["2026-11-17"]}
        sent = self.run_attempt("test", saved=saved, report_date="2026-11-17")
        self.assertIn("FlowForge shipped count summary for <strong>11/17/2026</strong>.", sent[0]["HtmlBody"])


class MainTests(unittest.TestCase):
    def test_a_live_run_refuses_a_report_date(self):
        self.assertEqual(job.main(["--report-date", "2026-11-10"]), 2)

    def test_the_default_source_is_the_dashboard(self):
        parser_args = []
        original = job.load_config
        job.load_config = lambda environ, need_sql=True: parser_args.append(need_sql) or (_ for _ in ()).throw(job.PermanentError("stop here"))
        try:
            self.assertEqual(job.main(["--dry-run"]), 1)
            self.assertEqual(job.main(["--dry-run", "--source", "sql"]), 1)
        finally:
            job.load_config = original
        self.assertEqual(parser_args, [False, True])


if __name__ == "__main__":
    unittest.main()
