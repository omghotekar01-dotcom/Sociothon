import os
from pathlib import Path
import tempfile

TEST_ROOT = Path(__file__).resolve().parents[1] / ".runtime" / "tests"
TEST_ROOT.mkdir(parents=True, exist_ok=True)
os.environ["CIVIC_DATA_DIR"] = tempfile.mkdtemp(prefix="suite-", dir=TEST_ROOT)
os.environ["DATABASE_URL"] = "sqlite:///" + (Path(os.environ["CIVIC_DATA_DIR"]) / "test.db").as_posix()
os.environ["CIVIC_DEMO_MODE"] = "true"

import pytest
from fastapi.testclient import TestClient
from services.api.main import app
from services.api.security import _attempts

@pytest.fixture(scope="session")
def server():
    with TestClient(app) as client:
        yield client

@pytest.fixture(autouse=True)
def isolated_rate_window():
    _attempts.clear()

@pytest.fixture
def login(server):
    def signin(role):
        client = TestClient(app)
        response = client.post("/api/v1/auth/login", json={"email": role + "@civicsignal.local", "password": "CivicDemo!2026"})
        assert response.status_code == 200, response.text
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        return client
    return signin
