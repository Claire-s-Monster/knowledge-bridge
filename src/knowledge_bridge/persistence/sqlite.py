"""SQLite database backend for knowledge-bridge.

Optimal for:
- Development and local deployment
- Single-user scenarios
- Zero external dependencies

Uses aiosqlite for async SQLite access.

Database location: ~/.claude/knowledge-bridge/knowledge_bridge.db
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import aiosqlite
except ImportError:
    aiosqlite = None  # type: ignore[assignment]  # noqa: F841

from .base import DEFAULT_SQLITE_PATH, BaseDatabaseBackend, get_default_data_dir

logger = logging.getLogger(__name__)


class SQLiteBackend(BaseDatabaseBackend):
    """SQLite database backend with async support."""

    SCHEMA = """
    -- Schema version tracking
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    -- Staging area for learnings awaiting promotion
    CREATE TABLE IF NOT EXISTS staging_queue (
        id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        source_id TEXT,
        content TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        status TEXT DEFAULT 'pending',
        curator_notes TEXT,
        promoted_to TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_staging_status ON staging_queue(status);
    CREATE INDEX IF NOT EXISTS idx_staging_created ON staging_queue(created_at);
    CREATE INDEX IF NOT EXISTS idx_staging_source ON staging_queue(source);

    -- Webhook subscriptions
    CREATE TABLE IF NOT EXISTS webhooks (
        id TEXT PRIMARY KEY,
        subscriber TEXT NOT NULL,
        events TEXT NOT NULL,
        endpoint TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        last_called TEXT,
        failure_count INTEGER DEFAULT 0,
        active INTEGER DEFAULT 1
    );

    CREATE INDEX IF NOT EXISTS idx_webhooks_active ON webhooks(active);
    CREATE INDEX IF NOT EXISTS idx_webhooks_subscriber ON webhooks(subscriber);

    -- Event log for debugging and replay
    CREATE TABLE IF NOT EXISTS event_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT NOT NULL,
        payload TEXT NOT NULL,
        timestamp TEXT DEFAULT (datetime('now')),
        delivered_to TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_event_type ON event_log(event_type);
    CREATE INDEX IF NOT EXISTS idx_event_timestamp ON event_log(timestamp);

    -- Feedback tracking
    CREATE TABLE IF NOT EXISTS feedback (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        knowledge_id TEXT NOT NULL,
        outcome TEXT NOT NULL,
        notes TEXT,
        reported_at TEXT DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_feedback_session ON feedback(session_id);
    CREATE INDEX IF NOT EXISTS idx_feedback_knowledge ON feedback(knowledge_id);
    CREATE INDEX IF NOT EXISTS idx_feedback_outcome ON feedback(outcome);

    -- Search log for analytics and gap analysis
    CREATE TABLE IF NOT EXISTS search_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        query TEXT NOT NULL,
        context TEXT,
        results_count INTEGER,
        top_result_id TEXT,
        searched_at TEXT DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_search_session ON search_log(session_id);
    CREATE INDEX IF NOT EXISTS idx_search_timestamp ON search_log(searched_at);
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        """Initialize SQLite backend.

        Args:
            db_path: Path to SQLite database file.
                Defaults to ~/.claude/knowledge-bridge/knowledge_bridge.db.
        """
        super().__init__()

        if aiosqlite is None:
            raise ImportError(
                "aiosqlite is required for SQLite backend. "
                "Install with: pip install aiosqlite"
            )

        if db_path is None:
            get_default_data_dir()  # Ensure directory exists
            self.db_path = DEFAULT_SQLITE_PATH
        else:
            self.db_path = Path(db_path)

        self._conn: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Initialize database connection and apply schema."""
        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Open connection with WAL mode for better concurrency
        self._conn = await aiosqlite.connect(str(self.db_path))
        self._conn.row_factory = aiosqlite.Row

        # Enable WAL mode for better concurrent access
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")

        # Apply schema
        for statement in self.SCHEMA.split(";"):
            statement = statement.strip()
            if statement:
                try:
                    await self._conn.execute(statement)
                except Exception as e:
                    if "already exists" not in str(e).lower():
                        logger.warning(f"Schema statement warning: {e}")

        # Track schema version
        await self._conn.execute(
            """
            INSERT OR IGNORE INTO schema_version (version, applied_at)
            VALUES (?, datetime('now'))
            """,
            (self.SCHEMA_VERSION,),
        )
        await self._conn.commit()

        self._is_connected = True
        logger.info(f"SQLite database initialized: {self.db_path}")

    async def close(self) -> None:
        """Close database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None
            self._is_connected = False
            logger.info("SQLite connection closed")

    def _ensure_connected(self) -> None:
        """Raise error if not connected."""
        if not self._conn:
            raise RuntimeError("Database not initialized")

    def _row_to_dict(self, row: aiosqlite.Row) -> dict[str, Any]:
        """Convert aiosqlite Row to dict."""
        return dict(row)

    def _timestamp_to_str(self, dt: datetime) -> str:
        """Convert datetime to ISO format string."""
        return dt.isoformat()

    # ===== Staging Queue Operations =====

    async def save_staged_entry(self, entry_data: dict[str, Any]) -> None:
        """Save or update a staged entry."""
        self._ensure_connected()
        assert self._conn is not None

        created_at = entry_data.get("created_at", self._get_timestamp())
        if isinstance(created_at, datetime):
            created_at = self._timestamp_to_str(created_at)

        await self._conn.execute(
            """
            INSERT OR REPLACE INTO staging_queue
            (id, source, source_id, content, created_at, status, curator_notes, promoted_to)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_data["id"],
                entry_data["source"],
                entry_data.get("source_id"),
                json.dumps(entry_data.get("content", {})),
                created_at,
                entry_data.get("status", "pending"),
                entry_data.get("curator_notes"),
                entry_data.get("promoted_to"),
            ),
        )
        await self._conn.commit()

    async def get_staged_entry(self, entry_id: str) -> dict[str, Any] | None:
        """Get a staged entry by ID."""
        self._ensure_connected()
        assert self._conn is not None

        async with self._conn.execute(
            "SELECT * FROM staging_queue WHERE id = ?", (entry_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                result = self._row_to_dict(row)
                if isinstance(result.get("content"), str):
                    result["content"] = json.loads(result["content"])
                return result
            return None

    async def query_staging_queue(
        self,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Query staging queue with optional status filter."""
        self._ensure_connected()
        assert self._conn is not None

        query = "SELECT * FROM staging_queue WHERE 1=1"
        params: list[Any] = []

        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        async with self._conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                result = self._row_to_dict(row)
                if isinstance(result.get("content"), str):
                    result["content"] = json.loads(result["content"])
                results.append(result)
            return results

    async def update_staged_entry_status(
        self,
        entry_id: str,
        status: str,
        curator_notes: str | None = None,
        promoted_to: str | None = None,
    ) -> bool:
        """Update status of a staged entry."""
        self._ensure_connected()
        assert self._conn is not None

        cursor = await self._conn.execute(
            """
            UPDATE staging_queue
            SET status = ?, curator_notes = COALESCE(?, curator_notes),
                promoted_to = COALESCE(?, promoted_to)
            WHERE id = ?
            """,
            (status, curator_notes, promoted_to, entry_id),
        )
        await self._conn.commit()
        return bool(cursor.rowcount > 0)

    # ===== Webhook Operations =====

    async def save_webhook(self, webhook_data: dict[str, Any]) -> None:
        """Save or update a webhook registration."""
        self._ensure_connected()
        assert self._conn is not None

        created_at = webhook_data.get("created_at", self._get_timestamp())
        if isinstance(created_at, datetime):
            created_at = self._timestamp_to_str(created_at)

        last_called = webhook_data.get("last_called")
        if isinstance(last_called, datetime):
            last_called = self._timestamp_to_str(last_called)

        await self._conn.execute(
            """
            INSERT OR REPLACE INTO webhooks
            (id, subscriber, events, endpoint, created_at, last_called, failure_count, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                webhook_data["id"],
                webhook_data["subscriber"],
                json.dumps(webhook_data.get("events", [])),
                webhook_data["endpoint"],
                created_at,
                last_called,
                webhook_data.get("failure_count", 0),
                1 if webhook_data.get("active", True) else 0,
            ),
        )
        await self._conn.commit()

    async def get_webhook(self, webhook_id: str) -> dict[str, Any] | None:
        """Get a webhook by ID."""
        self._ensure_connected()
        assert self._conn is not None

        async with self._conn.execute(
            "SELECT * FROM webhooks WHERE id = ?", (webhook_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                result = self._row_to_dict(row)
                if isinstance(result.get("events"), str):
                    result["events"] = json.loads(result["events"])
                result["active"] = bool(result.get("active", 1))
                return result
            return None

    async def query_webhooks(
        self,
        active_only: bool = True,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query webhooks with optional filters."""
        self._ensure_connected()
        assert self._conn is not None

        query = "SELECT * FROM webhooks WHERE 1=1"
        params: list[Any] = []

        if active_only:
            query += " AND active = ?"
            params.append(1)

        query += " ORDER BY created_at DESC"

        async with self._conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                result = self._row_to_dict(row)
                if isinstance(result.get("events"), str):
                    result["events"] = json.loads(result["events"])
                result["active"] = bool(result.get("active", 1))
                # Filter by event_type in Python (SQLite lacks JSONB operators)
                if event_type and event_type not in result.get("events", []):
                    continue
                results.append(result)
            return results

    async def delete_webhook(self, webhook_id: str) -> bool:
        """Delete a webhook by ID."""
        self._ensure_connected()
        assert self._conn is not None

        cursor = await self._conn.execute(
            "DELETE FROM webhooks WHERE id = ?", (webhook_id,)
        )
        await self._conn.commit()
        return bool(cursor.rowcount > 0)

    async def update_webhook_status(
        self,
        webhook_id: str,
        active: bool | None = None,
        failure_count: int | None = None,
        last_called: datetime | None = None,
    ) -> bool:
        """Update webhook status fields."""
        self._ensure_connected()
        assert self._conn is not None

        updates = []
        params: list[Any] = []

        if active is not None:
            updates.append("active = ?")
            params.append(1 if active else 0)

        if failure_count is not None:
            updates.append("failure_count = ?")
            params.append(failure_count)

        if last_called is not None:
            updates.append("last_called = ?")
            params.append(self._timestamp_to_str(last_called))

        if not updates:
            return False

        params.append(webhook_id)
        query = f"UPDATE webhooks SET {', '.join(updates)} WHERE id = ?"

        cursor = await self._conn.execute(query, params)
        await self._conn.commit()
        return bool(cursor.rowcount > 0)

    # ===== Event Log Operations =====

    async def save_event(self, event_data: dict[str, Any]) -> int:
        """Save an event to the log. Returns event ID."""
        self._ensure_connected()
        assert self._conn is not None

        timestamp = event_data.get("timestamp", self._get_timestamp())
        if isinstance(timestamp, datetime):
            timestamp = self._timestamp_to_str(timestamp)

        cursor = await self._conn.execute(
            """
            INSERT INTO event_log (event_type, payload, timestamp, delivered_to)
            VALUES (?, ?, ?, ?)
            """,
            (
                event_data["event_type"],
                json.dumps(event_data.get("payload", {})),
                timestamp,
                json.dumps(event_data.get("delivered_to", [])),
            ),
        )
        await self._conn.commit()
        return cursor.lastrowid or 0

    async def query_events(
        self,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query event log with optional type filter."""
        self._ensure_connected()
        assert self._conn is not None

        query = "SELECT * FROM event_log WHERE 1=1"
        params: list[Any] = []

        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        async with self._conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                result = self._row_to_dict(row)
                if isinstance(result.get("payload"), str):
                    result["payload"] = json.loads(result["payload"])
                if isinstance(result.get("delivered_to"), str):
                    result["delivered_to"] = json.loads(result["delivered_to"])
                results.append(result)
            return results

    # ===== Feedback Operations =====

    async def save_feedback(self, feedback_data: dict[str, Any]) -> None:
        """Save feedback for a knowledge entry."""
        self._ensure_connected()
        assert self._conn is not None

        reported_at = feedback_data.get("reported_at", self._get_timestamp())
        if isinstance(reported_at, datetime):
            reported_at = self._timestamp_to_str(reported_at)

        await self._conn.execute(
            """
            INSERT OR REPLACE INTO feedback
            (id, session_id, knowledge_id, outcome, notes, reported_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                feedback_data["id"],
                feedback_data["session_id"],
                feedback_data["knowledge_id"],
                feedback_data["outcome"],
                feedback_data.get("notes", ""),
                reported_at,
            ),
        )
        await self._conn.commit()

    async def query_feedback(
        self,
        knowledge_id: str | None = None,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query feedback with optional filters."""
        self._ensure_connected()
        assert self._conn is not None

        query = "SELECT * FROM feedback WHERE 1=1"
        params: list[Any] = []

        if knowledge_id:
            query += " AND knowledge_id = ?"
            params.append(knowledge_id)

        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)

        query += " ORDER BY reported_at DESC LIMIT ?"
        params.append(limit)

        async with self._conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_dict(row) for row in rows]

    # ===== Search Log Operations =====

    async def save_search(self, search_data: dict[str, Any]) -> int:
        """Save a search to the log. Returns search ID."""
        self._ensure_connected()
        assert self._conn is not None

        searched_at = search_data.get("searched_at", self._get_timestamp())
        if isinstance(searched_at, datetime):
            searched_at = self._timestamp_to_str(searched_at)

        cursor = await self._conn.execute(
            """
            INSERT INTO search_log
            (session_id, query, context, results_count, top_result_id, searched_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                search_data["session_id"],
                search_data["query"],
                json.dumps(search_data.get("context", {})),
                search_data.get("results_count", 0),
                search_data.get("top_result_id"),
                searched_at,
            ),
        )
        await self._conn.commit()
        return cursor.lastrowid or 0

    async def query_searches(
        self,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query search log with optional session filter."""
        self._ensure_connected()
        assert self._conn is not None

        query = "SELECT * FROM search_log WHERE 1=1"
        params: list[Any] = []

        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)

        query += " ORDER BY searched_at DESC LIMIT ?"
        params.append(limit)

        async with self._conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                result = self._row_to_dict(row)
                if isinstance(result.get("context"), str):
                    result["context"] = json.loads(result["context"])
                results.append(result)
            return results

    # ===== Statistics =====

    async def get_statistics(self) -> dict[str, Any]:
        """Get database statistics for monitoring."""
        self._ensure_connected()
        assert self._conn is not None

        stats: dict[str, Any] = {
            "backend": "sqlite",
            "db_path": str(self.db_path),
        }

        # Get table counts
        tables = ["staging_queue", "webhooks", "event_log", "feedback", "search_log"]
        for table in tables:
            async with self._conn.execute(
                f"SELECT COUNT(*) as count FROM {table}"  # noqa: S608
            ) as cursor:
                row = await cursor.fetchone()
                stats[f"{table}_count"] = row["count"] if row else 0

        # Get staging queue by status
        async with self._conn.execute(
            "SELECT status, COUNT(*) as count FROM staging_queue GROUP BY status"
        ) as cursor:
            rows = await cursor.fetchall()
            stats["staging_by_status"] = {
                str(row["status"]): row["count"] for row in rows
            }

        # Get database file size
        if self.db_path.exists():
            stats["size_bytes"] = self.db_path.stat().st_size

        return stats
