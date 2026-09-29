"""Local process exclusion and consistent SQLite backups; no broker side effects."""

from __future__ import annotations

import importlib
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from types import TracebackType
from typing import BinaryIO, Self

from forex.errors import OperatorError


class SingleWriter:
    def __init__(self, path: Path):
        self.path = path
        self.handle: BinaryIO | None = None

    def __enter__(self) -> Self:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        try:
            if self.path.stat().st_size == 0:
                self.handle.write(b"0")
                self.handle.flush()
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl = importlib.import_module("fcntl")
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            self.handle = None
            raise OperatorError("Another paper process holds this database lock. Do not start a duplicate runtime.") from None
        return self

    def __exit__(self, kind: type[BaseException] | None, value: BaseException | None,
                 traceback: TracebackType | None) -> None:
        if self.handle:
            self.handle.close()  # OS releases the lock, including after process crashes.


def backup_database(source: Path, target: Path) -> None:
    if source.resolve() == target.resolve() or target.exists():
        raise ValueError("backup target must be a new, separate file")
    if not source.is_file():
        raise ValueError("source database does not exist")
    target.parent.mkdir(parents=True, exist_ok=True)
    with (closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as src,
          closing(sqlite3.connect(target)) as dst):
        src.backup(dst)
        if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise OperatorError("Backup integrity check failed. Retain the original database.")
