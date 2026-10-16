# Implementation plan

| Milestone | Work | Gate |
| --- | --- | --- |
| M0 | Inspect sources, runtimes, decisions, specification, traceability, design | Sources accurately inventoried; project skeleton runnable |
| M1 | Authentication, roles, persistence, reports, audited cases, assignment, notifications | Citizen-to-inspector workflow and permission tests |
| M2 | Synthetic readings, ingestion, real water detector, evidence, monitoring | Independent anomaly generation; repeat analysis idempotent |
| M3 | Forecast, topology, tank simulation, scenarios and evaluation | Historical splits and conservation tests |
| M4 | Electrical telemetry, detection and qualified inspection | Domain workflow and safety boundaries |
| M5 | Road repair priorities/budgets, drainage screening and scenarios | Budget feasibility, conservation, follow-up |
| M6 | Waste capacity routing, streetlight schedules, general work orders | Dedicated rule and workflow tests |
| M7 | Cross-domain links, service coverage, drafts, Marathi, admin, frontend polish | API-backed routes, responsive interaction checks |
| M8 | Production build, tests, restart/offline checks, screenshots and documentation | Executed results and precise outstanding limitations |

Implementation runs in three bounded streams: API foundation, analytics, and frontend. Integration and documentation are owned by the primary agent. The streams do not imply milestone gates have passed. Failures found during integration are fixed before dependent verification is claimed.

No external deployment, purchase, notification delivery, or real infrastructure connection is authorized.
