# Daily Parts Shipped - GP email job

Sends the early-morning "Daily Parts Shipped - GP" email (pieces shipped by day for the week) from GP-AI01.
It replaced a Windows service on Chris Kolodziej's PC (CLC07-OPS002), which needed that PC to be on and connected.

This job is separate from the wallboard service. It has its own release root, system user, systemd units and
encrypted credential, and the wallboard keeps its "outbound mail: none" boundary. This is the only code in this
repository that sends mail.

## What it does

1. Runs the BRAK procedure `dbo.usp_QPTS_SendWeeklyShippedCountEmail` (database `Production Tracking (Version 1.0.0)SQL`).
   The procedure does not send anything. It returns the daily shipped counts for the week (Monday through yesterday),
   a summary row and the finished email. Its shipped count is the number of `dbo.[EDI Data Table]` rows with a ship date.
2. Checks what came back: summary row present, report date equals yesterday in Central time (so a wrong clock on BRAK
   cannot send the wrong day), numbers are numbers, and the daily rows add up to the week total.
3. Sends the email through the FlowForge Alerts mailer on GP-AI01 (`127.0.0.1:5096`, sender
   `flowforge-alerts@creativeliquidcoatings.com`). The mailer only accepts the configured subject prefixes and
   recipients in `creativeliquidcoatings.com`.
4. If the run cannot finish, it retries after 60 and 120 seconds. After that it sends a short failure notice to the
   configured failure recipient only, never to the list.

## Run modes

    python3 shipped_count_email.py             live run, to the configured recipients
    python3 shipped_count_email.py --dry-run   run the procedure and the checks, send nothing
    python3 shipped_count_email.py --test      one email to the test recipient only, marked as a test
    python3 shipped_count_email.py --report-date 2026-11-18   with --dry-run or --test only, for checking another day

## Configuration and secrets

- Settings: `/etc/clc/shipped-count-email/job.env` on GP-AI01 (see `deploy/job.env.example`). The real recipient list
  lives only there, not in Git.
- SQL password: systemd credential `shipped-count-sql` (encrypted at `/etc/credstore.encrypted/clc-shipped-count-email/`).
  It is read-only access as `GPAI01-RO`. Never put it in Git, a unit file, a change record or chat.

## Install layout on GP-AI01

- Install root `/opt/clc/shipped-count-email`: `releases/<timestamp>` holds `shipped_count_email.py` and `odbc_min.py`;
  `current` is a symlink to the active release.
- Units `clc-shipped-count-email.service` (oneshot, sandboxed, runs as the system user `clc-shipped-count`) and
  `clc-shipped-count-email.timer` (03:00 America/Chicago, `Persistent=true`).
- Rollback of a release: point `current` back to the previous release directory. Nothing else changes.

## Tests

    python3 -m unittest tests.test_daily_parts_shipped_email

The tests need no database and no network.

## Change records

Change folder `2026-11-19-Shipped-Pieces-Email` in `CLC Main Site - IT/Change Control/TH Changes` holds the discovery notes,
the install and rollback scripts, and the evidence for each release.
