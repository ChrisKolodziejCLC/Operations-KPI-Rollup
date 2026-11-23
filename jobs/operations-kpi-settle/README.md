# Operations KPI nightly settle

A small job on GP-AI01 that keeps the Operations KPI dashboard's saved days in step with BRAK. It exists so that the dashboard and the
Daily Parts Shipped - GP email, which reads the dashboard's saved days, always agree with BRAK.

## Why it exists

The dashboard saves a day as an immutable copy every time that day is refreshed, and it stops refreshing a day when the day ends. BRAK
keeps changing after the plant's day: for example a trailer number on a shipped part is corrected the next morning. The saved copy then
disagrees with BRAK (on 2026-11-16 the saved copy said 10 loaded trailers and BRAK said 11; on 2026-11-18, 8 and 10). The email's SQL path
reads BRAK live, so the two paths could differ for those days. The settle closes that gap once a night.

## What it does

Every night at 01:30 Central (`OnCalendar=*-*-* 01:30:00 America/Chicago`, `Persistent=true`), ninety minutes before the 03:00 Central email,
it asks the dashboard to re-read every day from the Monday of yesterday's week through yesterday, newest first. Each day takes about a
minute (the dashboard runs BRAK's read-only rollup procedure), so a full week takes under ten minutes.

It uses the dashboard's own explicit refresh control on the same host (`POST http://127.0.0.1:5193/api/refresh` with the refresh action
header). It never talks to BRAK itself, never sends an email and never changes SQL.

A refresh that arrives within 15 seconds of another refresh is answered with HTTP 200 and the old cached copy, and nothing is saved. So a
200 is not proof. A day counts as settled only when its saved copy (`GET /api/snapshot?report_date=...`) is newer than the request;
otherwise the job waits and retries (default 8 attempts, 20 seconds apart). A day that cannot be settled is logged and the job goes on with
the other days, then exits 1 so the unit shows as failed.

## Settings (unit environment)

- `SETTLE_BASE_URL` (default `http://127.0.0.1:5193`; only a local dashboard address is accepted)
- `SETTLE_TIMEZONE` (default `America/Chicago`, the plant and BRAK time zone: yesterday means the Central calendar day)
- `SETTLE_MAX_ATTEMPTS` (1 to 20, default 8), `SETTLE_RETRY_SECONDS` (16 to 300, default 20), `SETTLE_REQUEST_TIMEOUT_SECONDS` (60 to 1200, default 700)

## Running it by hand

- Plan only, nothing requested: `python3 settle_past_days.py --dry-run [--last-day YYYY-MM-DD]`
- Real run under the unit's sandbox: `sudo systemctl start operations-kpi-settle.service` (waits until it finishes)
- Logs, one JSON object per line (`start`, `day_ok`, `day_failed`, `done`): `journalctl -u operations-kpi-settle.service`

## Install and rollback

Installed under `/opt/clc/operations-kpi-settle/releases/<sha>` with a `current` link; the units in `deploy/` go to `/etc/systemd/system`, then
`systemctl enable --now operations-kpi-settle.timer`. It runs as a transient `DynamicUser` with the hardening listed in the unit and can only
reach 127.0.0.1. Rollback: `systemctl disable --now operations-kpi-settle.timer`, remove the two unit files and `systemctl daemon-reload`;
the dashboard and the email are not affected either way (the email then reads the copies the dashboard last saved, as before).

Change record: `2026-11-23-GP-AI01-Operations-KPI-Day-Window-Alignment` in TH Changes.
