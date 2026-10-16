# Recorded scenario playback

After a scenario job succeeds, Scenario Studio and the live-demo view offer Play/Pause, previous/next frame, a frame slider, 0.5×/1×/2×/4× speeds, Restart playback and Show completed run.

The calculation completes once in the durable worker. A separate persisted server clock then replays the timestamps and actual baseline/modified observations from that result. Each frame reveals only recorded rows at or before its timestamp; it is not a fabricated alert-card animation. Advancing the clock does not pause or rerun the analytics calculation and does not modify case decisions. The run's seed, parameters, checksums, results and linked case IDs remain the source of truth.

Both charts use the same ordered set of distinct recorded timestamps. Each frame reveals only observations at or before that timestamp; missing values and gaps remain missing. Domains with only a recorded snapshot get one frame, with no invented hourly observations. One-times speed advances one recorded frame per second, not one hour of real time.

The worker advances the server-owned cursor at the selected speed and automatically pauses at the last recorded frame. Pause, resume, step, seek, restart and speed changes are persisted against the job with version checks. Refreshing or opening the same authorized account in another browser loads that server state. The browser serializes polling requests and rejects responses from an older control version or earlier worker cursor, so a delayed response cannot undo a pause or backwards seek.

The analysis panel counts visible recorded chart observations, missing values and flagged observations separately for each branch. It reveals stored analytical events only once their full recorded evidence window ends; aggregate values from later windows are not attributed to early frames. The event window end is explicitly not described as the first time the detector raised an alert. At the final frame the saved analysis clock also exposes end-of-run quality assessments. Findings without a recorded window are available only in the completed snapshot. This is deterministic replay of stored observations and analyses, as required by P13D; retraining a detector on every displayed frame and reconstructing historical human decisions are not claimed.

The full-run case list appears at the final frame. The separate full-run comparison is explicitly labelled as independent of playback position. Any case opened from a recorded event shows its current workflow state. Only this run's authorized linked cases are available.

Seeking pauses playback. Reaching the last frame stops it. The selected run is retained in the URL and remembered in this tab for the signed-in account. Position, speed and playback status are stored with the job on the server. Only an authorized job owner can read or control its playback clock.

Restart playback only moves the cursor. The existing Reset this run action has a different purpose: it closes eligible simulated cases from that owned run while preserving reports, evidence, baseline data and job history. The controls have distinct labels to avoid conflating these actions.

Separate worker controls pause queued scenario jobs immediately or running calculations at their publication checkpoint, with durable resume. See worker-controls.md. New demo scenarios and their generated cases are browser-session scoped, and session reset clears eligible output only in the current demo session. Pre-migration jobs without session provenance stay owner-scoped; see demo-sessions.md.

Verification includes recorded-window withholding, zero-versus-missing values, UTC-equivalent clocks, final quality snapshots, API scope/version checks, worker pause behavior, stale-response ordering, and a real scenario replay after a human status decision. The status, version and saved scenario result remain unchanged by restart and seek. Browser visual verification of the analysis panel remains pending.
