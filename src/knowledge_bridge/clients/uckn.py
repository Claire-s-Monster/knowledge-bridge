"""Mock UCKN client for knowledge-bridge.

This is a stub implementation that returns mock data until
UCKN (port 4004) is available.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


class MockUCKNClient:
    """Mock client for UCKN knowledge base.

    Returns mock data until UCKN server is implemented.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:4004",
        timeout: float = 30.0,
    ) -> None:
        """Initialize mock client.

        Args:
            base_url: Base URL for UCKN server (not used yet).
            timeout: Request timeout in seconds (not used yet).
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._mock_entries: dict[str, dict[str, Any]] = {}
        logger.warning("Using MockUCKNClient - UCKN server not available")

    async def close(self) -> None:
        """Close client (no-op for mock)."""
        pass

    async def health_check(self) -> bool:
        """Check if UCKN is healthy.

        Returns:
            False since this is a mock client.
        """
        logger.debug("Mock UCKN health check - always returns False")
        return False

    async def search(
        self,
        query: str,
        context: dict[str, Any] | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Search knowledge base (mock implementation).

        Args:
            query: Search query.
            context: Optional context (project type, framework, etc.).
            limit: Maximum results to return.

        Returns:
            List of mock knowledge matches.
        """
        logger.debug(f"Mock UCKN search: {query[:50]}...")

        # Return mock results
        return [
            {
                "knowledge_id": f"mock-{uuid4().hex[:8]}",
                "problem_pattern": query[:100],
                "solution": (
                    "Mock solution - UCKN not available. "
                    "This is a placeholder result. "
                    "Implement UCKN server for real knowledge retrieval."
                ),
                "relevance_score": 0.5,
                "success_rate": 0.0,
                "times_applied": 0,
                "tags": ["mock", "placeholder"],
            }
        ]

    async def promote(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Promote entry to UCKN (mock implementation).

        Args:
            entry: Entry to promote with problem_pattern/problem/pattern field.

        Returns:
            Mock promotion result.
        """
        # Add field normalization to match KnowledgeStoreClient behavior
        # Handle various field names: problem_pattern, problem, pattern
        problem = (
            entry.get("problem_pattern")
            or entry.get("problem")
            or entry.get("pattern")
            or ""
        )

        # Normalize entry before storing
        normalized_entry = {
            "problem_pattern": problem,
            "solution": entry.get("solution", ""),
            **{
                k: v
                for k, v in entry.items()
                if k not in ["problem", "pattern", "problem_pattern", "solution"]
            },
        }

        entry_id = f"uckn-mock-{uuid4().hex[:8]}"
        logger.debug(f"Mock UCKN promotion: {entry_id}")

        # Store normalized entry
        self._mock_entries[entry_id] = normalized_entry

        return {
            "id": entry_id,
            "status": "mock_promoted",
            "message": "Entry stored in mock UCKN - will be lost on restart",
        }

    async def update_entry(
        self,
        entry_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """Update UCKN entry (mock implementation).

        Args:
            entry_id: Entry ID to update.
            updates: Fields to update.

        Returns:
            Mock update result.
        """
        logger.debug(f"Mock UCKN update: {entry_id}")

        if entry_id in self._mock_entries:
            self._mock_entries[entry_id].update(updates)
            return {
                "id": entry_id,
                "status": "mock_updated",
                "updated_fields": list(updates.keys()),
            }
        else:
            return {
                "id": entry_id,
                "status": "mock_not_found",
                "error": "Entry not found in mock storage",
            }

    async def get_entry(self, entry_id: str) -> dict[str, Any] | None:
        """Get UCKN entry by ID (mock implementation).

        Args:
            entry_id: Entry ID.

        Returns:
            Entry data if found in mock storage, None otherwise.
        """
        return self._mock_entries.get(entry_id)

    def get_mock_entry_count(self) -> int:
        """Get count of entries in mock storage.

        Returns:
            Number of mock entries.
        """
        return len(self._mock_entries)
