"""Lean MCP interface for knowledge-bridge.

Exposes 10 tools via 3-meta-tool pattern:
- discover_tools(pattern) - List available tools
- get_tool_spec(name) - Get schema for a tool
- execute_tool(name, params) - Execute a tool
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any

from pydantic import BaseModel, Field

from knowledge_bridge.core.service import KnowledgeBridgeService

logger = logging.getLogger(__name__)


# ===== Tool Definitions =====


class ToolSpec(BaseModel):
    """Specification for a tool."""

    name: str
    description: str
    parameters: dict[str, Any]
    examples: list[dict[str, Any]] = Field(default_factory=list)
    category: str = "general"


class ToolResult(BaseModel):
    """Result from tool execution."""

    tool: str
    status: str  # "success" | "error"
    result: Any = None
    error: str | None = None


# ===== Tool Registry =====


TOOL_SPECS: dict[str, ToolSpec] = {
    # Promotion tools
    "promote_learning": ToolSpec(
        name="promote_learning",
        description="Promote a learning to UCKN or staging queue",
        category="promotion",
        parameters={
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "enum": ["session-intelligence", "direct"],
                    "description": "Where the learning comes from",
                },
                "learning_id": {
                    "type": "string",
                    "description": "Learning ID if source is session-intelligence",
                },
                "content": {
                    "type": "object",
                    "description": "Learning content if source is direct",
                },
                "promotion_type": {
                    "type": "string",
                    "enum": ["immediate", "staged"],
                    "default": "staged",
                    "description": "Whether to promote immediately or stage for review",
                },
            },
            "required": ["source"],
        },
        examples=[
            {
                "source": "session-intelligence",
                "learning_id": "learn-abc123",
                "promotion_type": "staged",
            },
            {
                "source": "direct",
                "content": {"pattern": "error fix", "solution": "..."},
                "promotion_type": "immediate",
            },
        ],
    ),
    "batch_promote": ToolSpec(
        name="batch_promote",
        description="Batch promote learnings from a session",
        category="promotion",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID to fetch learnings from",
                },
                "filter": {
                    "type": "object",
                    "properties": {
                        "min_confidence": {"type": "number", "default": 0.5},
                        "categories": {"type": "array", "items": {"type": "string"}},
                    },
                    "description": "Filter criteria for learnings",
                },
            },
            "required": ["session_id"],
        },
        examples=[
            {
                "session_id": "session-xyz789",
                "filter": {"min_confidence": 0.8, "categories": ["error_fix"]},
            },
        ],
    ),
    "get_staging_queue": ToolSpec(
        name="get_staging_queue",
        description="Get entries from the staging queue",
        category="promotion",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "reviewing", "all"],
                    "default": "pending",
                    "description": "Filter by status",
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "description": "Maximum entries to return",
                },
            },
        },
        examples=[
            {"status": "pending", "limit": 20},
        ],
    ),
    # Retrieval tools
    "search_for_session": ToolSpec(
        name="search_for_session",
        description="Search knowledge base for a session",
        category="retrieval",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session making the search",
                },
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "context": {
                    "type": "object",
                    "description": "Optional context (project type, framework, etc.)",
                },
                "limit": {
                    "type": "integer",
                    "default": 5,
                    "description": "Maximum results",
                },
            },
            "required": ["session_id", "query"],
        },
        examples=[
            {
                "session_id": "session-abc",
                "query": "pytest fixture scope error",
                "context": {"project_type": "python", "framework": "pytest"},
                "limit": 5,
            },
        ],
    ),
    "prime_session": ToolSpec(
        name="prime_session",
        description="Prime a session with relevant knowledge",
        category="retrieval",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session to prime",
                },
                "project_context": {
                    "type": "object",
                    "properties": {
                        "project_type": {"type": "string"},
                        "tech_stack": {"type": "array", "items": {"type": "string"}},
                    },
                    "description": "Project information",
                },
            },
            "required": ["session_id", "project_context"],
        },
        examples=[
            {
                "session_id": "session-new",
                "project_context": {
                    "project_type": "python",
                    "tech_stack": ["fastapi", "pytest", "postgresql"],
                },
            },
        ],
    ),
    # Feedback tools
    "report_outcome": ToolSpec(
        name="report_outcome",
        description="Report outcome of applying knowledge",
        category="feedback",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session reporting",
                },
                "knowledge_id": {
                    "type": "string",
                    "description": "UCKN entry that was applied",
                },
                "outcome": {
                    "type": "string",
                    "enum": ["success", "failure", "partial"],
                    "description": "Result of applying the knowledge",
                },
                "notes": {
                    "type": "string",
                    "default": "",
                    "description": "Optional notes",
                },
            },
            "required": ["session_id", "knowledge_id", "outcome"],
        },
        examples=[
            {
                "session_id": "session-abc",
                "knowledge_id": "uckn-xyz",
                "outcome": "success",
                "notes": "Fixed the issue immediately",
            },
        ],
    ),
    # Webhook tools
    "register_webhook": ToolSpec(
        name="register_webhook",
        description="Register a webhook subscription",
        category="webhooks",
        parameters={
            "type": "object",
            "properties": {
                "subscriber": {
                    "type": "string",
                    "description": "Subscriber name (e.g., curator, dashboard)",
                },
                "events": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Event types to subscribe to",
                },
                "endpoint": {
                    "type": "string",
                    "format": "uri",
                    "description": "HTTP endpoint for delivery",
                },
            },
            "required": ["subscriber", "events", "endpoint"],
        },
        examples=[
            {
                "subscriber": "curator",
                "events": ["learning.staged", "outcome.reported"],
                "endpoint": "http://localhost:5000/webhook",
            },
        ],
    ),
    "unregister_webhook": ToolSpec(
        name="unregister_webhook",
        description="Unregister a webhook subscription",
        category="webhooks",
        parameters={
            "type": "object",
            "properties": {
                "webhook_id": {
                    "type": "string",
                    "description": "Webhook ID to delete",
                },
            },
            "required": ["webhook_id"],
        },
        examples=[
            {"webhook_id": "wh-abc123"},
        ],
    ),
    "list_webhooks": ToolSpec(
        name="list_webhooks",
        description="List all webhook subscriptions",
        category="webhooks",
        parameters={
            "type": "object",
            "properties": {},
        },
        examples=[{}],
    ),
    # Inter-server tools
    "request_session_data": ToolSpec(
        name="request_session_data",
        description="Request data from session-intelligence",
        category="inter_server",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID to fetch",
                },
                "data_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": ["learnings", "decisions", "notes"],
                    "description": "Types of data to request",
                },
            },
            "required": ["session_id"],
        },
        examples=[
            {
                "session_id": "session-abc",
                "data_types": ["learnings", "decisions"],
            },
        ],
    ),
}


# ===== Lean MCP Interface =====


class LeanMCPInterface:
    """Lean MCP interface using 3-meta-tool pattern."""

    def __init__(self, service: KnowledgeBridgeService) -> None:
        """Initialize interface with service.

        Args:
            service: Knowledge bridge domain service.
        """
        self.service = service
        self._tool_handlers: dict[
            str, Callable[..., Coroutine[Any, Any, Any]]
        ] = {
            "promote_learning": self._promote_learning,
            "batch_promote": self._batch_promote,
            "get_staging_queue": self._get_staging_queue,
            "search_for_session": self._search_for_session,
            "prime_session": self._prime_session,
            "report_outcome": self._report_outcome,
            "register_webhook": self._register_webhook,
            "unregister_webhook": self._unregister_webhook,
            "list_webhooks": self._list_webhooks,
            "request_session_data": self._request_session_data,
        }

    # ===== Meta Tools =====

    async def discover_tools(self, pattern: str = "") -> dict[str, Any]:
        """Discover available tools.

        Args:
            pattern: Filter pattern (substring match on name/description).

        Returns:
            Dict with available tools and categories.
        """
        tools = []
        categories: dict[str, int] = {}

        for name, spec in TOOL_SPECS.items():
            if pattern and pattern.lower() not in name.lower():
                if pattern.lower() not in spec.description.lower():
                    continue

            tools.append({
                "name": name,
                "description": spec.description,
                "category": spec.category,
            })

            categories[spec.category] = categories.get(spec.category, 0) + 1

        return {
            "available_tools": tools,
            "total_tools": len(TOOL_SPECS),
            "filtered_count": len(tools),
            "categories": categories,
        }

    async def get_tool_spec(self, tool_name: str) -> dict[str, Any]:
        """Get specification for a tool.

        Args:
            tool_name: Name of the tool.

        Returns:
            Tool specification with schema and examples.
        """
        if tool_name not in TOOL_SPECS:
            return {
                "error": f"Unknown tool: {tool_name}",
                "available_tools": list(TOOL_SPECS.keys()),
            }

        spec = TOOL_SPECS[tool_name]
        return {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
            "examples": spec.examples,
            "category": spec.category,
        }

    async def execute_tool(
        self,
        tool_name: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a tool.

        Args:
            tool_name: Name of the tool.
            parameters: Tool parameters.

        Returns:
            Tool execution result.
        """
        if tool_name not in self._tool_handlers:
            return {
                "tool": tool_name,
                "status": "error",
                "error": f"Unknown tool: {tool_name}",
            }

        try:
            handler = self._tool_handlers[tool_name]
            result = await handler(**parameters)

            return {
                "tool": tool_name,
                "status": "success",
                "result": result,
            }
        except TypeError as e:
            logger.error(f"Tool {tool_name} parameter error: {e}")
            return {
                "tool": tool_name,
                "status": "error",
                "error": f"Invalid parameters: {e}",
            }
        except Exception as e:
            logger.error(f"Tool {tool_name} execution error: {e}")
            return {
                "tool": tool_name,
                "status": "error",
                "error": str(e),
            }

    # ===== Tool Handlers =====

    async def _promote_learning(
        self,
        source: str,
        learning_id: str | None = None,
        content: dict[str, Any] | None = None,
        promotion_type: str = "staged",
    ) -> dict[str, Any]:
        """Handle promote_learning tool."""
        result = await self.service.promote_learning(
            source=source,  # type: ignore
            learning_id=learning_id,
            content=content,
            promotion_type=promotion_type,  # type: ignore
        )
        return result.model_dump()

    async def _batch_promote(
        self,
        session_id: str,
        filter: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Handle batch_promote tool."""
        result = await self.service.batch_promote(
            session_id=session_id,
            filter_config=filter,
        )
        return result.model_dump()

    async def _get_staging_queue(
        self,
        status: str = "pending",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Handle get_staging_queue tool."""
        entries = await self.service.get_staging_queue(
            status=status,  # type: ignore
            limit=limit,
        )
        return [e.model_dump() for e in entries]

    async def _search_for_session(
        self,
        session_id: str,
        query: str,
        context: dict[str, Any] | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Handle search_for_session tool."""
        matches = await self.service.search_for_session(
            session_id=session_id,
            query=query,
            context=context,
            limit=limit,
        )
        return [m.model_dump() for m in matches]

    async def _prime_session(
        self,
        session_id: str,
        project_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Handle prime_session tool."""
        result = await self.service.prime_session(
            session_id=session_id,
            project_context=project_context,
        )
        return result.model_dump()

    async def _report_outcome(
        self,
        session_id: str,
        knowledge_id: str,
        outcome: str,
        notes: str = "",
    ) -> dict[str, Any]:
        """Handle report_outcome tool."""
        result = await self.service.report_outcome(
            session_id=session_id,
            knowledge_id=knowledge_id,
            outcome=outcome,  # type: ignore
            notes=notes,
        )
        return result.model_dump()

    async def _register_webhook(
        self,
        subscriber: str,
        events: list[str],
        endpoint: str,
    ) -> dict[str, Any]:
        """Handle register_webhook tool."""
        result = await self.service.register_webhook(
            subscriber=subscriber,
            events=events,
            endpoint=endpoint,
        )
        return result.model_dump()

    async def _unregister_webhook(
        self,
        webhook_id: str,
    ) -> dict[str, Any]:
        """Handle unregister_webhook tool."""
        success = await self.service.unregister_webhook(webhook_id)
        return {"webhook_id": webhook_id, "deleted": success}

    async def _list_webhooks(self) -> list[dict[str, Any]]:
        """Handle list_webhooks tool."""
        webhooks = await self.service.list_webhooks()
        return [w.model_dump() for w in webhooks]

    async def _request_session_data(
        self,
        session_id: str,
        data_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Handle request_session_data tool."""
        result = await self.service.request_session_data(
            session_id=session_id,
            data_types=data_types,
        )
        return result.model_dump()
