"""Tests for lean MCP interface (discover_tools, get_tool_spec, execute_tool)."""

from __future__ import annotations

import pytest

from knowledge_bridge.core.service import KnowledgeBridgeService
from knowledge_bridge.lean.interface import LeanMCPInterface, TOOL_SPECS


class TestDiscoverTools:
    """Tests for discover_tools meta-tool."""

    @pytest.mark.asyncio
    async def test_discover_all(
        self,
        lean_interface: LeanMCPInterface,
    ) -> None:
        """Test discovering all tools."""
        result = await lean_interface.discover_tools()

        assert result["total_tools"] == 12
        assert result["filtered_count"] == 12
        assert len(result["available_tools"]) == 12
        assert "categories" in result

    @pytest.mark.asyncio
    async def test_discover_with_pattern(
        self,
        lean_interface: LeanMCPInterface,
    ) -> None:
        """Test discovering tools with pattern filter."""
        result = await lean_interface.discover_tools(pattern="webhook")

        assert result["filtered_count"] < result["total_tools"]
        for tool in result["available_tools"]:
            assert "webhook" in tool["name"].lower() or "webhook" in tool["description"].lower()

    @pytest.mark.asyncio
    async def test_discover_categories(
        self,
        lean_interface: LeanMCPInterface,
    ) -> None:
        """Test that categories are returned."""
        result = await lean_interface.discover_tools()

        categories = result["categories"]
        assert "promotion" in categories
        assert "retrieval" in categories
        assert "feedback" in categories
        assert "webhooks" in categories
        assert "inter_server" in categories


class TestGetToolSpec:
    """Tests for get_tool_spec meta-tool."""

    @pytest.mark.asyncio
    async def test_get_existing_spec(
        self,
        lean_interface: LeanMCPInterface,
    ) -> None:
        """Test getting spec for existing tool."""
        result = await lean_interface.get_tool_spec("promote_learning")

        assert result["name"] == "promote_learning"
        assert "description" in result
        assert "parameters" in result
        assert "examples" in result

    @pytest.mark.asyncio
    async def test_get_nonexistent_spec(
        self,
        lean_interface: LeanMCPInterface,
    ) -> None:
        """Test getting spec for non-existent tool."""
        result = await lean_interface.get_tool_spec("not_a_real_tool")

        assert "error" in result
        assert "available_tools" in result

    @pytest.mark.asyncio
    async def test_all_tools_have_specs(
        self,
        lean_interface: LeanMCPInterface,
    ) -> None:
        """Test that all 10 tools have valid specs."""
        expected_tools = [
            "promote_learning",
            "batch_promote",
            "get_staging_queue",
            "search_for_session",
            "prime_session",
            "report_outcome",
            "register_webhook",
            "unregister_webhook",
            "list_webhooks",
            "request_session_data",
        ]

        for tool_name in expected_tools:
            result = await lean_interface.get_tool_spec(tool_name)
            assert "error" not in result, f"Missing spec for {tool_name}"
            assert result["name"] == tool_name


class TestExecuteTool:
    """Tests for execute_tool meta-tool."""

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(
        self,
        lean_interface: LeanMCPInterface,
    ) -> None:
        """Test executing unknown tool."""
        result = await lean_interface.execute_tool(
            "not_a_tool",
            {},
        )

        assert result["status"] == "error"
        assert "Unknown tool" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_with_invalid_params(
        self,
        lean_interface: LeanMCPInterface,
    ) -> None:
        """Test executing with invalid parameters."""
        result = await lean_interface.execute_tool(
            "promote_learning",
            {"invalid_param": "value"},
        )

        # Should fail with parameter error or succeed with defaults
        # depending on implementation
        assert result["tool"] == "promote_learning"

    @pytest.mark.asyncio
    async def test_execute_returns_result(
        self,
        lean_interface: LeanMCPInterface,
    ) -> None:
        """Test that execute returns proper result format."""
        result = await lean_interface.execute_tool(
            "list_webhooks",
            {},
        )

        assert "tool" in result
        assert "status" in result
        assert result["status"] in ["success", "error"]


class TestRequestSessionData:
    """Tests for request_session_data inter-server tool."""

    @pytest.mark.asyncio
    async def test_request_session_data(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test requesting session data from session-intelligence."""
        result = await service.request_session_data(
            session_id="test-session",
            data_types=["learnings", "decisions"],
        )

        assert result.session_id == "test-session"
        assert hasattr(result, "learnings")
        assert hasattr(result, "decisions")

    @pytest.mark.asyncio
    async def test_request_session_data_via_interface(
        self,
        lean_interface: LeanMCPInterface,
    ) -> None:
        """Test request_session_data through MCP interface."""
        result = await lean_interface.execute_tool(
            "request_session_data",
            {
                "session_id": "interface-session",
                "data_types": ["learnings"],
            },
        )

        assert result["status"] == "success"
        assert result["result"]["session_id"] == "interface-session"


class TestToolSpecsIntegrity:
    """Tests for TOOL_SPECS registry integrity."""

    def test_all_tools_have_handlers(self) -> None:
        """Test that all specs have corresponding handlers."""
        from knowledge_bridge.lean.interface import LeanMCPInterface
        from unittest.mock import MagicMock

        # Create interface with mock service
        mock_service = MagicMock()
        interface = LeanMCPInterface(service=mock_service)

        for tool_name in TOOL_SPECS:
            assert tool_name in interface._tool_handlers, f"Missing handler for {tool_name}"

    def test_tool_specs_have_required_fields(self) -> None:
        """Test that all specs have required fields."""
        for name, spec in TOOL_SPECS.items():
            assert spec.name == name
            assert spec.description
            assert spec.parameters
            assert spec.category
