# Data, units and provenance

| Entity | Key fields / conventions |
| --- | --- |
| User / session | Role, authorized departments/zones, salted password hash; hashed opaque session token and expiry |
| Zone / asset / connection | Stable IDs, domain, schematic position, recorded properties and directed topology connections |
| Reading | ID, asset/meter, zone, UTC interval start, duration in minutes, quantity, explicit unit, source, quality flag, original data |
| Model run | Dataset identity, model version, timestamp and full analytical output snapshot |
| Case | Stable event key, domain/zone/asset, severity, priority, state, evidence basis, case version, owner assignment, review deadline |
| Report | Owning user, case, category, approximate manual location, description, idempotency key |
| Evidence | Authorized actor, case, observation/inspection/intervention/follow-up, notes, checklist, private raster metadata |
| Audit | Actor, time, action, reason, previous and next values; append-only through exposed application operations |
| Job | Owner, parameters, dedupe key, status, attempts, maximum attempts, lease, result/error |
| Association | Separate source/target cases, review disposition, recorded spatial/time/other basis |

Water quantities are interval litres; rates may be litres/hour. `1 m³ = 1000 L`. Excess volume sums `max(observed interval volume − expected interval volume, 0)` over eligible intervals; it is not multiplied by duration again. Electricity uses interval kWh; voltage is a separate measured/synthetic field and is never inferred from energy.

Tank volume uses L with inflow/outflow L/hour. Drainage scenarios use rainfall mm/hour, catchment m², runoff coefficient, discharge m³/hour and storage m³. Road priority is a rule score, not a probability. Budget costs use explicitly configured synthetic currency amounts. Waste capacities and stop volumes are L; route distances are straight-line kilometres. Streetlight state is on/off/unknown, compared against local schedule.

Provenance categories retain their meanings: **Synthetic** generated input; **Uploaded** user-submitted observations; **Measured** a declared measurement source; **Derived** calculations; **Simulated** counterfactual scenarios. Citizen statements are separately identified as reported observations. A source label does not verify a real-world cause.

UTC is stored; Asia/Kolkata is the local default. The fixed synthetic clock is intentionally separate from wall-clock retrieval time. A freshly fetched old observation remains old. Null values never count as zero usage, improvement or confirmed restoration.
