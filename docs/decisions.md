# Engineering decisions

1. **Local-first modular monolith.** FastAPI serves the production React build and versioned REST API from one origin. Durable SQLAlchemy database and separate worker avoid ephemeral job loss.
2. **SQLite default, PostgreSQL configurable.** Local setup must be reliable without Docker. PostgreSQL is an optional prepared deployment path. PostGIS is not required for a clearly labeled synthetic schematic.
3. **React/TypeScript/Vite.** The application requires client interactivity rather than server rendering. Vite simplifies a single-origin offline build. Vanilla design tokens replace Tailwind; accessible native controls avoid an unnecessary component stack.
4. **No hosted runtime dependencies.** Map shapes and icons are bundled. System fonts include Devanagari fallbacks. No external model, tile, authentication or cloud API is required.
5. **Honest evidence.** Detectors process generated readings. Rule-based planning is named as such. No hydraulic, causal impact, calibrated probability, or certified safety claims.
6. **Versioned contracts.** API endpoints are prefixed `/api/v1`; OpenAPI is exposed by FastAPI. UI formulas remain on the backend. Explicit errors must survive to the UI.

Further analytical choices and their limits are recorded in `docs/model-notes.md` after implementation inspection.
