# CivicSignal 360

AI-Powered Smart Water & Multi-Civic Infrastructure Intelligence Platform

**Detect Early. Act Smart. Build Better Cities.**

The full supplied specification is preserved in `docs/source-build-prompt.md`. It is the authoritative requirement source. This is a local, synthetic-data hackathon prototype, not an official utility service. The supplied PS7 competition wording has not been independently verified.

## Accepted scope

All seven domains remain in scope: water, electricity, roads, drainage, waste, streetlights, and general infrastructure. The common loop is observation, detection, explanation, corroboration, prioritization, assignment, intervention, monitoring, and human closure. No model may certify repairs or control real utility equipment.

Required foundation: durable local authentication and authorization, private reports and evidence, audited case state machine, optimistic concurrency, database-backed jobs and a separate worker, fixed-seed synthetic datasets, domain-specific analyses, usable responsive screens, English/Marathi citizen reporting, local drafts, exports, administration and honest evaluation.

Water leads the demonstration: historical-only seasonal robust detection with Isolation Forest comparison, quality incidents separate from anomalies, event grouping, excess volume accounting, forecasts, topology, and conservative tank calculations. Secondary domains require their own analytical methods and accountable workflows, not decorative placeholders.

All database views must use API responses. Offline operation is required after dependency installation. Synthetic, uploaded, measured, derived, and simulated evidence must remain distinguishable. Missing data never becomes zero. Unsupported results must say unavailable or not evaluated.

## Implementation decisions

The existing repository root is used directly (package name `civicsignal-360`), with React/TypeScript/Vite for the browser and FastAPI/SQLAlchemy for a same-origin modular monolith. SQLite provides dependable zero-service local persistence; PostgreSQL is configurable for Docker. A bundled schematic SVG map avoids external tiles. These are explicit deviations from the preferred Next.js/PostGIS stack, not changes to the requested product outcomes.

Acceptance status lives in `docs/requirements-traceability.md`; a feature is not verified merely because a route exists.
