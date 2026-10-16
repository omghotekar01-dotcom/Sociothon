import hashlib
import hmac
import os
import secrets
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request, Response
from .database import get_db
from .models import DemoSession, Session, User, now

DEMO_MODE = os.getenv("CIVIC_DEMO_MODE", "true").lower() == "true"
SECURE_COOKIES = os.getenv("COOKIE_SECURE", "false").lower() == "true"
COOKIE_NAME = "civic_session"
DEMO_COOKIE_NAME = "civic_demo_session"
DOMAINS = ["water", "electricity", "roads", "drainage", "waste", "streetlights", "general"]
_attempts = defaultdict(deque)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f"scrypt${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
        return hmac.compare_digest(candidate, digest)
    except (ValueError, TypeError):
        return False


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def ensure_demo_session(request, response, db):
    """Bind a login to a server-issued, browser-scoped demo namespace."""
    if not DEMO_MODE:
        return None
    raw = request.cookies.get(DEMO_COOKIE_NAME)
    demo_session = db.get(DemoSession, token_hash(raw)) if raw and len(raw) <= 128 else None
    if not demo_session or demo_session.expires_at <= time.time():
        raw = secrets.token_urlsafe(48)
        identity = token_hash(raw)
        demo_session = DemoSession(id=identity, created_at=now(), expires_at=time.time() + 8 * 3600)
        db.add(demo_session)
    else:
        demo_session.expires_at = time.time() + 8 * 3600
    response.set_cookie(DEMO_COOKIE_NAME, raw, httponly=True, secure=SECURE_COOKIES, samesite="strict", max_age=8 * 3600, path="/")
    return demo_session.id


def rate_limit(key, maximum=20, period=60):
    clock = time.time()
    queue = _attempts[key]
    while queue and queue[0] < clock - period:
        queue.popleft()
    if len(queue) >= maximum:
        raise HTTPException(429, "Too many attempts. Please wait and retry.", headers={"Retry-After": str(period)})
    queue.append(clock)


def current_user(request: Request, response: Response, db=Depends(get_db)):
    raw = request.cookies.get(COOKIE_NAME)
    session = db.get(Session, token_hash(raw)) if raw else None
    if not session or session.expires_at <= time.time():
        raise HTTPException(401, "Please sign in to continue.")
    user = db.get(User, session.user_id)
    if not user or not user.active:
        raise HTTPException(401, "Your session is no longer active.")
    if DEMO_MODE:
        demo_session = db.get(DemoSession, session.demo_session_id) if session.demo_session_id else None
        if not demo_session or demo_session.expires_at <= time.time():
            session.demo_session_id = ensure_demo_session(request, response, db)
            db.commit()
        user._demo_session_id = session.demo_session_id
    else:
        user._demo_session_id = None
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), session.csrf):
            raise HTTPException(403, "Security token missing or expired. Refresh and try again.")
        origin = request.headers.get("Origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            from urllib.parse import urlparse
            if urlparse(origin).netloc != request.headers.get("host"):
                raise HTTPException(403, "Cross-origin mutation rejected.")
    request.state.session = session
    return user


def require_staff(user):
    if user.role not in {"operator", "admin"}:
        raise HTTPException(403, "Operator or administrator access required.")


def require_admin(user):
    if user.role != "admin":
        raise HTTPException(403, "Administrator access required.")


def in_scope(user, domain, zone_id):
    return user.role == "admin" or (domain in user.domains and zone_id in user.zones)


def can_case(user, case):
    if case.demo_session_id and case.demo_session_id != getattr(user, "_demo_session_id", None):
        return False
    return user.role == "admin" or (user.role == "operator" and in_scope(user, case.domain, case.zone_id) and (not case.demo_owner_id or case.demo_owner_id == user.id)) or (user.role == "inspector" and (case.assigned_to == user.id or user.id in case.secondary_assignees) and in_scope(user, case.domain, case.zone_id))


def public_user(user):
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role, "domains": user.domains, "zones": user.zones, "settings": user.settings}
