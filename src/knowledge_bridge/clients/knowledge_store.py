"""HTTP client for knowledge-store MCP server (port 4004).

Uses JSON-RPC over HTTP to call MCP tools on the knowledge-store server.
"""

from __future__ import annotations

import logging
from typing import Any, cast
from uuid import uuid4

import httpx

logger = logging.getLogger(__name__)


class KnowledgeStoreClient:
    """Async HTTP client for knowledge-store server.

    Communicates with the knowledge-store MCP server using JSON-RPC
    to call tools like search, add_entry, update_entry, get_entry.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:4004",
        timeout: float = 30.0,
    ) -> None:
        """Initialize client.

        Args:
            base_url: Base URL for knowledge-store server.
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
        """Call an MCP tool via JSON-RPC.

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
                "name": tool_name,
                "arguments": arguments,
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
            # The response is a Python repr string, need to eval it safely
            # Actually it's a dict-like string, let's parse it
            import ast

            try:
                return cast(dict[str, Any], ast.literal_eval(text))
            except (ValueError, SyntaxError):
                return {"raw": text}

        return {}

    async def health_check(self) -> bool:
        """Check if knowledge-store is healthy.

        Returns:
            True if healthy, False otherwise.
        """
        try:
            client = await self._get_client()
            response = await client.get(f"{self.base_url}/health")
            if response.status_code == 200:
                data = response.json()
                return bool(data.get("status") == "healthy")
            return False
        except httpx.HTTPError as e:
            logger.warning(f"Knowledge-store health check failed: {e}")
            return False

    async def search(
        self,
        query: str,
        context: dict[str, Any] | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Search knowledge base for matching entries.

        Args:
            query: Search query text.
            context: Optional context filters (project_type, framework, etc.).
            limit: Maximum results to return.

        Returns:
            List of knowledge matches with relevance scores.
        """
        try:
            arguments: dict[str, Any] = {
                "query": query,
                "limit": limit,
            }

            # Add context as filters if provided
            if context:
                arguments["filters"] = context

            result = await self._call_tool("search", arguments)

            # Transform results to match expected format
            entries = result.get("entries", [])
            matches = []
            for entry in entries:
                matches.append({
                    "knowledge_id": entry.get("id", ""),
                    "problem_pattern": entry.get("problem_pattern", ""),
                    "solution": entry.get("solution", ""),
                    "relevance_score": entry.get("distance", 0.5),
                    "success_rate": entry.get("metadata", {}).get("quality_score", 0.0),
                    "times_applied": entry.get("metadata", {}).get("times_applied", 0),
                    "tags": entry.get("metadata", {}).get("tags", []),
                })

            return matches

        except httpx.HTTPError as e:
            logger.error(f"Knowledge-store search failed: {e}")
            return []
        except ValueError as e:
            logger.error(f"Knowledge-store search error: {e}")
            return []

    async def promote(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Promote an entry to knowledge-store.

        Args:
            entry: Entry to promote with problem_pattern, solution, etc.

        Returns:
            Promotion result with entry ID and status.
        """
        try:
            # Map entry fields to add_entry parameters
            arguments: dict[str, Any] = {
                "problem_pattern": entry.get("problem_pattern", ""),
                "solution": entry.get("solution", ""),
            }

            # Optional fields
            if "code_example" in entry:
                arguments["code_example"] = entry["code_example"]
            if "tags" in entry:
                arguments["tags"] = entry["tags"]
            if "pattern_type" in entry:
                arguments["pattern_type"] = entry["pattern_type"]
            if "source_session" in entry:
                arguments["source_session"] = entry["source_session"]
            if "source_type" in entry:
                arguments["source_type"] = entry["source_type"]

            result = await self._call_tool("add_entry", arguments)

            return {
                "id": result.get("id", result.get("entry_id", "")),
                "status": "promoted",
                "message": "Entry added to knowledge-store",
            }

        except httpx.HTTPError as e:
            logger.error(f"Knowledge-store promotion failed: {e}")
            return {
                "id": "",
                "status": "error",
                "error": str(e),
            }
        except ValueError as e:
            logger.error(f"Knowledge-store promotion error: {e}")
            return {
                "id": "",
                "status": "error",
                "error": str(e),
            }

    async def update_entry(
        self,
        entry_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """Update a knowledge-store entry.

        Args:
            entry_id: Entry ID to update.
            updates: Fields to update.

        Returns:
            Update result.
        """
        try:
            result = await self._call_tool(
                "update_entry",
                {"entry_id": entry_id, "updates": updates},
            )

            return {
                "id": entry_id,
                "status": "updated",
                "updated_fields": list(updates.keys()),
                "result": result,
            }

        except httpx.HTTPError as e:
            logger.error(f"Knowledge-store update failed: {e}")
            return {
                "id": entry_id,
                "status": "error",
                "error": str(e),
            }
        except ValueError as e:
            logger.error(f"Knowledge-store update error: {e}")
            return {
                "id": entry_id,
                "status": "error",
                "error": str(e),
            }

    async def get_entry(self, entry_id: str) -> dict[str, Any] | None:
        """Get a knowledge-store entry by ID.

        Args:
            entry_id: Entry ID.

        Returns:
            Entry data if found, None otherwise.
        """
        try:
            result = await self._call_tool("get_entry", {"entry_id": entry_id})

            if result.get("error") or result.get("status") == "not_found":
                return None

            return result

        except httpx.HTTPError as e:
            logger.error(f"Knowledge-store get_entry failed: {e}")
            return None
        except ValueError as e:
            logger.error(f"Knowledge-store get_entry error: {e}")
            return None
