"""HTTP client for session-intelligence MCP server (port 4002).

Uses JSON-RPC over HTTP to call MCP tools on the session-intelligence server.
Follows the same 3-meta-tool pattern as KnowledgeStoreClient.
"""

from __future__ import annotations

import json
import logging
from typing import Any, cast
from uuid import uuid4

import httpx

logger = logging.getLogger(__name__)


class SessionIntelligenceClient:
    """Async HTTP client for session-intelligence server.

    Communicates with the session-intelligence MCP server using JSON-RPC
    to call tools like session_get_dashboard, session_search, etc.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:4002",
        timeout: float = 30.0,
    ) -> None:
        """Initialize client.

        Args:
            base_url: Base URL for session-intelligence server.
            timeout: Request timeout in seconds.
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Call an MCP tool via JSON-RPC using 3-meta-tool pattern.

        Args:
            tool_name: Name of the tool to call.
            arguments: Tool arguments.

        Returns:
            Tool result as dict.

        Raises:
            httpx.HTTPError: On HTTP errors.
            ValueError: On JSON-RPC errors.
        """
        client = await self._get_client()
        request_id = str(uuid4())[:8]

        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {
                "name": "execute_tool",
                "arguments": {
                    "tool_name": tool_name,
                    "parameters": arguments,
                },
            },
        }

        response = await client.post(
            f"{self.base_url}/mcp",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()

        result = response.json()

        if "error" in result:
            error = result["error"]
            raise ValueError(f"JSON-RPC error: {error.get('message', error)}")

        # Extract text content from MCP response
        content = result.get("result", {}).get("content", [])
        if content and len(content) > 0:
            text = content[0].get("text", "{}")
            try:
                parsed = json.loads(text)
                logger.debug(f"Parsed response: {parsed}")
                return cast(dict[str, Any], parsed)
            except json.JSONDecodeError as e:
                logger.error(
                    f"Failed to parse JSON response: {e}, text: {text[:200]}"
                )
                return {"raw": text, "error": "Failed to parse response"}

        logger.warning("Empty response content from session-intelligence")
        return {}

    async def health_check(self) -> bool:
        """Check if session-intelligence is healthy."""
        try:
            client = await self._get_client()
            response = await client.get(f"{self.base_url}/health")
            return response.status_code == 200
        except httpx.HTTPError as e:
            logger.warning(f"Session-intelligence health check failed: {e}")
            return False

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Get session data by ID via dashboard tool.

        Args:
            session_id: The session ID to look up.

        Returns:
            Session data if found, None otherwise.
        """
        try:
            result = await self._call_tool(
                "session_get_dashboard",
                {
                    "session_id": session_id,
                    "dashboard_type": "overview",
                    "export_format": "json",
                },
            )
            if result.get("error"):
                return None
            return result
        except (httpx.HTTPError, ValueError) as e:
            logger.error(f"Error fetching session {session_id}: {e}")
            return None

    async def get_session_learnings(
        self,
        session_id: str,
    ) -> list[dict[str, Any]]:
        """Get learnings for a session via search.

        Args:
            session_id: The session ID.

        Returns:
            List of learnings.
        """
        try:
            result = await self._call_tool(
                "session_search",
                {
                    "query": session_id,
                    "search_type": "fulltext",
                    "limit": 50,
                },
            )

            # Extract learnings from search results
            results = result.get("results", result.get("entries", []))
            if isinstance(results, list):
                return cast(list[dict[str, Any]], results)
            return []
        except (httpx.HTTPError, ValueError) as e:
            logger.error(f"Error fetching learnings for {session_id}: {e}")
            return []

    async def get_session_decisions(
        self,
        session_id: str,
    ) -> list[dict[str, Any]]:
        """Get decisions for a session via dashboard.

        Args:
            session_id: The session ID.

        Returns:
            List of decisions.
        """
        try:
            result = await self._call_tool(
                "session_get_dashboard",
                {
                    "session_id": session_id,
                    "dashboard_type": "decisions",
                    "export_format": "json",
                },
            )
            decisions = result.get("decisions", [])
            if isinstance(decisions, list):
                return cast(list[dict[str, Any]], decisions)
            return []
        except (httpx.HTTPError, ValueError) as e:
            logger.error(f"Error fetching decisions for {session_id}: {e}")
            return []

    async def get_session_notes(
        self,
        session_id: str,
    ) -> list[dict[str, Any]]:
        """Get notes/notebooks for a session.

        Args:
            session_id: The session ID.

        Returns:
            List of notes.
        """
        try:
            result = await self._call_tool(
                "session_query_notebooks",
                {"limit": 50},
            )
            notebooks = result.get("notebooks", result.get("results", []))
            if isinstance(notebooks, list):
                return cast(list[dict[str, Any]], notebooks)
            return []
        except (httpx.HTTPError, ValueError) as e:
            logger.error(f"Error fetching notes for {session_id}: {e}")
            return []

    async def get_session_data(
        self,
        session_id: str,
        data_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Get multiple data types for a session.

        Args:
            session_id: The session ID.
            data_types: List of data types to fetch. Defaults to all.

        Returns:
            Dict with requested data.
        """
        if data_types is None:
            data_types = ["learnings", "decisions", "notes"]

        result: dict[str, Any] = {"session_id": session_id}

        for data_type in data_types:
            if data_type == "learnings":
                result["learnings"] = await self.get_session_learnings(
                    session_id
                )
            elif data_type == "decisions":
                result["decisions"] = await self.get_session_decisions(
                    session_id
                )
            elif data_type == "notes":
                result["notes"] = await self.get_session_notes(session_id)

        return result

    async def get_learning(self, learning_id: str) -> dict[str, Any] | None:
        """Get a specific learning by ID via search.

        Args:
            learning_id: The learning ID.

        Returns:
            Learning data if found, None otherwise.
        """
        try:
            result = await self._call_tool(
                "session_search",
                {
                    "query": learning_id,
                    "search_type": "fulltext",
                    "limit": 1,
                },
            )
            results = result.get("results", result.get("entries", []))
            if isinstance(results, list) and results:
                return cast(dict[str, Any], results[0])
            return None
        except (httpx.HTTPError, ValueError) as e:
            logger.error(f"Error fetching learning {learning_id}: {e}")
            return None
