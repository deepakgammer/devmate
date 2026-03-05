"""
DEVMATE – Hybrid Memory Module
Manages:
  - Short-term session memory  : collections.deque (fast, in-RAM, 20-turn cap)
  - Long-term persistent memory: SQLite via sqlite3 (conversation history,
                                  user preferences, project history, command log)
"""

import json
import logging
import sqlite3
import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Database Schema (DDL)
# ─────────────────────────────────────────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL,
    role        TEXT    NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
    content     TEXT    NOT NULL,
    session_id  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS preferences (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    path        TEXT    NOT NULL,
    language    TEXT    NOT NULL DEFAULT 'python',
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS commands (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    command     TEXT    NOT NULL UNIQUE,
    run_count   INTEGER NOT NULL DEFAULT 1,
    last_used   TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_session ON memory(session_id);
CREATE INDEX IF NOT EXISTS idx_memory_ts      ON memory(timestamp);
CREATE INDEX IF NOT EXISTS idx_commands_count ON commands(run_count DESC);
"""


# ─────────────────────────────────────────────────────────────────────────────
# MemoryManager
# ─────────────────────────────────────────────────────────────────────────────
class MemoryManager:
    """
    Hybrid memory system.

    Short-term: deque of the last SHORT_TERM_MAXLEN message dicts kept in RAM.
    Long-term: SQLite database stored at config.DB_PATH.
    Thread safety: a single threading.Lock protects all DB writes.
    """

    def __init__(self):
        self.session_id: str = str(uuid.uuid4())
        # Short-term buffer – capped to avoid RAM bloat
        self._short_term: deque = deque(maxlen=config.SHORT_TERM_MAXLEN)
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()
        logger.info("MemoryManager initialised  session=%s", self.session_id)

    # ──────────────────── DB Initialisation ──────────────────────────────────

    def _init_db(self) -> None:
        """Create data directory and SQLite schema if they don't exist."""
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(config.DB_PATH),
            check_same_thread=False,  # we use a lock ourselves
            timeout=10,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")   # better concurrency
        self._conn.execute("PRAGMA synchronous=NORMAL;") # faster writes
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ──────────────────── Core Message Store ─────────────────────────────────

    def add_message(self, role: str, content: str) -> None:
        """Store a message in both short-term buffer and SQLite."""
        now = datetime.now(timezone.utc).isoformat()
        entry = {"role": role, "content": content, "timestamp": now}
        self._short_term.append(entry)

        with self._lock:
            self._conn.execute(
                "INSERT INTO memory (timestamp, role, content, session_id) "
                "VALUES (?, ?, ?, ?)",
                (now, role, content, self.session_id),
            )
            self._conn.commit()

    def get_context(self, n: int = None) -> List[Dict[str, str]]:
        """
        Return the last *n* messages suitable for injection into LLM prompt.
        Prefer short-term buffer (fast); only touches DB if buffer is empty.
        """
        n = n or config.LLM_CONTEXT_TURNS
        messages = list(self._short_term)
        if not messages:
            # Cold start – load from DB
            rows = self._conn.execute(
                "SELECT role, content FROM memory "
                "WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (self.session_id, n),
            ).fetchall()
            messages = [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
        return messages[-n:]

    def get_all_sessions_summary(self, limit: int = 5) -> List[Dict]:
        """Return a brief summary of the last *limit* distinct sessions."""
        rows = self._conn.execute(
            "SELECT session_id, MIN(timestamp) as started, COUNT(*) as turns "
            "FROM memory GROUP BY session_id ORDER BY started DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ──────────────────── Preferences ────────────────────────────────────────

    def save_preference(self, key: str, value: Any) -> None:
        """Upsert a user preference (JSON-serialised value)."""
        now = datetime.now(timezone.utc).isoformat()
        serialised = json.dumps(value)
        with self._lock:
            self._conn.execute(
                "INSERT INTO preferences (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, serialised, now),
            )
            self._conn.commit()

    def get_preference(self, key: str, default: Any = None) -> Any:
        """Fetch a user preference, returning *default* if not found."""
        row = self._conn.execute(
            "SELECT value FROM preferences WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            return row["value"]

    def get_all_preferences(self) -> Dict[str, Any]:
        """Return all preferences as a dict."""
        rows = self._conn.execute("SELECT key, value FROM preferences").fetchall()
        result = {}
        for r in rows:
            try:
                result[r["key"]] = json.loads(r["value"])
            except (json.JSONDecodeError, TypeError):
                result[r["key"]] = r["value"]
        return result

    # ──────────────────── Project History ────────────────────────────────────

    def log_project(self, name: str, path: str, language: str = "python") -> None:
        """Record a newly created project."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                "INSERT INTO projects (name, path, language, created_at) VALUES (?, ?, ?, ?)",
                (name, path, language, now),
            )
            self._conn.commit()

    def get_projects(self, limit: int = 20) -> List[Dict]:
        """Return most-recently created projects."""
        rows = self._conn.execute(
            "SELECT name, path, language, created_at FROM projects "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ──────────────────── Command Log ────────────────────────────────────────

    def log_command(self, command: str) -> None:
        """Upsert a command and increment its run count."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                "INSERT INTO commands (command, run_count, last_used) VALUES (?, 1, ?) "
                "ON CONFLICT(command) DO UPDATE SET "
                "run_count=run_count+1, last_used=excluded.last_used",
                (command, now),
            )
            self._conn.commit()

    def get_frequent_commands(self, limit: int = 5) -> List[Tuple[str, int]]:
        """Return top *limit* most-run commands as (command, count) tuples."""
        rows = self._conn.execute(
            "SELECT command, run_count FROM commands ORDER BY run_count DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [(r["command"], r["run_count"]) for r in rows]

    # ──────────────────── Housekeeping ───────────────────────────────────────

    def clear_session(self) -> None:
        """Start a fresh session (clears in-memory buffer; DB is preserved)."""
        self._short_term.clear()
        self.session_id = str(uuid.uuid4())
        logger.info("New session started  session=%s", self.session_id)

    def close(self) -> None:
        """Flush and close the DB connection gracefully."""
        if self._conn:
            self._conn.close()
            self._conn = None
        logger.info("MemoryManager closed.")

    def __del__(self):
        self.close()
