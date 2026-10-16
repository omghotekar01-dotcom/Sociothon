# Local operations

## Start and stop

From the repository, run `.venv\Scripts\python.exe scripts/run.py`. The launcher migrates and seeds before starting the API and worker. The default address is http://127.0.0.1:8000. Use Ctrl+C to stop both processes. The SQLite database and private evidence remain under `data/`.

The seed is repeatable and does not replace existing cases. Scenarios produce isolated runs; their reset action only closes the selected user's simulated cases without attached evidence or reports. It preserves baseline readings, uploaded data, user reports and run history. A scenario reset does not reset the entire database.

For a separate demonstration environment, set `CIVIC_DATA_DIR` to a new directory before starting. Do not reuse a demo database in non-demo mode. Non-demo mode requires configured administrator credentials and rejects the built-in demo password; see `services/api/database.py` and `services/api/seed.py` for environment inputs. Deployment beyond localhost needs separate review and is not validated here.

## Build

The normal setup is documented in README. If the installed pnpm wrapper requests an interactive module purge during a build, use the already-installed tools from `apps/web`:

```powershell
node node_modules/typescript/bin/tsc -b
if ($LASTEXITCODE -eq 0) { node node_modules/vite/bin/vite.js build }
```

This workaround does not install missing dependencies. Fresh installation and Docker/PostgreSQL execution remain separate validation tasks.

## Backups

Stop the local services before backing up so the database and evidence files represent the same quiet point in time:

```powershell
.venv\Scripts\python.exe scripts/backup.py --destination .runtime/backups/demo-2026-10-14
```

The destination must be new. SQLite's backup API includes committed WAL contents; evidence is copied from `private-evidence`. A manifest records SHA-256 checksums and sizes, and the database is integrity checked. Backups contain private data and are not public artifacts. Keep them out of version control.

Restore into a new directory using the verified manifest:

```powershell
.venv\Scripts\python.exe -m scripts.restore --source .runtime/backups/demo-2026-10-14 --destination .runtime/restored-demo
$env:CIVIC_DATA_DIR = Join-Path (Get-Location) '.runtime/restored-demo'
.venv\Scripts\python.exe scripts/run.py --port 8011
```

Restore checks the inventory, paths, checksums and SQLite integrity before creating the target. Existing targets, linked paths and tampered backups are refused. Keep the original data until you have checked the restored reports and evidence. PostgreSQL requires its own database backup tooling; these helpers support SQLite only. Checksums detect accidental modification, not authenticity against an attacker who can replace both files and manifest.

## Acceptance checks

`python scripts/verify_startup.py` creates its own directory under `.runtime`, migrates and seeds twice, checks the worker and assets, then verifies shutdown, restart and persistence. It needs installed dependencies and a built frontend; it is not a clean-machine installation test.

`scripts/completion-browser-check.mjs` requires an explicit localhost `CIVIC_BASE_URL`. Run it against a separate `CIVIC_DATA_DIR`, followed by `scripts/browser-check.mjs`, then the offline recovery scripts. Run these suites sequentially: they intentionally create synthetic reports and change demo configuration. The completion check records a synthetic electrical qualification on the demo inspector, which correctly revokes that inspector's old sessions.

GitHub Actions additionally defines a disposable Docker/PostgreSQL job that builds the image, runs both browser suites and checks evidence counts across an application restart. Its execution status must be checked on GitHub; a configured workflow alone is not verification.

## Worker and diagnostics

Jobs have persisted states, bounded retry attempts, lease expiry and recovery. Check the job result before interpreting a scenario as complete. A succeeded simulation is not a verified field repair. Failed jobs retain an error state; restart the worker only after examining the cause.

`/api/v1/health` reports local service health. The API schema is available at `/docs`. Verification scripts and artifacts are listed in `docs/verification.md`. Avoid copying the live database, evidence or session-bearing browser storage into public bug reports.
