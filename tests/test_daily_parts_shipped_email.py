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
            job.attempt(cfg, "pw", mode, "", now)
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


if __name__ == "__main__":
    unittest.main()
