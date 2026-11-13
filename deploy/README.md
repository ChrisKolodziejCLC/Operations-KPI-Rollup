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
- Employee detail: disabled by default

The initial LAN pilot is a metric-validation surface, not yet the final leadership wallboard. Before broad promotion it needs an approved DNS/TLS/authentication route and metric-owner signoff.

## Protected credentials

The service expects two encrypted systemd credentials:

1. `operations-kpi-qpts-ro` — a SQL Server connection string for the exact approved server, database, and execute-only login.
2. `operations-kpi-refresh-key` — a random key required only for a user-triggered database refresh.

Never place either value in Git, a unit `Environment=` line, a change record, command output, or chat. The browser keeps the refresh key in `sessionStorage`, not persistent local storage.

## Release procedure

1. Confirm the deployment commit is visible in `ChrisKolodziejCLC/Operations-KPI-Rollup`.
2. Capture current GP-AI01 listeners, memory/disk headroom, and relevant service state.
3. Create the unprivileged service account and release/state roots if absent.
4. Copy a manifest-backed archive to a new `releases/<commit>` directory.
5. Verify every release hash before changing `current`.
6. Install the reviewed unit and encrypted credentials.
7. Point `current` at the new release, reload systemd, enable, and start the service.
8. Verify unit hardening, port ownership, `/api/health`, cached snapshot state, one authenticated read-only refresh, and immutable snapshot creation.
9. Recheck all pre-existing GP-AI01 protected services and listener ownership.

## Rollback

- If an earlier release exists, repoint `current` to it and restart the service.
- For the first pilot release, stop and disable `operations-kpi-rollup.service`; remove only the `current` symlink and leave the versioned release, encrypted credentials, and snapshots intact for evidence.
- Rollback never alters either legacy stored procedure or QPTS data.

## Stop conditions

- Source commit is not verified on Chris's repository.
- Port 5193 is no longer free.
- SQL credential identity/server/database validation fails.
- Procedure definition hash differs from the reviewed contract without approval.
- Refresh returns part-level detail, unexpected result-set shape, or a future date.
- Any existing GP-AI01 protected service regresses.
