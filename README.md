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
- require a separate refresh key;
- save an immutable aggregate JSON snapshot before displaying it;
- perform no QPTS writes and send no mail;
- omit employee-level painter detail unless explicitly enabled.

The Pieces Loaded card counts both normal and repaint load events. Version 0.7.0 headlines both production-flow tiles as `Total / Unique`: Pieces Loaded uses load-event total versus distinct QPTS Part IDs loaded that day, and Pieces Painted uses oven-exit total versus distinct QPTS Part IDs painted that day. The headline stays on one line and scales to the tile width rather than wrapping. Loaded/painted cart counts and `Prd / BV / Svc` piece splits remain in regular-weight detail below the headline. Trailers Prepared retains its total with FUKA, Bumpers, and Fairings beneath it. The event totals still drive charts and hard validation: every class split must equal its event total, each daily unique count cannot exceed that total, and cart classes are mutually exclusive.

PPY (Paint Process Yield) and Paint FTY are physical-pass metrics. PPY divides initial oven-exit passes by every oven-exit pass, including every repaint loop. Paint FTY divides initial passes by initial plus first-repaint passes; second and later repaint loops remain PPY-only. A repaint designation alone does not count, and every pass is assigned to the day it physically exits the oven. Complete assembly sets are dated when their fourth N33/Chassis Fairing piece is assembled. Receiving and final quantities use `insp_receive_stamp` and `insp_final_stamp`; inspection FTY remains based on first decisions.

Run the safe local fixture mode:

```bash
KPI_DATA_MODE=fixture \
KPI_FIXTURE_PATH=examples/2026-09-16.json \
KPI_SNAPSHOT_DIR=build/web-snapshots \
KPI_PORT=5193 \
.venv/bin/operations-kpi-wallboard
```

Then open `http://127.0.0.1:5193/`. Live GP-AI01 deployment details and rollback boundaries are in [deploy/README.md](deploy/README.md).
