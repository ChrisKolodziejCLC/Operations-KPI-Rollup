# GP-AI01 deployment contract

## Pilot boundary

- Host: `GP-AI01`
- Install root: `/opt/clc/operations-kpi-rollup`
- Release layout: `releases/<commit>` with an atomic `current` symlink
- Service: `operations-kpi-rollup.service`
- Listener: TCP 5193 (separate from every existing FlowForge/QPTS service)
- State: `/var/lib/operations-kpi-rollup/snapshots`, mode `0700`
- Runtime identity: dedicated unprivileged `operations-kpi` user and group
- SQL identity: dedicated `OperationsKpiRollup_RO` SQL login with `CONNECT`, object-scoped `VIEW DEFINITION`, and `EXECUTE` only on the recovered rollup procedure
- Outbound mail: none
- QPTS writes: none
- Aggregate snapshot (`/api/snapshot`): no employee, part, cart, trailer, or DriverLog rows. Drill-down detail is served by the same process from its own snapshot (see the standard drill-down below)
- Refresh ownership: one service-side current-day producer; wallboards consume cached snapshots only

The drill-down (painter, repaint, and Finesse detail) is a standard view in the same wallboard process, effective release 0.36.0. Chris approved unrestricted viewing on 2026-11-18 because the information is already published to the paint department:

- Routes: `/drilldown/`, `/drilldown/app.js`, `/drilldown/styles.css`, `/api/drilldown/health`, `/api/drilldown/snapshot`, and `POST /api/drilldown/refresh` (same required action header and private-network source gate as `/api/refresh`)
- State: `/var/lib/operations-kpi-rollup/snapshots/drilldown`, directory mode `0700`, files mode `0600`; never mixed into the aggregate snapshot files
- SQL contract: the wallboard's pinned procedure hash (`KPI_SQL_PROCEDURE_HASH`) and read-only credential, explicit `@IncludeRestrictedDetail = 1`, and result sets 16–20 only
- Authorization: none for now. When restrictions are wanted, add Active Directory group checks like the other CLC applications rather than reviving the Entra proxy
- Controls: `KPI_DRILLDOWN_ENABLED=0` removes every drill-down route without a redeploy; `KPI_DRILLDOWN_INITIAL_DELAY_SECONDS` (default 20) staggers the first drill-down query behind the wallboard's startup refresh; the drill-down refreshes the current day every ten minutes. A drill-down startup failure disables only the drill-down; the aggregate wallboard keeps running

The earlier identity-gated surface (`operations-kpi-restricted.service` on loopback TCP 5194 and `operations-kpi-restricted-proxy.service` on HTTPS TCP 5195 with a dedicated Entra application) is superseded. It was never usable by ordinary users because the tenant blocks user consent and no administrator consent was granted. See `restricted-auth-proxy-contract.md` for the retained design.

The initial LAN pilot is a metric-validation surface, not yet the final leadership wallboard. Before broad promotion it needs an approved DNS/TLS/authentication route and metric-owner signoff.

## Protected credential

The public service expects one encrypted systemd credential:

1. `operations-kpi-qpts-ro` — a SQL Server connection string for the exact approved server, database, and execute-only login.

The restricted service loads that same execute-only SQL credential plus:

2. `operations-kpi-restricted-allowed-object-ids` — one approved Entra object ID per line. This credential is the backend authorization list and must never be committed or placed in a unit `Environment=` line.

Never place its value in Git, a unit `Environment=` line, a change record, command output, or chat. Browser refresh requests are limited by private-network origin, a required action header, strict date bounds, per-date snapshot reuse, a global execution lock, freshness deduplication, and rate limiting; the SQL identity remains execute-only and the approved procedure hash remains pinned. The service owns the ten-minute current-day refresh schedule. Wallboards poll the current-day cache and never initiate SQL.

## Release procedure

1. Confirm the deployment commit is visible in `ChrisKolodziejCLC/Operations-KPI-Rollup`.
2. Capture current GP-AI01 listeners, memory/disk headroom, and relevant service state.
3. Create the unprivileged service account and release/state roots if absent.
4. Copy a manifest-backed archive to a new `releases/<commit>` directory.
5. Verify every release hash before changing `current`.
6. Install the reviewed unit and encrypted SQL credential.
7. Point `current` at the new release, reload systemd, enable, and start the service.
8. Verify unit hardening, port ownership, `/api/health`, one service-owned private-LAN bounded read-only refresh, immutable snapshot creation, a same-day cache hit, a historical cache hit, and wallboard GET-only polling.
9. Recheck all pre-existing GP-AI01 protected services and listener ownership.

For the standard drill-down (release 0.36.0), additionally verify that the drill-down routes return 200, the aggregate `/api/snapshot` response and its historical core hash are unchanged, no drill-down field appears in the aggregate API or browser assets, the drill-down state directory is mode `0700` with files mode `0600`, the first drill-down refresh is staggered behind the wallboard refresh, live painter rows are present, the wallboard header link renders, and a browser render shows zero page and console errors.

For the retired restricted service (legacy), additionally verify the audience approval, authenticated-proxy boundary, claim-derived header stripping/replacement, exact-ID denial and allow behavior, loopback-only listener, separate state permissions, no-store headers, synthetic browser render, and absence of restricted fields from the public API and process.

Any approved procedure change must be committed as a hash-gated migration, previewed in a rolled-back SQL transaction, and paired with a reviewed reverse migration before it is applied. Update the pinned procedure hash in both source and the deployed unit only after the candidate hash is recorded.

The live extractor enforces every aggregate invariant before saving a snapshot: Prd/BV/Svc load, paint, and staged totals; first-pass outcome totals; first-Receiving Finesse outcomes and repair families; inspection families; prepared-trailer families; and shipped-rack families. Any mismatch blocks refresh rather than publishing a plausible-looking but internally inconsistent wallboard.

## Rollback

- If an earlier release exists, repoint `current` to it and restart the service. Release 0.36.0 changes no SQL object: repoint `current` to the previous release and restart `operations-kpi-rollup.service`, or set `KPI_DRILLDOWN_ENABLED=0` through a systemd drop-in to switch only the drill-down off.
- If the release depends on a procedure migration, run its reviewed reverse migration and update the unit to the recorded rollback hash before permitting refresh.
- Stop and disable `operations-kpi-restricted-proxy.service` and `operations-kpi-restricted.service`, then remove only the restricted DNS/proxy route before reversing the restricted procedure migration.
- For the first pilot release, stop and disable `operations-kpi-rollup.service`; remove only the `current` symlink and leave the versioned release, encrypted credentials, and snapshots intact for evidence.
- Rollback never writes QPTS business data.

## Stop conditions

- Source commit is not verified on Chris's repository.
- Port 5193 is no longer free.
- While the legacy restricted surface remains installed, TCP 5194 is not loopback-only or the authenticated proxy is not ready.
- SQL credential identity/server/database validation fails.
- Procedure definition hash differs from the reviewed contract without approval.
- Refresh returns part-level detail, unexpected result-set shape, or a future date.
- A drill-down field (painter, part, cart, trailer, or DriverLog row) appears in the aggregate `/api/snapshot` response or its browser assets.
- Any existing GP-AI01 protected service regresses.
