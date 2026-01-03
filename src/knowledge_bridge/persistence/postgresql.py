"""PostgreSQL database backend for knowledge-bridge.

Optimal for:
- Production environments
- Concurrent access from multiple processes
- Real-time notifications via LISTEN/NOTIFY

Requires: asyncpg

Connection string format:
    postgresql://user:password@host:port/database
    postgresql://localhost/knowledge_bridge
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

try:
    import asyncpg
except ImportError:
    asyncpg = None  # type: ignore[assignment]

from .base import DEFAULT_POSTGRES_DSN, BaseDatabaseBackend

logger = logging.getLogger(__name__)


class PostgreSQLBackend(BaseDatabaseBackend):
    """PostgreSQL database backend with async support."""

    SCHEMA = """
    -- Schema version tracking
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    -- Staging area for learnings awaiting promotion
    CREATE TABLE IF NOT EXISTS staging_queue (
        id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        source_id TEXT,
        content JSONB NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW(),
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
        events JSONB NOT NULL,
        endpoint TEXT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        last_called TIMESTAMPTZ,
        failure_count INTEGER DEFAULT 0,
        active BOOLEAN DEFAULT TRUE
    );

    CREATE INDEX IF NOT EXISTS idx_webhooks_active ON webhooks(active);
    CREATE INDEX IF NOT EXISTS idx_webhooks_subscriber ON webhooks(subscriber);

    -- Event log for debugging and replay
    CREATE TABLE IF NOT EXISTS event_log (
        id SERIAL PRIMARY KEY,
        event_type TEXT NOT NULL,
        payload JSONB NOT NULL,
        timestamp TIMESTAMPTZ DEFAULT NOW(),
        delivered_to JSONB
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
        reported_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_feedback_session ON feedback(session_id);
    CREATE INDEX IF NOT EXISTS idx_feedback_knowledge ON feedback(knowledge_id);
    CREATE INDEX IF NOT EXISTS idx_feedback_outcome ON feedback(outcome);

    -- Search log for analytics and gap analysis
    CREATE TABLE IF NOT EXISTS search_log (
        id SERIAL PRIMARY KEY,
        session_id TEXT NOT NULL,
        query TEXT NOT NULL,
        context JSONB,
        results_count INTEGER,
        top_result_id TEXT,
        searched_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_search_session ON search_log(session_id);
    CREATE INDEX IF NOT EXISTS idx_search_timestamp ON search_log(searched_at);

    -- Analytical views
    CREATE OR REPLACE VIEW staging_analytics AS
    SELECT
        status,
        source,
        COUNT(*) as count,
        MIN(created_at) as oldest,
        MAX(created_at) as newest
    FROM staging_queue
    GROUP BY status, source;

    CREATE OR REPLACE VIEW feedback_analytics AS
    SELECT
        knowledge_id,
        outcome,
        COUNT(*) as count,
        MIN(reported_at) as first_report,
        MAX(reported_at) as last_report
    FROM feedback
    GROUP BY knowledge_id, outcome;
    """

    def __init__(self, dsn: str | None = None, **kwargs: Any) -> None:
        """Initialize PostgreSQL backend.

        Args:
            dsn: PostgreSQL connection string. Defaults to postgresql://localhost/knowledge_bridge.
            **kwargs: Additional arguments passed to asyncpg.create_pool().
        """
        super().__init__()

        if asyncpg is None:
            raise ImportError(
                "asyncpg is required for PostgreSQL backend. "
                "Install with: pixi add asyncpg"
            )

        self.dsn = dsn or DEFAULT_POSTGRES_DSN
        self._pool_kwargs = kwargs
        self._pool: asyncpg.Pool | None = None

    async def initialize(self) -> None:
        """Initialize database connection pool and apply schema."""
        self._pool = await asyncpg.create_pool(
            self.dsn,
            **self._pool_kwargs,
        )

        # Apply schema
        async with self._pool.acquire() as conn:
            statements = [s.strip() for s in self.SCHEMA.split(";") if s.strip()]
            for statement in statements:
                try:
                    await conn.execute(statement)
                except Exception as e:
                    if "already exists" not in str(e).lower():
                        logger.warning(f"Schema statement warning: {e}")

            # Track schema version
            await conn.execute(
                """
                INSERT INTO schema_version (version)
                VALUES ($1)
                ON CONFLICT (version) DO NOTHING
                """,
                self.SCHEMA_VERSION,
            )

        self._is_connected = True
        logger.info(f"PostgreSQL database initialized: {self.dsn.split('@')[-1]}")

    async def close(self) -> None:
        """Close database connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            self._is_connected = False
            logger.info("PostgreSQL connection pool closed")

    def _ensure_connected(self) -> None:
        """Raise error if not connected."""
        if not self._pool:
            raise RuntimeError("Database not initialized")

    def _from_record(self, record: asyncpg.Record) -> dict[str, Any]:
        """Convert asyncpg Record to dict."""
        return dict(record)

    # ===== Staging Queue Operations =====

    async def save_staged_entry(self, entry_data: dict[str, Any]) -> None:
        """Save or update a staged entry."""
        self._ensure_connected()
        assert self._pool is not None  # Type narrowing after _ensure_connected

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO staging_queue
                (id, source, source_id, content, created_at, status, curator_notes, promoted_to)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (id) DO UPDATE SET
                    content = EXCLUDED.content,
                    status = EXCLUDED.status,
                    curator_notes = EXCLUDED.curator_notes,
                    promoted_to = EXCLUDED.promoted_to
                """,
                entry_data["id"],
                entry_data["source"],
                entry_data.get("source_id"),
                json.dumps(entry_data.get("content", {})),
                entry_data.get("created_at", self._get_timestamp()),
                entry_data.get("status", "pending"),
                entry_data.get("curator_notes"),
                entry_data.get("promoted_to"),
            )

            # Notify listeners
            await conn.execute(
                "SELECT pg_notify('staging_changes', $1)",
                json.dumps({"entry_id": entry_data["id"], "action": "upsert"}),
            )

    async def get_staged_entry(self, entry_id: str) -> dict[str, Any] | None:
        """Get a staged entry by ID."""
        self._ensure_connected()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM staging_queue WHERE id = $1", entry_id
            )
            if row:
                result = self._from_record(row)
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
        assert self._pool is not None

        query = "SELECT * FROM staging_queue WHERE 1=1"
        params: list[Any] = []
        param_idx = 1

        if status:
            query += f" AND status = ${param_idx}"
            params.append(status)
            param_idx += 1

        query += f" ORDER BY created_at DESC LIMIT ${param_idx}"
        params.append(limit)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            results = []
            for row in rows:
                result = self._from_record(row)
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
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE staging_queue
                SET status = $1, curator_notes = COALESCE($2, curator_notes),
                    promoted_to = COALESCE($3, promoted_to)
                WHERE id = $4
                """,
                status,
                curator_notes,
                promoted_to,
                entry_id,
            )
            return result == "UPDATE 1"

    # ===== Webhook Operations =====

    async def save_webhook(self, webhook_data: dict[str, Any]) -> None:
        """Save or update a webhook registration."""
        self._ensure_connected()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO webhooks
                (id, subscriber, events, endpoint, created_at, last_called, failure_count, active)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (id) DO UPDATE SET
                    subscriber = EXCLUDED.subscriber,
                    events = EXCLUDED.events,
                    endpoint = EXCLUDED.endpoint,
                    active = EXCLUDED.active
                """,
                webhook_data["id"],
                webhook_data["subscriber"],
                json.dumps(webhook_data.get("events", [])),
                webhook_data["endpoint"],
                webhook_data.get("created_at", self._get_timestamp()),
                webhook_data.get("last_called"),
                webhook_data.get("failure_count", 0),
                webhook_data.get("active", True),
            )

    async def get_webhook(self, webhook_id: str) -> dict[str, Any] | None:
        """Get a webhook by ID."""
        self._ensure_connected()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM webhooks WHERE id = $1", webhook_id
            )
            if row:
                result = self._from_record(row)
                if isinstance(result.get("events"), str):
                    result["events"] = json.loads(result["events"])
                return result
            return None

    async def query_webhooks(
        self,
        active_only: bool = True,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query webhooks with optional filters."""
        self._ensure_connected()
        assert self._pool is not None

        query = "SELECT * FROM webhooks WHERE 1=1"
        params: list[Any] = []
        param_idx = 1

        if active_only:
            query += f" AND active = ${param_idx}"
            params.append(True)
            param_idx += 1

        if event_type:
            query += f" AND events ? ${param_idx}"
            params.append(event_type)
            param_idx += 1

        query += " ORDER BY created_at DESC"

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            results = []
            for row in rows:
                result = self._from_record(row)
                if isinstance(result.get("events"), str):
                    result["events"] = json.loads(result["events"])
                results.append(result)
            return results

    async def delete_webhook(self, webhook_id: str) -> bool:
        """Delete a webhook by ID."""
        self._ensure_connected()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM webhooks WHERE id = $1", webhook_id
            )
            return result == "DELETE 1"

    async def update_webhook_status(
        self,
        webhook_id: str,
        active: bool | None = None,
        failure_count: int | None = None,
        last_called: datetime | None = None,
    ) -> bool:
        """Update webhook status fields."""
        self._ensure_connected()
        assert self._pool is not None

        updates = []
        params: list[Any] = []
        param_idx = 1

        if active is not None:
            updates.append(f"active = ${param_idx}")
            params.append(active)
            param_idx += 1

        if failure_count is not None:
            updates.append(f"failure_count = ${param_idx}")
            params.append(failure_count)
            param_idx += 1

        if last_called is not None:
            updates.append(f"last_called = ${param_idx}")
            params.append(last_called)
            param_idx += 1

        if not updates:
            return False

        params.append(webhook_id)
        query = f"UPDATE webhooks SET {', '.join(updates)} WHERE id = ${param_idx}"

        async with self._pool.acquire() as conn:
            result = await conn.execute(query, *params)
            return result == "UPDATE 1"

    # ===== Event Log Operations =====

    async def save_event(self, event_data: dict[str, Any]) -> int:
        """Save an event to the log. Returns event ID."""
        self._ensure_connected()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO event_log (event_type, payload, timestamp, delivered_to)
                VALUES ($1, $2, $3, $4)
                RETURNING id
                """,
                event_data["event_type"],
                json.dumps(event_data.get("payload", {})),
                event_data.get("timestamp", self._get_timestamp()),
                json.dumps(event_data.get("delivered_to", [])),
            )
            return int(row["id"])

    async def query_events(
        self,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query event log with optional type filter."""
        self._ensure_connected()
        assert self._pool is not None

        query = "SELECT * FROM event_log WHERE 1=1"
        params: list[Any] = []
        param_idx = 1

        if event_type:
            query += f" AND event_type = ${param_idx}"
            params.append(event_type)
            param_idx += 1

        query += f" ORDER BY timestamp DESC LIMIT ${param_idx}"
        params.append(limit)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            results = []
            for row in rows:
                result = self._from_record(row)
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
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO feedback (id, session_id, knowledge_id, outcome, notes, reported_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (id) DO UPDATE SET
                    outcome = EXCLUDED.outcome,
                    notes = EXCLUDED.notes
                """,
                feedback_data["id"],
                feedback_data["session_id"],
                feedback_data["knowledge_id"],
                feedback_data["outcome"],
                feedback_data.get("notes", ""),
                feedback_data.get("reported_at", self._get_timestamp()),
            )

    async def query_feedback(
        self,
        knowledge_id: str | None = None,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query feedback with optional filters."""
        self._ensure_connected()
        assert self._pool is not None

        query = "SELECT * FROM feedback WHERE 1=1"
        params: list[Any] = []
        param_idx = 1

        if knowledge_id:
            query += f" AND knowledge_id = ${param_idx}"
            params.append(knowledge_id)
            param_idx += 1

        if session_id:
            query += f" AND session_id = ${param_idx}"
            params.append(session_id)
            param_idx += 1

        query += f" ORDER BY reported_at DESC LIMIT ${param_idx}"
        params.append(limit)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [self._from_record(row) for row in rows]

    # ===== Search Log Operations =====

    async def save_search(self, search_data: dict[str, Any]) -> int:
        """Save a search to the log. Returns search ID."""
        self._ensure_connected()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO search_log
                (session_id, query, context, results_count, top_result_id, searched_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """,
                search_data["session_id"],
                search_data["query"],
                json.dumps(search_data.get("context", {})),
                search_data.get("results_count", 0),
                search_data.get("top_result_id"),
                search_data.get("searched_at", self._get_timestamp()),
            )
            return int(row["id"])

    async def query_searches(
        self,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query search log with optional session filter."""
        self._ensure_connected()
        assert self._pool is not None

        query = "SELECT * FROM search_log WHERE 1=1"
        params: list[Any] = []
        param_idx = 1

        if session_id:
            query += f" AND session_id = ${param_idx}"
            params.append(session_id)
            param_idx += 1

        query += f" ORDER BY searched_at DESC LIMIT ${param_idx}"
        params.append(limit)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            results = []
            for row in rows:
                result = self._from_record(row)
                if isinstance(result.get("context"), str):
                    result["context"] = json.loads(result["context"])
                results.append(result)
            return results

    # ===== Statistics =====

    async def get_statistics(self) -> dict[str, Any]:
        """Get database statistics for monitoring."""
        self._ensure_connected()
        assert self._pool is not None

        stats: dict[str, Any] = {
            "backend": "postgresql",
            "dsn": self.dsn.split("@")[-1] if "@" in self.dsn else self.dsn,
        }

        async with self._pool.acquire() as conn:
            # Get table counts
            tables = ["staging_queue", "webhooks", "event_log", "feedback", "search_log"]
            for table in tables:
                row = await conn.fetchrow(f"SELECT COUNT(*) as count FROM {table}")
                stats[f"{table}_count"] = int(row["count"]) if row else 0

            # Get staging queue by status
            rows = await conn.fetch(
                "SELECT status, COUNT(*) as count FROM staging_queue GROUP BY status"
            )
            stats["staging_by_status"] = {
                str(row["status"]): int(row["count"]) for row in rows
            }

            # Get database size
            row = await conn.fetchrow(
                "SELECT pg_database_size(current_database()) as size"
            )
            if row:
                stats["size_bytes"] = int(row["size"])

            # Get pool stats
            stats["pool_size"] = self._pool.get_size()
            stats["pool_free"] = self._pool.get_idle_size()

        return stats
