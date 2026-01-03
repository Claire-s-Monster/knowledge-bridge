"""HTTP client for session-intelligence MCP server (port 4002)."""

from __future__ import annotations

import logging
from typing import Any, cast

import httpx

logger = logging.getLogger(__name__)


class SessionIntelligenceClient:
    """Async HTTP client for session-intelligence server."""

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
        """Get session data by ID.

        Args:
            session_id: The session ID to look up.

        Returns:
            Session data if found, None otherwise.
        """
        try:
            client = await self._get_client()
            response = await client.get(
                f"{self.base_url}/api/sessions/{session_id}"
            )
            if response.status_code == 200:
                return cast(dict[str, Any], response.json())
            elif response.status_code == 404:
                return None
            else:
                logger.warning(
                    f"Failed to get session {session_id}: {response.status_code}"
                )
                return None
        except httpx.HTTPError as e:
            logger.error(f"Error fetching session {session_id}: {e}")
            return None

    async def get_session_learnings(
        self,
        session_id: str,
    ) -> list[dict[str, Any]]:
        """Get learnings for a session.

        Args:
            session_id: The session ID.

        Returns:
            List of learnings.
        """
        try:
            client = await self._get_client()
            response = await client.get(
                f"{self.base_url}/api/sessions/{session_id}/learnings"
            )
            if response.status_code == 200:
                data = cast(dict[str, Any], response.json())
                return cast(list[dict[str, Any]], data.get("learnings", []))
            else:
                logger.warning(
                    f"Failed to get learnings for {session_id}: {response.status_code}"
                )
                return []
        except httpx.HTTPError as e:
            logger.error(f"Error fetching learnings for {session_id}: {e}")
            return []

    async def get_session_decisions(
        self,
        session_id: str,
    ) -> list[dict[str, Any]]:
        """Get decisions for a session.

        Args:
            session_id: The session ID.

        Returns:
            List of decisions.
        """
        try:
            client = await self._get_client()
            response = await client.get(
                f"{self.base_url}/api/sessions/{session_id}/decisions"
            )
            if response.status_code == 200:
                data = cast(dict[str, Any], response.json())
                return cast(list[dict[str, Any]], data.get("decisions", []))
            else:
                logger.warning(
                    f"Failed to get decisions for {session_id}: {response.status_code}"
                )
                return []
        except httpx.HTTPError as e:
            logger.error(f"Error fetching decisions for {session_id}: {e}")
            return []

    async def get_session_notes(
        self,
        session_id: str,
    ) -> list[dict[str, Any]]:
        """Get notes for a session.

        Args:
            session_id: The session ID.

        Returns:
            List of notes.
        """
        try:
            client = await self._get_client()
            response = await client.get(
                f"{self.base_url}/api/sessions/{session_id}/notes"
            )
            if response.status_code == 200:
                data = cast(dict[str, Any], response.json())
                return cast(list[dict[str, Any]], data.get("notes", []))
            else:
                logger.warning(
                    f"Failed to get notes for {session_id}: {response.status_code}"
                )
                return []
        except httpx.HTTPError as e:
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
                result["learnings"] = await self.get_session_learnings(session_id)
            elif data_type == "decisions":
                result["decisions"] = await self.get_session_decisions(session_id)
            elif data_type == "notes":
                result["notes"] = await self.get_session_notes(session_id)

        return result

    async def get_learning(self, learning_id: str) -> dict[str, Any] | None:
        """Get a specific learning by ID.

        Args:
            learning_id: The learning ID.

        Returns:
            Learning data if found, None otherwise.
        """
        try:
            client = await self._get_client()
            response = await client.get(
                f"{self.base_url}/api/learnings/{learning_id}"
            )
            if response.status_code == 200:
                return cast(dict[str, Any], response.json())
            elif response.status_code == 404:
                return None
            else:
                logger.warning(
                    f"Failed to get learning {learning_id}: {response.status_code}"
                )
                return None
        except httpx.HTTPError as e:
            logger.error(f"Error fetching learning {learning_id}: {e}")
            return None
