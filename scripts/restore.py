"""Verify a backup and restore into a NEW directory; never overwrite live data."""
import argparse
import json
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
from scripts.backup import digest


def restore_backup(source,destination):
    source=Path(source).resolve()
    destination=Path(destination).resolve()
    if destination.exists():
        raise ValueError('Restore destination must be a new directory; existing data is never overwritten.')
    if source == destination or source in destination.parents:
        raise ValueError('Restore outside the backup directory.')
    if any(p.is_symlink() for p in source.rglob('*')):
        raise ValueError('Backup contains linked paths; restoration refused.')
    manifest=json.loads((source/'manifest.json').read_text(encoding='utf-8'))
    files=manifest.get('files',{})
    if manifest.get('schema')!=1 or not isinstance(files,dict) or 'civicsignal.db' not in files:
        raise ValueError('This backup has no supported checksum inventory. Create a new verified backup.')
    actual={p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file() and p.relative_to(source).as_posix()!='manifest.json'}
    if actual!=set(files):
        raise ValueError('Backup file inventory differs from the manifest.')
    for relative,entry in files.items():
        path=PurePosixPath(relative)
        if path.is_absolute() or '..' in path.parts or '\\' in relative or ':' in relative or (relative!='civicsignal.db' and not relative.startswith('private-evidence/')):
            raise ValueError('Unsafe path in backup manifest.')
        file=source.joinpath(*path.parts)
        if file.stat().st_size!=entry['bytes'] or digest(file)!=entry['sha256']:
            raise ValueError('Backup checksum failed. No restored directory was created.')
    with sqlite3.connect(f'{(source/"civicsignal.db").as_uri()}?mode=ro',uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise ValueError('Backup database integrity check failed.')
    destination.mkdir(parents=True)
    for relative in files:
        target=destination.joinpath(*PurePosixPath(relative).parts)
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source.joinpath(*PurePosixPath(relative).parts),target)
    return {'status':'restored','files_verified':len(files)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True)
    parser.add_argument('--destination',required=True)
    args=parser.parse_args()
    try:
        result=restore_backup(args.source,args.destination)
    except (ValueError,OSError,KeyError,TypeError,sqlite3.Error) as error:
        raise SystemExit(str(error)) from error
    print(f"Restored {result['files_verified']} verified files. Set CIVIC_DATA_DIR to the restored directory before starting.")


if __name__=='__main__':
    main()
