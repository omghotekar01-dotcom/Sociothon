# CivicSignal 360 — Four-role workflow handoff, 17 Oct 2026

This document describes implemented source and concrete acceptance evidence needed. It does **not** claim that every future-scope module or public deployment is production-complete.

## Four roles, full route

| Role | Entry | Persistent actions | Access boundary |
| --- | --- | --- | --- |
| Citizen | Register / log in, Start → Add a case | Zone, title, category, description, location; receipt; upload PNG/JPEG privately after receipt; tracking and status | Own reports and own uploaded photos only |
| Administrator | Administration → Users | Create inspector/operator accounts with initial password, departments/zones, record electrical qualification if externally verified, activate/deactivate accounts, manage registry, parameters and review audit | Administrator-only service routes; role edits revoke sessions |
| Operator | Citizen submissions / Incident Explorer | Review original citizen description and photos, move to investigation, choose eligible inspector by case zone/domain, add supporting inspectors, review field records and record closure decision | Scoped cases and eligible staff; backend validates both |
| Inspector | Field workspace | Assigned cases only; view citizen report/photos; add structured inspection, intervention and follow-up evidence; monitoring handoff | Cannot self-assign, inspect unrelated cases, or close independently |

## Dynamic data contract
1. POST /api/v1/reports persists Report and linked Case with one idempotency key.
2. GET /api/v1/reports returns role-scoped persisted submissions. Staff UI refreshes every 45s and offers a manual refresh.
3. GET /api/v1/cases/{id} only after case_access returns the underlying citizen report metadata, original descriptions/locations, private evidence URLs, team and audit records.
4. Citizen uploads a photo to the same case. The image is sanitized and stored outside web assets, and is downloaded only through the authorized evidence endpoint.
5. POST /api/v1/admin/staff hashes the new user's initial password, saves domains/zones, audits nonsecret metadata and returns no password. Admin permission updates can suspend that account.
6. GET /api/v1/bootstrap supplies a scoped active inspector directory. Client filters it again for the exact case zone/domain; electricity requires an administrator-recorded qualification.
7. POST /api/v1/cases/{id}/assign still enforces case version, inspector active status, domain/zone and qualification.
8. Assigned inspector sees the case in /inspector, and related updates and evidence persist through restart.

## Important behavior
- A photograph is attached **after** the report is committed, using the receipt page or My Reports tracking. This prevents anonymous orphan attachments. A finished report and its photo are connected by case ID.
- The operator may see an uploaded image after it is synchronized with the server. It does not rely on browser memory or fake photos.
- Only authorized staff can open detailed report information; report text is not added to a public /cases payload.
- No automatic assignment, safety certification, proof of repair or municipal affiliation is implied.
- Role changes revoke existing sessions; staff must sign in again.

## Acceptance still required beyond this targeted code change
- CI full Python suite, TS typecheck, ESLint and production build on the final head commit.
- Browser smoke across admin creation → operator assignment → new inspector login → inspection → monitoring → human closure, including a citizen image upload and another-user forbidden download.
- Mobile 390px, 768px and 1440px visual QA of admin staff form, inbox, image gallery and action drawer.
- Complete actual domain-specific functional tests, real field data integration, regulatory/privacy/security review, backup restoration on target deployment, accessibility audit and operating environment monitoring.
- For a demonstration, use four separate browser profiles to keep credentials and sessions separate; show data recorded by one role visible to the next after refresh.
