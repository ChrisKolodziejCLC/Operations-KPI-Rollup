# Daily Parts Shipped - GP email job

Sends the early-morning "Daily Parts Shipped - GP" email (pieces shipped, trailers loaded and trailers departed, by day
for the week) from GP-AI01. It replaced a Windows service on Chris Kolodziej's PC (CLC07-OPS002), which needed that PC to be
on and connected. The numbers are the Operations KPI dashboard's own saved numbers, so the email always agrees with the dashboard.

This job is separate from the wallboard service. It has its own release root, system user, systemd units and
encrypted credential, and the wallboard keeps its "outbound mail: none" boundary. This is the only code in this
repository that sends mail.

## What it does

1. Works out the report date: yesterday in Central time. The email week runs from the Monday of that week through the report date.
2. For each of those days it reads the dashboard's saved day: `GET /api/snapshot?report_date=<day>` on the local dashboard
   (`http://127.0.0.1:5193`). This is a plain read; it never makes the dashboard refresh or save anything. From that day's row
   it takes three numbers: `parts_shipped`, `trailers_prepared` (shown as Trailers Loaded) and `trailers_shipped` (shown as
   Trailers Departed).
3. Checks each day: the dashboard answered for that day, the day was saved after it was over (at or after midnight Central at
   its end, so it is a whole day with any late corrections in it), and the three numbers are whole numbers. A day with no saved copy, or one saved
   before the day was over, stops the send.
4. Builds the email itself (HTML and plain text, the same look as the old procedure email plus the two trailer columns and a
   short footnote). The previous-day number is the report date's row and the week total is the sum of the days shown.
   Wording and layout are changed in `build_html` and `build_text`.
5. Sends the email through the FlowForge Alerts mailer on GP-AI01 (`127.0.0.1:5096`, sender
   `flowforge-alerts@creativeliquidcoatings.com`). The mailer only accepts the configured subject prefixes and
   recipients in `creativeliquidcoatings.com`.
6. If the run cannot finish, it retries after 60 and 120 seconds when the problem may pass (the dashboard or the mailer not
   reachable, an HTTP 5xx). After that, or straight away for a problem that will not pass (a missing or partial saved day), it sends a
   short failure notice to the configured failure recipient only, never to the list. The email is all or nothing.

### How the dashboard saves days

The dashboard refreshes the current day every few minutes and keeps each refresh as an immutable saved file; the latest saved
copy of a day is what it shows for that day. Since v0.46.0 its day is the plant's Central day (`KPI_TIMEZONE` America/Chicago, the same
day BRAK uses), so its last automatic save of a day is about 23:55 Central, just before the day is over. The nightly settle job
(`jobs/operations-kpi-settle`, 01:30 Central) saves every day of the week again once it is finished, which picks up late corrections
in BRAK, and this job insists on such a copy. If someone refreshes a past day in the dashboard later,
that day is saved again and the dashboard, and the next email, show the refreshed numbers. Changing how the dashboard saves days
or what a day row contains changes this email, so check this job's tests when you do.

## Trailer counts

The two trailer columns are the dashboard's Loaded and Departed trailers:

- **Trailers Loaded**: the number of distinct (ship date, ship trailer) pairs on `dbo.[EDI Data Table]` for that day, with
  service parts (`Model = Service`) and blank trailers left out. Dashboard field `trailers_prepared`; SQL in
  `sql/2026-11-12-add-bv-quality-trailer-breakdowns.sql` (`TrailerContents`, `TrailerDaily`). A trailer name typed two ways
  counts as two trailers.
- **Trailers Departed**: the number of `dbo.DriverLog` rows whose `TimeOut` falls on that day and whose `TrailerID` is not
  blank. Dashboard field `trailers_shipped`; SQL in `sql/2026-11-13-driverlog-trailer-inspection-details.sql`
  (`TrailerDepartureDaily`). The two counts are separate; they are not matched trailer by trailer.

## Manual fallback: `--source sql`

`--source sql` skips the dashboard and reads BRAK directly, the way the first version of this job did: it runs the procedure
`dbo.usp_QPTS_SendWeeklyShippedCountEmail` for the shipped counts and two read-only SELECTs (`TRAILER_SQL`, `READ UNCOMMITTED`, no
writes; a test checks that) for the trailer counts, as `GPAI01-RO`. Use it by hand if the dashboard is down. The numbers can differ
slightly from the dashboard's saved days because they are counted live. If the dashboard's trailer definitions change, change
`TRAILER_SQL` and its tests to match. The scheduled run does not use it.

## Run modes

    python3 shipped_count_email.py             live run, to the configured recipients
    python3 shipped_count_email.py --dry-run   read and check the numbers, send nothing
    python3 shipped_count_email.py --test      one email to the test recipient only, marked as a test
    python3 shipped_count_email.py --report-date 2026-11-18   with --dry-run or --test only, for checking another day
    python3 shipped_count_email.py --source sql   with any of the above: read BRAK directly instead of the dashboard

A live run refuses `--report-date` (it always reports yesterday).

## Configuration and secrets

- Settings: `/etc/clc/shipped-count-email/job.env` on GP-AI01 (see `deploy/job.env.example`). The real recipient list
  lives only there, not in Git. `SHIPPED_COUNT_DASHBOARD_URL` is optional (default `http://127.0.0.1:5193`, loopback only). The SQL
  settings are only needed for `--source sql`.
- SQL password (only for `--source sql`): systemd credential `shipped-count-sql` (encrypted at
  `/etc/credstore.encrypted/clc-shipped-count-email/`). It is read-only access as `GPAI01-RO`. Never put it in Git, a unit file, a
  change record or chat.

## Install layout on GP-AI01

- Install root `/opt/clc/shipped-count-email`: `releases/<timestamp>` holds `shipped_count_email.py` and `odbc_min.py`;
  `current` is a symlink to the active release.
- Units `clc-shipped-count-email.service` (oneshot, sandboxed, runs as the system user `clc-shipped-count`) and
  `clc-shipped-count-email.timer` (03:00 America/Chicago, `Persistent=true`).
- Rollback of a release: point `current` back to the previous release directory. Nothing else changes.

## Tests

    python3 -m unittest tests.test_daily_parts_shipped_email

The tests need no database and no network (one test confirms that an unreachable address is reported as a retryable problem).

## Change records

Change folder `2026-11-19-Shipped-Pieces-Email` in `CLC Main Site - IT/Change Control/TH Changes` holds the discovery notes,
the install and rollback scripts, and the evidence for each release.
