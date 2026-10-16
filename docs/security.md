# Security and permissions

| Role | Authorized actions |
| --- | --- |
| Citizen | Register as citizen only, submit reports, see own reports/tracking, privacy-safe public metadata |
| Operator | Review cases in assigned departments/zones, assign inspectors, manage investigation and human closure, run permitted analytics |
| Inspector | View assigned cases, record inspection/intervention/follow-up evidence; cannot independently resolve cases |
| Administrator | Manage permissions/configuration and inspect authorized audits; exceptional actions require reasons |

The server enforces authorization; hiding a control is not an access boundary. Passwords use salted scrypt. Opaque sessions are stored by token hash, expire after eight hours, and are revoked on logout or permission changes. Authenticated mutations require a session-specific CSRF header. Cookies are HttpOnly and SameSite=Strict; use `COOKIE_SECURE=true` only with HTTPS. Local HTTP deliberately uses non-Secure cookies.

Demo credentials are for isolated local demonstration only. Run with `CIVIC_DEMO_MODE=false`, unique administrator credentials, TLS, isolated storage, and reviewed deployment configuration before considering any non-demo installation. No public release is claimed here. Do not reuse a demo database in non-demo mode.

Images are stored outside public web assets and served only through authorized endpoints. Uploaded active HTML/SVG is rejected; supported raster content is decoded and rewritten. File checks, session checks and rate limits require the executed verification evidence in `docs/verification.md`; this document is not an audit certificate.

Public views omit private report details and meter histories. Citizen free text remains untrusted data. Analytical explanations do not execute instructions found in reports. This system never controls real devices or authorizes hazardous repairs.

Remaining deployment work includes external penetration testing, TLS/reverse-proxy configuration, distributed rate limiting, managed secret rotation, operational monitoring and a real organizational permission policy. None is implied by the local prototype.
