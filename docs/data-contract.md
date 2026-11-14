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
| `shipping` | array | Date and exclusive FUKA, Fairings, Bumpers, N71-6164, and optional Other piece counts. N71-6164 takes precedence over its underlying Bumper description in this display split. |
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
| `n71_6164_parts_loaded` | Retained audit subset of N71-6164 loaded piece events within `production_parts_loaded`. It is not displayed separately on the Pieces Loaded card. |
| `production_carts_loaded` / `bv_carts_loaded` / `service_carts_loaded` | Distinct loaded carts under the same classes. Cart precedence is Service, then BV, then Prd so each cart is counted once and the three fields sum to `carts_loaded`. |
| `n71_6164_carts_loaded` | Retained audit subset of loaded carts in the Prd class that contain N71-6164. Service and BV cart precedence remains unchanged; the subset is not displayed separately on Pieces Loaded. |
| `paint_carts` / `paint_pieces_processed` | Distinct paint carts and oven-exit pieces under the approved scope. |
| `unique_pieces_processed` | Distinct QPTS Part IDs represented by paint oven-exit events on that report date. For aggregate periods, this is the sum of the represented daily distinct counts, not a cross-day deduplication. |
| `production_paint_carts` / `bv_paint_carts` / `service_paint_carts` | Distinct oven-exit carts split into Prd, BV, and Svc using the same exclusive cart precedence. |
| `n71_6164_paint_carts` | Retained audit subset of oven-exit carts in the Prd class that contain N71-6164. It is not displayed separately on the Pieces Painted card. |
| `production_paint_pieces_processed` / `bv_paint_pieces_processed` / `service_paint_pieces_processed` | Oven-exit piece events split into Prd, BV, and Svc. |
| `n71_6164_paint_pieces_processed` | Retained audit subset of N71-6164 oven-exit piece events within `production_paint_pieces_processed`; the displayed Prd value includes this subset. |
| `staged_carts` / `staged_pieces` | Current Paint Prep queue as of the selected report-date cutoff. Eligible Origin F rows come from `EDI Data Table`, have no booth scan in `tblCarts_Paint`, have a nonblank color, exclude `Arc%` paint blocks, and have a null or Repaint line-end disposition. The normal queue includes the selected day and prior two days; active repaint carts include the selected day and prior six days. Cart groups use paint-block prefix plus cart ID, matching the deployed Paint Prep Wallboard. |
| `production_staged_*` / `bv_staged_*` / `service_staged_*` | Exclusive Prd, BV, and Svc splits for staged cart groups and pieces. Cart precedence is Service, then BV, then Prd; each cart-group and piece total must reconcile to its staged headline. |
| `paint_decision_pieces` / `ppy_approved` | All physical paint passes, and passes with a resolved non-repaint outcome. Their ratio is Repaint PPY. The matching `production_`, `bv_`, and `service_` fields retain each class numerator and denominator. |
| `ppy_repaint_count` | Physical passes whose EOL outcome is Repaint or Direct Repaint. Together with pending outcomes and `ppy_approved`, it reconciles to all paint passes. |
| `paint_fty_total` / `paint_fty_approved` | Physical initial passes, and initial passes with a resolved non-repaint outcome. Their ratio is Repaint FTY. |
| `paint_fty_repaint_count` | Initial passes whose preserved first EOL disposition is Repaint or Direct Repaint. Its ratio to `paint_fty_total` is the standalone Repaint %. |
| `fuka_paint_fty_repaint_count` / `bumper_paint_fty_repaint_count` / `fairing_paint_fty_repaint_count` | Aggregate product-family split of `paint_fty_repaint_count`, displayed in FUKA / Bumpers / Fairings order. Families use normalized EDI `Description`: `Fender` = FUKA, `Bumper` = Bumpers, and `Chassis Fairing` = Fairings. These fields expose no part-level rows and do not change the Repaint % formula. |
| `paint_fty_repair_count` | Initial physical passes whose preserved first EOL disposition is Repair. Its ratio to `reject_fty_rejected_count` is Finesse %. Pending outcomes are excluded from the denominator. |
| `fuka_paint_fty_repair_count` / `fairing_paint_fty_repair_count` / `bumper_paint_fty_repair_count` | Aggregate product-family split of `paint_fty_repair_count`, displayed as repaired quantities using the same normalized EDI `Description` rule. These three fields must sum to the Repair total. The Finesse detail labels the denominator as `Total Rejected`. |
| `reject_ppy_total` / `reject_ppy_approved` | All physical paint passes, and passes with an Approved EOL outcome. Their ratio is Reject PPY. |
| `reject_ppy_rejected_count` / `reject_ppy_pending_count` | All EOL Repair, Repaint, Direct Repaint, or Reject outcomes for those passes; and passes with no EOL outcome yet. |
| `reject_fty_total` / `reject_fty_approved` | Initial physical passes, and initial passes with an Approved preserved first EOL disposition. Their ratio is Reject FTY. |
| `reject_fty_rejected_count` / `reject_fty_pending_count` | Non-approved and pending EOL outcomes restricted to initial physical passes. |
| `receiving_total` / `receiving_approved` | Parts with a first receiving decision and those approved first pass. |
| `receiving_bumper_total` / `receiving_bumper_approved` / `receiving_fairing_total` / `receiving_fairing_approved` | Receiving first-decision totals and approvals split by normalized EDI `Description` into all Bumpers and all Chassis Fairings. Both totals and approvals reconcile to the overall Receiving FTY fields. |
| `receiving_quantity` | Distinct non-service parts dated by `insp_receive_stamp`. |
| `final_total` / `final_approved` | Parts with a first final decision and those approved first pass. |
| `final_fuka_total` / `final_fuka_approved` / `final_bumper_total` / `final_bumper_approved` / `final_fairing_total` / `final_fairing_approved` | Final-inspection first-decision totals and approvals split by normalized EDI `Description` into FUKA, all Bumpers, and all Chassis Fairings. Family totals and approvals reconcile to the overall Final FTY fields. |
| `final_quantity` | Distinct non-service parts dated by `insp_final_stamp`. |
| `eol_inspected` | End-of-line inspections under the approved event-count rule. |
| `painted_parts_shipped` | Non-service Origin F pieces shipped. This is a paint-flow metric and intentionally remains Origin-based; it is not a Fairings product-family count. |
| `bumpers_shipped` / `parts_shipped` | All non-service pieces whose normalized EDI `Description` is `Bumper`, including N71-6164; and all non-service pieces shipped. The shipping-mix array displays N71-6164 separately instead. |
| `complete_assy_sets` | Four-piece N33/Chassis Fairing sets dated by the latest `AssembledDate` among the set's pieces. `mic_complete_assy_sets` counts sets whose four pieces all have normalized `Color = MIC`; `painted_complete_assy_sets` counts the remaining non-MIC sets. The current source window has no mixed/blank sets, and the two detail fields sum to the headline. |
| `assembled_bumper_count` | N71-6171 parts dated by `AssembledDate`. `mic_assembled_bumper_count` uses normalized `Color = MIC`; `painted_assembled_bumper_count` is the non-MIC complement. |
| `trailers_prepared` | Prepared trailers as of the snapshot cutoff. `fuka_trailers_prepared`, `bumper_trailers_prepared`, `fairing_trailers_prepared`, and the internal `other_trailers_prepared` integrity bucket sum to this total. Trailers have no service category. Mixed historical trailers are classified by dominant piece type. |
| `trailers_shipped` | Completed physical departures recorded by nonblank `dbo.DriverLog.TrailerID`, dated by `TimeOut`. The tile compares this departure count with `trailers_prepared`; it does not infer shipping from QPTS preparation state. |
| `racks_shipped` | Distinct nonblank physical `Rack` values on shipped, non-service pieces, grouped by ship date. `fuka_racks_shipped`, `bumper_racks_shipped`, `n71_6164_racks_shipped`, `fairing_racks_shipped`, and the internal `other_racks_shipped` integrity bucket sum to this total. Rack contents use normalized EDI `Description`, with N71-6164 taking display precedence. Mixed racks are counted once under their dominant family with deterministic N71-6164, FUKA, Bumpers, then Fairings tie order. Rack IDs are not included in the snapshot. |
| `pieces_scheduled` / `hours_scheduled` / `paint_hours` | Inputs to the provisional paint-plan composite. |

Every ratio is calculated by the renderer from a saved numerator and denominator. A zero denominator renders as `No Data`, not `0.0%`.

## Derived values

- `average per production day = period total / data_days`
- `parts_loaded = production_parts_loaded + bv_parts_loaded + service_parts_loaded`
- `carts_loaded = production_carts_loaded + bv_carts_loaded + service_carts_loaded`
- `paint_carts = production_paint_carts + bv_paint_carts + service_paint_carts`
- `paint_pieces_processed = production_paint_pieces_processed + bv_paint_pieces_processed + service_paint_pieces_processed`
- Pieces Loaded and Pieces Painted display their full Prd values; retained N71-6164 fields are audit subsets and are not subtracted.
- `staged_carts = production_staged_carts + bv_staged_carts + service_staged_carts`
- `staged_pieces = production_staged_pieces + bv_staged_pieces + service_staged_pieces`
- `complete_assy_sets = mic_complete_assy_sets + painted_complete_assy_sets`
- `assembled_bumper_count = mic_assembled_bumper_count + painted_assembled_bumper_count`
- `0 <= unique_pieces_loaded <= parts_loaded`
- `0 <= unique_pieces_processed <= paint_pieces_processed`
- legacy class splits remain auditable, but the wallboard displays overall exit-day yield because a narrow class can have repaint exits without initial exits on that day
- `trailers_prepared = FUKA + Bumpers + Fairings + internal Other`
- `racks_shipped = fuka_racks_shipped + bumper_racks_shipped + n71_6164_racks_shipped + fairing_racks_shipped + other_racks_shipped`
- `Repaint PPY = ppy_approved / paint_decision_pieces`
- `Repaint FTY = paint_fty_approved / paint_fty_total`
- `Repaint % = paint_fty_repaint_count / paint_fty_total`
- `fuka_paint_fty_repaint_count + bumper_paint_fty_repaint_count + fairing_paint_fty_repaint_count = paint_fty_repaint_count`
- `Finesse % = paint_fty_repair_count / reject_fty_rejected_count`
- `fuka_paint_fty_repair_count + fairing_paint_fty_repair_count + bumper_paint_fty_repair_count = paint_fty_repair_count`
- `Reject PPY = reject_ppy_approved / reject_ppy_total`
- `Reject FTY = reject_fty_approved / reject_fty_total`
- `Receiving FTY = receiving_approved / receiving_total`
- `receiving_total = receiving_bumper_total + receiving_fairing_total`, with the same invariant for approvals
- `Final FTY = final_approved / final_total`
- `final_total = final_fuka_total + final_bumper_total + final_fairing_total`, with the same invariant for approvals
- `Paint plan composite = min(paint pieces / scheduled pieces, 1) × ((paint FTY total - repaint count) / paint FTY total) × min(active paint hours / scheduled hours, 1)`

Every pass and its outcome is attributed to the physical oven-exit date. Item history supplies part/cart lineage for `paint_oven_exited` and `load_line_repaint`, but not the preserved first-pass result. Master Data Table supplies the first EOL disposition; `RepaintCount` controls repaint ordinals; current EDI supplies the latest completed repaint outcome. A pending outcome is not silently classified as good or rejected; its pending count remains visible and a later refresh can restate that oven-exit day. The separate hourly report groups by inspection time and is a reconciliation source rather than the wallboard date grain. Period rows use their summed numerator and denominator.

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

- Reject and repaint count fields are non-negative integers.
- `ppy_approved + ppy_repaint_count + reject_ppy_pending_count = paint_decision_pieces`.
- `paint_fty_approved + paint_fty_repaint_count + reject_fty_pending_count = paint_fty_total`.
- `fuka_paint_fty_repaint_count + bumper_paint_fty_repaint_count + fairing_paint_fty_repaint_count = paint_fty_repaint_count` for every daily and aggregate metric row.
- `fuka_paint_fty_repair_count + fairing_paint_fty_repair_count + bumper_paint_fty_repair_count = paint_fty_repair_count`, and repairs cannot exceed `reject_fty_rejected_count`.
- `reject_ppy_approved + reject_ppy_rejected_count + reject_ppy_pending_count = reject_ppy_total`.
- `reject_fty_approved + reject_fty_rejected_count + reject_fty_pending_count = reject_fty_total`.
- Every displayed rate retains a denominator greater than or equal to its numerator where the outcome classes are exclusive.
- Receiving and final family totals and approvals reconcile exactly to their overall first-decision fields.
- Staged Prd/BV/Svc cart-group and piece splits reconcile exactly to their staged totals.
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
