from sqlalchemy import create_engine, inspect, select, text
import pytest

from database.migrations import BASELINE, EVIDENCE_KEYS, CASE_INSPECTORS, BASELINE_VERSIONS, JOB_CONTROLS, SCENARIO_PLAYBACK, DEMO_SESSION_ISOLATION, migrate
from services.api.database import Base
from services.api.models import Case, ModelRun, Zone


@pytest.mark.parametrize('with_supporting_table', [False, True])
def test_schema_upgrade_preserves_cases_and_model_outputs(with_supporting_table):
    engine = create_engine('sqlite:///:memory:')
    # Reproduce the schema at revision 0002 without creating the new join table.
    with engine.begin() as connection:
        excluded = {'baseline_versions', 'baseline_deployments'} | (set() if with_supporting_table else {'case_inspectors'})
        Base.metadata.create_all(connection, tables=[table for table in Base.metadata.sorted_tables if table.name not in excluded])
        connection.execute(text('CREATE TABLE schema_migrations (revision VARCHAR(100) PRIMARY KEY, applied_at VARCHAR(100) NOT NULL)'))
        for revision in (BASELINE, EVIDENCE_KEYS, CASE_INSPECTORS) if with_supporting_table else (BASELINE, EVIDENCE_KEYS):
            connection.execute(text('INSERT INTO schema_migrations VALUES (:revision, :at)'), {'revision': revision, 'at': '2026-10-14'})
        connection.execute(Zone.__table__.insert().values(id='legacy-zone', name='Existing zone'))
        connection.execute(Case.__table__.insert().values(id='legacy-case', event_key='legacy-event', title='Existing case', domain='water', zone_id='legacy-zone', severity='medium', summary='Preserve existing evidence', provenance='Synthetic', version=7, evidence={'existing': True}))
        before = connection.execute(select(Case.__table__)).mappings().one()
        connection.execute(ModelRun.__table__.insert().values(id='old-run', domain='water', dataset_id='old-data', model_version='old-model', output={'preserved': True}))
    migrate(engine, Base.metadata)
    migrate(engine, Base.metadata)
    with engine.connect() as connection:
        assert connection.execute(select(Case.__table__)).mappings().one() == before
        assert 'case_inspectors' in inspect(connection).get_table_names()
        assert connection.execute(text('SELECT count(*) FROM case_inspectors')).scalar_one() == 0
        assert connection.execute(text('SELECT count(*) FROM schema_migrations WHERE revision=:revision'), {'revision': CASE_INSPECTORS}).scalar_one() == 1
        assert connection.execute(text('SELECT count(*) FROM schema_migrations WHERE revision=:revision'), {'revision': BASELINE_VERSIONS}).scalar_one() == 1
        assert {'baseline_versions', 'baseline_deployments'} <= set(inspect(connection).get_table_names())
        assert 'scenario_playbacks' in inspect(connection).get_table_names()
        assert connection.execute(text('SELECT count(*) FROM schema_migrations WHERE revision=:revision'), {'revision': SCENARIO_PLAYBACK}).scalar_one() == 1
        assert connection.execute(text('SELECT count(*) FROM schema_migrations WHERE revision=:revision'), {'revision': DEMO_SESSION_ISOLATION}).scalar_one() == 1
        assert "demo_sessions" in inspect(connection).get_table_names()
        for table_name in ("sessions", "jobs", "cases", "audit_events"):
            assert "demo_session_id" in {column["name"] for column in inspect(connection).get_columns(table_name)}
        assert connection.execute(select(ModelRun.__table__.c.output)).scalar_one() == {'preserved': True}
    engine.dispose()


def test_job_control_upgrade_preserves_queued_and_finished_records():
    engine=create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE schema_migrations (revision VARCHAR(100) PRIMARY KEY, applied_at VARCHAR(100) NOT NULL)'))
        for revision in (BASELINE,EVIDENCE_KEYS,CASE_INSPECTORS,BASELINE_VERSIONS):
            connection.execute(text('INSERT INTO schema_migrations VALUES (:revision, :at)'),{'revision':revision,'at':'2026-10-15'})
        connection.execute(text('CREATE TABLE jobs (id VARCHAR PRIMARY KEY, status VARCHAR NOT NULL, result JSON)'))
        connection.execute(text("INSERT INTO jobs VALUES ('queued-job','queued',NULL), ('done-job','succeeded',:result)"), {'result':'{"preserved":true}'})
        before=connection.execute(text('SELECT id,status,result FROM jobs ORDER BY id')).all()
    migrate(engine,Base.metadata)
    migrate(engine,Base.metadata)
    with engine.connect() as connection:
        assert connection.execute(text('SELECT id,status,result FROM jobs ORDER BY id')).all()==before
        assert connection.execute(text('SELECT control_version FROM jobs')).scalars().all()==[1,1]
        assert connection.execute(text('SELECT count(*) FROM jobs WHERE checkpoint IS NOT NULL OR claim_token IS NOT NULL')).scalar_one()==0
        assert connection.execute(text('SELECT count(*) FROM schema_migrations WHERE revision=:revision'),{'revision':JOB_CONTROLS}).scalar_one()==1
        assert 'scenario_playbacks' in inspect(connection).get_table_names()
        assert 'demo_sessions' in inspect(connection).get_table_names()
        assert connection.execute(text('SELECT count(*) FROM schema_migrations WHERE revision=:revision'),{'revision':SCENARIO_PLAYBACK}).scalar_one()==1
        assert connection.execute(text('SELECT count(*) FROM schema_migrations WHERE revision=:revision'),{'revision':DEMO_SESSION_ISOLATION}).scalar_one()==1
        assert 'demo_session_id' in {column['name'] for column in inspect(connection).get_columns('jobs')}
    engine.dispose()
