"""SQLite run tracker with WAL mode and race-guarded migrations.

Records training runs for audit/history.  Resume is HF-Trainer-native
(orthogonal — tracker records outcomes, Trainer owns resume).

Schema lives in a single ``runs`` table; migrations are lazy and
idempotent (CREATE IF NOT EXISTS).  Concurrent kiln processes open the
same DB safely via WAL + busy_timeout.

Orphaned runs (PID gone) are reconciled on startup.
"""

from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Generator

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA_VERSION = 1

_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    config_sha  TEXT    NOT NULL,
    model       TEXT    NOT NULL,
    mode        TEXT    NOT NULL DEFAULT 'sft',
    pid         INTEGER NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'running',
    started_at  REAL    NOT NULL,
    ended_at    REAL,
    adapter_path TEXT,
    notes       TEXT
);
"""

_CREATE_META = """\
CREATE TABLE IF NOT EXISTS _meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------

@dataclass
class RunRecord:
    id: int
    config_sha: str
    model: str
    mode: str
    pid: int
    status: str
    started_at: float
    ended_at: float | None = None
    adapter_path: str | None = None
    notes: str | None = None


class RunTracker:
    """SQLite-backed run history with WAL mode."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    # -- connection management -------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path),
                timeout=30.0,
                isolation_level=None,
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=10000")
            self._conn.row_factory = sqlite3.Row
            self._migrate(self._conn)
        return self._conn

    @contextmanager
    def _tx(self) -> Generator[sqlite3.Cursor, None, None]:
        conn = self._connect()
        cur = conn.cursor()
        cur.execute("BEGIN IMMEDIATE")
        try:
            yield cur
            cur.execute("COMMIT")
        except BaseException:
            cur.execute("ROLLBACK")
            raise

    # -- migrations ------------------------------------------------------------

    def _migrate(self, conn: sqlite3.Connection) -> None:
        cur = conn.cursor()
        cur.execute(_CREATE_META)
        cur.execute(_CREATE_TABLE)
        cur.execute(
            "INSERT OR REPLACE INTO _meta (key, value) VALUES (?, ?)",
            ("schema_version", str(_SCHEMA_VERSION)),
        )

    # -- public API ------------------------------------------------------------

    def start_run(
        self,
        *,
        config_sha: str,
        model: str,
        mode: str = "sft",
        notes: str | None = None,
    ) -> RunRecord:
        """Begin a new training run, returning its record."""
        now = time.time()
        pid = os.getpid()
        with self._tx() as cur:
            cur.execute(
                """\
                INSERT INTO runs (config_sha, model, mode, pid, status, started_at)
                VALUES (?, ?, ?, ?, 'running', ?)
                """,
                (config_sha, model, mode, pid, now),
            )
            run_id = cur.lastrowid
        return RunRecord(
            id=run_id,  # type: ignore[arg-type]
            config_sha=config_sha,
            model=model,
            mode=mode,
            pid=pid,
            status="running",
            started_at=now,
        )

    def finish_run(
        self,
        run_id: int,
        *,
        status: str = "completed",
        adapter_path: str | None = None,
        notes: str | None = None,
    ) -> None:
        """Mark a run as finished."""
        now = time.time()
        with self._tx() as cur:
            cur.execute(
                "UPDATE runs SET ended_at=?, status=?, adapter_path=?, notes=? WHERE id=?",
                (now, status, adapter_path, notes, run_id),
            )

    def list_runs(
        self,
        *,
        model: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[RunRecord]:
        """List runs with optional filters, newest first."""
        conn = self._connect()
        query = "SELECT * FROM runs WHERE 1=1"
        params: list[object] = []
        if model:
            query += " AND model=?"
            params.append(model)
        if status:
            query += " AND status=?"
            params.append(status)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [
            RunRecord(
                id=r["id"],
                config_sha=r["config_sha"],
                model=r["model"],
                mode=r["mode"],
                pid=r["pid"],
                status=r["status"],
                started_at=r["started_at"],
                ended_at=r["ended_at"],
                adapter_path=r["adapter_path"],
                notes=r["notes"],
            )
            for r in rows
        ]

    def reconcile_orphans(self) -> list[int]:
        """Mark runs whose PID is dead as 'orphaned'.  Returns their IDs."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT id, pid FROM runs WHERE status='running'"
        ).fetchall()
        orphaned: list[int] = []
        for r in rows:
            if not _pid_alive(r["pid"]):
                with self._tx() as cur:
                    cur.execute(
                        "UPDATE runs SET status='orphaned', ended_at=? WHERE id=?",
                        (time.time(), r["id"]),
                    )
                orphaned.append(r["id"])
        return orphaned

    def get_run(self, run_id: int) -> RunRecord | None:
        """Get a single run by ID."""
        conn = self._connect()
        row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            return None
        return RunRecord(
            id=row["id"],
            config_sha=row["config_sha"],
            model=row["model"],
            mode=row["mode"],
            pid=row["pid"],
            status=row["status"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            adapter_path=row["adapter_path"],
            notes=row["notes"],
        )


def _pid_alive(pid: int) -> bool:
    """Check if a process is alive (POSIX-safe)."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but we can't signal it
