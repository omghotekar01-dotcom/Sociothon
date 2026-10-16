"""Consistent SQLite backup, including WAL, with private evidence manifest."""
import argparse
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import shutil
import sqlite3

def create_backup(source, destination):
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if not source.is_file():
        raise ValueError("Source database does not exist.")
    if destination.exists():
        raise ValueError("Backup destination must be a new directory.")
    evidence = source.parent / "private-evidence"
    if evidence.is_symlink() or (evidence.exists() and any(p.is_symlink() for p in evidence.rglob("*"))):
        raise ValueError("Linked evidence paths are unsupported.")
    if destination == evidence or evidence in destination.parents:
        raise ValueError("Backup cannot be inside evidence.")
    destination.mkdir(parents=True)
    with sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True) as live, sqlite3.connect(destination / "civicsignal.db") as backup:
        live.backup(backup)
        if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Database integrity check failed.")
    if evidence.is_dir():
        shutil.copytree(evidence, destination / "private-evidence")
    files = {p.relative_to(destination).as_posix(): {"bytes": p.stat().st_size, "sha256": digest(p)} for p in sorted(destination.rglob("*")) if p.is_file()}
    manifest = {"schema": 1, "created_at": datetime.now(timezone.utc).isoformat(), "private_data": True, "files": files}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser(description="Stop services before backing up database and evidence.")
    parser.add_argument("--source", default="data/civicsignal.db")
    parser.add_argument("--destination", required=True)
    args = parser.parse_args()
    try:
        create_backup(args.source, args.destination)
    except (ValueError, OSError, sqlite3.Error) as error:
        raise SystemExit(str(error)) from error
    print("Private backup created. Keep it out of version control.")


if __name__ == "__main__":
    main()
