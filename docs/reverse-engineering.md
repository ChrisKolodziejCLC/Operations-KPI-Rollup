# Reverse-engineering record

## What was recovered

The September 16, 2026 test email retained enough information to reconstruct the report without the original repository:

- complete HTML layout and inline styles;
- six embedded chart images;
- the headline KPI values, daily tables, painter throughput, defects, and shipping split;
- the two stored-procedure names used by the abandoned implementation.

Both procedures still existed in the production-tracking database and were read through the approved read-only administration route. No procedure was executed in a write mode, altered, installed, or replaced.

| Procedure | Definition SHA-256 | Last modified (EDT) |
|---|---|---|
| `dbo.usp_QPTS_GetOperationsQualityShippingRollup` | `E4A53C4F86BA1CEBBA303A6CC51E42AE8F43D73371E9924E1BD02F631031C78C` | 2026-09-17 14:36:27 |
| `dbo.usp_QPTS_GetWeeklyOperationsQualityShippingReport` | `98D7F2E8689074370C3FD816B51214E99B26C2E81F2D2639E2F2CCB637DE5361` | verified 2026-11-12 |

The raw procedure definitions and part-level replay results are intentionally not committed. This repository records the contract, aggregate evidence, and corrections needed for a safe replacement.

## Legacy result-set map

`usp_QPTS_GetOperationsQualityShippingRollup` returned metadata, combined periods, separate daily/weekly/monthly/quarterly/yearly/long-month rows, painter detail, top defects, rejection detail, repaint summary, shipping split, and high-repaint detail.

`usp_QPTS_GetWeeklyOperationsQualityShippingReport` returned the report window, event counts, paint output by hour/day, painter summary, operations and assembly counts, inspection scorecard, first end-of-line outcomes, defects, rejection detail, shipping summaries, trailer counts, and repaint detail.

## Verified accuracy defects

### 1. Historical replay was not stable

A read-only replay for 2026-09-16 using the unchanged procedure definition no longer matched the received email. Receiving repair, repaint, and trailer values changed from `4 / 4 / 9` in the email to `0 / 6 / 10` in the later replay.

The procedures combine event history with mutable current-state columns. That makes a past report change when a part or trailer is updated later. The replacement saves the complete aggregate input snapshot beside each report.

### 2. Weekly averages divided by calendar days

The partial week contained three production days and one no-production Sunday. The legacy email divided totals by four:

| Metric | Total | Legacy average | Correct production-day average |
|---|---:|---:|---:|
| Parts loaded | 909 | 227.3 | 303.0 |
| Paint pieces | 903 | 225.8 | 301.0 |
| EOL inspected | 887 | 221.8 | 295.7 |
| Painted parts shipped | 667 | 166.8 | 222.3 |
| Bumpers shipped | 638 | 159.5 | 212.7 |

The rebuilt contract carries both `calendar_days` and `data_days`; throughput averages use `data_days` unless explicitly labeled otherwise.

### 3. The scorecard was neither previous-day nor first-pass yield

The section labeled as a previous-day inspection scorecard was week-to-date. Its distinct approved and defect counts could overlap, so approved plus defect could exceed the inspected denominator. For example, Receiving was `705 approved / 757 inspected / 78 defects`, and Final was `1,519 / 1,520 / 2`.

The replacement requires an ordered first applicable decision per part and retains the numerator and denominator used for every displayed rate.

### 4. The high-repaint appendix ignored its own label

The email described previous-day parts with `RepaintCount > 3`. The procedure actually selected every historical row with `RepaintCount > 2` and had no date predicate. The fixture suppresses that appendix until a bounded, reviewed query exists.

### 5. Mixed-grain trend data

The rollup result combined days, weeks, months, quarters, years, and a second long-month series. September was duplicated, and the chart mixed incompatible grains on one x-axis. The rebuilt charts show daily production data only; period rollups remain in a separate table.

### 6. “Paint OEE” was not standard OEE

The legacy formula was:

`schedule attainment × no-repaint quality × active clock-hour coverage`

where active coverage was distinct clock hours containing oven exits divided by scheduled hours. This is not Availability × Performance × Quality based on runtime and ideal cycle time. The replacement calls it **Paint plan composite** and marks it provisional.

### 7. Scope and pass-order inconsistencies

- Paint included normal and service origins, while several downstream metrics excluded service parts.
- Loaded and oven-exit values counted events, while quality logic deduplicated parts or carts.
- “First” decisions were first only within a hard-coded history boundary, not lifetime first pass.
- Some quality-event joins used only a later ID condition, allowing a later repair event to be associated with an earlier pass.

These rules must be resolved in the live extractor rather than hidden in the renderer.

## Reconstruction decision

The original visual hierarchy is retained: headline cards, daily performance, charts, period rollups, painter throughput, defects, and shipping. The generator is deliberately fixture-first and send-disabled so metric rules can be approved before any production query or outbound automation is introduced.

The committed example contains aggregate recovery data only. Painter names are replaced with aliases, and part-level rejection detail is excluded.
