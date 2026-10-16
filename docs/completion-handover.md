# Selected requirements: prototype handover

Date: 16 October 2026. This handover covers the requested completion pass for requirements **1, 2, 4 and 5**. It is not certification of the broader master prompt or a live municipal deployment.

## What to try

1. **Start:** double-click `START-CIVICSIGNAL.bat`. Keep its terminal open; Ctrl+C stops API and worker. If an older server is already running, stop it before launching updated backend code. Default URL: http://127.0.0.1:8000.
2. **Water:** sign in as Administrator → Water → Operations. Select River Ward, expand supply schedule/accounting boundary, enter a supply window and reason, and save. Review the recorded period. Without explicit accounting inputs and a confirmed meter boundary, the balance correctly stays unavailable. Export the review JSON, or choose an open water case and attach the reviewed snapshot with a reason. Open its saved Evidence Passport to inspect or export the preserved readings and configuration. Administrators can record effective supply periods with sources; select historical mode to review them. Use Compare multiple meters for a complete-window group comparison. Opt in to device retention when an attachment must survive reload.
3. **Report:** sign in as Citizen → Report a problem. Switch English/Marathi, choose Water and a service zone, enter a clearly labelled synthetic observation and location, review and submit. Save the receipt and open My reports to track it.
4. **Review and assign:** as Operator, search for that report, open Evidence Passport → Take action. Record a reason and move it into investigation. Enter a fresh assignment reason, choose an inspector, and save.
5. **Inspect:** as the assigned Inspector, open Field workspace → the case → Take action. Record domain observations and narrative, leaving unknown values blank. Submit inspection. Record intervention with its three checklist confirmations, move to monitoring with a reason, and submit a follow-up observation.
6. **Close:** as Operator, review the evidence and follow-up, then record a reasoned resolution. The citizen can see the updated report status. The model never performs this decision automatically.
7. **Water evidence gaps:** in a water case, open Evidence assistant and inspect the water review table. Missing quantities, operating context, inspection or follow-up stay explicit and cite the attached source records where present.
8. **Other domains:** the same human workflow supports electricity, roads, drainage, waste, streetlights and general infrastructure, each with different manual fields. Electricity requires an administrator-recorded qualification and a case-specific inspector confirmation; the prototype does not verify professional credentials.

Use only the supplied demo accounts with the synthetic local demonstration. Credentials and first-time dependency setup are in the README.

## Delivery and recovery

- Source is in the existing GitHub repository on `main`. Verification history and current hosted-run links are in `docs/verification.md`.
- SQLite backup and restore commands are in `docs/operations.md`. Stop services before the backup, retain the checksum manifest, restore to a new directory, and validate the restored records before changing your active data directory.
- Docker Compose is a local PostgreSQL demo configuration, bound to localhost. It is not a production hosting configuration.
- The browser acceptance database under `.runtime/completion-preview` is disposable synthetic test data. It is separate from the normal `data/` directory and is not committed to Git.

## Acceptance and limits

Local evidence: 208 backend tests, 46 JavaScript tests, 37 browser regression checks, eight completion journeys, three saved-water-review checks and four historical/multi-meter checks, 13 offline recovery checks and eight fresh-directory startup checks passed. Typecheck, lint and production build passed. See the verification log for hosted checks and earlier failures corrected during this pass.

Citizen reporting, receipt/tracking and recovery support English and Marathi. The staff shell, water controls and field labels also have Marathi support; all analytical prose and server errors are not fully translated. Native file-picker text and user-supplied content retain their own language.

Water balances are conditional accounting residuals; current schedules are not proof of historical operations. Authorized reviewers can explicitly attach the exact review snapshot to an open water case; this preserves context without changing status or counting as field inspection. The network is schematic, not a hydraulic model. Synthetic results do not establish real-world accuracy or savings.

Public deployment, real utility/sensor connections, independent security and accessibility audits, full staff translation, and other broader master-prompt gaps remain separate. Consult `docs/limitations.md` and `docs/requirements-traceability.md` before describing the entire platform as production-complete.
