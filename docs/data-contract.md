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
| `paint_decision_pieces` / `ppy_approved` | Compatibility field names for all physical paint passes and physical initial passes. Their ratio is PPY (Paint Process Yield). The matching `production_`, `bv_`, and `service_` fields retain each class numerator and denominator. |
| `paint_fty_total` / `paint_fty_approved` | Physical initial plus first-repaint passes, and physical initial passes. Their ratio is Paint FTY. The matching class fields retain each class numerator and denominator. |
| `paint_fty_repaint_count` | Physical first-repaint-loop passes on the report date. Second and later repaint loops affect PPY but are excluded from Paint FTY. |
| `receiving_total` / `receiving_approved` | Parts with a first receiving decision and those approved first pass. |
| `receiving_quantity` | Distinct non-service parts dated by `insp_receive_stamp`. |
| `final_total` / `final_approved` | Parts with a first final decision and those approved first pass. |
| `final_quantity` | Distinct non-service parts dated by `insp_final_stamp`. |
| `eol_inspected` | End-of-line inspections under the approved event-count rule. |
| `painted_parts_shipped` | Non-service painted pieces shipped. |
| `bumpers_shipped` / `parts_shipped` | Non-service bumper pieces and all non-service pieces shipped. |
| `complete_assy_sets` | Four-piece N33/Chassis Fairing sets dated by the latest `AssembledDate` among the set's pieces. |
| `assembled_bumper_count` | N71-6171 parts dated by `AssembledDate`. |
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
- `Repaint percentage = physical first-repaint-loop passes / (physical initial + first-repaint-loop passes)`, grouped by physical oven-exit date
- `Paint plan composite = min(paint pieces / scheduled pieces, 1) × ((paint FTY total - repaint count) / paint FTY total) × min(active paint hours / scheduled hours, 1)`

The last value is an inherited proxy and must not be renamed OEE without a separate approved definition for runtime, ideal cycle time, and good count.

## Required live-extractor behavior

The live SQL adapter is read-only and emits this contract. It must:

1. declare the timezone and a single inclusive/exclusive cutoff convention;
2. declare whether service parts are included for each metric;
3. order decisions by an approved event timestamp and stable tie-breaker;
4. count only physical paint passes and assign each pass to its oven-exit date; a repaint designation alone is not a paint event;
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

- Service-part scope by section.
- Production-day calendar and shift cutoff.
- True OEE versus continued use of the provisional composite.
- Prepared-trailer date semantics.
- Approved recipients, employee-detail visibility, schedule, and retention period.
