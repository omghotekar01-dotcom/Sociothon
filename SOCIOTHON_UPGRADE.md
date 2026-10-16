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

## Transparent administrative review queue (additional enhancement)
The Sociothon Impact workspace now shows a deterministic, explainable review queue for **authorised visible open cases**. It uses existing case severity labels, administrative deadlines, elapsed age, reopened state and assignment gaps. Each suggestion lists its reasons; human reviewers remain responsible for field decisions, verification, and case closure. No additional sensitive case content is included in aggregate exports.

To validate the ranking independently, run `node --experimental-strip-types --test scripts/impact-review.test.mjs`. This is a triage *demonstrator*, not an emergency-prediction system or evidence of actual service delivery.
