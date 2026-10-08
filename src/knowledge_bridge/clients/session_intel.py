"""HTTP client for session-intelligence MCP server (port 4002).

Uses JSON-RPC over HTTP to call MCP tools on the session-intelligence server.
Follows the same 3-meta-tool pattern as KnowledgeStoreClient.

session-intelligence rejects every non-``initialize`` POST that lacks an
``MCP-Session-Id`` header (400) and forgets session IDs when it restarts (404).
The client therefore initializes lazily, sends the header on every request,
and on a 404 initializes again once before retrying.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, cast
from uuid import uuid4

import httpx

logger = logging.getLogger(__name__)

SESSION_HEADER = "MCP-Session-Id"
MCP_PROTOCOL_VERSION = "2024-11-05"
CLIENT_INFO = {"name": "knowledge-bridge", "version": "0.1.0"}


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    """Return value if it is a list, else an empty list."""
    if isinstance(value, list):
        return cast(list[dict[str, Any]], value)
    return []


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
        self._session_id: str | None = None
        self._session_lock = asyncio.Lock()

    @property
    def _mcp_url(self) -> str:
        return f"{self.base_url}/mcp"

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self) -> None:
        """Close HTTP client and forget the MCP session."""
        if self._client:
            await self._client.aclose()
            self._client = None
        self._session_id = None

    @staticmethod
    def _headers(session_id: str | None = None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if session_id:
            headers[SESSION_HEADER] = session_id
        return headers

    async def _initialize(self) -> str:
        """Open an MCP session and return its ID.

        Raises:
            httpx.HTTPError: On HTTP errors.
            ValueError: If the server returns no session ID.
        """
        client = await self._get_client()
        response = await client.post(
            self._mcp_url,
            json={
                "jsonrpc": "2.0",
                "id": str(uuid4())[:8],
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": CLIENT_INFO,
                },
            },
            headers=self._headers(),
        )
        response.raise_for_status()

        session_id: str | None = response.headers.get(SESSION_HEADER)
        if not session_id:
            raise ValueError(
                f"session-intelligence returned no {SESSION_HEADER} header"
            )

        notified = await client.post(
            self._mcp_url,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers=self._headers(session_id),
        )
        notified.raise_for_status()

        logger.info(f"Opened session-intelligence MCP session {session_id}")
        return session_id

    async def _ensure_session(self, stale: str | None = None) -> str:
        """Return the current session ID, initializing if needed.

        Args:
            stale: A session ID the server rejected. If it is still the
                current one, a new session is opened. Concurrent callers that
                saw the same stale ID share one re-initialization.
        """
        async with self._session_lock:
            if self._session_id is None or self._session_id == stale:
                self._session_id = await self._initialize()
            return self._session_id

    async def _post_rpc(self, payload: dict[str, Any]) -> httpx.Response:
        """POST a JSON-RPC request inside the MCP session.

        Re-initializes and retries exactly once if the server no longer
        knows the session (404).
        """
        client = await self._get_client()
        session_id = await self._ensure_session()
        response = await client.post(
            self._mcp_url, json=payload, headers=self._headers(session_id)
        )

        if response.status_code == 404:
            logger.info(
                f"session-intelligence dropped session {session_id}; "
                "re-initializing"
            )
            session_id = await self._ensure_session(stale=session_id)
            response = await client.post(
                self._mcp_url, json=payload, headers=self._headers(session_id)
            )

        response.raise_for_status()
        return response

    async def _call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        """Call an MCP tool via JSON-RPC using 3-meta-tool pattern.

        Args:
            tool_name: Name of the tool to call.
            arguments: Tool arguments.

        Returns:
            The tool's ``result`` value from the execute_tool envelope
            (a dict or a list, depending on the tool).

        Raises:
            httpx.HTTPError: On HTTP errors.
            ValueError: On JSON-RPC errors, unparseable responses, or a
                non-success execute_tool envelope.
        """
        response = await self._post_rpc(
            {
                "jsonrpc": "2.0",
                "id": str(uuid4())[:8],
                "method": "tools/call",
                "params": {
                    "name": "execute_tool",
                    "arguments": {
                        "tool_name": tool_name,
                        "parameters": arguments,
                    },
                },
            }
        )

        result = response.json()

        if "error" in result:
            error = result["error"]
            raise ValueError(f"JSON-RPC error: {error.get('message', error)}")

        # Extract text content from MCP response
        content = result.get("result", {}).get("content", [])
        if not content:
            raise ValueError(f"Empty response content for {tool_name}")

        text = content[0].get("text", "")
        try:
            envelope = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Failed to parse {tool_name} response: {e}, text: {text[:200]}"
            ) from e

        # execute_tool wraps results as {"tool", "status", "result"}. Unknown
        # tools come back as {"error", "available_tools"} with no status.
        if not isinstance(envelope, dict) or envelope.get("status") != "success":
            error = (
                envelope.get("error", envelope)
                if isinstance(envelope, dict)
                else envelope
            )
            raise ValueError(f"{tool_name} failed: {error}")

        logger.debug(f"Parsed {tool_name} result: {envelope.get('result')}")
        return envelope.get("result")

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
            The overview dashboard if found, None otherwise.
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
            if isinstance(result, dict):
                return cast(dict[str, Any], result)
            return None
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
            List of search hits.
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
            if isinstance(result, dict):
                return _list_of_dicts(result.get("results"))
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
            if isinstance(result, dict):
                metrics = result.get("metrics")
                if isinstance(metrics, dict):
                    return _list_of_dicts(metrics.get("recent_decisions"))
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
            # session_query_notebooks returns a bare list.
            result = await self._call_tool(
                "session_query_notebooks",
                {"limit": 50},
            )
            return _list_of_dicts(result)
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
            results = (
                _list_of_dicts(result.get("results"))
                if isinstance(result, dict)
                else []
            )
            return results[0] if results else None
        except (httpx.HTTPError, ValueError) as e:
            logger.error(f"Error fetching learning {learning_id}: {e}")
            return None
