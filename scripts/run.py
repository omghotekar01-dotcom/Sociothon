"""Launch the same-origin API/web app and durable analytics worker locally."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]


def running_app(url):
    """Recognize our public endpoint without requiring a signed-in browser."""
    try:
        with urllib.request.urlopen(url + "/api/v1/public", timeout=2) as response:
            return json.load(response).get("name") == "CivicSignal 360"
    except (urllib.error.URLError, OSError, ValueError, AttributeError):
        return False


def main():
    parser = argparse.ArgumentParser(description="CivicSignal 360 local services")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument("--no-worker", action="store_true")
    parser.add_argument("--open-browser", action="store_true", help="Open the local preview when ready; reuse an already running app")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    os.chdir(ROOT)
    url = f"http://{args.host}:{args.port}"
    if args.open_browser and running_app(url):
        print(f"CivicSignal 360 is already running: {url}", flush=True)
        webbrowser.open(url)
        return 0
    if not (ROOT / "apps/web/dist/index.html").exists():
        print("Frontend build missing. Run: pnpm --dir apps/web build", file=sys.stderr)
        return 1
    # Complete migrations/seed before either process can claim jobs or initialize
    # the schema. This also gives a failed setup a clear nonzero exit status.
    initialized = subprocess.run([sys.executable, "-m", "services.api.seed"])
    if initialized.returncode:
        return initialized.returncode
    children = []
    shutdown_requested = False
    def stop(*_):
        nonlocal shutdown_requested
        shutdown_requested = True
        for process in children:
            if process.poll() is None:
                process.terminate()

    signal.signal(signal.SIGTERM, stop)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, stop)
    exit_code = 0
    try:
        children.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "services.api.main:app", "--host", args.host, "--port", str(args.port)]))
        if not args.no_worker:
            children.append(subprocess.Popen([sys.executable, "-m", "services.api.worker"]))
        print(f"CivicSignal 360 starting: http://{args.host}:{args.port}", flush=True)
        print("Independent hackathon prototype — synthetic local demonstration. Ctrl+C stops both services.", flush=True)
        browser_opened = False
        while all(process.poll() is None for process in children):
            if args.open_browser and not browser_opened and running_app(url):
                browser_opened = True
                webbrowser.open(url)
            time.sleep(0.5)
        if not shutdown_requested:
            failed = next(process for process in children if process.poll() is not None)
            exit_code = failed.returncode if failed.returncode and failed.returncode > 0 else 1
            print(f"A required service stopped unexpectedly (exit {failed.returncode}); stopping the other services.", file=sys.stderr, flush=True)
    except KeyboardInterrupt:
        pass
    except OSError as exc:
        print(f"Unable to launch local services: {exc}", file=sys.stderr)
        exit_code = 1
    finally:
        stop()
        for process in children:
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=8)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
