# Baseline versions and rollback

Open Model & Sensor Lab → Baseline versions for water or electricity. Operators with department and all-zone access can choose a training window and request a candidate. The durable worker computes its evaluation. An administrator reviews the result and supplies a reason to promote it. A previously active version can be restored through Roll back to this version.

## What is versioned

Each version contains an immutable normalized-input snapshot, SHA-256 checksum, algorithm identifier, training dates, parent baseline, creation reason, actor, excluded interval/case counts and evaluation. The robust seasonal medians and Isolation Forest are deterministically fitted from that frozen snapshot. Routine analysis does not learn new readings into the training baseline. It still recalculates predictions against current stored observations. Model binaries and arbitrary new algorithm code cannot be uploaded through this feature.

Training must contain at least fourteen days and 168 valid intervals per observed asset. Invalid, missing and inactive readings are excluded. Open, non-scenario cases exclude overlapping training intervals, conservatively including their final interval. Cases without an asset apply to their zone; malformed observation dates conservatively exclude that case's asset/zone. Exclusions are checked at preparation, evaluation and promotion. This protects known unresolved periods; it does not establish that all remaining observations are normal.

Evaluation uses observations after both the candidate's and previous baseline's training cutoffs. Both errors use the same valid interval IDs outside known unresolved incident periods. At least 24 evaluation intervals per asset are required. MAE and RMSE measure baseline residual error in interval units; unlabeled data cannot establish anomaly precision, recall or real-world accuracy. Rejected candidates remain visible with the reason. There is no automatic winner or silent promotion.

## Activation and history

The active deployment has an optimistic version counter. Promotion requires an evaluated candidate whose parent is still active, compatible algorithm code, an unchanged training checksum and a human review reason. Rollback permits only previously active versions. All changes record previous/new IDs and the reviewer in the audit trail. Ordinary operators cannot activate or roll back versions.

Promotion selects the candidate's evaluated analytics snapshot. Run analysis from the domain workspace to apply it to current readings and create new findings. Rollback selects the last stored snapshot for the restored version; that snapshot may be older than current readings. Neither action deletes findings or changes case statuses, assignments, field evidence or prior decisions. A baseline change during a running analysis prevents publishing that run's findings; the worker retries against the current deployment.

Forecasts and synthetic scenarios retain their own pipelines. This feature versions the water/electricity consumption detector baseline, not every model in the application. Fixed-seed fitting relies on the installed dependency versions; activating an incompatible algorithm artifact is refused. PostgreSQL and multi-worker concurrency stress remain unverified.

## Upgrade

Migration `0004_baseline_versions` adds version/deployment tables. Startup captures the existing historical training window once and identifies it as a legacy baseline, not a newly evaluated candidate. Existing analytics are retained in a tagged snapshot for rollback. A production database without readings starts with no active baseline and requires candidate evaluation and promotion. Repeated startup preserves the current deployment. No credentials or external connections are required.

API routes: `GET /api/v1/baselines/{domain}`, `POST /api/v1/baselines/{domain}/candidates`, and administrator-only `POST /api/v1/baselines/{domain}/promote` or `/rollback`. Candidate submissions require an idempotency key; activation requires the current deployment version. Mutation requests use the existing session/CSRF checks.
