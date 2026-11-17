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

Version 0.18.0 corrects every product-family split after live source evidence proved that EDI `Origin` mixes physical Bumpers and Chassis Fairings. Repaint, Finesse, Receiving FTY, Final FTY, Pieces Shipped, shipping mix, and shipped-rack classifications now use normalized EDI `Description`: `Fender` = FUKA, `Bumper` = Bumpers, and `Chassis Fairing` = Fairings. N71-6164 remains its requested exclusive shipping/rack subset, while all-inclusive bumper fields still use `Description = Bumper`. Workflow scope fields such as staged paint carts and painted pieces shipped retain their existing Origin-based definitions because they describe process flow, not product family. The Finesse headline detail is also clarified to `Repaired / Total Rejected`. Headline totals, yield formulas, refresh ownership, snapshot grain, permissions, and QPTS business rows are unchanged.

Version 0.19.0 moves Finesse to its intended Receiving-inspection cohort. It starts with each non-service part's first Receiving reject, so Brownsville Origin-B parts remain represented even if a later repaint changes current Origin to F. Completed `repair_disposition = Repaired` parts are the numerator; completed WFP/repaint outcomes form the other resolved outcome; pending outcomes remain visible and are excluded from the percentage denominator. Repair detail uses normalized Description for Bumpers and Fairings. The browser keeps the header, date controls, and complete three-row tile grid while removing the obsolete charts and report sections beneath the tiles. Their aggregate snapshot fields remain available for future chart designs.

Version 0.20.1 labels the Loaded, Staged, and Painted cards as `Carts / Pieces` so their headings match the two measures already shown in each card. Each Carts and Pieces category-count detail stays on one line in both standard and wallboard views, and the obsolete decision-use boundary banner is removed while the read-only pilot badge remains. Version 0.20.0 keeps the OEE/provisional paint-plan-composite tile and reflows all 14 tiles into two desktop rows. Finesse combines the governed first-Receiving-reject cohort with GP-paint first-pass rejects: completed repairs from both stages are divided by all rejects from both stages, including unresolved Receiving rejects. The simplified detail shows repaired/rejected totals plus repaired FUKA, Bumper, and Fairing quantities. The Trailers tile restores shipped Bumper, FUKA, and Fairing rack quantities from the existing aggregate snapshot fields. No SQL, permissions, source-table rows, or OEE formula change is involved.

Version 0.21.0 makes repaint lineage plant-local for BV-origin parts. Their first physical Grand Prairie oven exit is now the GP initial pass; Brownsville `RepaintCount`, disposition, or receiving-reject history cannot by itself count as a GP repaint. A BV pass becomes a GP repaint failure only when a later physical GP pass proves it was repeated or when that pass has a GP-local Repaint/Direct Repaint disposition. Non-BV parts retain the reviewed Master Data Table, `RepaintCount`, and `load_line_repaint` contract. Separate repaint-pending fields keep Repaint PPY/FTY reconciliation independent from the unchanged Reject/Finesse outcome contract. The migration changes only the aggregate read procedure definition and writes no QPTS business rows.

Version 0.21.1 relabels the unchanged metrics as `Finesse Effectiveness`, `Preliminary OEE`, and trailer `Loaded / Departed`. The trailer rack details remain distinct EDI racks on non-service `SHIPPED` rows dated by `ship_date`; they are not matched to DriverLog trailer identifiers. Only Departed uses completed `DriverLog.TimeOut` records. A normal browser reload now opens today's saved immutable snapshot before falling back to the latest available snapshot, so viewing a historical day does not make that day persist across page reloads. No SQL, formula, source row, permission, or automatic-refresh change is involved.

Version 0.22.0 introduces the first shared, tile-selectable chart area for `Carts / Pieces Loaded`. The first row contains aligned 24-hour Carts and Pieces charts for the selected report date; the second row contains aligned rolling 30-calendar-day charts with exclusive `Prd / BV / Svc` stacks. Pieces retain a Unique Pieces comparison line. Load-event totals stay in their actual event hour, while each distinct piece and cart is assigned to its first load-event hour so all 24 buckets reconcile exactly to the unchanged daily card. The chart series is aggregate-only, is built once by the existing service-owned refresh, and is saved in the immutable snapshot; selecting a tile never queries SQL. Other tiles are selectable but intentionally show a not-yet-enabled state until this pilot layout is approved.

Version 0.24.0 keeps the two selected-day hourly Carts and Pieces plots as total-only line charts and adds Day Total, Peak Hour, and Active Hours summaries above each. The 13-week represented-day-average plots use vertical bars with the existing completed-week least-squares trendlines, weekly summaries, null-week omission, partial-week treatment, and vertical labels. The selected-day detail table remains beneath the hourly charts. This is an application-only presentation release; the v20 aggregate snapshot contract, KPI formulas, QPTS procedure and permissions, and cache-only wallboard polling are unchanged.

Version 0.25.0 adds visible whole-number values above every hourly point and 13-week column. Loaded-chart point and column labels, tooltips, and y-axis scales are rounded to the nearest whole cart or piece; the summary tiles and completed-week least-squares trend calculation retain decimal precision. The aggregate snapshot contract, KPI formulas, QPTS procedure and permissions, and cache-only wallboard polling remain unchanged.

Version 0.32.0 extends the approved chart format to Carts / Pieces Staged, Carts / Pieces Painted, Repaint %, and Finesse Effectiveness. Staged charts use point-in-time hourly queue snapshots and 13-week close-of-day averages against minimum goals of 12 carts and 36 pieces. Painted charts use hourly exit totals and represented-day weekly averages against net-time goals of 10 carts/hour and 30 pieces/hour. Repaint and Finesse retain weighted numerators and denominators against 4% (lower is better) and 90% (higher is better) goals. Each interim target closes 25% of the reviewed September 8–November 15 baseline gap. Result set 14 remains aggregate-only, all browser polling stays cache-only, and the migration writes no QPTS business rows.

Version 0.31.0 removes the redundant Loaded performance-contract banner above the 13-week charts. The frozen baseline and rate calculations remain unchanged. Interim-target and long-term-goal rates continue to appear where they are useful in chart summaries, legends, and reference lines. This is an application-only presentation cleanup; chart formulas, straight historical references, aggregate snapshots, SQL, refresh behavior, and cache-only polling remain unchanged.

Version 0.30.0 makes each 13-week Loaded interim-target and long-term-goal reference a single horizontal line. One representative daily net-loading span is calculated across all completed loading days in completed weeks within the displayed 13-week window, then applied to the frozen target and goal rates for the entire plot. The reference can update when the 13-week window rolls, but it never bends week by week within one chart. The redundant selected-day Loaded tile summary between the hourly and historical sections is removed while the per-chart hourly summaries remain. This is an application-only presentation correction; hourly references, actual weekly averages, trendlines, KPI formulas, aggregate snapshots, SQL, and cache-only polling remain unchanged.

Version 0.29.0 extends each 13-week Loaded interim-target and long-term-goal reference across the full historical plot. The line uses only the existing fully comparable weekly reference values, connects those values across unscored gaps, and carries the nearest comparable value to each plot edge; unscored weeks do not create new target values. This is an application-only rendering correction: the goal rates, interim-target formula, partial-week scoring, aggregate snapshot contract, SQL procedure, and cache-only polling behavior are unchanged.

Version 0.28.0 corrects the Loaded goals to 12 carts/hour and 36 pieces/hour. The retained 25% gap-closing formula recalculates interim targets to 9.2274 carts/hour and 27.4911 pieces/hour from the unchanged frozen baseline. The 10 carts/hour and 30 pieces/hour goals are reserved for the future Carts / Pieces Painted contract. No SQL or business data changes are required.

Version 0.27.0 corrects the Loaded chart presentation so the approved interim target and long-term goal are visible as horizontal references on both hourly charts. Weekly target and goal values now remain visible as bounded segments when fully comparable weeks are separated by unscored weeks; missing comparisons are left blank rather than inferred. The aggregate contract, formulas, procedure, and cache-only polling behavior are unchanged.

Version 0.26.0 added the approved Loaded performance contract without exposing identifiers. Net loading time runs from the first distinct-cart load to the last distinct-cart load. A completed day spanning at least six hours receives the standard 30-minute lunch allowance; the current partial day is visible but not scored. Frozen September 8–November 15 history establishes baselines of 8.3033 carts/hour and 24.6548 pieces/hour. Interim targets close 25% of each gap to the long-term goals, yielding 8.7274 carts/hour against a 10.0 goal and 25.9911 pieces/hour against a 30.0 goal. The selected-day summary and 13-week charts show net-time-adjusted target and goal comparisons. Wallboard polling remains cache-only and all QPTS access remains read-only.

Run the safe local fixture mode:

```bash
KPI_DATA_MODE=fixture \
KPI_FIXTURE_PATH=examples/2026-09-16.json \
KPI_SNAPSHOT_DIR=build/web-snapshots \
KPI_PORT=5193 \
.venv/bin/operations-kpi-wallboard
```

Then open `http://127.0.0.1:5193/`. Live GP-AI01 deployment details and rollback boundaries are in [deploy/README.md](deploy/README.md).
