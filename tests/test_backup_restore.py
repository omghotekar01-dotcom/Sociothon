import sqlite3
import pytest
from scripts.backup import create_backup
from scripts.restore import restore_backup


def test_backup_restore_preserves_database_and_private_evidence(tmp_path):
    source=tmp_path/'original';source.mkdir()
    with sqlite3.connect(source/'civicsignal.db') as db:
        db.execute('CREATE TABLE records (id INTEGER PRIMARY KEY, note TEXT)')
        db.execute("INSERT INTO records VALUES (1,'Retain this evidence')")
    evidence=source/'private-evidence';evidence.mkdir();(evidence/'example.bin').write_bytes(b'private synthetic test bytes')
    backup=tmp_path/'backup'
    manifest=create_backup(source/'civicsignal.db',backup)
    assert len(manifest['files'])==2
    restored=tmp_path/'restored'
    assert restore_backup(backup,restored)['files_verified']==2
    with sqlite3.connect(restored/'civicsignal.db') as db:
        assert db.execute('SELECT note FROM records').fetchone()[0]=='Retain this evidence'
    assert (restored/'private-evidence'/'example.bin').read_bytes()==b'private synthetic test bytes'
    with pytest.raises(ValueError,match='new directory'):
        restore_backup(backup,source)
    (backup/'private-evidence'/'example.bin').write_bytes(b'changed')
    with pytest.raises(ValueError,match='checksum'):
        restore_backup(backup,tmp_path/'corrupted')
    assert not (tmp_path/'corrupted').exists()
