import json
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class StateStore:
    """Persistent, user-bound callback state with automatic expiry."""

    def __init__(self, path: Path, ttl: int = 3600):
        self.path = path
        self.ttl = max(60, ttl)
        self.lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.lock, self._connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS preferences (
                    user_id INTEGER PRIMARY KEY,
                    language TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS requests (
                    request_id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_requests_created_at
                    ON requests(created_at);
                """
            )

    def language(self, user_id: int, default: str = "uz") -> str:
        with self.lock, self._connection() as connection:
            row = connection.execute(
                "SELECT language FROM preferences WHERE user_id = ?", (user_id,)
            ).fetchone()
        return str(row["language"]) if row else default

    def set_language(self, user_id: int, language: str) -> None:
        if language not in {"uz", "ru", "en"}:
            raise ValueError("Unsupported language")
        with self.lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO preferences(user_id, language, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    language = excluded.language,
                    updated_at = excluded.updated_at
                """,
                (user_id, language, int(time.time())),
            )

    def create(self, user_id: int, kind: str, payload: dict[str, Any]) -> str:
        request_id = secrets.token_urlsafe(6)
        now = int(time.time())
        with self.lock, self._connection() as connection:
            connection.execute(
                "DELETE FROM requests WHERE created_at < ?", (now - self.ttl,)
            )
            connection.execute(
                "INSERT INTO requests(request_id, user_id, kind, payload, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (request_id, user_id, kind, json.dumps(payload), now),
            )
        return request_id

    def get(self, request_id: str, user_id: int, kind: str) -> dict[str, Any] | None:
        cutoff = int(time.time()) - self.ttl
        with self.lock, self._connection() as connection:
            row = connection.execute(
                """
                SELECT payload FROM requests
                WHERE request_id = ? AND user_id = ? AND kind = ? AND created_at >= ?
                """,
                (request_id, user_id, kind, cutoff),
            ).fetchone()
        if not row:
            return None
        try:
            payload = json.loads(row["payload"])
        except (TypeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None
