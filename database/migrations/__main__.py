from sqlalchemy import text
from services.api.database import engine, init_db

init_db()
with engine.connect() as connection:
    revisions = connection.execute(text("SELECT revision FROM schema_migrations ORDER BY revision")).scalars().all()
print(f"CivicSignal 360 schema is up to date: {revisions[-1]} ({len(revisions)} revisions applied)")
