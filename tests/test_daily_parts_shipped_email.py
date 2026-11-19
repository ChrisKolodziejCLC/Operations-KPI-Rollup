import datetime
import os
import sys
import unittest

JOB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "jobs", "daily-parts-shipped-email")
sys.path.insert(0, JOB_DIR)
import shipped_count_email as job

HTML = '<html><body style="x"><p>QPTS shipped count summary for <strong>11/18/2026</strong>.</p><table><tr><td>1</td></tr></table></body></html>'
DAILY = [["2026-11-16", "Monday", "407"], ["2026-11-17", "Tuesday", "301"], ["2026-11-18", "Wednesday", "528"]]


def sets(report_date="2026-11-18", total="1236", html=HTML, subject="Daily Parts Shipped - GP"):
    return [DAILY, [[report_date, "528", total, subject, "a@creativeliquidcoatings.com", "dbo.[EDI Data Table]", html]]]


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

    def test_missing_table_is_refused(self):
        with self.assertRaises(job.PermanentError):
            job.check_result(sets(html="<p>nothing</p>"), "2026-11-18", False)

    def test_missing_summary_is_refused(self):
        with self.assertRaises(job.PermanentError):
            job.check_result([DAILY], "2026-11-18", False)

    def test_multiline_subject_is_refused(self):
        with self.assertRaises(job.PermanentError):
            job.check_result(sets(subject="a\nBcc: x"), "2026-11-18", False)


class FormatTests(unittest.TestCase):
    def test_expected_date_is_yesterday_in_chicago(self):
        # 2026-11-20 09:00 UTC is 03:00 in Chicago on 11-20, so yesterday is 11-19.
        now = datetime.datetime(2026, 11, 20, 9, 0, tzinfo=datetime.timezone.utc)
        self.assertEqual(job.expected_report_date(now, "America/Chicago"), "2026-11-19")
        # 2026-11-20 05:30 UTC is still 11-19 in Chicago, so yesterday is 11-18.
        now = datetime.datetime(2026, 11, 20, 5, 30, tzinfo=datetime.timezone.utc)
        self.assertEqual(job.expected_report_date(now, "America/Chicago"), "2026-11-18")

    def test_text_body_matches_the_email_shape(self):
        summary, daily = job.check_result(sets(), "2026-11-18", False)
        text = job.build_text(summary, daily)
        self.assertIn("QPTS shipped count summary for 11/18/2026.", text)
        self.assertIn("Previous day shipped count: 528", text)
        self.assertIn("11/16/2026\tMonday\t407", text)
        self.assertIn("Week Total\t\t1236", text)

    def test_payload_has_the_mailer_fields(self):
        cfg = job.load_config(ConfigTests.ENV)
        payload = job.mail_payload(cfg, "k" * 300, "Daily Parts Shipped - GP", "<p>x</p>", "x", cfg["recipients"], "t")
        self.assertEqual(len(payload["IdempotencyKey"]), 200)
        self.assertEqual(payload["SenderIdentity"], "flowforge-alerts@creativeliquidcoatings.com")
        self.assertEqual(payload["To"], cfg["recipients"])
        self.assertTrue(payload["Subject"].startswith("Daily Parts Shipped"))

    def test_test_banner_goes_inside_the_body(self):
        marked = job.with_test_banner(HTML)
        self.assertTrue(marked.index("Test from the server") > marked.index("<body"))
        self.assertTrue(marked.index("Test from the server") < marked.index("QPTS shipped count summary"))

    def test_failure_notice_goes_to_the_failure_recipient_with_an_allowed_prefix(self):
        cfg = job.load_config(ConfigTests.ENV)
        payload = job.failure_notice(cfg, "boom <b>", "2026-11-18")
        self.assertEqual(payload["To"], cfg["failure_recipient"])
        self.assertTrue(payload["Subject"].startswith("[FlowForge] "))
        self.assertNotIn("<b>", payload["HtmlBody"])


if __name__ == "__main__":
    unittest.main()
