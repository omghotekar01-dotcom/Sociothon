# Gemini Investigation Desk — local, opt-in integration

## What it does
The staff-only **AI Investigation Desk** at `/ai` can request a compact brief with competing hypotheses, missing evidence and recommended authorized checks. Choose a case and one of Evidence review, Water context or Connected signals. Outputs are structured and their claimed source IDs are checked against a backend-built catalog. All output is **advisory**. It cannot confirm faults, close cases, change statuses, create inspection records or operate infrastructure.

Only coded metadata from authorized cases is sent to Google Gemini: domain, service zone identifier, severity, status, provenance, optional asset identifier, case version, assignment presence and limited same-zone case counts/types. No citizen account data, report text, title/summary, free-text evidence, photographs, uploaded meter series or raw field notes are transmitted. Gemini receives information **only when the staff member explicitly clicks Generate**. Do not use this integration for a live municipality without appropriate privacy/data processing approvals.

## Local setup (Windows PowerShell)
1. Copy `.env.example` to `.env` at the project root: `Copy-Item .env.example .env`.
2. Open **the local `.env` file** with Notepad; fill `GEMINI_API_KEY=YOUR_KEY_HERE`.
3. Keep `GEMINI_MODEL=gemini-2.5-flash` unless your Google account has access to another supported model.
4. Restart `START-CIVICSIGNAL.bat`; sign in as Operator, Inspector or Administrator, then choose **AI Investigation Desk** from the sidebar, or the welcome-page AI shortcut for staff.
5. If the key is absent, you will see a setup notice, not an invented AI answer.

The `.env` file is already gitignored. Never put a live key into `.env.example`, React, a GitHub issue or PR, a URL or an image. Shell-level `GEMINI_API_KEY` takes precedence over local `.env`. If a key is shared inadvertently, revoke/rotate it.

## Dependencies, reliability and limitations
No new pip or npm dependency is needed: the server calls Google's `models.generateContent` REST API over HTTPS. There is an 18s timeout, payload/response size bound, per-user rate limit and structured output validation. Provider errors show recoverable messages. The existing deterministic Evidence Assistant and all current local cases work without internet or a key. Requests to Google require internet and may incur quota/cost.

This project does not use Apple native UI code. The cited `cjwirth/awesome-ios-ui` repository lists native iOS components, many intended for Swift/Objective-C. We drew on **design concepts**—subtle depth, readable type hierarchy, tactile feedback, reduced motion and clarity—in our existing React app without transplanting or redistributing native component code.

## Verification requirements
Run the Python unit suite and front-end lint/typecheck/build; exercise unauthorized citizen requests (403), out-of-scope inspector cases, no-key behavior, malformed provider output, rate limiting and Gemini rejection. Run the actual provider request once only after adding your key to the local .env. GitHub CI intentionally has **no real key** and must not transmit any live secret.
