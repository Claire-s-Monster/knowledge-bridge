"""Core domain models for knowledge-bridge.

Pydantic models for staging queue, webhooks, knowledge matches,
promotion results, and feedback tracking.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class StagedEntry(BaseModel):
    """Learning entry in the staging queue awaiting promotion."""

    id: str
    source: Literal["session-intelligence", "direct"]
    source_id: str | None = None
    content: dict[str, Any]
    status: Literal["pending", "reviewing", "promoted", "rejected"] = "pending"
    created_at: datetime = Field(default_factory=datetime.now)
    curator_notes: str | None = None
    promoted_to: str | None = None  # UCKN entry ID if promoted


class WebhookRegistration(BaseModel):
    """Webhook subscription for event notifications."""

    id: str
    subscriber: str  # e.g., "curator", "dashboard"
    events: list[str]  # e.g., ["learning.staged", "outcome.reported"]
    endpoint: str  # HTTP endpoint to POST to
    active: bool = True
    failure_count: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    last_called: datetime | None = None


class KnowledgeMatch(BaseModel):
    """Search result from UCKN knowledge base."""

    knowledge_id: str
    problem_pattern: str
    solution: str
    relevance_score: float
    success_rate: float
    times_applied: int
    tags: list[str] = Field(default_factory=list)


class PromotionResult(BaseModel):
    """Result of promoting a single learning."""

    success: bool
    entry_id: str  # staging_queue ID or UCKN entry ID
    status: Literal["promoted", "staged", "rejected"]
    reason: str | None = None


class BatchPromotionResult(BaseModel):
    """Result of batch promoting learnings from a session."""

    total_learnings: int
    promoted_immediately: int
    staged_for_review: int
    rejected: int
    details: list[PromotionResult] = Field(default_factory=list)


class PrimingResult(BaseModel):
    """Result of priming a session with relevant knowledge."""

    session_id: str
    patterns_loaded: int
    top_patterns: list[KnowledgeMatch] = Field(default_factory=list)
    project_type_detected: str | None = None


class FeedbackReport(BaseModel):
    """Feedback on solution effectiveness."""

    id: str
    session_id: str
    knowledge_id: str  # UCKN entry ID
    outcome: Literal["success", "failure", "partial"]
    notes: str = ""
    reported_at: datetime = Field(default_factory=datetime.now)


class SessionData(BaseModel):
    """Data retrieved from session-intelligence."""

    session_id: str
    learnings: list[dict[str, Any]] = Field(default_factory=list)
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    notes: list[dict[str, Any]] = Field(default_factory=list)


class EventLogEntry(BaseModel):
    """Log entry for emitted events."""

    id: int | None = None
    event_type: str
    payload: dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.now)
    delivered_to: list[str] = Field(default_factory=list)  # Webhook IDs


class SearchLogEntry(BaseModel):
    """Log entry for knowledge searches."""

    id: int | None = None
    session_id: str
    query: str
    context: dict[str, Any] = Field(default_factory=dict)
    results_count: int = 0
    top_result_id: str | None = None
    searched_at: datetime = Field(default_factory=datetime.now)
