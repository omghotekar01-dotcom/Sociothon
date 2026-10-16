# Model and rule notes

## Data and interpretation

The demonstration dataset has 8,064 hourly interval readings across three zones and two metered domains over 56 days, with seed 360 and a fixed observation clock of 13 October 2026, 00:00 UTC. Readings represent interval quantities, not cumulative counters. Missing values remain missing. Water is normalized to litres and energy to kWh. Separate synthetic labels support evaluation; these are not operational inspection evidence.

The benchmark artifact is `artifacts/verification/benchmark.json`. Its 11.9147-second runtime is a measurement on this Windows machine, not a service-level guarantee. Existing database snapshots may precede code changes; explicitly rerun analysis to obtain current model output without deleting cases or readings.

## Meter anomaly detection

A seasonal hour-of-week median and median absolute deviation baseline uses historical training data. A relative threshold floor and minimum scale prevent unstable thresholds around near-zero demand. Three consecutive flagged intervals establish an event. Missing observations do not become zero demand or confirmed outages. Isolation Forest provides a separate anomaly score; neither score is a fault probability. Legitimate operating context and sensor quality must be reviewed before intervention.

Evaluation uses a separate synthetic seed, 37031, with 42 training days, seven reserved validation days and seven held-out days. Thresholds are predefined, not tuned on the held-out data. Validation seed 7301 is recorded for future experiments; no validation tuning result is claimed.

| Domain | Method | Held-out precision | Recall | F1 |
| --- | --- | ---: | ---: | ---: |
| Water | Robust baseline | 1.00000 | 1.00000 | 1.00000 |
| Water | Isolation Forest | 0.48571 | 1.00000 | 0.65385 |
| Electricity | Robust baseline | 1.00000 | 1.00000 | 1.00000 |
| Electricity | Isolation Forest | 0.42424 | 1.00000 | 0.59574 |

These results come from deliberately generated synthetic patterns. Perfect robust-baseline metrics on this dataset do not establish real-world accuracy. The Isolation Forest false positives are retained and reported.

## Forecasting and physical accounting

Forecasts require one meter with sufficient hourly history. The baseline predicts the corresponding hour from the previous week. Interval calibration and chronological holdout evaluation are separate; actual MAE, RMSE and interval coverage are returned with output. A histogram gradient boosting comparison requires sufficient history. Forecast bounds are empirical and do not guarantee future coverage.

Tank and drainage simulations enforce bounded storage and explicit inflow, outflow, spill and unmet-demand accounting. They are simplified storage models, not hydraulic network or flood models. Depletion time is unavailable when net depletion is nonpositive. Missing rainfall produces an unavailable screening result.

## Other domains

- Roads use transparent severity, extent, exposure, recurrence and vulnerability components with a greedy budget plan; no optimal allocation or image-based defect dimensions are claimed.
- Waste uses fill history, capacity limits and a nearest-neighbour route heuristic. Distances are schematic straight-line distances. Unserviceable stops are explicitly excluded.
- Streetlights compare local operating schedules with persisted observation sequences; missing/stale telemetry is distinct from a failed lamp. Fault location and wiring causes are not inferred.
- General infrastructure uses reported evidence and audited work orders without a predictive AI claim.
- Network paths represent directed graph reachability and configured edge closures, not pressure or flow calculations.
- Cross-domain proximity and time relationships are investigation leads. They do not establish a common physical cause.

Follow-up comparisons require comparable hours and sufficient coverage. Estimated excess is not verified savings. Closure always requires an authorized human and recorded follow-up evidence. Model-version rollback and a full retraining approval workflow are not implemented.
