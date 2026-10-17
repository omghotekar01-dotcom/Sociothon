"""Server-owned case policy, evidence access and priority components."""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import update
from .models import Audit, Case, Configuration, Evidence, Notification, Report, Session, User, now, uid
from .priorities import case_priority_reviews, case_priority_snapshot
from .security import can_case, in_scope

TRANSITIONS = {
    "needs_review": {"investigating", "assigned", "closed"},
    "investigating": {"assigned", "closed"},
    "assigned": {"investigating", "intervention", "closed"},
    "intervention": {"monitoring"},
    "monitoring": {"resolved", "assigned", "closed"},
    "resolved": {"investigating"},
    "closed": {"investigating"},
}


def case_access(db, user, case_id):
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found.")
    if not can_case(user, case):
        raise HTTPException(403, "This case is outside your domain, zone or assignment.")
    return case


def serialize_case(case):
    result = {key: getattr(case, key) for key in ("id", "title", "domain", "zone_id", "asset_id", "severity", "status", "summary", "created_at", "updated_at", "provenance", "priority", "evidence", "version", "assigned_to", "secondary_assignees", "deadline_at")}
    review = getattr(case, "priority_review", None)
    if review is not None:
        result["priority"] = review["score"]
        result["priority_review"] = review
    return result


def serialize_row(row, keys):
    return {key: getattr(row, key) for key in keys}


def visible_cases(db, user):
    query = db.query(Case)
    if user.role == "citizen":
        return []
    demo_session_id = getattr(user, "_demo_session_id", None)
    query = query.filter((Case.demo_session_id.is_(None)) | (Case.demo_session_id == demo_session_id))
    if user.role != "admin":
        query = query.filter(Case.domain.in_(user.domains), Case.zone_id.in_(user.zones))
    if user.role == "operator":
        query = query.filter((Case.demo_owner_id.is_(None)) | (Case.demo_owner_id == user.id))
    if user.role == "inspector":
        query = query.filter((Case.assigned_to == user.id) | Case.support_assignments.any(user_id=user.id))
    cases = query.all()
    reviews = case_priority_reviews(db, cases, user=user, visible_case_ids={case.id for case in cases})
    for case in cases:
        case.priority_review = reviews[case.id]
    return sorted(cases, key=lambda case: (-case.priority_review["score"], case.created_at), reverse=False)


def audit(db, user, case, action, reason, before=None, after=None):
    session_id = case.demo_session_id if case and case.demo_session_id else None
    if session_id is None and action in {"job_pause", "job_resume", "demo_session_reset"} and user:
        session_id = getattr(user, "_demo_session_id", None)
    db.add(Audit(actor_id=user.id if user else None, case_id=case.id if case else None, action=action, reason=reason, before=before or {}, after=after or {}, demo_session_id=session_id))


def notify(db, user_id, case, title, event):
    user = db.get(User, user_id)
    if not user or user.settings.get("notifications") is False:
        return
    key = f"{user_id}:{case.id if case else 'system'}:{event}"
    if not db.query(Notification).filter_by(dedupe_key=key).first():
        db.add(Notification(user_id=user_id, case_id=case.id if case else None, dedupe_key=key, title=title))


def notify_case(db, case, title, event):
    if case.demo_session_id:
        participants = {row[0] for row in db.query(Session.user_id).filter_by(demo_session_id=case.demo_session_id).distinct().all()}
        if case.demo_owner_id:
            participants.add(case.demo_owner_id)
        users = db.query(User).filter(User.active.is_(True), User.id.in_(participants)).all() if participants else []
        for user in users:
            notify(db, user.id, case, title, event)
    else:
        for user in db.query(User).filter(User.active.is_(True)).all():
            if can_case(user, case):
                notify(db, user.id, case, title, event)
    for report in db.query(Report).filter_by(case_id=case.id).all():
        notify(db, report.user_id, case, title, event)


def mutate_case(db, user, case, version, action, reason, evidence_ids=None, audit_before=None, audit_after=None, **values):
    if not reason.strip():
        raise HTTPException(422, "A decision reason is required.")
    before = {key: getattr(case, key) for key in values}
    result = db.execute(update(Case).where(Case.id == case.id, Case.version == version).values(**values, version=version + 1, updated_at=now()), execution_options={"synchronize_session": False})
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "This case changed since you opened it. Refresh before saving.")
    db.refresh(case)
    audit(db, user, case, action, reason, {**before, **(audit_before or {})}, {**values, **(audit_after or {}), **({"evidence_ids": evidence_ids} if evidence_ids else {})})
    notify_case(db, case, f"{case.title}: {case.status.replace('_', ' ')}", f"version-{case.version}")
    return case


def notify_overdue(db):
    """Idempotent administrative escalation, never a statutory deadline claim."""
    for case in db.query(Case).filter(Case.deadline_at < now(), Case.status.notin_(["resolved", "closed"])).all():
        notify_case(db, case, f"Review overdue: {case.title}", f"overdue:{case.deadline_at}")


def transition(db, user, case, target, reason, version):
    if target not in TRANSITIONS.get(case.status, set()):
        raise HTTPException(409, f"Cannot move from {case.status} to {target}.")
    if user.role == "inspector" and target != "monitoring":
        raise HTTPException(403, "Inspectors record findings and interventions; operators review closure.")
    if target == "assigned":
        raise HTTPException(422, "Use Assign inspector to create an accountable assignment.")
    if target == "intervention":
        raise HTTPException(422, "Record an intervention with supporting notes first.")
    if target == "monitoring" and not db.query(Evidence).filter_by(case_id=case.id, kind="intervention").first():
        raise HTTPException(409, "Record an intervention before monitoring.")
    if target == "resolved":
        intervention = db.query(Evidence).filter_by(case_id=case.id, kind="intervention").order_by(Evidence.created_at.desc()).first()
        if not intervention or not db.query(Evidence).filter(Evidence.case_id == case.id, Evidence.kind == "follow_up", Evidence.created_at > intervention.created_at).first():
            raise HTTPException(409, "A documented follow-up inspection after the latest intervention is required before human-reviewed resolution.")
    return mutate_case(db, user, case, version, "transition", reason, status=target)


def create_finding_case(db, finding, provenance="Synthetic", prefix="", demo_owner_id=None, demo_session_id=None, priority_weights=None, priority_version=None):
    domain = finding.get("domain", "general")
    if domain == "infrastructure":
        domain = "general"
    event_key = prefix + finding["id"]
    existing = db.query(Case).filter_by(event_key=event_key).first()
    if existing:
        return existing
    severity = finding.get("severity", "medium").lower()
    score = {"critical": 90, "high": 75, "medium": 50, "low": 25, "warning": 50}.get(severity, 40)
    evidence = dict(finding.get("evidence", {}))
    evidence.update({"finding_id": finding["id"], "reason_codes": finding.get("reason_codes", []), "start": finding.get("start"), "end": finding.get("end"), "estimated_excess": finding.get("estimated_excess"), "unit": finding.get("unit"), "limitations": ["Analytical evidence supports investigation; it does not confirm a physical fault."]})
    evidence["priority_configuration"] = case_priority_snapshot(db, priority_weights, priority_version)
    config = db.get(Configuration, "platform")
    review_hours = (config.value if config else {}).get("review_hours", 72)
    case = Case(id=uid(), event_key=event_key, title=finding.get("title", "Observation requires review"), domain=domain, zone_id=finding["zone_id"], asset_id=finding.get("asset_id"), severity=severity, summary=finding.get("summary") or "; ".join(finding.get("reason_codes", [])) or "Inspect the analytical evidence and consider alternative explanations.", provenance=provenance, priority=score, evidence=evidence, deadline_at=(datetime.now(timezone.utc) + timedelta(hours=review_hours)).isoformat(), demo_owner_id=demo_owner_id, demo_session_id=demo_session_id)
    db.add(case)
    db.flush()
    audit(db, None, case, "detected", "Created from the real analytical pipeline; human review required.", after={"status": "needs_review", "finding_id": finding["id"]})
    notify_case(db, case, case.title, "detected")
    return case


def full_case(db, case, user=None):
    case.priority_review = case_priority_reviews(db, [case], user=user)[case.id]
    result = serialize_case(case)
    members = db.query(User).filter(User.id.in_([case.assigned_to, *case.secondary_assignees])).all()
    names = {member.id: member.name for member in members}
    result["assignment_team"] = {"lead": {"id": case.assigned_to, "name": names.get(case.assigned_to, case.assigned_to)} if case.assigned_to else None, "supporting": [{"id": ident, "name": names.get(ident, ident)} for ident in case.secondary_assignees]}
    result["audits"] = [serialize_row(row, ["id", "actor_id", "action", "reason", "before", "after", "created_at"]) for row in db.query(Audit).filter_by(case_id=case.id).order_by(Audit.created_at).all()]
    result["evidence_records"] = [serialize_row(row, ["id", "actor_id", "kind", "notes", "mime", "checklist", "observations", "created_at"]) for row in db.query(Evidence).filter_by(case_id=case.id).all()]
    for record in result["evidence_records"]:
        if record["kind"] == "photograph":
            record["url"] = f"/api/v1/evidence/{record['id']}/download"
    reports = db.query(Report).filter_by(case_id=case.id).order_by(Report.created_at.desc()).all()
    # Only returned after the existing case_access permission check. Preserve the
    # submitted citizen content exactly; do not substitute the generic case summary.
    result["citizen_reports"] = [{
        "id": report.id, "receipt": "CS360-" + report.id[:8].upper(),
        "title": report.title, "description": report.description,
        "location": report.location, "domain": report.domain,
        "zone_id": report.zone_id, "created_at": report.created_at
    } for report in reports]
    reports_by_account = {}
    for report in reports:
        reports_by_account[report.user_id] = reports_by_account.get(report.user_id, 0) + 1
    repeat_groups = [count for count in reports_by_account.values() if count > 1]
    result["corroboration"] = {
        "reports": len(reports),
        "unique_reporters": len(reports_by_account),
        "same_account_repeat_groups": len(repeat_groups),
        "same_account_additional_reports": sum(count - 1 for count in repeat_groups),
        "meaning": "Distinct accounts are observation sources, not proof of a fault. Repeat submissions from the same account are grouped in these counts and do not add independent corroboration.",
    }
    result["allowed_transitions"] = sorted(TRANSITIONS.get(case.status, set()))
    return result
