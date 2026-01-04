"""Base database backend interface for knowledge-bridge.

Provides a base class for database backends:
- SQLite (development, single-user)
- PostgreSQL (production, multi-session)

Data directory: ~/.claude/knowledge-bridge/
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

# Default global location for knowledge-bridge data
DEFAULT_DATA_DIR = Path.home() / ".claude" / "knowledge-bridge"
DEFAULT_SQLITE_PATH = DEFAULT_DATA_DIR / "knowledge_bridge.db"
DEFAULT_POSTGRES_DSN = "postgresql://localhost/knowledge_bridge"


def get_default_data_dir() -> Path:
    """Get the default data directory, creating it if needed."""
    DEFAULT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DEFAULT_DATA_DIR


class BaseDatabaseBackend(ABC):
    """Abstract base class for database backends."""

    SCHEMA_VERSION = 1

    def __init__(self) -> None:
        self._is_connected = False

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize database connection and apply schema."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close database connection."""
        pass

    def _get_timestamp(self) -> datetime:
        """Get current timestamp."""
        return datetime.now()

    # ===== Staging Queue Operations =====

    @abstractmethod
    async def save_staged_entry(self, entry_data: dict[str, Any]) -> None:
        """Save or update a staged entry."""
        pass

    @abstractmethod
    async def get_staged_entry(self, entry_id: str) -> dict[str, Any] | None:
        """Get a staged entry by ID."""
        pass

    @abstractmethod
    async def query_staging_queue(
        self,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Query staging queue with optional status filter."""
        pass

    @abstractmethod
    async def update_staged_entry_status(
        self,
        entry_id: str,
        status: str,
        curator_notes: str | None = None,
        promoted_to: str | None = None,
    ) -> bool:
        """Update status of a staged entry."""
        pass

    # ===== Webhook Operations =====

    @abstractmethod
    async def save_webhook(self, webhook_data: dict[str, Any]) -> None:
        """Save or update a webhook registration."""
        pass

    @abstractmethod
    async def get_webhook(self, webhook_id: str) -> dict[str, Any] | None:
        """Get a webhook by ID."""
        pass

    @abstractmethod
    async def query_webhooks(
        self,
        active_only: bool = True,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query webhooks with optional filters."""
        pass

    @abstractmethod
    async def delete_webhook(self, webhook_id: str) -> bool:
        """Delete a webhook by ID."""
        pass

    @abstractmethod
    async def update_webhook_status(
        self,
        webhook_id: str,
        active: bool | None = None,
        failure_count: int | None = None,
        last_called: datetime | None = None,
    ) -> bool:
        """Update webhook status fields."""
        pass

    # ===== Event Log Operations =====

    @abstractmethod
    async def save_event(self, event_data: dict[str, Any]) -> int:
        """Save an event to the log. Returns event ID."""
        pass

    @abstractmethod
    async def query_events(
        self,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query event log with optional type filter."""
        pass

    # ===== Feedback Operations =====

    @abstractmethod
    async def save_feedback(self, feedback_data: dict[str, Any]) -> None:
        """Save feedback for a knowledge entry."""
        pass

    @abstractmethod
    async def query_feedback(
        self,
        knowledge_id: str | None = None,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query feedback with optional filters."""
        pass

    # ===== Search Log Operations =====

    @abstractmethod
    async def save_search(self, search_data: dict[str, Any]) -> int:
        """Save a search to the log. Returns search ID."""
        pass

    @abstractmethod
    async def query_searches(
        self,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query search log with optional session filter."""
        pass

    # ===== Statistics =====

    @abstractmethod
    async def get_statistics(self) -> dict[str, Any]:
        """Get database statistics for monitoring."""
        pass
