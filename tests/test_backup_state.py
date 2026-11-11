import sqlite3

import pytest

from clinagent.gateway.backup_state import backup_databases


def test_backup_includes_wal_and_can_be_restored(tmp_path):
    source = tmp_path / "auth.sqlite3"
    with sqlite3.connect(source) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE sample(value TEXT)")
        db.execute("INSERT INTO sample VALUES ('review')")
        db.commit()
        snapshot = backup_databases({"auth": source}, tmp_path / "backups")
    with sqlite3.connect(snapshot / "auth.sqlite3") as restored:
        assert restored.execute("SELECT value FROM sample").fetchone()[0] == "review"
        assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_failed_backup_preserves_last_good_snapshot(tmp_path):
    source = tmp_path / "auth.sqlite3"
    sqlite3.connect(source).close()
    root = tmp_path / "backups"
    first = backup_databases({"auth": source}, root, keep=1)
    with pytest.raises(FileNotFoundError):
        backup_databases({"auth": tmp_path / "missing"}, root, keep=1)
    assert first.is_dir()
    assert not list(root.glob(".pending-*"))
    second = backup_databases({"auth": source}, root, keep=1)
    assert second.is_dir()
    assert not first.exists()
