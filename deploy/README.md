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
- Employee and part detail: never requested, retained, or served by the public process
- Refresh ownership: one service-side current-day producer; wallboards consume cached snapshots only

The restricted drill-down is a separate security and process boundary:

- Service: `operations-kpi-restricted.service`
- Backend listener: loopback-only `127.0.0.1:5194`; never a LAN listener
- State: `/var/lib/operations-kpi-restricted/snapshots`, mode `0700`, files mode `0600`
- Authorization: authenticated proxy plus exact Entra object-ID allowlist loaded from an encrypted systemd credential
- SQL contract: explicit `@IncludeRestrictedDetail = 1`, separately pinned procedure hash, and result sets 16–20 only
- Publication: dedicated HTTPS origin `https://kpi.eliteenterprisesinc.com:5195`, with a dedicated Entra application and Chris Kolodziej as the initial exact-ID audience

See `restricted-auth-proxy-contract.md`. The public and restricted services must not share routes, snapshots, browser assets, or authorization state.

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

For the restricted service, additionally verify the audience approval, authenticated-proxy boundary, claim-derived header stripping/replacement, exact-ID denial and allow behavior, loopback-only listener, separate state permissions, no-store headers, synthetic browser render, and absence of restricted fields from the public API and process.

Any approved procedure change must be committed as a hash-gated migration, previewed in a rolled-back SQL transaction, and paired with a reviewed reverse migration before it is applied. Update the pinned procedure hash in both source and the deployed unit only after the candidate hash is recorded.

The live extractor enforces every aggregate invariant before saving a snapshot: Prd/BV/Svc load, paint, and staged totals; first-pass outcome totals; first-Receiving Finesse outcomes and repair families; inspection families; prepared-trailer families; and shipped-rack families. Any mismatch blocks refresh rather than publishing a plausible-looking but internally inconsistent wallboard.

## Rollback

- If an earlier release exists, repoint `current` to it and restart the service.
- If the release depends on a procedure migration, run its reviewed reverse migration and update the unit to the recorded rollback hash before permitting refresh.
- Stop and disable `operations-kpi-restricted-proxy.service` and `operations-kpi-restricted.service`, then remove only the restricted DNS/proxy route before reversing the restricted procedure migration.
- For the first pilot release, stop and disable `operations-kpi-rollup.service`; remove only the `current` symlink and leave the versioned release, encrypted credentials, and snapshots intact for evidence.
- Rollback never writes QPTS business data.

## Stop conditions

- Source commit is not verified on Chris's repository.
- Port 5193 is no longer free.
- TCP 5194 is not loopback-only, the authenticated proxy is not ready, or the access audience is unapproved.
- SQL credential identity/server/database validation fails.
- Procedure definition hash differs from the reviewed contract without approval.
- Refresh returns part-level detail, unexpected result-set shape, or a future date.
- Restricted identity headers can be supplied directly by a client, an unapproved object ID is allowed, or a restricted field appears in the public process/API.
- Any existing GP-AI01 protected service regresses.
