# CivicSignal 360

CivicSignal 360 is a civic infrastructure monitoring platform for water, electricity, roads, drainage, waste, and streetlights, featuring English/Marathi citizen reporting, explainable analytics, case management, and reproducible simulations.

**AI-Powered Smart Water & Multi-Civic Infrastructure Intelligence Platform**  
**Detect Early. Act Smart. Build Better Cities.**

Local hackathon prototype for the user-supplied Sociathon 2026 PS7 water-management problem. Water, electricity, roads, drainage, waste, streetlights and general infrastructure share evidence-backed investigation workflows.

> Independent hackathon prototype — not affiliated with an official government authority.

This repository contains real Python analytics, a durable relational API, a separate job worker, and a React/TypeScript interface. Synthetic data is generated and processed; findings are not hardcoded success responses. See [STATUS.md](STATUS.md) for the current verified scope and unfinished requirements. No real utility systems are connected.

## Start locally

**One-click Windows start (after initial setup):** double-click `START-CIVICSIGNAL.bat` in the project folder. It starts the API and worker and opens the preview once ready. Keep its terminal window open; press Ctrl+C to stop. If the application is already running on port 8000, it opens that instance instead of starting another copy. In VS Code's PowerShell terminal, use `./START-CIVICSIGNAL.bat`.

Prerequisites: Python 3.12 (pinned CI dependencies) or Python 3.14 (additional wheel-based install profile), Node.js 22 or newer, and pnpm 11.25.0. Python 3.14 runtime compatibility still requires a full regression pass. The first installation requires internet; runtime data, charts, map and authentication are local.

Windows setup (automatically selects requirements for your Python version, and builds the frontend):

```powershell
.\scripts\setup.ps1
```

To use Python 3.14 explicitly when multiple interpreters exist: `.\scripts\setup.ps1 -Python python` (provided `python --version` prints Python 3.14). If `.venv` belongs to a different Python version, remove that virtual environment first. Your `data/` folder and source files are not part of `.venv`.

Manual Python 3.12 setup, from this repository:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
pnpm --dir apps/web install --frozen-lockfile
pnpm --dir apps/web build
.\.venv\Scripts\python.exe scripts/run.py
```

Open [CivicSignal 360](http://127.0.0.1:8000). The launcher migrates and seeds the local database, then starts the API and worker. Initial seed generation computes synthetic evaluation and can take longer than subsequent launches. Ctrl+C stops both services. Data remains in `data/`.

On this Codex workspace, dependencies are already installed. The immediate start command is:

```powershell
.\.venv\Scripts\python.exe scripts/run.py
```

If using Codex's bundled Python and `venv` reports an `ensurepip` error, the interpreter can still have been created. Use the bundled pip to target it:

```powershell
& 'C:\Users\Nikhil Jadhav\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pip --python '.venv\Scripts\python.exe' install -r requirements.txt
node 'C:\Users\Nikhil Jadhav\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules\pnpm\bin\pnpm.cjs' --dir apps/web build
```

POSIX equivalent:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
pnpm --dir apps/web install --frozen-lockfile
pnpm --dir apps/web build
.venv/bin/python scripts/run.py
```

## Demo accounts

Use the role buttons on the local sign-in screen or these credentials:

| Role | Email | Password |
| --- | --- | --- |
| Operator | operator@civicsignal.local | CivicDemo!2026 |
| Inspector | inspector@civicsignal.local | CivicDemo!2026 |
| Supporting inspector | support@civicsignal.local | CivicDemo!2026 |
| Citizen | citizen@civicsignal.local | CivicDemo!2026 |
| Administrator | admin@civicsignal.local | CivicDemo!2026 |

These credentials are deliberately public and local-demo-only. Registration creates citizens. Server checks enforce domain, zone, assignment and ownership permissions. Demo entry: [Sociathon Live Demo — CivicSignal 360](http://127.0.0.1:8000/demo).

## Development and verification

```powershell
# API terminal
.\.venv\Scripts\python.exe -m uvicorn services.api.main:app --host 127.0.0.1 --port 8000
# Worker terminal
.\.venv\Scripts\python.exe -m services.api.worker
# Frontend terminal
pnpm --dir apps/web dev

# Checks
.\.venv\Scripts\python.exe -m pytest tests -q
pnpm --dir apps/web typecheck
pnpm --dir apps/web build
.\.venv\Scripts\python.exe scripts/benchmark.py

# Explicit migration / repeatable seed
.\.venv\Scripts\python.exe -m database.migrations
.\.venv\Scripts\python.exe -m services.api.seed
```

Executed results, screenshots and blockers are recorded in [docs/verification.md](docs/verification.md), not inferred from these command examples. Python direct versions are pinned in `requirements.txt`; the actual local dependency resolution is saved in `requirements-lock.txt`. Frontend dependencies use `pnpm-lock.yaml`.

## Docker

```sh
docker compose up --build
```

The prepared Compose stack uses PostgreSQL 16 and a persistent evidence volume. It binds the app to localhost. Docker availability and execution status are explicitly listed in the verification document. Local SQLite is the default when `DATABASE_URL` is unset. No PostGIS or hydraulic solver is implied.

## Data and architecture

- [Architecture](docs/architecture.md) and [decisions](docs/decisions.md)
- [Source inventory](docs/source-inventory.md) and [requirements traceability](docs/requirements-traceability.md)
- [API and CSV guide](docs/api.md), [data dictionary](docs/data-dictionary.md), [model notes](docs/model-notes.md)
- [Security](docs/security.md), [operations](docs/operations.md), [demo script](docs/demo-script.md)
- [Water operations and structured field evidence](docs/water-operations.md)
- [Selected-requirements handover and walkthrough](docs/completion-handover.md)

FastAPI's local [OpenAPI explorer](http://127.0.0.1:8000/docs) documents request schemas. The map is a bundled schematic city. Fixed-seed observations and separate ground-truth labels are generated by `datasets/synthetic/generate.py`. Synthetic benchmark results do not establish real-world accuracy.

The supplied master prompt is authoritative and preserved under `docs/source-build-prompt.md`. No additional blueprint PDF is required; no content from an unavailable PDF is claimed.
