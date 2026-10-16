from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.database import Base
from services.api.domain import notify_overdue
from services.api.models import Case, Notification, User, Zone


def test_review_deadline_notifies_scoped_staff_once_and_skips_closed_or_future_cases():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    now = datetime.now(timezone.utc)
    try:
        session.add_all([
            Zone(id="river", name="River Ward"),
            Zone(id="market", name="Market Ward"),
            User(id="river-operator", name="River operator", email="river@example.test", password_hash="unused", role="operator", domains=["water"], zones=["river"], settings={}),
            User(id="market-operator", name="Market operator", email="market@example.test", password_hash="unused", role="operator", domains=["water"], zones=["market"], settings={}),
        ])
        due = now - timedelta(hours=1)
        future = now + timedelta(hours=4)
        def case(ident, status, deadline):
            return Case(id=ident, event_key=ident, title=ident, domain="water", zone_id="river", severity="medium", status=status, summary="Synthetic test", provenance="Reported", priority=50, evidence={}, deadline_at=deadline.isoformat())
        session.add_all([
            case("overdue-open", "needs_review", due),
            case("overdue-closed", "closed", due),
            case("future-open", "investigating", future),
        ])
        session.commit()

        notify_overdue(session)
        session.commit()
        notifications = session.query(Notification).all()
        assert [(note.user_id, note.case_id) for note in notifications] == [("river-operator", "overdue-open")]
        assert "Review overdue" in notifications[0].title

        notify_overdue(session)
        session.commit()
        assert session.query(Notification).count() == 1
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()
