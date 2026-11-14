# Operations KPI Rollup

A clean-room reconstruction of the Operations / Quality / Shipping rollup that was previously generated from QPTS data and delivered as an HTML email.

## Current phase

This repository contains the fixture-driven report generator, audited data contract, on-demand wallboard service, and hash-gated SQL migrations approved for that service. It does **not** write QPTS business data or send email. The first preview is built from aggregate values recovered from the September 16, 2026 test message.

The legacy design is worth keeping: compact KPI cards, daily and period rollups, static charts that work in Outlook, and detail below the summary. The replacement fixes the original report's misleading labels and denominator problems and records an immutable input snapshot beside every generated report.

## Build the recovered preview

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/operations-kpi-rollup build \
  --input examples/2026-09-16.json \
  --output build/2026-09-16
```

Open `build/2026-09-16/report.html`. The build also produces a preview-only `.eml` with inline chart images and a copy of the normalized snapshot.

## Accuracy rules

1. Averages per day use `data_days` (represented production days), not every calendar date in the range.
2. Yield percentages are weighted from their summed numerators and denominators.
3. Current-week, weekly, monthly, and quarterly trends are never mixed on one x-axis.
4. Empty or single-point charts are omitted instead of filling the email with blank canvas.
5. First-pass metrics use the first applicable decision per part/pass. Later repair or approval events do not rewrite the original first-pass outcome.
6. The legacy "Paint OEE" value is presented as a **paint plan composite** until a true OEE contract is approved.
7. Every generated report saves its source snapshot so a historical email does not drift with mutable QPTS columns.

See [docs/reverse-engineering.md](docs/reverse-engineering.md), [docs/data-contract.md](docs/data-contract.md), and the retained [future charting requirements](docs/future-charting-requirements.md).

## Live-data boundary

The renderer consumes a versioned JSON snapshot. The included live adapter can produce that snapshot through a dedicated execute-only SQL identity while intentionally discarding part-level result sets. Email delivery remains a separate, explicitly enabled transport; preview and wallboard builds cannot send.

## On-demand dashboard pilot

Version 0.2 adds a dependency-free web service intended for an isolated GP-AI01 pilot. The browser view renders the same KPI contract without email and supports a cached leadership-wallboard mode. Live refreshes:

- execute only `dbo.usp_QPTS_GetOperationsQualityShippingRollup` through a dedicated login with object-scoped execute and definition-check permissions;
- request no part-level rejection or unbounded high-repaint result sets;
- accept refresh requests only from private-network clients with a required action header, strict date bounds, a global execution lock, and rate limiting;
- save an immutable aggregate JSON snapshot before displaying it;
- perform no QPTS writes and send no mail;
- omit employee-level painter detail unless explicitly enabled.

The Pieces Loaded card counts both normal and repaint load events. Version 0.8.0 headlines both production-flow tiles as `Total / Unique`: Pieces Loaded uses load-event total versus distinct QPTS Part IDs loaded that day, and Pieces Painted uses oven-exit total versus distinct QPTS Part IDs painted that day. The headline stays on one line and scales to the tile width rather than wrapping. Loaded/painted cart counts and `Prd / BV / Svc` piece splits remain in regular-weight detail below the headline. Trailers Prepared retains its total with FUKA, Bumpers, and Fairings beneath it. The event totals still drive charts and hard validation: every class split must equal its event total, each daily unique count cannot exceed that total, and cart classes are mutually exclusive.

Version 0.9.0 keeps the PPY and FTY tiles side by side for **Repaint** and **Reject** yield and restores a separate **Repaint %** tile for the familiar first-pass repaint rate. Every pass is assigned to its actual oven-exit date. Master Data Table supplies the preserved first EOL disposition, while `RepaintCount` and `load_line_repaint` establish repeat-pass lineage and current EDI supplies the latest completed repeat-pass outcome. Repaint PPY is non-repaint outcomes across every completed pass; Repaint FTY applies that outcome test only to initial passes. Reject PPY is Approved outcomes across every completed pass; Reject FTY is Approved outcomes among initial passes. Repair, Repaint, Direct Repaint, and Reject are rejected outcomes. Passes without a resolved outcome remain pending and are not silently counted good. The separate inspection-time hourly report is a reconciliation source, not the wallboard date grain, so daily values can differ and should converge over longer periods. The existing Paint plan composite is unchanged and excluded from this yield correction. Complete assembly sets are dated when their fourth N33/Chassis Fairing piece is assembled. Receiving and final quantities use `insp_receive_stamp` and `insp_final_stamp`; inspection FTY remains based on first decisions.

Version 0.10.0 adds direct Previous, Today, Next, date-picker, and Load Selected Day controls. The header separately identifies the selected report date and the full daily range represented by its snapshot. Wallboard mode requests the Grand Prairie local current day at startup and every five minutes, while retaining the latest immutable snapshot if a refresh is unavailable. The browser refresh key was removed; the service retains the private-network source gate, required action header, date bounds, one-at-a-time execution, rate limiting, execute-only SQL identity, and pinned procedure hash.

Version 0.11.0 makes refresh ownership server-side. Historical navigation reuses the newest valid immutable snapshot for that date, and repeated current-day requests inside the default ten-minute freshness window return the saved snapshot instead of executing SQL. One server worker refreshes the current day every ten minutes; wallboard browsers poll the cached current-day snapshot every 30 seconds and never initiate SQL themselves. The health endpoint reports the configured intervals, producer state, latest refresh source, and last SQL duration. The stored procedure, KPI formulas, QPTS permissions, and immutable snapshot contract are unchanged.

Version 0.12.0 makes that server-owned schedule visible. The header counts down to the next ten-minute current-day refresh, shows when the bounded query is running, and resynchronizes from the health endpoint while the wallboard continues to display and poll the saved snapshot. Pieces Shipped now sits immediately left of the rightmost Trailers Prepared tile and lists the saved Bumpers, Fenders, and Chassis Fairings mix beneath its unchanged non-service total. No SQL, KPI formula, snapshot grain, or database permission changes are involved.

Version 0.13.0 keeps the Repaint % tile's existing total-repaint / initial-pass detail and adds a second small line with the aggregate FUKA, Bumpers, and Fairings repaint counts. Pieces Shipped presents its existing aggregate mix in that same FUKA / Bumpers / Fairings order. The rollup procedure adds only the three aggregate repaint line-set counts; the Repaint % numerator, denominator, formula, snapshot grain, and database permissions remain unchanged. Every accepted snapshot must reconcile the three line-set counts exactly to `paint_fty_repaint_count`.

Version 0.14.0 keeps the Trailers Prepared headline as the unchanged total trailer count and replaces only its small category detail with physical racks shipped: each value is labeled `rack` or `racks` in FUKA / Bumpers / Fairings order. Racks come from the QPTS `Rack` field, are grouped once per ship date, and mixed racks are assigned to their dominant line set with deterministic FUKA / Bumpers / Fairings tie order. The procedure exposes only aggregate rack counts plus an internal Other integrity bucket; it does not expose rack IDs or part detail, and every pre-existing KPI result remains unchanged.

Version 0.16.0 keeps the clarified PPY/FTY rows from 0.15.0 and adds governed aggregate detail requested by the metric owner. Complete assembly sets and assembled N71-6171 bumpers now show separate MIC and Painted rows. Pieces Loaded and Pieces Painted expose N71-6164 separately from the existing production bucket; Pieces Shipped and Trailers Prepared likewise show N71-6164 as an exclusive piece/rack category. Every new split is validated against its existing headline total, and the headline formulas, refresh behavior, and read-only database permissions remain unchanged.

Version 0.17.0 simplifies the production-flow cards and adds the requested queue and quality context. Pieces Loaded and Pieces Painted return to `Prd / BV / Svc` detail; their retained N71-6164 subset fields remain available for audit but are no longer displayed on those two cards. A new Pieces Staged card mirrors the Paint Prep Wallboard contract: eligible Grand Prairie EDI-loaded cart groups with no `tblCarts_Paint` booth scan, using a three-day normal queue and seven-day active-repaint queue. Repaint % moves immediately after Pieces Painted, and Finesse % reports first-pass Repair outcomes as a percentage of all first-pass rejected outcomes, with FUKA, Fairings, and Bumpers repair counts. Receiving FTY now shows Bumpers and Fairings; Final FTY shows FUKA, Bumpers, and Fairings. The final trailer card compares prepared trailers with completed `DriverLog.TimeOut` departures. All additions remain aggregate-only, read-only, and reconciliation-gated.

Run the safe local fixture mode:

```bash
KPI_DATA_MODE=fixture \
KPI_FIXTURE_PATH=examples/2026-09-16.json \
KPI_SNAPSHOT_DIR=build/web-snapshots \
KPI_PORT=5193 \
.venv/bin/operations-kpi-wallboard
```

Then open `http://127.0.0.1:5193/`. Live GP-AI01 deployment details and rollback boundaries are in [deploy/README.md](deploy/README.md).
