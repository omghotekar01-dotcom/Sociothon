"""Exercise the documented launcher with a fresh isolated SQLite database.

Requires installed Python dependencies and a built frontend. All writes are in a
new .runtime directory; existing application databases and servers are untouched.
"""
import argparse
from datetime import datetime, timezone
import http.cookiejar
import json
import os
from pathlib import Path
import re
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def database_snapshot(path):
    with sqlite3.connect(path) as db:
        tables = db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        return {name: sorted(db.execute(f'SELECT * FROM "{name}"').fetchall(), key=repr) for (name,) in tables}


def wait_until(check, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.25)
    raise TimeoutError("Local service verification timed out")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="artifacts/verification/fresh-start-results.json")
    args = parser.parse_args()
    runtime = ROOT / ".runtime"
    runtime.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="fresh-start-", dir=runtime))
    db_path = work / "data" / "civicsignal.db"
    env = {**os.environ, "CIVIC_DATA_DIR": str(db_path.parent), "DATABASE_URL": f"sqlite:///{db_path.as_posix()}", "CIVIC_DEMO_MODE": "true", "COOKIE_SECURE": "false"}
    report = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "python": sys.version, "workspace": str(ROOT), "data_directory": str(db_path.parent), "checks": []}
    started = time.monotonic()
    process = None
    log = (work / "services.log").open("w", encoding="utf-8")
    # Reserving and releasing an ephemeral loopback port leaves existing servers alone.
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    csrf = ""

    def record(name, **details):
        report["checks"].append({"name": name, "status": "passed", **details})
        print(f"PASS: {name}", flush=True)

    def command(*parts):
        subprocess.run([sys.executable, *parts], cwd=ROOT, env=env, stdout=log, stderr=log, check=True, timeout=180)

    def request(path, body=None):
        headers = {"X-CSRF-Token": csrf}
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
        with opener.open(req, timeout=15) as response:
            content = response.read()
            return json.loads(content) if "application/json" in response.headers.get("Content-Type", "") else content

    def launch():
        nonlocal process
        process = subprocess.Popen([sys.executable, "scripts/run.py", "--port", str(port)], cwd=ROOT, env=env, stdout=log, stderr=log, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
        def ready():
            if process.poll() is not None:
                raise RuntimeError(f"Launcher exited {process.returncode}; see {log.name}")
            try:
                return request("/api/v1/health")
            except (OSError, urllib.error.URLError):
                return None
        assert wait_until(ready)["status"] == "ok"

    def stop():
        nonlocal process
        if process is None:
            return
        if process.poll() is None:
            process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
        code = process.wait(timeout=25)
        process = None
        if code != 0:
            raise RuntimeError(f"Launcher failed during requested shutdown: {code}")
        def closed():
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    return False
            except OSError:
                return True
        wait_until(closed, 10)

    def login(role):
        nonlocal csrf
        session = request("/api/v1/auth/login", {"email": f"{role}@civicsignal.local", "password": "CivicDemo!2026"})
        csrf = session["csrf_token"]
        assert session["user"]["role"] == role

    try:
        command("-m", "database.migrations")
        command("-m", "services.api.seed")
        first = database_snapshot(db_path)
        assert len(first["users"]) == 5 and len(first["readings"]) > 0 and len(first["cases"]) > 0
        record("fresh migrations and synthetic seed", table_counts={name: len(rows) for name, rows in first.items()})
        command("-m", "database.migrations")
        command("-m", "services.api.seed")
        assert database_snapshot(db_path) == first, "Repeating migrations/seed changed persisted rows"
        record("repeat migrations and seed preserve every existing row")
        launch()
        html = request("/").decode()
        assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html)
        assert assets, "Built frontend did not reference bundled assets"
        for asset in assets:
            assert request(asset)
        record("documented launcher serves API and built local frontend", bundled_assets=len(assets))
        login("citizen")
        body = {"domain": "general", "zone_id": "river", "title": "Isolated startup verification", "description": "Synthetic verification record in a dedicated temporary database.", "location": "Synthetic public facility", "idempotency_key": "startup-verification-report"}
        receipt = request("/api/v1/reports", body)
        assert request("/api/v1/reports", body)["id"] == receipt["id"]
        record("authenticated report persists once after duplicate submission")
        login("operator")
        job = request("/api/v1/scenarios", {"domain": "roads", "scenario": "pothole", "idempotency_key": "startup-verification-job"})
        def completed():
            current = request("/api/v1/jobs/" + job["id"])
            if current["status"] == "failed":
                raise RuntimeError(f"Worker job failed: {current.get('error')}")
            return current if current["status"] == "succeeded" else None
        result = wait_until(completed)
        assert result["result"]
        record("separate durable worker processes queued scenario", job_id=job["id"])
        stop()
        record("requested shutdown closes API listener")
        launch()
        assert request("/api/v1/auth/me")["user"]["role"] == "operator"
        assert request("/api/v1/jobs/" + job["id"])["result"] == result["result"]
        login("citizen")
        assert request("/api/v1/reports/" + receipt["id"])["receipt"] == receipt["receipt"]
        record("service restart preserves session report receipt and completed job")
        stop()
        # Exercise a real startup error: the launcher must fail and reap its worker.
        with socket.socket() as occupied:
            # A just-closed listener can remain in TIME_WAIT on Linux. Reserve a
            # fresh port so the test measures the launcher's occupied-port error.
            occupied.bind(("127.0.0.1", 0))
            occupied_port = occupied.getsockname()[1]
            occupied.listen()
            failed = subprocess.run([sys.executable, "scripts/run.py", "--port", str(occupied_port)], cwd=ROOT, env=env, stdout=log, stderr=log, timeout=45)
            assert failed.returncode != 0, "Occupied-port startup incorrectly reported success"
        record("occupied-port startup returns failure", exit_code=failed.returncode)
        report["status"] = "passed"
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        raise
    finally:
        try:
            stop()
        finally:
            log.close()
            report["duration_seconds"] = round(time.monotonic() - started, 2)
            report["service_log"] = str(work / "services.log")
            output = ROOT / args.output
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(f"Verification evidence: {output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
