# Sociothon upgrade — light-first impact demonstration

## Scope
The baseline CivicSignal 360 repository was transferred from its upstream source with attribution. This branch adds:

- A light-first interface with reversible dark theme selection stored only in the local browser.
- A Sociothon Impact workspace using currently authorized case records: open cases, human-reviewed administrative closures, zones and per-domain signals.
- A six-stage evidence-to-action explanation and a JSON export of aggregate demo metrics (no citizen descriptions exported).
- Clear, visible distinctions between synthetic simulation, administrative case status and independently verified outcomes.

The new view is a presentation aid, **not** proof of a deployment, government endorsement, certified water savings, actual repairs or model accuracy.

## Demo
Use the existing local launcher / Python FastAPI app and choose an Operator or Administrator demo account. From the sidebar open **Sociothon Impact**. Switch service filters, export aggregate JSON, and open the existing Scenario Studio demo. Check **Theme** in the header to toggle light/dark.

## Verification
Run `pnpm --dir apps/web typecheck`, `pnpm --dir apps/web build`, `pnpm --dir apps/web lint` and `python -m pytest tests -q`. Deployment, security review, field validation, municipal integrations and permission from the original upstream authors remain separate requirements.

See [SOURCE_ATTRIBUTION.md](SOURCE_ATTRIBUTION.md) and upstream [docs/limitations.md](docs/limitations.md).
