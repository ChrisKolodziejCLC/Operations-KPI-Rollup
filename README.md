# Operations KPI Rollup

A clean-room reconstruction of the Operations / Quality / Shipping rollup that was previously generated from QPTS data and delivered as an HTML email.

## Current phase

This repository contains a fixture-driven report generator and an audited data contract. It does **not** change QPTS, install SQL objects, or send email. The first preview is built from aggregate values recovered from the September 16, 2026 test message.

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

See [docs/reverse-engineering.md](docs/reverse-engineering.md) and [docs/data-contract.md](docs/data-contract.md).

## Planned live-data boundary

The renderer consumes a versioned JSON snapshot. A future read-only extractor can produce that snapshot from SQL after the corrected source query is reviewed. Email delivery remains a separate, explicitly enabled transport; preview builds cannot send.
