"""Tests for feedback flow (report_outcome)."""

from __future__ import annotations

import pytest

from knowledge_bridge.core.service import KnowledgeBridgeService
from knowledge_bridge.lean.interface import LeanMCPInterface


class TestReportOutcome:
    """Tests for report_outcome tool."""

    @pytest.mark.asyncio
    async def test_report_success(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test reporting successful outcome."""
        result = await service.report_outcome(
            session_id="test-session",
            knowledge_id="uckn-abc",
            outcome="success",
            notes="Worked perfectly",
        )

        assert result.session_id == "test-session"
        assert result.knowledge_id == "uckn-abc"
        assert result.outcome == "success"
        assert result.notes == "Worked perfectly"
        assert result.id.startswith("fb-")

    @pytest.mark.asyncio
    async def test_report_failure(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test reporting failed outcome."""
        result = await service.report_outcome(
            session_id="test-session",
            knowledge_id="uckn-xyz",
            outcome="failure",
            notes="Did not work for this case",
        )

        assert result.outcome == "failure"

    @pytest.mark.asyncio
    async def test_report_partial(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test reporting partial success."""
        result = await service.report_outcome(
            session_id="test-session",
            knowledge_id="uckn-123",
            outcome="partial",
            notes="Partially worked, needed adjustment",
        )

        assert result.outcome == "partial"

    @pytest.mark.asyncio
    async def test_report_without_notes(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test reporting without notes."""
        result = await service.report_outcome(
            session_id="test-session",
            knowledge_id="uckn-456",
            outcome="success",
        )

        assert result.notes == ""

    @pytest.mark.asyncio
    async def test_feedback_stored_in_database(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test that feedback is stored in database."""
        await service.report_outcome(
            session_id="test-session",
            knowledge_id="uckn-db-test",
            outcome="success",
        )

        feedback = await service.database.query_feedback(
            knowledge_id="uckn-db-test",
        )
        assert len(feedback) == 1
        assert feedback[0]["outcome"] == "success"


class TestFeedbackViaInterface:
    """Tests for feedback tools via lean interface."""

    @pytest.mark.asyncio
    async def test_report_outcome_via_interface(
        self,
        lean_interface: LeanMCPInterface,
    ) -> None:
        """Test report_outcome through MCP interface."""
        result = await lean_interface.execute_tool(
            "report_outcome",
            {
                "session_id": "interface-session",
                "knowledge_id": "uckn-interface",
                "outcome": "success",
                "notes": "Via interface",
            },
        )

        assert result["status"] == "success"
        assert result["result"]["outcome"] == "success"
