import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


class AuditStore:
    def __init__(self, path: Path, retention_days: int = 90):
        self.path = path
        self.retention_days = max(1, retention_days)
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
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT NOT NULL,
                    language_code TEXT,
                    first_seen INTEGER NOT NULL,
                    last_seen INTEGER NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at INTEGER NOT NULL,
                    user_id INTEGER,
                    chat_id INTEGER NOT NULL,
                    direction TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_user_id
                    ON events(user_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_events_created_at
                    ON events(created_at DESC);
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                INSERT OR IGNORE INTO settings(key, value) VALUES('live_log', '1');
                """
            )
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        self.purge_expired()

    def purge_expired(self) -> int:
        cutoff = int(time.time()) - self.retention_days * 86400
        with self.lock, self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM events WHERE created_at < ?", (cutoff,)
            )
        return max(0, int(cursor.rowcount))

    def touch_user(
        self,
        user_id: int,
        username: str | None,
        full_name: str,
        language_code: str | None,
        increment: bool = False,
    ) -> None:
        now = int(time.time())
        increment_by = 1 if increment else 0
        with self.lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO users(
                    user_id, username, full_name, language_code,
                    first_seen, last_seen, message_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    full_name = excluded.full_name,
                    language_code = excluded.language_code,
                    last_seen = excluded.last_seen,
                    message_count = users.message_count + excluded.message_count
                """,
                (
                    user_id,
                    username,
                    full_name or "Unknown",
                    language_code,
                    now,
                    now,
                    increment_by,
                ),
            )

    def record_event(
        self,
        user_id: int | None,
        chat_id: int,
        direction: str,
        kind: str,
        content: str,
    ) -> int:
        clean_content = (content or "").strip()[:4000]
        with self.lock, self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO events(created_at, user_id, chat_id, direction, kind, content)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    int(time.time()),
                    user_id,
                    chat_id,
                    direction,
                    kind,
                    clean_content,
                ),
            )
            return int(cursor.lastrowid)

    def live_enabled(self) -> bool:
        with self.lock, self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = 'live_log'"
            ).fetchone()
        return bool(row and row["value"] == "1")

    def toggle_live(self) -> bool:
        enabled = not self.live_enabled()
        with self.lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO settings(key, value) VALUES('live_log', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                ("1" if enabled else "0",),
            )
        return enabled

    def dashboard(self) -> dict[str, int]:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        start_of_day = int(today.timestamp())
        with self.lock, self._connection() as connection:
            users = connection.execute("SELECT COUNT(*) AS count FROM users").fetchone()
            incoming = connection.execute(
                "SELECT COUNT(*) AS count FROM events WHERE direction = 'in'"
            ).fetchone()
            outgoing = connection.execute(
                "SELECT COUNT(*) AS count FROM events WHERE direction = 'out'"
            ).fetchone()
            today_events = connection.execute(
                "SELECT COUNT(*) AS count FROM events WHERE created_at >= ?",
                (start_of_day,),
            ).fetchone()
        return {
            "users": int(users["count"]),
            "incoming": int(incoming["count"]),
            "outgoing": int(outgoing["count"]),
            "today_events": int(today_events["count"]),
        }

    def recent_events(self, limit: int = 20) -> list[dict]:
        with self.lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT e.*, u.username, u.full_name
                FROM events e
                LEFT JOIN users u ON u.user_id = e.user_id
                ORDER BY e.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def recent_users(self, limit: int = 10) -> list[dict]:
        with self.lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM users
                ORDER BY last_seen DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def user_count(self) -> int:
        with self.lock, self._connection() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM users").fetchone()
        return int(row["count"] if row else 0)

    def users_page(self, offset: int, limit: int = 10) -> list[dict]:
        with self.lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM users
                ORDER BY last_seen DESC
                LIMIT ? OFFSET ?
                """,
                (limit, max(0, offset)),
            ).fetchall()
        return [dict(row) for row in rows]

    def user_history(self, user_id: int, limit: int = 30) -> list[dict]:
        with self.lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM events
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def user(self, user_id: int) -> dict | None:
        with self.lock, self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return dict(row) if row else None
