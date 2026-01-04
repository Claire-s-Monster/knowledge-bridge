"""Tests for webhook management (register, unregister, list)."""

from __future__ import annotations

import pytest

from knowledge_bridge.core.service import KnowledgeBridgeService
from knowledge_bridge.lean.interface import LeanMCPInterface


class TestRegisterWebhook:
    """Tests for register_webhook tool."""

    @pytest.mark.asyncio
    async def test_register_basic(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test basic webhook registration."""
        result = await service.register_webhook(
            subscriber="curator",
            events=["learning.staged", "outcome.reported"],
            endpoint="http://localhost:5000/webhook",
        )

        assert result.id.startswith("wh-")
        assert result.subscriber == "curator"
        assert result.events == ["learning.staged", "outcome.reported"]
        assert result.endpoint == "http://localhost:5000/webhook"
        assert result.active is True

    @pytest.mark.asyncio
    async def test_register_multiple(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test registering multiple webhooks."""
        await service.register_webhook(
            subscriber="curator",
            events=["learning.staged"],
            endpoint="http://localhost:5001/webhook",
        )
        await service.register_webhook(
            subscriber="dashboard",
            events=["learning.promoted"],
            endpoint="http://localhost:5002/webhook",
        )

        webhooks = await service.list_webhooks()
        assert len(webhooks) == 2


class TestUnregisterWebhook:
    """Tests for unregister_webhook tool."""

    @pytest.mark.asyncio
    async def test_unregister_existing(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test unregistering existing webhook."""
        # Register first
        reg = await service.register_webhook(
            subscriber="test",
            events=["test.event"],
            endpoint="http://localhost:9999/test",
        )

        # Unregister
        success = await service.unregister_webhook(reg.id)
        assert success is True

        # Verify gone
        webhooks = await service.list_webhooks()
        assert len(webhooks) == 0

    @pytest.mark.asyncio
    async def test_unregister_nonexistent(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test unregistering non-existent webhook."""
        success = await service.unregister_webhook("wh-does-not-exist")
        assert success is False


class TestListWebhooks:
    """Tests for list_webhooks tool."""

    @pytest.mark.asyncio
    async def test_list_empty(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test listing empty webhooks."""
        webhooks = await service.list_webhooks()
        assert webhooks == []

    @pytest.mark.asyncio
    async def test_list_with_webhooks(
        self,
        service: KnowledgeBridgeService,
    ) -> None:
        """Test listing registered webhooks."""
        await service.register_webhook(
            subscriber="curator",
            events=["learning.staged"],
            endpoint="http://localhost:5001/webhook",
        )
        await service.register_webhook(
            subscriber="dashboard",
            events=["learning.promoted"],
            endpoint="http://localhost:5002/webhook",
        )

        webhooks = await service.list_webhooks()
        assert len(webhooks) == 2
        subscribers = [w.subscriber for w in webhooks]
        assert "curator" in subscribers
        assert "dashboard" in subscribers


class TestWebhooksViaInterface:
    """Tests for webhook tools via lean interface."""

    @pytest.mark.asyncio
    async def test_register_via_interface(
        self,
        lean_interface: LeanMCPInterface,
    ) -> None:
        """Test register_webhook through MCP interface."""
        result = await lean_interface.execute_tool(
            "register_webhook",
            {
                "subscriber": "test-service",
                "events": ["test.event"],
                "endpoint": "http://localhost:8000/hook",
            },
        )

        assert result["status"] == "success"
        assert result["result"]["subscriber"] == "test-service"

    @pytest.mark.asyncio
    async def test_unregister_via_interface(
        self,
        lean_interface: LeanMCPInterface,
    ) -> None:
        """Test unregister_webhook through MCP interface."""
        # Register first
        reg_result = await lean_interface.execute_tool(
            "register_webhook",
            {
                "subscriber": "to-delete",
                "events": ["test.event"],
                "endpoint": "http://localhost:8000/delete",
            },
        )
        webhook_id = reg_result["result"]["id"]

        # Unregister
        result = await lean_interface.execute_tool(
            "unregister_webhook",
            {"webhook_id": webhook_id},
        )

        assert result["status"] == "success"
        assert result["result"]["deleted"] is True

    @pytest.mark.asyncio
    async def test_list_via_interface(
        self,
        lean_interface: LeanMCPInterface,
    ) -> None:
        """Test list_webhooks through MCP interface."""
        result = await lean_interface.execute_tool("list_webhooks", {})

        assert result["status"] == "success"
        assert isinstance(result["result"], list)
