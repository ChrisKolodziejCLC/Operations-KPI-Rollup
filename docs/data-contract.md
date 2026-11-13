# Snapshot data contract

The renderer accepts one immutable JSON document with `schema_version` set to `operations-kpi-snapshot/v1`. A report can always be regenerated from that document without querying QPTS again.

## Top-level fields

| Field | Type | Purpose |
|---|---|---|
| `schema_version` | string | Contract identifier. |
| `report_date` | ISO date | Operational day represented by the headline cards. |
| `generated_at` | ISO timestamp | Time the snapshot was produced. |
| `scope` | object | Human label, timezone, method version, and history boundary. |
| `daily` | array | One row per calendar date in the displayed report week. |
| `periods` | array | Separate weekly, monthly, and quarterly aggregate rows. |
| `painters` | array | Painter/booth throughput rows; the committed fixture uses aliases. |
| `shipping` | array | Date and line-set piece counts. |
| `top_defects` | array | Aggregate step, defect description, and count. |
| `attention` | object | Reviewed exceptions suitable for the report. |
| `data_quality_notes` | array | Method limitations shown to the reader. |

## Daily and period metric fields

| Field | Meaning |
|---|---|
| `production_day` | Whether the date participates in production-day averages. |
| `calendar_days` | Calendar dates in a period, including no-production dates. |
| `data_days` | Represented production days with reportable activity. |
| `parts_loaded` / `carts_loaded` | Loaded piece events (including repaint loads) and distinct non-null loaded carts. |
| `unique_pieces_loaded` | Distinct QPTS Part IDs represented by load events on that report date. For aggregate periods, this is the sum of the represented daily distinct counts, not a cross-day deduplication. |
| `production_parts_loaded` / `bv_parts_loaded` / `service_parts_loaded` | Loaded piece events split into ordinary production, BV (`N33` or `N71-6171`), and QPTS `Model = Service`. Service takes precedence over BV; the three fields sum to `parts_loaded`. |
| `production_carts_loaded` / `bv_carts_loaded` / `service_carts_loaded` | Distinct loaded carts under the same classes. Cart precedence is Service, then BV, then Prd so each cart is counted once and the three fields sum to `carts_loaded`. |
| `paint_carts` / `paint_pieces_processed` | Distinct paint carts and oven-exit pieces under the approved scope. |
| `unique_pieces_processed` | Distinct QPTS Part IDs represented by paint oven-exit events on that report date. For aggregate periods, this is the sum of the represented daily distinct counts, not a cross-day deduplication. |
| `production_paint_carts` / `bv_paint_carts` / `service_paint_carts` | Distinct oven-exit carts split into Prd, BV, and Svc using the same exclusive cart precedence. |
| `production_paint_pieces_processed` / `bv_paint_pieces_processed` / `service_paint_pieces_processed` | Oven-exit piece events split into Prd, BV, and Svc. |
| `paint_decision_pieces` / `ppy_approved` | Overall PPY denominator and approved numerator. The matching `production_`, `bv_`, and `service_` fields retain each class numerator and denominator. |
| `paint_fty_total` / `paint_fty_approved` | Overall initial paint passes and approved initial passes. The matching `production_`, `bv_`, and `service_` fields retain each class numerator and denominator. |
| `paint_fty_repaint_count` | Initial paint passes whose part is permanently classified `Repaint` at line end or `WFP` in repair. The count remains assigned to the original first-paint date even when the classification or physical repaint happens later. |
| `receiving_total` / `receiving_approved` | Parts with a first receiving decision and those approved first pass. |
| `final_total` / `final_approved` | Parts with a first final decision and those approved first pass. |
| `eol_inspected` | End-of-line inspections under the approved event-count rule. |
| `painted_parts_shipped` | Non-service painted pieces shipped. |
| `bumpers_shipped` / `parts_shipped` | Non-service bumper pieces and all non-service pieces shipped. |
| `complete_assy_sets` | Approved four-piece N33 assembly patterns. |
| `assembled_bumper_count` | Approved N71-6171 assembly count. |
| `trailers_prepared` | Prepared trailers as of the snapshot cutoff. `fuka_trailers_prepared`, `bumper_trailers_prepared`, `fairing_trailers_prepared`, and the internal `other_trailers_prepared` integrity bucket sum to this total. Trailers have no service category. Mixed historical trailers are classified by dominant piece type. |
| `pieces_scheduled` / `hours_scheduled` / `paint_hours` | Inputs to the provisional paint-plan composite. |

Every ratio is calculated by the renderer from a saved numerator and denominator. A zero denominator renders as `No Data`, not `0.0%`.

## Derived values

- `average per production day = period total / data_days`
- `parts_loaded = production_parts_loaded + bv_parts_loaded + service_parts_loaded`
- `carts_loaded = production_carts_loaded + bv_carts_loaded + service_carts_loaded`
- `paint_carts = production_paint_carts + bv_paint_carts + service_paint_carts`
- `paint_pieces_processed = production_paint_pieces_processed + bv_paint_pieces_processed + service_paint_pieces_processed`
- `0 <= unique_pieces_loaded <= parts_loaded`
- `0 <= unique_pieces_processed <= paint_pieces_processed`
- each PPY and Paint FTY class rate uses its saved class numerator and denominator
- `trailers_prepared = FUKA + Bumpers + Fairings + internal Other`
- `PPY = ppy_approved / paint_decision_pieces`
- `Paint FTY = paint_fty_approved / paint_fty_total`
- `Receiving FTY = receiving_approved / receiving_total`
- `Final FTY = final_approved / final_total`
- `Repaint percentage = permanently classified Repaint/WFP initial passes / initial passes`, grouped by the original first-paint date
- `Paint plan composite = min(paint pieces / scheduled pieces, 1) × ((paint FTY total - repaint count) / paint FTY total) × min(active paint hours / scheduled hours, 1)`

The last value is an inherited proxy and must not be renamed OEE without a separate approved definition for runtime, ideal cycle time, and good count.

## Required live-extractor behavior

The future SQL adapter must be read-only and emit this contract. Before it is considered production-ready, it must:

1. declare the timezone and a single inclusive/exclusive cutoff convention;
2. declare whether service parts are included for each metric;
3. order decisions by an approved event timestamp and stable tie-breaker;
4. attribute permanent Repaint/WFP classification to the original first-paint cohort rather than the later rework date;
5. distinguish event counts, distinct pieces, and distinct carts in both field names and documentation;
6. derive `production_day` from an approved calendar or activity rule;
7. snapshot mutable trailer and disposition values at generation time;
8. exclude or separately secure part-level and employee-level detail;
9. record the query/method version in `scope.method_version`;
10. validate aggregate invariants before writing the snapshot.

## Validation invariants

- All count fields are non-negative integers.
- Every displayed rate retains a denominator greater than or equal to its numerator where the outcome classes are exclusive.
- `data_days <= calendar_days` for period rows.
- Daily rows include the exact `report_date`.
- Period grains are not combined into one trend series.
- A snapshot is immutable after a report build; corrections create a new method version and snapshot.

## Open decisions before live automation

- Formal PPY and FTY pass/outcome definitions.
- Service-part scope by section.
- Production-day calendar and shift cutoff.
- True OEE versus continued use of the provisional composite.
- Prepared-trailer date semantics.
- Approved recipients, employee-detail visibility, schedule, and retention period.
