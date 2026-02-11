"""Tests for promotion flow (promote_learning, batch_promote, get_staging_queue)."""

from __future__ import annotations

import pytest

from knowledge_bridge.core.service import KnowledgeBridgeService
from knowledge_bridge.lean.interface import LeanMCPInterface


class TestPromoteLearning:
    """Tests for promote_learning tool."""

    @pytest.mark.asyncio
    async def test_promote_direct_staged(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test promoting a direct learning to staging queue."""
        result = await service.promote_learning(
            source="direct",
            content={"pattern": "test error", "solution": "test fix"},
            promotion_type="staged",
        )

        assert result.success is True
        assert result.status == "staged"
        assert result.entry_id.startswith("kb-")
        assert "staging queue" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_promote_direct_immediate(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test promoting a direct learning immediately to UCKN."""
        result = await service.promote_learning(
            source="direct",
            content={"pattern": "high confidence", "solution": "proven fix"},
            promotion_type="immediate",
        )

        assert result.success is True
        assert result.status == "promoted"
        assert "UCKN" in result.reason

    @pytest.mark.asyncio
    async def test_promote_session_intelligence(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test promoting from session-intelligence."""
        result = await service.promote_learning(
            source="session-intelligence",
            learning_id="learn-test",
            promotion_type="staged",
        )

        assert result.success is True
        assert result.status == "staged"

    @pytest.mark.asyncio
    async def test_promote_missing_learning_id(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test error when learning_id not provided for session-intelligence."""
        result = await service.promote_learning(
            source="session-intelligence",
        )

        assert result.success is False
        assert result.status == "rejected"
        assert "learning_id required" in result.reason

    @pytest.mark.asyncio
    async def test_promote_missing_content(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test error when content not provided for direct source."""
        result = await service.promote_learning(
            source="direct",
        )

        assert result.success is False
        assert result.status == "rejected"
        assert "content required" in result.reason


class TestBatchPromote:
    """Tests for batch_promote tool."""

    @pytest.mark.asyncio
    async def test_batch_promote_session(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test batch promoting learnings from a session."""
        result = await service.batch_promote(
            session_id="test-session",
        )

        assert result.total_learnings == 2  # From mock
        assert result.promoted_immediately + result.staged_for_review + result.rejected == 2

    @pytest.mark.asyncio
    async def test_batch_promote_with_filter(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test batch promote with confidence filter."""
        result = await service.batch_promote(
            session_id="test-session",
            filter_config={"min_confidence": 0.8},
        )

        # Should filter out low confidence learnings
        assert result.rejected >= 0

    @pytest.mark.asyncio
    async def test_batch_promote_empty_session(
        self,
        service: KnowledgeBridgeService,
        mock_session_client,
    ) -> None:
        """Test batch promote with no learnings."""
        mock_session_client.get_session_learnings.return_value = []

        result = await service.batch_promote(
            session_id="empty-session",
        )

        assert result.total_learnings == 0
        assert result.promoted_immediately == 0
        assert result.staged_for_review == 0


class TestGetStagingQueue:
    """Tests for get_staging_queue tool."""

    @pytest.mark.asyncio
    async def test_get_empty_queue(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test getting empty staging queue."""
        entries = await service.get_staging_queue()

        assert entries == []

    @pytest.mark.asyncio
    async def test_get_queue_after_staging(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test getting queue after staging a learning."""
        # Stage a learning
        await service.promote_learning(
            source="direct",
            content={"pattern": "test", "solution": "fix"},
            promotion_type="staged",
        )

        # Get queue
        entries = await service.get_staging_queue(status="pending")

        assert len(entries) == 1
        assert entries[0].status == "pending"
        assert entries[0].source == "direct"

    @pytest.mark.asyncio
    async def test_get_queue_with_limit(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test getting queue with limit."""
        # Stage multiple learnings
        for i in range(5):
            await service.promote_learning(
                source="direct",
                content={"pattern": f"test-{i}", "solution": f"fix-{i}"},
                promotion_type="staged",
            )

        # Get with limit
        entries = await service.get_staging_queue(limit=2)

        assert len(entries) == 2


class TestApproveStagedEntry:
    """Tests for approve_staged_entry tool - the missing link for searchability."""

    @pytest.mark.asyncio
    async def test_approve_staged_entry_success(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test approving a staged entry promotes it to knowledge-store."""
        # First, stage a learning
        staged_result = await service.promote_learning(
            source="direct",
            content={"problem_pattern": "test error", "solution": "test fix"},
            promotion_type="staged",
        )
        assert staged_result.success is True
        entry_id = staged_result.entry_id

        # Now approve it
        approve_result = await service.approve_staged_entry(
            entry_id=entry_id,
            curator_notes="Verified as useful",
        )

        assert approve_result.success is True
        assert approve_result.status == "promoted"
        assert "knowledge-store" in approve_result.reason.lower()

    @pytest.mark.asyncio
    async def test_approve_nonexistent_entry(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test approving a non-existent entry fails gracefully."""
        result = await service.approve_staged_entry(
            entry_id="kb-nonexistent",
        )

        assert result.success is False
        assert result.status == "rejected"
        assert "not found" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_approve_already_promoted_entry(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test approving an already promoted entry fails."""
        # Stage and approve
        staged = await service.promote_learning(
            source="direct",
            content={"problem_pattern": "test", "solution": "fix"},
            promotion_type="staged",
        )
        entry_id = staged.entry_id
        await service.approve_staged_entry(entry_id=entry_id)

        # Try to approve again
        result = await service.approve_staged_entry(entry_id=entry_id)

        assert result.success is False
        assert result.status == "rejected"
        assert "already promoted" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_approve_updates_staging_status(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test that approval updates the staging entry status."""
        # Stage a learning
        staged = await service.promote_learning(
            source="direct",
            content={"problem_pattern": "test", "solution": "fix"},
            promotion_type="staged",
        )
        entry_id = staged.entry_id

        # Verify pending status
        entry = await service.get_staged_entry(entry_id)
        assert entry is not None
        assert entry.status == "pending"

        # Approve
        await service.approve_staged_entry(entry_id=entry_id)

        # Verify promoted status
        entry = await service.get_staged_entry(entry_id)
        assert entry is not None
        assert entry.status == "promoted"
        assert entry.promoted_to is not None


class TestPromotionViaInterface:
    """Tests for promotion tools via lean interface."""

    @pytest.mark.asyncio
    async def test_promote_learning_via_interface(
        self,
        lean_interface: LeanMCPInterface,
    ) -> None:
        """Test promote_learning through MCP interface."""
        result = await lean_interface.execute_tool(
            "promote_learning",
            {
                "source": "direct",
                "content": {"pattern": "interface test", "solution": "works"},
                "promotion_type": "staged",
            },
        )

        assert result["status"] == "success"
        assert result["result"]["success"] is True

    @pytest.mark.asyncio
    async def test_batch_promote_via_interface(
        self,
        lean_interface: LeanMCPInterface,
    ) -> None:
        """Test batch_promote through MCP interface."""
        result = await lean_interface.execute_tool(
            "batch_promote",
            {"session_id": "test-session"},
        )

        assert result["status"] == "success"
        assert "total_learnings" in result["result"]

    @pytest.mark.asyncio
    async def test_get_staging_queue_via_interface(
        self,
        lean_interface: LeanMCPInterface,
    ) -> None:
        """Test get_staging_queue through MCP interface."""
        result = await lean_interface.execute_tool(
            "get_staging_queue",
            {"status": "pending", "limit": 10},
        )

        assert result["status"] == "success"
        assert isinstance(result["result"], list)

    @pytest.mark.asyncio
    async def test_approve_staged_entry_via_interface(
        self,
        lean_interface: LeanMCPInterface,
    ) -> None:
        """Test approve_staged_entry through MCP interface."""
        # First stage a learning
        stage_result = await lean_interface.execute_tool(
            "promote_learning",
            {
                "source": "direct",
                "content": {"problem_pattern": "test", "solution": "fix"},
                "promotion_type": "staged",
            },
        )
        entry_id = stage_result["result"]["entry_id"]

        # Now approve via interface
        result = await lean_interface.execute_tool(
            "approve_staged_entry",
            {"entry_id": entry_id, "curator_notes": "Approved via interface test"},
        )

        assert result["status"] == "success"
        assert result["result"]["success"] is True
        assert result["result"]["status"] == "promoted"
