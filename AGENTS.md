# Operations KPI Rollup project rules

- The authoritative repository is `ChrisKolodziejCLC/Operations-KPI-Rollup`.
- Keep this project separate from FlowForge. Reuse infrastructure patterns, not FlowForge services, ports, credentials, or release directories.
- Do not change production SQL objects or send report email without Chris's explicit approval for that exact action.
- Version every approved SQL-object change as a pre-hash-gated migration, preview it inside a rolled-back transaction, and commit its reverse migration before applying it.
- Treat generated report inputs as immutable snapshots. A historical report must be reproducible from its saved snapshot even when QPTS current-state columns later change.
- Every rate must retain its numerator and denominator. Period averages use represented production days, not calendar days, unless the label explicitly says calendar-day average.
- Do not label the legacy paint composite as standard OEE. It is a provisional proxy until availability, performance, and quality definitions are approved.
- Never commit credentials, connection strings containing secrets, raw rejection-detail exports, or employee-level data fixtures.
- GP-AI01 hosting uses a separate `operations-kpi-rollup` service, release root, state root, port 5193, SQL identity, and encrypted systemd credentials. Never reuse FlowForge services, ports, credentials, or directories.
- The on-demand service may execute only the approved rollup procedure. The wallboard snapshot fetches result sets 0, 2, 3, 4, 5, 9, 12, 14, and 15 only (never result set 8 or the raw rejection and high-repaint detail); the drill-down snapshot fetches result sets 16–20 only.
- Chris approved unrestricted viewing of everything on the rollup for now (2026-11-18, 17:01–17:08 EST). The painter, repaint, and Finesse drill-down is a standard view at `/drilldown/` on the GP-AI01 wallboard because the information is already published to the paint department. Keep the pilot banner visible. When restrictions are wanted later, use Active Directory groups like the other CLC applications (for example the scheduling app), not a separate Entra proxy.
- The aggregate `/api/snapshot` contract stays free of names, part rows, cart rows, trailer rows, and DriverLog rows. The drill-down has its own snapshot, routes, and state directory and can be switched off with `KPI_DRILLDOWN_ENABLED=0`.
- Chris offered (2026-11-18, 17:12 EST) to show employee ID numbers instead of employee names. That needs a hash-gated procedure change and his explicit approval of that exact action before it is applied.
