# API and CSV guide

Base path: `/api/v1`. Interactive schema: `/docs`; JSON contract: `/openapi.json`. Browser access is same-origin. Sign in returns a `csrf_token`; send it as `X-CSRF-Token` with the HttpOnly session cookie for mutations. Errors use non-success HTTP status and a `detail` field; clients must not fabricate successful responses.

| Area | Endpoints |
| --- | --- |
| Identity | POST `/auth/login`, `/auth/register`, `/auth/logout`; GET `/auth/me` |
| Workspace | GET `/public`, `/bootstrap`, `/search`, `/health` |
| Cases | GET `/cases`, `/cases/{id}`; POST `/cases/{id}/transition`, `/assign`, `/inspection`, `/intervention` |
| Reporting | POST/GET `/reports`; GET `/reports/{id}` |
| Evidence | POST `/cases/{id}/evidence` multipart; GET `/evidence/{id}/download`, `/cases/{id}/export` |
| Intelligence | GET `/analytics/{domain}`, `/network`; POST `/network/path` |
| Jobs | POST `/jobs`, `/scenarios`; GET `/jobs/{id}` |
| Imports | GET `/uploads/template`; POST `/uploads/preview`, `/uploads/{id}/commit` |
| Coordination | GET `/associations`; POST `/cases/{id}/link`; PATCH `/associations/{id}` |
| Preferences | PATCH `/settings`; GET `/notifications`; POST `/notifications/{id}/read` |
| Administration | GET `/admin`; PATCH `/admin/users/{id}`, `/admin/config` |

Case mutations include the current integer `version` and a reason or notes. Stale versions return 409. Report and job idempotency keys protect retry submissions and reject reuse with different content. A case cannot be resolved just because an anomaly score declines.

## Interval CSV

Always use the downloadable template, which is authoritative for the implemented schema. Supported analytical domains are water and electricity. Include an existing registered asset/zone, an explicitly offset timestamp, interval duration, quantity, unit, source and quality flag. Missing values remain missing. Water volumes normalize to litres; energy normalizes to kWh.

Interval timestamps are **start-inclusive**, stored in UTC. A row represents the quantity during that interval, not a cumulative meter reading. Ambiguous naive local timestamps, unsupported counters, incompatible units, negative or non-finite quantities, overlapping intervals and duplicate times are rejected or identified explicitly during preview.

Preview persists accepted rows and row-specific errors. Commit is transactional and idempotent. It does not silently convert rejected rows into measurements. Late readings accepted into a nonoverlapping interval require an explicit new analysis job; existing snapshots are preserved in model-run history. Uploaded values are stored alongside normalized values. Uploading a file alone does not imply a new analytical conclusion.

The declared `source` is provenance supplied by the uploader, not independent proof that a sensor measured it. Authorized operators must review it. No exported CSV containing arbitrary report text is produced by the current API; authorized evidence exports are JSON.
# Additional registry and reporting endpoints

`POST /api/v1/admin/zones` and `POST /api/v1/admin/assets` create validated, audited registry records and require administrator access. Duplicate IDs return 409; unknown asset zones return 422. Registration does not create telemetry or analytical conclusions.

`POST /api/v1/reports/{id}/link` accepts `case_id` and a reason from authorized staff, requires matching domain/zone, and records both sides of the change. Distinct reporting accounts are counted separately from report count. `GET /api/v1/impact` returns scoped administrative metrics and explicit interpretation limits.

`POST /api/v1/scenarios/{job_id}/reset` only operates on the caller's successful demo scenario. Cases with reports/evidence are preserved. Baseline data, user submissions and run history are retained.

