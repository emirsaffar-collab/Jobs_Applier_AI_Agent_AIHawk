"""Persistent state checkpointing for crash recovery.

Saves the bot's progress (platform index, job index, stats, rate-limiter
state) to a SQLite database after each job so the bot can resume after a
crash without re-processing already-handled jobs.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.logging import logger

_DB_PATH = Path("data_folder/bot_checkpoint.db")


@dataclass
class CheckpointData:
    """Snapshot of bot progress at a point in time."""
    session_id: str
    platform_index: int = 0
    job_index: int = 0
    stats: dict[str, Any] = field(default_factory=dict)
    rate_limiter_state: dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0


class CheckpointManager:
    """Persist and restore bot checkpoints via SQLite."""

    def __init__(self, db_path: Path | str = _DB_PATH):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), timeout=10)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS checkpoints (
                session_id   TEXT PRIMARY KEY,
                platform_idx INTEGER NOT NULL DEFAULT 0,
                job_idx      INTEGER NOT NULL DEFAULT 0,
                stats_json   TEXT NOT NULL DEFAULT '{}',
                rl_state_json TEXT NOT NULL DEFAULT '{}',
                updated_at   REAL NOT NULL
            )
        """)
        self._conn.commit()

    def save(
        self,
        session_id: str,
        platform_index: int = 0,
        job_index: int = 0,
        stats: dict[str, Any] | None = None,
        rate_limiter_state: dict[str, Any] | None = None,
    ) -> None:
        """Upsert a checkpoint for the given session."""
        now = time.time()
        # Sanitize stats — drop the log list to keep the row small
        clean_stats = dict(stats or {})
        clean_stats.pop("log", None)

        self._conn.execute(
            """INSERT INTO checkpoints (session_id, platform_idx, job_idx, stats_json, rl_state_json, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET
                   platform_idx  = excluded.platform_idx,
                   job_idx       = excluded.job_idx,
                   stats_json    = excluded.stats_json,
                   rl_state_json = excluded.rl_state_json,
                   updated_at    = excluded.updated_at
            """,
            (
                session_id,
                platform_index,
                job_index,
                json.dumps(clean_stats),
                json.dumps(rate_limiter_state or {}),
                now,
            ),
        )
        self._conn.commit()

    def load(self, session_id: str | None = None) -> CheckpointData | None:
        """Load the checkpoint for a session, or the most recent one if no ID given."""
        if session_id:
            row = self._conn.execute(
                "SELECT session_id, platform_idx, job_idx, stats_json, rl_state_json, updated_at "
                "FROM checkpoints WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT session_id, platform_idx, job_idx, stats_json, rl_state_json, updated_at "
                "FROM checkpoints ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()

        if row is None:
            return None

        return CheckpointData(
            session_id=row[0],
            platform_index=row[1],
            job_index=row[2],
            stats=json.loads(row[3]),
            rate_limiter_state=json.loads(row[4]),
            timestamp=row[5],
        )

    def clear(self, session_id: str) -> None:
        """Remove the checkpoint for a completed session."""
        self._conn.execute("DELETE FROM checkpoints WHERE session_id = ?", (session_id,))
        self._conn.commit()
        logger.debug("Checkpoint cleared for session {}", session_id)

    def clear_old(self, max_age_hours: float = 48) -> int:
        """Remove checkpoints older than *max_age_hours*. Returns count deleted."""
        cutoff = time.time() - max_age_hours * 3600
        cur = self._conn.execute("DELETE FROM checkpoints WHERE updated_at < ?", (cutoff,))
        self._conn.commit()
        return cur.rowcount

    def close(self) -> None:
        self._conn.close()
