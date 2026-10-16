# Water operations and field evidence

The **Water → Operations** tab provides supply-window review and zone accounting using recorded interval quantities. It is additional investigation context; it does not change the existing anomaly detector, automatically open or close cases, control supply, or certify leakage.

## Configure a zone

1. Sign in as an administrator and open Water → Operations.
2. Choose an authorized service zone. Expand its configuration.
3. Enter recurring supply windows and legitimate recurring exceptions (for example tank refilling), with a description, weekdays and local start/end times. Choose Asia/Kolkata or UTC explicitly. Overnight windows extend into the following day; use 00:00–24:00 for a whole day.
4. Set the outside-window review threshold in litres/hour. This is an operational review threshold, not a calibrated fault probability.
5. For accounting, choose inlet, outlet and consumption meters and record known parent/child relationships. Each meter can have only one role. Cycles and parent/child double counting on the same accounting side are rejected.
6. Confirm that the selected meters cover the intended accounting boundary only when you have checked it. Enter the reason and assumptions, then save. The server checks administrator permission, zone scope and configuration version and records an audit event. A stale edit must be reloaded before saving.

Operators can review an authorized configuration but cannot edit it. Inspectors use their assigned case evidence workflows; they do not receive the zone operations workspace.

## Review observations

Choose a timezone-aware period of at most 31 days. Review inputs use the displayed workspace timezone preference and convert boundaries to UTC; recurring supply windows use the separately configured schedule timezone. Schedule review classifies recorded intervals as inside a supplied window, outside and above the review threshold, below threshold, straddling a boundary, invalid, or not configured. Straddling intervals are not artificially split into invented measurements. Missing/invalid readings are not replaced with zero.

Zone balance is:

`inlet − outlet − metered consumption − storage change − authorized unmetered volume`

All quantities are litres for the same selected period. A positive storage change means water retained in storage; a negative value means release. Storage change and authorized unmetered use are explicit operator inputs: leave them blank when unknown. If entered, include the source and assumptions. They are not independently verified by the system. A calculated balance requires a confirmed boundary and complete, valid, non-overlapping interval coverage for every selected meter. Otherwise it returns **Unavailable** with reasons. A residual is unexplained water accounting, not a confirmed leak, illegal use or proven saving.

The screen displays the first 100 schedule rows and total status counts. Export the complete JSON review for the source observations, inputs and configuration snapshot. Reviews accept at most 10,000 input observations, including the one-day lookback needed for overlapping intervals; choose a shorter window when this limit is exceeded. Choose current configuration or recorded effective schedules explicitly. Current configuration does not prove the schedule in force during a historical incident. Meter hierarchy is scoped to this operations configuration. The original Impact-page tool remains single-meter; Water Operations now also provides a comparison across a selected meter group.

## Save a reviewed snapshot to a case

1. As an authorized operator or administrator, run and inspect the review.
2. Under **Save to an Evidence Passport**, choose an open water case in the same service zone and explain why this review is relevant.
3. Select **Attach reviewed snapshot**. The server recomputes the analysis and compares its SHA-256 fingerprint with the result you reviewed. Changed configuration, changed readings or a stale case version cause a conflict, requiring a refreshed review or case selection.
4. Open the saved Evidence Passport. It includes the exact source observations, configuration, inputs, balance, schedule review, fingerprint, author and reason. Export the saved JSON even after the live configuration changes. The water evidence-gap assistant cites this record as operating context.

If confirmation is lost, choose **Retry exact attachment**. The original request identifier returns the saved record without creating another evidence or audit entry, even if the live configuration has changed. By default the pending request stays in page memory. Explicitly enable **Retain this pending attachment on this device** to retain its exact inputs, case/version, reason, accounting note, fingerprint and submission identifier across reload. Original meter readings and the full case are not stored on the device. Recovery is account/zone-scoped and always manual. Open Water Operations in the original zone to recover it without rerunning analysis. Successful confirmation removes the local reference. Corrupt references are retained until explicitly removed; removing a local reference never deletes evidence already on the server. Storage failures are visible and require keeping the page open. A stale unsaved request still requires a new review; recovery does not bypass permission, configuration or case checks. A saved review is analytical context, not a field inspection, independently verified supply history or proof of leakage. It does not change the case status or satisfy the inspection/intervention/follow-up requirements for resolution. Closed/resolved cases must first be reopened through the normal human review workflow. Existing evidence JSON storage is reused; no new migration is required.

## Historical supply schedules

Expand **Historical supply schedules**. An administrator can record the saved schedule for a bounded effective period, with a source reference and reason. Inputs use the displayed timezone and are stored as UTC, start inclusive and end exclusive. Overlapping active periods are rejected. History records freeze the saved schedule timezone, weekly windows, recurring exceptions, threshold and configuration version; later edits do not rewrite them. To correct a record, revoke it with a reason and then add its replacement. The original record and correction remain retained and audited. Up to 200 history records are supported per zone; effective periods are bounded to ten years.

Select **Recorded effective schedules** before reviewing observations. Each interval must fit wholly inside one active historical period. Gaps return `history_missing`; an interval crossing a period boundary returns `history_boundary`. Neither falls back to today's schedule or invents a volume split. History-version changes reject stale reviews and attachments. Saved Evidence Passports retain the exact history snapshot even after a correction. These records document an administrator's source-backed assertion, not independently verified actual supply. Historical schedule selection does not change the current meter accounting boundary or user-entered storage quantities.

## Compare multiple meters

Expand **Compare multiple meters** in Water Operations. The administrator must first configure and confirm the meter boundary. Select meters in one accounting role (inlets, outlets or consumption); mixed roles, duplicates and configured parent/child double counting are rejected. Confirm that selected meters represent separate volumes and document supply, demand and storage assumptions.

Use equal, ordered, non-overlapping windows of at least 24 hours and at most 31 days, aligned to the same weekday/time an exact number of weeks apart. Every meter needs complete valid interval coverage in both windows. Gaps, overlaps, invalid values, unmatched periods or intervals crossing the boundary leave aggregate comparison unavailable. Valid units are converted to litres. The observed reduction is `before total − after total`; a negative result is an increase. It is not verified savings or a closure decision. Selection is limited to 50 meters and 10,000 source rows per window. Export retains exact inputs, original rows, current configuration, recorded schedule history and a fingerprint. It does not automatically attach a multi-meter comparison to a case.

## Domain-specific field observations

In an assigned case, open Evidence Passport → Take action. Record the domain fields, checklist and narrative, then explicitly submit an inspection, intervention or follow-up. Unknown measurements stay blank. Fields include water volume/duration/method, manually measured road dimensions, drain observations, waste collection, lamp state, authorized electrical observations, and general asset condition. Measured water volume requires duration and method. No dimensions are inferred from photos.

The API rejects fields from another domain, invalid numeric values and unsupported inputs. Submitted observations stay with the evidence record and appear in Evidence Passport and its JSON export. Consent-based field drafts retain observations and the exact pending submission for safe retry. The additive `0008_field_observations` migration preserves earlier evidence with an empty observations object.

The water Evidence assistant adds an evidence-gap table for quantities, supply context, inspection and follow-up after the latest intervention. It cites actual source IDs and identifies missing support; it does not invent measurements or decide closure.

## API and verification

- `GET /api/v1/water/zones/{zone_id}/operations`
- `PUT /api/v1/water/zones/{zone_id}/operations` (administrator, versioned)
- `POST /api/v1/water/zones/{zone_id}/review` (authorized operator/administrator)
- `POST /api/v1/water/zones/{zone_id}/cases/{case_id}/reviews` (scoped operator/administrator, versioned and idempotent)
- `POST /api/v1/water/zones/{zone_id}/schedule-history` (administrator, versioned, duplicate-safe)
- `POST /api/v1/water/zones/{zone_id}/schedule-history/{record_id}/revoke` (administrator, audited correction)
- `POST /api/v1/water/zones/{zone_id}/impact-comparison` (authorized operator/administrator)
- `GET /api/v1/cases/{case_id}/field-schema` (authorized case access)

See `tests/test_water_operations.py`, `tests/test_water_review_evidence.py`, `tests/test_water_history.py`, `tests/test_field_observations.py`, `scripts/water-investigation.test.mjs`, `scripts/water-review-evidence-check.mjs`, `scripts/water-review-recovery.test.mjs`, `scripts/water-history-check.mjs` and `scripts/completion-browser-check.mjs`. Browser acceptance uses an isolated demo database and labelled synthetic reports; it is not municipal field validation.
