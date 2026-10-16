# Explainable priority scores

Administrators can edit shared case-priority weights and road-repair weights under Administration → Configuration. Each set must contain every supported factor and total 100 points. Saving uses the platform configuration version, rejects stale edits, and records the reason and before/after settings in the audit log. Cases and queued scenarios keep the configuration version and weights they were created with.

## Shared case score

For each factor, the API computes `normalized value × weight ÷ 100`; available contributions are summed and capped at 100. Defaults are severity 50, persistence 10, exposure 10, evidence diversity 15, open-case age 10, and accepted cross-domain hazard 5. The case Evidence Passport shows the value, weight, contribution and source for every factor. Missing values contribute zero and are explicitly listed; no value is imputed.

- **Severity:** recorded severity maps critical 100, high 75, medium/warning 50, low 25; unknown values map to 40. This is also shown separately as hazard urgency.
- **Persistence:** recorded finding start/end duration, linearly normalized to 100 at 72 hours. Missing or invalid intervals remain missing.
- **Exposure:** recorded daily exposure is normalized to 100 at 10,000 people/day; otherwise a recorded percentage is used directly, capped at 100. No exposure estimate is inferred.
- **Evidence diversity:** distinct recorded source channels (analytical, scenario, citizen report, inspector record, photographic evidence). Each additional channel after the first adds one third of the scale, capped at 100. Multiple reports from the same account do not add channels; unique reporter count is separately shown.
- **Open-case age:** hours open relative to twice the case's recorded administrative review target, capped at 100. Resolved and closed cases stop accruing age.
- **Cross-domain hazard:** only an accepted link between different domains and two high/critical-severity cases qualifies. A shared recorded asset scores 100; a shared service zone scores 50; otherwise it scores zero. Related-case details are considered only when both cases are visible to the requesting user.

Hazard urgency and evidence quality are separate fields. Active high-severity reports remain in the human review queue before telemetry corroboration. Evidence diversity and reporter counts help reviewers understand the available sources; they do not prove a physical fault, a causal relationship, or an accident probability. The score is a deterministic triage aid, not an automated decision to repair or close a case.

## Road repair score

Road inspection uses five configurable 100-point factors: recorded damage severity, affected area, daily public exposure, repeat history, and vulnerable-location context. The analytics pipeline normalizes available inputs against documented caps before applying the weights. Missing inputs contribute zero and are reported. Unverified reports initiate inspection; they do not become confirmed damage measurements. A scenario freezes the road-weight map and configuration version when it is queued.

## Reproducibility

New reported cases snapshot the current shared case weights at creation. Analysis findings snapshot the configuration used for their run; scenario jobs freeze settings when queued. Changing admin weights affects future work and does not rewrite an existing case's configured factors. Evidence records may grow as the investigation proceeds, so the displayed contribution breakdown reflects the current authorized evidence against that frozen weight version. The JSON export includes the current breakdown and configuration metadata.
