"""Auditable case priority scoring from documented inputs and current evidence."""
from datetime import datetime, timezone
import math

from sqlalchemy import func, or_

from .models import Association, Case, Configuration, Evidence, Report

DEFAULT_CASE_PRIORITY_WEIGHTS = {
    "severity": 50,
    "persistence": 10,
    "exposure": 10,
    "evidence_diversity": 15,
    "case_age": 10,
    "cross_domain_hazard": 5,
}
SEVERITY_SCORE = {"critical": 100, "high": 75, "medium": 50, "warning": 50, "low": 25}
INSPECTOR_EVIDENCE_KINDS = {"inspection", "finding", "follow_up", "intervention"}


def validate_case_priority_weights(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULT_CASE_PRIORITY_WEIGHTS):
        raise ValueError("Case priority weights must define each supported component exactly once.")
    weights = {}
    for key, raw in value.items():
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw) or raw < 0 or raw > 100:
            raise ValueError("Case priority weights must be finite values from 0 to 100.")
        weights[key] = raw
    if abs(sum(weights.values()) - 100) > 1e-6:
        raise ValueError("Case priority weights must total 100 points.")
    return weights


def case_priority_snapshot(db, weights=None, version=None):
    config = db.get(Configuration, "platform")
    config_value = config.value if config else {}
    selected = weights if weights is not None else config_value.get("case_priority_weights", DEFAULT_CASE_PRIORITY_WEIGHTS)
    try:
        selected = validate_case_priority_weights(selected)
    except ValueError:
        # A damaged or partially upgraded configuration must not prevent staff
        # from reviewing a case. Use the last known documented default and
        # expose that fallback in the scoring record.
        selected = dict(DEFAULT_CASE_PRIORITY_WEIGHTS)
        fallback = True
    else:
        fallback = False
    return {
        "weights": selected,
        "version": int(version if version is not None else (getattr(config, "version", 1) if config else 1)),
        "fallback": fallback,
    }


def freeze_case_priority_config(db, evidence, weights=None, version=None):
    evidence["priority_configuration"] = case_priority_snapshot(db, weights, version)
    return evidence["priority_configuration"]


def _stamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def case_priority_reviews(db, cases, user=None, visible_case_ids=None, at=None):
    """Return live priority breakdowns; visible IDs prevent link side channels."""
    case_list = list(cases)
    if not case_list:
        return {}
    ids = {case.id for case in case_list}
    now = at or datetime.now(timezone.utc)

    report_counts = dict(
        db.query(Report.case_id, func.count(func.distinct(Report.user_id)))
        .filter(Report.case_id.in_(ids))
        .group_by(Report.case_id)
        .all()
    )
    evidence_types = {ident: set() for ident in ids}
    evidence_rows = db.query(Evidence.case_id, Evidence.kind).filter(Evidence.case_id.in_(ids)).all()
    for ident, kind in evidence_rows:
        evidence_types.setdefault(ident, set()).add(kind)

    accepted_links = db.query(Association.source_id, Association.target_id, Association.basis).filter(
        Association.status == "accepted",
        or_(Association.source_id.in_(ids), Association.target_id.in_(ids)),
    ).all()
    related_ids = {ident for source_id, target_id, _basis in accepted_links for ident in (source_id, target_id)}
    related_cases = {case.id: case for case in db.query(Case).filter(Case.id.in_(related_ids)).all()} if related_ids else {}
    permitted = set(visible_case_ids) if visible_case_ids is not None else set(ids)
    if user is not None:
        from .security import can_case
        permitted.update(ident for ident, related in related_cases.items() if can_case(user, related))
    link_factors = {ident: [] for ident in ids}
    for source_id, target_id, basis in accepted_links:
        if source_id not in permitted or target_id not in permitted:
            continue
        source, target = related_cases.get(source_id), related_cases.get(target_id)
        if not source or not target or source.domain == target.domain:
            continue
        if min(SEVERITY_SCORE.get((source.severity or "").casefold(), 40), SEVERITY_SCORE.get((target.severity or "").casefold(), 40)) < 75:
            continue
        same_asset = bool(source.asset_id and source.asset_id == target.asset_id)
        same_zone = source.zone_id == target.zone_id
        component_value = 100 if same_asset else 50 if same_zone else 0
        for ident in (source_id, target_id):
            if ident in link_factors:
                link_factors[ident].append({"score": component_value, "same_asset": same_asset, "same_zone": same_zone})

    result = {}
    for case in case_list:
        evidence = case.evidence if isinstance(case.evidence, dict) else {}
        frozen = evidence.get("priority_configuration")
        if isinstance(frozen, dict):
            try:
                snapshot = {"weights": validate_case_priority_weights(frozen.get("weights")), "version": int(frozen.get("version", 1)), "fallback": bool(frozen.get("fallback", False))}
            except (ValueError, TypeError):
                snapshot = case_priority_snapshot(db)
                snapshot["fallback"] = True
                snapshot["legacy"] = True
        else:
            snapshot = case_priority_snapshot(db)
            snapshot["legacy"] = True
        weights = snapshot["weights"]

        severity = SEVERITY_SCORE.get((case.severity or "").casefold(), 40)
        start, end = _stamp(evidence.get("start")), _stamp(evidence.get("end"))
        if start is not None and end is not None and end >= start:
            persistence = min(100., max(0., (end - start).total_seconds() / 3600 / 72 * 100))
            persistence_source = "Finding interval duration; normalized to a 72-hour cap"
        else:
            persistence, persistence_source = None, "Finding interval is not recorded"

        inspection = evidence.get("inspection") if isinstance(evidence.get("inspection"), dict) else {}
        observation = evidence.get("observation") if isinstance(evidence.get("observation"), dict) else {}
        exposure = inspection.get("daily_exposure", observation.get("daily_exposure"))
        if isinstance(exposure, (int, float)) and not isinstance(exposure, bool) and math.isfinite(exposure) and exposure >= 0:
            exposure_score = min(100., exposure / 10000 * 100)
            exposure_source = "Recorded daily exposure; normalized to 10,000 people/day"
        else:
            exposure = observation.get("exposure")
            if isinstance(exposure, (int, float)) and not isinstance(exposure, bool) and math.isfinite(exposure) and exposure >= 0:
                exposure_score = min(100., exposure)
                exposure_source = "Recorded exposure percentage"
            else:
                exposure_score, exposure_source = None, "Public exposure is not recorded"

        source_types = set()
        if case.provenance == "Derived":
            source_types.add("analytical")
        elif case.provenance == "Simulated":
            source_types.add("scenario")
        elif case.provenance == "Reported":
            source_types.add("citizen report")
        reporters = int(report_counts.get(case.id, 0))
        if reporters:
            source_types.add("citizen report")
        kinds = evidence_types.get(case.id, set())
        if kinds.intersection(INSPECTOR_EVIDENCE_KINDS):
            source_types.add("inspector record")
        if "photograph" in kinds:
            source_types.add("photographic evidence")
        diversity = min(100., max(0, len(source_types) - 1) * (100 / 3))

        created = _stamp(case.created_at)
        if case.status in {"resolved", "closed"}:
            age_score, age_source = 0., "Case is resolved or closed; open-case age is not accrued"
        elif created is not None:
            review_hours = 72.
            deadline = _stamp(case.deadline_at)
            if deadline is not None and deadline > created:
                review_hours = (deadline - created).total_seconds() / 3600
            age_hours = max(0., (now - created).total_seconds() / 3600)
            age_score = min(100., age_hours / max(1., review_hours * 2) * 100)
            age_source = "Open-case age relative to twice its recorded review target"
        else:
            age_score, age_source = None, "Case creation time is unavailable"

        hazard_links = link_factors.get(case.id, [])
        cross_domain = max((item["score"] for item in hazard_links), default=0.)
        cross_source = "Accepted cross-domain link between high-severity cases; same asset scores 100, same service zone scores 50"
        raw = {
            "severity": (severity, "Recorded case severity"),
            "persistence": (persistence, persistence_source),
            "exposure": (exposure_score, exposure_source),
            "evidence_diversity": (diversity, "Distinct source channels; repeated reports by the same account do not add diversity"),
            "case_age": (age_score, age_source),
            "cross_domain_hazard": (cross_domain, cross_source),
        }
        components, missing = {}, []
        score = 0.
        for key, (value, source) in raw.items():
            weight = weights[key]
            contribution = (float(value) * weight / 100) if value is not None else 0.
            score += contribution
            if value is None:
                missing.append(key)
            components[key] = {
                "value": round(float(value), 2) if value is not None else None,
                "weight": weight,
                "contribution": round(contribution, 2),
                "status": "available" if value is not None else "missing",
                "source": source,
            }
        result[case.id] = {
            "score": round(min(100., max(0., score)), 2),
            "components": components,
            "missing": missing,
            "weights": weights,
            "configuration_version": snapshot["version"],
            "configuration_fallback": snapshot.get("fallback", False),
            "legacy_configuration": snapshot.get("legacy", False),
            "urgency": {"severity": case.severity, "score": severity, "review_required": case.status not in {"resolved", "closed"}},
            "evidence_quality": {"source_types": sorted(source_types), "unique_reporters": reporters, "assessment": "Evidence quantity and diversity support review; they do not prove a physical fault."},
            "cross_domain_links": hazard_links,
            "method": "Deterministic weighted score; missing inputs contribute zero and are listed. Hazard urgency remains a separate severity field.",
        }
    return result
