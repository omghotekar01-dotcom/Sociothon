# CivicSignal 360 integration review — 17 October 2026

## Compared repositories
Compared the full main trees of omghotekar01-dotcom/Sociothon and nikhiljadhav6869-sudo/Civic-Signal-360. Their shared files match except the React entry/App shell files; Sociothon adds ThemeSwitcher, light CSS, Showcase and impact review. Bulk copying upstream would erase user-specific changes without importing new features. The base domain logic already matches.

## Implemented on the separate integration branch
- One shared live light/dark/system theme state. Settings and header switch now both change the appearance; account persistence uses existing authenticated /settings API.
- Explicit notification when the immediate local theme change cannot sync to the server.
- Chart grid, axis labels, baseline, tooltip and additional panels use theme-responsive colors. Narrow layout, print exclusions and reduced motion styles included.
- A Python 3.14 pip-wheel requirements profile. Original Python 3.12 requirements and CI remain unchanged.
- Version-aware PowerShell setup with clear virtual-environment incompatibility messaging.

## Important scope / acceptance
These are code changes, not proof that all screens were exercised. The 7-domain case journeys, full evidence print/export, bilingual verification, session expiry, persistence, worker recovery, database restoration, Docker/PostgreSQL and final presentation video remain unverified here. Do not label them complete without execution.

## Prioritized acceptance steps
1. Build/typecheck/lint. Exercise light/dark/system on desktop/mobile, CSS readability for cards, overlays, charts and input states, Settings reload/persistence, forced API failure and keyboard focus.
2. Verify case reporting, review, assignment, inspection, intervention, monitoring and authorized closure *for each domain*; include permission-denied branches and interrupted retry.
3. Verify Evidence Passport priority snapshot, export, print, chronological evidence, cross-domain accept/reject/unlink and database consistency.
4. Water: supply schedule exceptions, parent-child meter topology, storage adjustments, incomplete-data flags, recommended checks and before/after classification; each must have an explicit acceptance scenario.
5. Run Python 3.12 + 3.14 suites, JS tests, CI, fresh-machine installation, persistence, worker-recovery, backup/restore incl. private evidence.
6. Use only final working UI recordings in the 5–6 minute Peaky Coders demo. Cite synthetic vs. production data honestly.
