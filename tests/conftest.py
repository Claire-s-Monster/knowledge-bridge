"""Pytest fixtures for knowledge-bridge tests."""

from __future__ import annotations

from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from knowledge_bridge.clients.session_intel import SessionIntelligenceClient
from knowledge_bridge.clients.uckn import MockUCKNClient
from knowledge_bridge.core.models import (
    KnowledgeMatch,
    PromotionResult,
    StagedEntry,
    WebhookRegistration,
)
from knowledge_bridge.core.service import KnowledgeBridgeService
from knowledge_bridge.lean.interface import LeanMCPInterface
from knowledge_bridge.persistence.base import BaseDatabaseBackend
from knowledge_bridge.webhooks.emitter import WebhookEmitter


# ===== Mock Database Backend =====


class MockDatabaseBackend(BaseDatabaseBackend):
    """In-memory mock database for testing."""

    def __init__(self) -> None:
        super().__init__()
        self._staging_queue: dict[str, dict[str, Any]] = {}
        self._webhooks: dict[str, dict[str, Any]] = {}
        self._events: list[dict[str, Any]] = []
        self._feedback: list[dict[str, Any]] = []
        self._searches: list[dict[str, Any]] = []

    async def initialize(self) -> None:
        self._is_connected = True

    async def close(self) -> None:
        self._is_connected = False

    # Staging Queue
    async def save_staged_entry(self, entry_data: dict[str, Any]) -> None:
        self._staging_queue[entry_data["id"]] = entry_data

    async def get_staged_entry(self, entry_id: str) -> dict[str, Any] | None:
        return self._staging_queue.get(entry_id)

    async def query_staging_queue(
        self,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        results = list(self._staging_queue.values())
        if status:
            results = [e for e in results if e.get("status") == status]
        return results[:limit]

    async def update_staged_entry_status(
        self,
        entry_id: str,
        status: str,
        curator_notes: str | None = None,
        promoted_to: str | None = None,
    ) -> bool:
        if entry_id not in self._staging_queue:
            return False
        self._staging_queue[entry_id]["status"] = status
        if curator_notes:
            self._staging_queue[entry_id]["curator_notes"] = curator_notes
        if promoted_to:
            self._staging_queue[entry_id]["promoted_to"] = promoted_to
        return True

    # Webhooks
    async def save_webhook(self, webhook_data: dict[str, Any]) -> None:
        self._webhooks[webhook_data["id"]] = webhook_data

    async def get_webhook(self, webhook_id: str) -> dict[str, Any] | None:
        return self._webhooks.get(webhook_id)

    async def query_webhooks(
        self,
        active_only: bool = True,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        results = list(self._webhooks.values())
        if active_only:
            results = [w for w in results if w.get("active", True)]
        if event_type:
            results = [w for w in results if event_type in w.get("events", [])]
        return results

    async def delete_webhook(self, webhook_id: str) -> bool:
        if webhook_id in self._webhooks:
            del self._webhooks[webhook_id]
            return True
        return False

    async def update_webhook_status(
        self,
        webhook_id: str,
        active: bool | None = None,
        failure_count: int | None = None,
        last_called: Any = None,
    ) -> bool:
        if webhook_id not in self._webhooks:
            return False
        if active is not None:
            self._webhooks[webhook_id]["active"] = active
        if failure_count is not None:
            self._webhooks[webhook_id]["failure_count"] = failure_count
        if last_called is not None:
            self._webhooks[webhook_id]["last_called"] = last_called
        return True

    # Events
    async def save_event(self, event_data: dict[str, Any]) -> int:
        event_id = len(self._events) + 1
        event_data["id"] = event_id
        self._events.append(event_data)
        return event_id

    async def query_events(
        self,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        results = self._events.copy()
        if event_type:
            results = [e for e in results if e.get("event_type") == event_type]
        return results[:limit]

    # Feedback
    async def save_feedback(self, feedback_data: dict[str, Any]) -> None:
        self._feedback.append(feedback_data)

    async def query_feedback(
        self,
        knowledge_id: str | None = None,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        results = self._feedback.copy()
        if knowledge_id:
            results = [f for f in results if f.get("knowledge_id") == knowledge_id]
        if session_id:
            results = [f for f in results if f.get("session_id") == session_id]
        return results[:limit]

    # Searches
    async def save_search(self, search_data: dict[str, Any]) -> int:
        search_id = len(self._searches) + 1
        search_data["id"] = search_id
        self._searches.append(search_data)
        return search_id

    async def query_searches(
        self,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        results = self._searches.copy()
        if session_id:
            results = [s for s in results if s.get("session_id") == session_id]
        return results[:limit]

    # Statistics
    async def get_statistics(self) -> dict[str, Any]:
        return {
            "backend": "mock",
            "staging_queue_count": len(self._staging_queue),
            "webhooks_count": len(self._webhooks),
            "event_log_count": len(self._events),
            "feedback_count": len(self._feedback),
            "search_log_count": len(self._searches),
        }


# ===== Fixtures =====


@pytest.fixture
def mock_database() -> MockDatabaseBackend:
    """Create mock database backend."""
    db = MockDatabaseBackend()
    db._is_connected = True
    return db


@pytest_asyncio.fixture
async def mock_database_async() -> AsyncGenerator[MockDatabaseBackend, None]:
    """Create and initialize mock database backend."""
    db = MockDatabaseBackend()
    await db.initialize()
    yield db
    await db.close()


@pytest.fixture
def mock_session_client() -> SessionIntelligenceClient:
    """Create mock session-intelligence client."""
    client = SessionIntelligenceClient()
    # Replace methods with mocks
    client.health_check = AsyncMock(return_value=True)
    client.get_learning = AsyncMock(return_value={
        "id": "learn-test",
        "problem": "Test problem pattern",
        "solution": "Test solution",
        "confidence": 0.9,
    })
    client.get_session_learnings = AsyncMock(return_value=[
        {
            "id": "learn-1",
            "problem": "Learning 1 problem",
            "solution": "Learning 1 solution",
            "confidence": 0.9,
        },
        {
            "id": "learn-2",
            "problem": "Learning 2 problem",
            "solution": "Learning 2 solution",
            "confidence": 0.6,
        },
    ])
    client.get_session_data = AsyncMock(return_value={
        "session_id": "test-session",
        "learnings": [],
        "decisions": [],
        "notes": [],
    })
    client.close = AsyncMock()
    return client


@pytest.fixture
def mock_knowledge_store_client():
    """Create mock knowledge-store client (using MockUCKNClient for testing)."""
    return MockUCKNClient()


@pytest.fixture
def mock_webhook_emitter(mock_database: MockDatabaseBackend) -> WebhookEmitter:
    """Create mock webhook emitter."""
    emitter = WebhookEmitter(database=mock_database)
    # Don't make actual HTTP calls
    emitter._deliver_to_webhook = AsyncMock(return_value=True)
    return emitter


@pytest_asyncio.fixture
async def service(
    mock_database_async: MockDatabaseBackend,
    mock_session_client: SessionIntelligenceClient,
    mock_knowledge_store_client,
) -> AsyncGenerator[KnowledgeBridgeService, None]:
    """Create service with mock dependencies."""
    emitter = WebhookEmitter(database=mock_database_async)
    emitter._deliver_to_webhook = AsyncMock(return_value=True)

    svc = KnowledgeBridgeService(
        database=mock_database_async,
        session_client=mock_session_client,
        knowledge_store_client=mock_knowledge_store_client,
        webhook_emitter=emitter,
    )
    yield svc
    await emitter.close()


@pytest_asyncio.fixture
async def lean_interface(
    service: KnowledgeBridgeService,
) -> LeanMCPInterface:
    """Create lean MCP interface with service."""
    return LeanMCPInterface(service=service)


# ===== Test Data Factories =====


@pytest.fixture
def sample_learning() -> dict[str, Any]:
    """Create sample learning data."""
    return {
        "id": "learn-sample",
        "session_id": "session-test",
        "content": "Sample learning content",
        "category": "error_fix",
        "confidence": 0.85,
    }


@pytest.fixture
def sample_staged_entry() -> StagedEntry:
    """Create sample staged entry."""
    return StagedEntry(
        id="staged-sample",
        source="direct",
        content={"pattern": "test", "solution": "solution"},
        status="pending",
    )


@pytest.fixture
def sample_webhook() -> WebhookRegistration:
    """Create sample webhook registration."""
    return WebhookRegistration(
        id="wh-sample",
        subscriber="test",
        events=["learning.staged"],
        endpoint="http://localhost:5000/webhook",
    )


@pytest.fixture
def sample_knowledge_match() -> KnowledgeMatch:
    """Create sample knowledge match."""
    return KnowledgeMatch(
        knowledge_id="uckn-sample",
        problem_pattern="Test pattern",
        solution="Test solution",
        relevance_score=0.9,
        success_rate=0.8,
        times_applied=10,
        tags=["test"],
    )
