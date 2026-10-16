"""Ordered, idempotent application migration registry.

The baseline creates the relational schema. Future schema changes must add a new
numbered migration; do not edit an applied revision. SQLite and PostgreSQL use
the same SQLAlchemy type mapping. This lightweight registry is not Alembic.
"""
from sqlalchemy import inspect, text

BASELINE = "0001_initial_schema"
EVIDENCE_KEYS = "0002_evidence_idempotency"
CASE_INSPECTORS = "0003_supporting_inspectors"
BASELINE_VERSIONS = "0004_baseline_versions"
JOB_CONTROLS = "0005_job_controls"
SCENARIO_PLAYBACK = "0006_scenario_playback"
DEMO_SESSION_ISOLATION = "0007_demo_session_isolation"
FIELD_OBSERVATIONS = "0008_field_observations"


def migrate(engine, metadata):
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (revision VARCHAR(100) PRIMARY KEY, applied_at VARCHAR(100) NOT NULL)"))
        applied = {r[0] for r in connection.execute(text("SELECT revision FROM schema_migrations"))}
        if applied - {BASELINE, EVIDENCE_KEYS, CASE_INSPECTORS, BASELINE_VERSIONS, JOB_CONTROLS, SCENARIO_PLAYBACK, DEMO_SESSION_ISOLATION, FIELD_OBSERVATIONS}:
            raise RuntimeError("Database schema is newer than this application; migration refused.")
        if BASELINE not in applied:
            from datetime import datetime, timezone
            metadata.create_all(connection)
            connection.execute(text("INSERT INTO schema_migrations (revision, applied_at) VALUES (:revision, :at)"), {"revision": BASELINE, "at": datetime.now(timezone.utc).isoformat()})
        if EVIDENCE_KEYS not in applied:
            from datetime import datetime, timezone
            columns = {column["name"] for column in inspect(connection).get_columns("evidence")}
            for column in ("content_hash", "idempotency_key"):
                if column not in columns:
                    connection.execute(text(f"ALTER TABLE evidence ADD COLUMN {column} VARCHAR"))
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_evidence_submission ON evidence (case_id, actor_id, idempotency_key)"))
            connection.execute(text("INSERT INTO schema_migrations (revision, applied_at) VALUES (:revision, :at)"), {"revision": EVIDENCE_KEYS, "at": datetime.now(timezone.utc).isoformat()})
        if CASE_INSPECTORS not in applied:
            from datetime import datetime, timezone
            metadata.tables["case_inspectors"].create(connection, checkfirst=True)
            connection.execute(text("INSERT INTO schema_migrations (revision, applied_at) VALUES (:revision, :at)"), {"revision": CASE_INSPECTORS, "at": datetime.now(timezone.utc).isoformat()})
        if BASELINE_VERSIONS not in applied:
            from datetime import datetime, timezone
            for name in ('baseline_versions', 'baseline_deployments'):
                metadata.tables[name].create(connection, checkfirst=True)
            connection.execute(text('INSERT INTO schema_migrations (revision, applied_at) VALUES (:revision, :at)'), {'revision': BASELINE_VERSIONS, 'at': datetime.now(timezone.utc).isoformat()})
        if JOB_CONTROLS not in applied:
            from datetime import datetime, timezone
            columns = {column['name'] for column in inspect(connection).get_columns('jobs')}
            for name, definition in [('claim_token', 'VARCHAR'), ('checkpoint', 'JSON'), ('control_version', 'INTEGER NOT NULL DEFAULT 1')]:
                if name not in columns:
                    connection.execute(text(f'ALTER TABLE jobs ADD COLUMN {name} {definition}'))
            connection.execute(text('INSERT INTO schema_migrations (revision, applied_at) VALUES (:revision, :at)'), {'revision': JOB_CONTROLS, 'at': datetime.now(timezone.utc).isoformat()})
        if SCENARIO_PLAYBACK not in applied:
            from datetime import datetime, timezone
            metadata.tables["scenario_playbacks"].create(connection, checkfirst=True)
            connection.execute(text('INSERT INTO schema_migrations (revision, applied_at) VALUES (:revision, :at)'), {'revision': SCENARIO_PLAYBACK, 'at': datetime.now(timezone.utc).isoformat()})
        if DEMO_SESSION_ISOLATION not in applied:
            from datetime import datetime, timezone
            metadata.tables["demo_sessions"].create(connection, checkfirst=True)
            tables = set(inspect(connection).get_table_names())
            for table_name in ("sessions", "jobs", "cases", "audit_events"):
                if table_name not in tables:
                    continue
                columns = {column["name"] for column in inspect(connection).get_columns(table_name)}
                if "demo_session_id" not in columns:
                    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN demo_session_id VARCHAR"))
            for table_name in ("sessions", "jobs", "cases", "audit_events"):
                if table_name in tables:
                    connection.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table_name}_demo_session_id ON {table_name} (demo_session_id)"))
            connection.execute(text('INSERT INTO schema_migrations (revision, applied_at) VALUES (:revision, :at)'), {'revision': DEMO_SESSION_ISOLATION, 'at': datetime.now(timezone.utc).isoformat()})


        if FIELD_OBSERVATIONS not in applied:
            from datetime import datetime, timezone
            if "evidence" in inspect(connection).get_table_names():
                columns = {column["name"] for column in inspect(connection).get_columns("evidence")}
                if "observations" not in columns:
                    connection.execute(text("ALTER TABLE evidence ADD COLUMN observations JSON NOT NULL DEFAULT '{}'"))
            connection.execute(text('INSERT INTO schema_migrations (revision, applied_at) VALUES (:revision, :at)'), {'revision': FIELD_OBSERVATIONS, 'at': datetime.now(timezone.utc).isoformat()})


if __name__ == "__main__":
    from services.api.database import init_db
    init_db()
