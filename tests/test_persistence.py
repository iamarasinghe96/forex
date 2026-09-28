import sqlite3

from forex.persistence import initialise_database


def test_initialise_database_is_idempotent_and_uses_wal(tmp_path):
    path = tmp_path / "state.sqlite3"
    initialise_database(path)
    initialise_database(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("SELECT count(*) FROM schema_version").fetchone()[0] == 1
