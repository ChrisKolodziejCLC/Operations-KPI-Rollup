# Operations KPI Rollup project rules

- The authoritative repository is `ChrisKolodziejCLC/Operations-KPI-Rollup`.
- Keep this project separate from FlowForge. Reuse infrastructure patterns, not FlowForge services, ports, credentials, or release directories.
- Do not change production SQL objects or send report email without Chris's explicit approval for that exact action.
- Treat generated report inputs as immutable snapshots. A historical report must be reproducible from its saved snapshot even when QPTS current-state columns later change.
- Every rate must retain its numerator and denominator. Period averages use represented production days, not calendar days, unless the label explicitly says calendar-day average.
- Do not label the legacy paint composite as standard OEE. It is a provisional proxy until availability, performance, and quality definitions are approved.
- Never commit credentials, connection strings containing secrets, raw rejection-detail exports, or employee-level data fixtures.
- GP-AI01 hosting uses a separate `operations-kpi-rollup` service, release root, state root, port 5193, SQL identity, and encrypted systemd credentials. Never reuse FlowForge services, ports, credentials, or directories.
- The on-demand service may execute only the approved rollup procedure and must never fetch its part-level rejection or high-repaint result sets.
- Keep employee detail disabled and the pilot banner visible until authentication and leadership visibility rules are approved.
