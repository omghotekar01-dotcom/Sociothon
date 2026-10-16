import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest
from fastapi import HTTPException

from services.api import main as api_main
from services.api import security


ROOT = Path(__file__).resolve().parents[1]


def _seed_in_isolated_directory(data_dir, *, demo, email=None, password=None):
    env = os.environ.copy()
    for key in ("DATABASE_URL", "CIVIC_DATA_DIR", "CIVIC_ADMIN_EMAIL", "CIVIC_ADMIN_PASSWORD"):
        env.pop(key, None)
    env["CIVIC_DATA_DIR"] = str(data_dir)
    env["CIVIC_DEMO_MODE"] = "true" if demo else "false"
    if email is not None:
        env["CIVIC_ADMIN_EMAIL"] = email
    if password is not None:
        env["CIVIC_ADMIN_PASSWORD"] = password
    return subprocess.run(
        [sys.executable, "-m", "services.api.seed"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.mark.parametrize("password", [None, "CivicDemo!2026", "short"])
def test_non_demo_seed_rejects_missing_default_or_weak_admin_password(tmp_path, password):
    result = _seed_in_isolated_directory(
        tmp_path,
        demo=False,
        email="admin@example.test",
        password=password,
    )

    assert result.returncode != 0
    assert "Non-demo setup requires CIVIC_ADMIN_EMAIL and a unique CIVIC_ADMIN_PASSWORD" in result.stderr


def test_non_demo_seed_creates_only_configured_admin_and_rejects_mode_reuse(tmp_path):
    email = "deployment-admin@example.test"
    result = _seed_in_isolated_directory(
        tmp_path,
        demo=False,
        email=email,
        password="IsolatedDeploymentPassword2026!",
    )
    assert result.returncode == 0, result.stderr

    with sqlite3.connect(tmp_path / "civicsignal.db") as connection:
        accounts = connection.execute("SELECT email, role FROM users ORDER BY email").fetchall()
    assert accounts == [(email, "admin")]

    switched = _seed_in_isolated_directory(tmp_path, demo=True)
    assert switched.returncode != 0
    assert "Database mode differs from CIVIC_DEMO_MODE" in switched.stderr


def test_scenario_reset_handler_refuses_non_demo_mode(monkeypatch):
    monkeypatch.setattr(api_main, "DEMO_MODE", False)

    with pytest.raises(HTTPException) as blocked:
        api_main.reset_scenario("not-a-real-job", user=None, db=None)
    assert blocked.value.status_code == 403
    assert blocked.value.detail == "Synthetic reset is disabled outside demo mode."


def test_rate_limit_returns_retry_after_then_allows_expired_window(monkeypatch):
    clock = [1_000.0]
    key = "security-boundary-test"
    security._attempts.clear()
    monkeypatch.setattr(security.time, "time", lambda: clock[0])

    security.rate_limit(key, maximum=2, period=30)
    security.rate_limit(key, maximum=2, period=30)
    with pytest.raises(HTTPException) as blocked:
        security.rate_limit(key, maximum=2, period=30)
    assert blocked.value.status_code == 429
    assert blocked.value.headers["Retry-After"] == "30"

    clock[0] += 31
    security.rate_limit(key, maximum=2, period=30)
    assert len(security._attempts[key]) == 1
