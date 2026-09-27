"""SQLite connection handling and schema migrations."""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Open a connection, commit on success, roll back on error, always close."""
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def migrate(self) -> int:
        """Apply migrations/NNNN_*.sql files newer than PRAGMA user_version. Returns the new version."""
        self._check_writable()
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            current = conn.execute("PRAGMA user_version").fetchone()[0]
            for script in sorted(MIGRATIONS_DIR.glob("*.sql")):
                version = int(script.name.split("_", 1)[0])
                if version <= current:
                    continue
                conn.executescript(f"BEGIN;\n{script.read_text()}\nPRAGMA user_version = {version};\nCOMMIT;")
                current = version
            return current

    def _check_writable(self) -> None:
        """Fail with a fix, not SQLite's bare "unable to open database file". On Linux, Docker creates a
        missing bind-mount folder owned by root, and the app (a non-root user) cannot write to it."""
        folder = self.path.parent
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            pass
        if os.access(folder, os.W_OK) and (not self.path.exists() or os.access(self.path, os.W_OK)):
            return
        raise PermissionError(
            f"Cannot write the database in {folder} as user id {os.getuid()}. On the Docker host, run: "
            f"sudo chown -R {os.getuid()}:{os.getgid()} ./data"
        )
