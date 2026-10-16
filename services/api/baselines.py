"""Immutable training snapshots, chronological evaluation and audited activation."""
import copy
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import update

from .database import get_db
from .domain import audit
from .models import Asset, Audit, BaselineDeployment, BaselineVersion, Case, Configuration, Job, ModelRun, Reading, Zone, now, uid
from .security import current_user, require_admin, require_staff

router = APIRouter(prefix='/api/v1/baselines')
Domain = Literal['water', 'electricity']


def stamp(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Dates require an explicit timezone.') from None


def checksum(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, allow_nan=False).encode()).hexdigest()


def stored_readings(db, domain):
    return [{**{k: r.original[k] for k in ('expected_multiplier', 'active', 'voltage', 'voltage_unit', 'power_kw', 'power_unit', 'current_a', 'current_unit', 'supply_expected') if k in r.original}, **{k: getattr(r, k) for k in ('id', 'asset_id', 'zone_id', 'timestamp', 'interval_minutes', 'quantity', 'unit', 'source', 'quality_flag')}} for r in db.query(Reading).filter_by(domain=domain).order_by(Reading.asset_id, Reading.timestamp).all()]


def registered_meters(db, domain):
    """Return registered telemetry meters so a never-reporting asset is visible."""
    units = {'water': {'L', 'litres', 'm3', 'm³'}, 'electricity': {'kWh', 'Wh'}}[domain]
    result = []
    for asset in db.query(Asset).filter_by(domain=domain).all():
        properties = asset.properties or {}
        is_meter = 'meter' in (asset.kind or '').casefold() or properties.get('unit') in units
        if is_meter and properties.get('active', True) is not False:
            result.append({'id': asset.id, 'zone_id': asset.zone_id, 'reporting_interval_minutes': properties.get('reporting_interval_minutes', 60)})
    return result


def authorized(db, user, domain):
    require_staff(user)
    if user.role != 'admin' and (domain not in user.domains or not {z.id for z in db.query(Zone).all()}.issubset(set(user.zones))):
        raise HTTPException(403, 'Baseline management requires department and all-zone authorization.')


def blocked_readings(db, domain, rows):
    blocked, cases = set(), []
    for case in db.query(Case).filter(Case.domain == domain, Case.status.notin_(['resolved', 'closed']), Case.demo_owner_id.is_(None)).all():
        if case.provenance == 'Simulated':
            continue
        try:
            start = stamp(case.evidence.get('start') or case.created_at)
            end = stamp(case.evidence.get('end') or case.evidence.get('start') or case.created_at)
            # Event ends may identify the last interval start. Conservatively
            # include the full last interval, and point reports' whole interval.
            if end < start:
                raise ValueError()
        except ValueError:
            start = end = None
        matched = []
        for row in rows:
            if (case.asset_id and row['asset_id'] != case.asset_id) or row['zone_id'] != case.zone_id:
                continue
            at = stamp(row['timestamp'])
            if start is None or (at <= end and at + timedelta(minutes=row['interval_minutes']) > start):
                matched.append(row['id'])
        if matched:
            blocked.update(matched)
            cases.append(case.id)
    return blocked, cases


def valid_rows(rows, domain):
    from services.analytics.pipeline import normalize_readings
    frame = normalize_readings(rows, domain)
    ids = set(frame.loc[frame.valid, 'id']) if not frame.empty else set()
    return [r for r in rows if r['id'] in ids]


def initialize_baselines(db):
    """Capture existing historical baselines once; never reinitialize a deployment."""
    from services.analytics.pipeline import MODEL_VERSION
    for domain in ('water', 'electricity'):
        if db.get(BaselineDeployment, domain):
            continue
        run = db.query(ModelRun).filter_by(domain=domain).order_by(ModelRun.created_at.desc()).first()
        rows = stored_readings(db, domain)
        cutoff = run.output.get('details', {}).get('train_end_exclusive') if run else None
        if not rows or not cutoff:
            db.add(BaselineDeployment(domain=domain, active_id=None, history=[]))
            continue
        end = stamp(cutoff)
        training = valid_rows([r for r in rows if stamp(r['timestamp']) + timedelta(minutes=r['interval_minutes']) <= end], domain)
        if not training:
            db.add(BaselineDeployment(domain=domain, active_id=None, history=[]))
            continue
        ident = uid()
        baseline = BaselineVersion(id=ident, domain=domain, algorithm=MODEL_VERSION, status='legacy', training=training, checksum=checksum(training), train_start=min(r['timestamp'] for r in training), train_end=end.isoformat(), evaluation={'status': 'existing_baseline', 'note': 'Captured existing baseline; not a newly evaluated candidate.'}, reason='Preserve the existing historical baseline for explicit future promotion and rollback.')
        db.add(baseline)
        db.flush()
        output = label_output(run.output, baseline)
        db.add(ModelRun(domain=domain, dataset_id=run.dataset_id, model_version=ident, output=output))
        db.add(BaselineDeployment(domain=domain, active_id=ident, history=[ident]))
    db.flush()


def label_output(output, baseline):
    result = copy.deepcopy(output)
    result['baseline_id'] = baseline.id
    result['details'] = {**result.get('details', {}), 'baseline_id': baseline.id, 'training_checksum': baseline.checksum, 'baseline_train_end': baseline.train_end}
    for finding in result.get('findings', []):
        finding['evidence'] = {**finding.get('evidence', {}), 'baseline_id': baseline.id}
    return result


def analyze_version(domain, rows, baseline, **kwargs):
    from services.analytics.pipeline import MODEL_VERSION, analyze_consumption
    if baseline.algorithm != MODEL_VERSION or checksum(baseline.training) != baseline.checksum:
        raise ValueError('Baseline artifact is incompatible or its checksum changed.')
    return label_output(analyze_consumption(rows, domain, train_end=baseline.train_end, training_readings=baseline.training, **kwargs), baseline)


def evaluate_candidate(db, ident):
    candidate = db.get(BaselineVersion, ident)
    if candidate.status != 'pending':
        return {'baseline_id': ident, 'status': candidate.status}
    rows = stored_readings(db, candidate.domain)
    try:
        blocked, _ = blocked_readings(db, candidate.domain, candidate.training)
        if blocked:
            raise ValueError('New unresolved evidence overlaps training. Prepare another candidate.')
        parent = db.get(BaselineVersion, candidate.parent_id) if candidate.parent_id else None
        expected_assets = registered_meters(db, candidate.domain)
        config = db.get(Configuration, 'platform')
        config_value = config.value if config else {}
        thresholds = {'voltage_lower_v': config_value.get('voltage_lower_v', 207), 'voltage_upper_v': config_value.get('voltage_upper_v', 253)}
        output = analyze_version(candidate.domain, rows, candidate, expected_assets=expected_assets, **thresholds)
        prior = analyze_version(candidate.domain, rows, parent, expected_assets=expected_assets, **thresholds) if parent else None
        start = max(stamp(candidate.train_end), stamp(parent.train_end)) if parent else stamp(candidate.train_end)
        excluded, cases = blocked_readings(db, candidate.domain, rows)
        scores = {r['id']: r for r in output['_rows'] if r['valid'] and stamp(r['timestamp']) >= start and r['id'] not in excluded}
        previous = {r['id']: r for r in prior['_rows']} if prior else {}
        if parent:
            scores = {ident: row for ident, row in scores.items() if ident in previous}
        assets = sorted({r['asset_id'] for r in rows})
        if any(sum(r['asset_id'] == asset for r in scores.values()) < 24 for asset in assets):
            raise ValueError('Evaluation needs at least 24 later valid intervals per asset outside unresolved incident periods.')
        def metric(values):
            errors = [r['actual'] - r['expected'] for r in values]
            return {'mae': sum(abs(e) for e in errors)/len(errors), 'rmse': math.sqrt(sum(e*e for e in errors)/len(errors))}
        evaluation = {'status': 'evaluated', 'candidate': metric(scores.values()), 'previous': metric([previous[ident] for ident in scores]) if parent else None, 'intervals': len(scores), 'per_asset_intervals': {asset: sum(r['asset_id'] == asset for r in scores.values()) for asset in assets}, 'start': start.isoformat(), 'end': max(r['timestamp'] for r in scores.values()), 'dataset_checksum': checksum(rows), 'excluded_case_ids': cases, 'unit': 'L / interval' if candidate.domain == 'water' else 'kWh / interval', 'limitation': 'Chronological baseline residual error on unlabeled observations; not anomaly accuracy or proof that all evaluation periods are normal.'}
        candidate.evaluation, candidate.status = evaluation, 'evaluated'
        output.pop('_rows', None)
        output['baseline_evaluation'] = evaluation
        db.add(ModelRun(domain=candidate.domain, model_version=candidate.id, dataset_id=evaluation['dataset_checksum'], output=output))
    except ValueError as exc:
        candidate.status, candidate.evaluation = 'rejected', {'status': 'rejected', 'reason': str(exc)}
    return {'baseline_id': ident, 'status': candidate.status, 'evaluation': candidate.evaluation}


def public_version(version):
    return {**{key: getattr(version, key) for key in ('id', 'domain', 'algorithm', 'parent_id', 'status', 'checksum', 'train_start', 'train_end', 'evaluation', 'exclusions', 'created_by', 'reason', 'created_at')}, 'training_rows': len(version.training)}


@router.get('/{domain}')
def registry(domain: Domain, user=Depends(current_user), db=Depends(get_db)):
    authorized(db, user, domain)
    deployment = db.get(BaselineDeployment, domain)
    rows = stored_readings(db, domain)
    earliest = min((stamp(r['timestamp']) for r in rows), default=None)
    latest = max((stamp(r['timestamp']) for r in rows), default=None)
    versions = db.query(BaselineVersion).filter_by(domain=domain).order_by(BaselineVersion.created_at.desc()).all()
    decisions = [a for a in db.query(Audit).filter(Audit.action.in_(['baseline_candidate', 'baseline_promote', 'baseline_rollback'])).order_by(Audit.created_at.desc()).all() if a.after.get('domain') == domain]
    jobs = {j.parameters.get('baseline_id'): j for j in db.query(Job).filter_by(kind='baseline_candidate').all()}
    return {'active_id': deployment.active_id if deployment else None, 'version': deployment.version if deployment else 0, 'history': deployment.history if deployment else [], 'can_activate': user.role == 'admin', 'versions': [{**public_version(v), 'job_status': jobs[v.id].status if v.id in jobs else None, 'job_error': jobs[v.id].error if v.id in jobs else None} for v in versions], 'suggested_start': (earliest + timedelta(days=7)).isoformat() if earliest else None, 'suggested_end': min(earliest + timedelta(days=42), latest - timedelta(days=2)).isoformat() if earliest else None, 'decisions': [{key: getattr(a, key) for key in ('id', 'action', 'actor_id', 'reason', 'before', 'after', 'created_at')} for a in decisions[:30]]}


class CandidateBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    train_start: str
    train_end: str
    reason: str = Field(min_length=5, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=100)


@router.post('/{domain}/candidates', status_code=202)
def create_candidate(domain: Domain, body: CandidateBody, user=Depends(current_user), db=Depends(get_db)):
    authorized(db, user, domain)
    if not body.reason.strip():
        raise HTTPException(422, 'A review reason is required.')
    parameters = body.model_dump(exclude={'idempotency_key'}) | {'domain': domain}
    key = user.id + ':baseline:' + body.idempotency_key
    existing = db.query(Job).filter_by(dedupe_key=key).first()
    if existing:
        if {k: v for k, v in existing.parameters.items() if k != 'baseline_id'} != parameters:
            raise HTTPException(409, 'This request key belongs to different training parameters.')
        return {'job_id': existing.id, 'baseline_id': existing.parameters['baseline_id']}
    from services.analytics.pipeline import MODEL_VERSION
    try:
        start, end = stamp(body.train_start), stamp(body.train_end)
        if end - start < timedelta(days=14):
            raise ValueError('Choose at least 14 days of training before the evaluation period.')
        rows = stored_readings(db, domain)
        selected = [r for r in rows if stamp(r['timestamp']) >= start and stamp(r['timestamp']) + timedelta(minutes=r['interval_minutes']) <= end]
        blocked, cases = blocked_readings(db, domain, selected)
        training = valid_rows([r for r in selected if r['id'] not in blocked], domain)
        assets = {r['asset_id'] for r in rows}
        if not assets or any(sum(r['interval_minutes'] for r in training if r['asset_id'] == asset) < 14*24*60 or sum(r['asset_id'] == asset for r in training) < 168 for asset in assets):
            raise ValueError('Each asset needs at least 14 days and 168 valid training intervals after exclusions.')
        if end > max(stamp(r['timestamp']) for r in rows) - timedelta(hours=24):
            raise ValueError('Leave at least 24 hours of later observations for evaluation.')
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    deployment = db.get(BaselineDeployment, domain)
    if not deployment:
        raise HTTPException(409, 'Restart the service to initialize the baseline registry.')
    ident = uid()
    candidate = BaselineVersion(id=ident, domain=domain, algorithm=MODEL_VERSION, parent_id=deployment.active_id, training=training, checksum=checksum(training), train_start=start.isoformat(), train_end=end.isoformat(), reason=body.reason, created_by=user.id, exclusions={'reading_count': len(blocked), 'case_ids': cases, 'invalid_or_inactive_count': len(selected)-len(blocked)-len(training)})
    db.add(candidate)
    job = Job(id=uid(), user_id=user.id, kind='baseline_candidate', parameters={**parameters, 'baseline_id': ident}, dedupe_key=key)
    db.add(job)
    audit(db, user, None, 'baseline_candidate', body.reason, after={'domain': domain, 'baseline_id': ident, 'checksum': candidate.checksum})
    db.commit()
    return {'job_id': job.id, 'baseline_id': ident}


class ActivationBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    baseline_id: str
    version: int = Field(ge=1)
    reason: str = Field(min_length=5, max_length=2000)


@router.post('/{domain}/{action}')
def activate(domain: Domain, action: Literal['promote', 'rollback'], body: ActivationBody, user=Depends(current_user), db=Depends(get_db)):
    require_admin(user)
    deployment = db.get(BaselineDeployment, domain)
    baseline = db.get(BaselineVersion, body.baseline_id)
    if not body.reason.strip():
        raise HTTPException(422, 'A review reason is required.')
    if not deployment or not baseline or baseline.domain != domain:
        raise HTTPException(404, 'Baseline not found in this domain.')
    if baseline.id == deployment.active_id:
        raise HTTPException(409, 'This version is already active.')
    from services.analytics.pipeline import MODEL_VERSION
    if baseline.algorithm != MODEL_VERSION or checksum(baseline.training) != baseline.checksum:
        raise HTTPException(409, 'Incompatible or changed baseline artifact; activation refused.')
    if action == 'promote':
        if baseline.status != 'evaluated' or baseline.parent_id != deployment.active_id:
            raise HTTPException(409, 'Evaluate a candidate against the currently active baseline before promotion.')
        if blocked_readings(db, domain, baseline.training)[0]:
            raise HTTPException(409, 'Unresolved evidence now overlaps training; prepare another candidate.')
    elif baseline.id not in deployment.history:
        raise HTTPException(409, 'Rollback requires a previously active baseline.')
    before = {'active_id': deployment.active_id, 'version': deployment.version}
    history = list(dict.fromkeys([*deployment.history, baseline.id]))
    changed = db.execute(update(BaselineDeployment).where(BaselineDeployment.domain == domain, BaselineDeployment.version == body.version).values(active_id=baseline.id, version=body.version+1, history=history), execution_options={'synchronize_session': False})
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, 'Active baseline changed. Refresh before saving.')
    audit(db, user, None, 'baseline_'+action, body.reason, before=before, after={'domain': domain, 'active_id': baseline.id, 'version': body.version+1})
    db.commit()
    return {'active_id': baseline.id, 'version': body.version+1}
