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

Run the safe local fixture mode:

```bash
KPI_DATA_MODE=fixture \
KPI_FIXTURE_PATH=examples/2026-09-16.json \
KPI_SNAPSHOT_DIR=build/web-snapshots \
KPI_PORT=5193 \
.venv/bin/operations-kpi-wallboard
```

Then open `http://127.0.0.1:5193/`. Live GP-AI01 deployment details and rollback boundaries are in [deploy/README.md](deploy/README.md).
