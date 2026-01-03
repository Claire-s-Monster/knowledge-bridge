"""Event type definitions for knowledge-bridge webhooks."""

from __future__ import annotations

from enum import Enum


class EventType(str, Enum):
    """Event types emitted by knowledge-bridge."""

    # Promotion events
    LEARNING_STAGED = "learning.staged"
    LEARNING_PROMOTED = "learning.promoted"
    LEARNING_REJECTED = "learning.rejected"

    # Retrieval events
    KNOWLEDGE_SEARCHED = "knowledge.searched"
    KNOWLEDGE_APPLIED = "knowledge.applied"

    # Feedback events
    OUTCOME_REPORTED = "outcome.reported"
    QUALITY_UPDATED = "quality.updated"

    # Curation events (for curator daemon)
    CURATION_REQUESTED = "curation.requested"
    CURATION_COMPLETED = "curation.completed"

    # Health events
    BRIDGE_HEALTH = "bridge.health"
    QUEUE_BACKLOG = "queue.backlog"


# Event descriptions for documentation
BRIDGE_EVENTS: dict[str, str] = {
    EventType.LEARNING_STAGED: "New learning added to staging queue",
    EventType.LEARNING_PROMOTED: "Learning promoted to UCKN",
    EventType.LEARNING_REJECTED: "Learning rejected from promotion",
    EventType.KNOWLEDGE_SEARCHED: "Session searched for knowledge",
    EventType.KNOWLEDGE_APPLIED: "Session received knowledge injection",
    EventType.OUTCOME_REPORTED: "Solution outcome reported",
    EventType.QUALITY_UPDATED: "Entry quality score changed",
    EventType.CURATION_REQUESTED: "Entry flagged for curator review",
    EventType.CURATION_COMPLETED: "Curator finished processing entry",
    EventType.BRIDGE_HEALTH: "Periodic health check",
    EventType.QUEUE_BACKLOG: "Staging queue exceeds threshold (>100 pending)",
}


def get_event_description(event_type: str | EventType) -> str:
    """Get description for an event type.

    Args:
        event_type: Event type string or enum.

    Returns:
        Description string.
    """
    if isinstance(event_type, EventType):
        event_type = event_type.value
    return BRIDGE_EVENTS.get(event_type, f"Unknown event: {event_type}")
