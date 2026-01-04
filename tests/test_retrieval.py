"""Tests for retrieval flow (search_for_session, prime_session)."""

from __future__ import annotations

import pytest

from knowledge_bridge.core.service import KnowledgeBridgeService
from knowledge_bridge.lean.interface import LeanMCPInterface


class TestSearchForSession:
    """Tests for search_for_session tool."""

    @pytest.mark.asyncio
    async def test_search_basic(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test basic search."""
        matches = await service.search_for_session(
            session_id="test-session",
            query="pytest fixture error",
        )

        assert isinstance(matches, list)
        # Mock returns results
        assert len(matches) > 0

    @pytest.mark.asyncio
    async def test_search_with_context(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test search with project context."""
        matches = await service.search_for_session(
            session_id="test-session",
            query="database connection pool",
            context={
                "project_type": "python",
                "framework": "sqlalchemy",
            },
        )

        assert isinstance(matches, list)

    @pytest.mark.asyncio
    async def test_search_with_limit(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test search with result limit."""
        matches = await service.search_for_session(
            session_id="test-session",
            query="any query",
            limit=3,
        )

        assert len(matches) <= 3

    @pytest.mark.asyncio
    async def test_search_logs_to_database(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test that searches are logged."""
        await service.search_for_session(
            session_id="test-session",
            query="logged search",
        )

        # Check search was logged
        searches = await service.database.query_searches(session_id="test-session")
        assert len(searches) == 1
        assert searches[0]["query"] == "logged search"


class TestPrimeSession:
    """Tests for prime_session tool."""

    @pytest.mark.asyncio
    async def test_prime_session_basic(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test basic session priming."""
        result = await service.prime_session(
            session_id="new-session",
            project_context={
                "project_type": "python",
                "tech_stack": ["fastapi", "pytest"],
            },
        )

        assert result.session_id == "new-session"
        assert result.project_type_detected == "python"
        assert result.patterns_loaded >= 0

    @pytest.mark.asyncio
    async def test_prime_session_returns_patterns(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test that priming returns relevant patterns."""
        result = await service.prime_session(
            session_id="test-session",
            project_context={
                "project_type": "python",
                "tech_stack": ["django", "postgresql"],
            },
        )

        # Should have patterns (from mock)
        assert isinstance(result.top_patterns, list)

    @pytest.mark.asyncio
    async def test_prime_session_empty_context(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test priming with minimal context."""
        result = await service.prime_session(
            session_id="minimal-session",
            project_context={},
        )

        assert result.session_id == "minimal-session"
        assert result.project_type_detected == "unknown"


class TestRetrievalViaInterface:
    """Tests for retrieval tools via lean interface."""

    @pytest.mark.asyncio
    async def test_search_via_interface(
        self,
        lean_interface: LeanMCPInterface,
    ) -> None:
        """Test search_for_session through MCP interface."""
        result = await lean_interface.execute_tool(
            "search_for_session",
            {
                "session_id": "test-session",
                "query": "test query",
                "limit": 5,
            },
        )

        assert result["status"] == "success"
        assert isinstance(result["result"], list)

    @pytest.mark.asyncio
    async def test_prime_session_via_interface(
        self,
        lean_interface: LeanMCPInterface,
    ) -> None:
        """Test prime_session through MCP interface."""
        result = await lean_interface.execute_tool(
            "prime_session",
            {
                "session_id": "new-session",
                "project_context": {
                    "project_type": "python",
                    "tech_stack": ["pytest"],
                },
            },
        )

        assert result["status"] == "success"
        assert result["result"]["session_id"] == "new-session"
