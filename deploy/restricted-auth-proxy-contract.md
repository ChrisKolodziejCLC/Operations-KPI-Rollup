# Restricted KPI authenticated-proxy contract

> **Superseded on 2026-11-18.** Chris Kolodziej directed that the drill-down be an unrestricted standard view on the GP-AI01 wallboard (`/drilldown/`). This contract is kept only as the design of the retired identity-gated surface. If restrictions are wanted later, prefer Active Directory group checks like the other CLC applications over this Entra proxy; tenant user consent is disabled, so any new Entra application would also need administrator consent.

Approved production origin: `https://kpi.eliteenterprisesinc.com:5195`.

Initial audience: Chris Kolodziej only, exact Entra object ID `033cd244-8162-4389-a2b3-4f83d6c78bc0` and UPN `ChrisKolodziej@creativeliquidcoatings.com`. The Teams/OpenClaw requester ID is a different identifier and must never be substituted for the Entra object ID.

## Network boundary

- Publish the restricted drill-down only at the root of its dedicated HTTPS origin.
- The authenticated proxy is the only caller of `127.0.0.1:5194`; TCP 5194 must never be exposed on a LAN interface or firewall rule.
- Keep the public wallboard on TCP 5193 unchanged. Do not route restricted endpoints through its process.
- Backend health `/healthz` is intentionally minimal. All pages, assets, health detail, snapshots, and refresh endpoints require identity.

## Entra authentication and authorization

- Use the tenant-specific Microsoft authorization and token endpoints, authorization code with PKCE, state correlation, and certificate client authentication. The application does not trust or locally authorize from an unverified ID-token payload.
- Resolve the signed-in principal through Microsoft Graph `/me` using the access token accepted by Graph, then enforce the exact Entra object-ID and email pair.
- Remove every inbound `X-CLC-*`, Authorization, and Cookie header before proxying.
- Set `X-CLC-Object-Id`, `X-CLC-User`, and `X-CLC-Name` only from the Graph-validated profile.
- The backend independently authorizes only exact object IDs loaded from the encrypted `operations-kpi-restricted-allowed-object-ids` systemd credential. Display names, email addresses, groups, and client headers are not sufficient.
- A denied or missing identity must never reach the backend as an authenticated request.

## Header and data handling

- Forward the original method and body only after authentication, with a bounded request size and normal proxy timeouts.
- Preserve backend `Cache-Control: no-store, private` and add HSTS and anti-framing headers at the proxy.
- Do not cache or index restricted responses.
- Do not log response bodies, part identifiers, part numbers, colors, employee names, authorization tokens, cookies, or identity headers. Access logs may retain only timestamp, outcome, bounded route, and a non-reversible request correlation ID.
- Use a separate signed session-cookie namespace with Secure, HttpOnly, and SameSite=Lax.

## Acceptance proof

Before production use, capture: unauthenticated denial; wrong-object-ID denial; exact-object-ID allow; spoofed-header denial; direct-LAN TCP 5194 failure; TLS validation; tenant-specific auth redirect; no-store/security headers; and a browser render using synthetic data. Never use live restricted rows in screenshots or shared change evidence.
