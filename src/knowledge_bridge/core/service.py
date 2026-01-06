"""Domain service for knowledge-bridge.

Orchestrates promotion, retrieval, feedback, and webhook operations.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from knowledge_bridge.clients.knowledge_store import KnowledgeStoreClient
from knowledge_bridge.clients.session_intel import SessionIntelligenceClient
from knowledge_bridge.persistence.base import BaseDatabaseBackend
from knowledge_bridge.webhooks.emitter import WebhookEmitter
from knowledge_bridge.webhooks.events import EventType

from .models import (
    BatchPromotionResult,
    FeedbackReport,
    KnowledgeMatch,
    PrimingResult,
    PromotionResult,
    SessionData,
    StagedEntry,
    WebhookRegistration,
)

logger = logging.getLogger(__name__)


class KnowledgeBridgeService:
    """Domain service for knowledge-bridge operations."""

    # Confidence threshold for immediate promotion (vs staging)
    IMMEDIATE_PROMOTION_THRESHOLD = 0.8

    def __init__(
        self,
        database: BaseDatabaseBackend,
        session_client: SessionIntelligenceClient,
        knowledge_store_client: KnowledgeStoreClient,
        webhook_emitter: WebhookEmitter,
    ) -> None:
        """Initialize service with dependencies.

        Args:
            database: Database backend.
            session_client: Session-intelligence HTTP client.
            knowledge_store_client: Knowledge-store HTTP client.
            webhook_emitter: Webhook emitter for events.
        """
        self.database = database
        self.session_client = session_client
        self.knowledge_store_client = knowledge_store_client
        self.webhook_emitter = webhook_emitter

    # ===== Promotion Flow =====

    async def promote_learning(
        self,
        source: Literal["session-intelligence", "direct"],
        learning_id: str | None = None,
        content: dict[str, Any] | None = None,
        promotion_type: Literal["immediate", "staged"] = "staged",
    ) -> PromotionResult:
        """Promote a learning to UCKN or staging queue.

        Args:
            source: Where the learning comes from.
            learning_id: If from session-intelligence, the learning ID.
            content: If direct, the learning content.
            promotion_type: Whether to promote immediately or stage for review.

        Returns:
            PromotionResult with status and entry ID.
        """
        # Get the learning content
        if source == "session-intelligence":
            if not learning_id:
                return PromotionResult(
                    success=False,
                    entry_id="",
                    status="rejected",
                    reason="learning_id required for session-intelligence source",
                )

            learning = await self.session_client.get_learning(learning_id)
            if not learning:
                return PromotionResult(
                    success=False,
                    entry_id="",
                    status="rejected",
                    reason=f"Learning {learning_id} not found in session-intelligence",
                )
            content = learning
        elif source == "direct":
            if not content:
                return PromotionResult(
                    success=False,
                    entry_id="",
                    status="rejected",
                    reason="content required for direct source",
                )
        else:
            return PromotionResult(
                success=False,
                entry_id="",
                status="rejected",
                reason=f"Unknown source: {source}",
            )

        # Generate entry ID
        entry_id = f"kb-{uuid4().hex[:12]}"

        # Decide on immediate vs staged
        if promotion_type == "immediate":
            # Promote directly to UCKN
            result = await self.knowledge_store_client.promote(content)
            uckn_id = result.get("id", entry_id)

            # Save to staging as promoted
            await self.database.save_staged_entry({
                "id": entry_id,
                "source": source,
                "source_id": learning_id,
                "content": content,
                "status": "promoted",
                "promoted_to": uckn_id,
            })

            # Emit event
            await self.webhook_emitter.emit(
                EventType.LEARNING_PROMOTED,
                {
                    "entry_id": entry_id,
                    "uckn_id": uckn_id,
                    "source": source,
                    "content": content,
                },
            )

            return PromotionResult(
                success=True,
                entry_id=uckn_id,
                status="promoted",
                reason="Immediately promoted to UCKN",
            )
        else:
            # Stage for review
            await self.database.save_staged_entry({
                "id": entry_id,
                "source": source,
                "source_id": learning_id,
                "content": content,
                "status": "pending",
            })

            # Emit event
            await self.webhook_emitter.emit(
                EventType.LEARNING_STAGED,
                {
                    "entry_id": entry_id,
                    "source": source,
                    "content": content,
                },
            )

            return PromotionResult(
                success=True,
                entry_id=entry_id,
                status="staged",
                reason="Added to staging queue for curator review",
            )

    async def batch_promote(
        self,
        session_id: str,
        filter_config: dict[str, Any] | None = None,
    ) -> BatchPromotionResult:
        """Batch promote learnings from a session.

        Args:
            session_id: Session ID to fetch learnings from.
            filter_config: Optional filter (min_confidence, categories, etc.).

        Returns:
            BatchPromotionResult with statistics.
        """
        filter_config = filter_config or {}
        min_confidence = filter_config.get("min_confidence", 0.5)
        categories = filter_config.get("categories", [])

        # Get all learnings from session
        learnings = await self.session_client.get_session_learnings(session_id)

        if not learnings:
            return BatchPromotionResult(
                total_learnings=0,
                promoted_immediately=0,
                staged_for_review=0,
                rejected=0,
                details=[],
            )

        results: list[PromotionResult] = []
        promoted = 0
        staged = 0
        rejected = 0

        for learning in learnings:
            # Apply filters
            confidence = learning.get("confidence", 0.5)
            category = learning.get("category", "")

            if confidence < min_confidence:
                results.append(PromotionResult(
                    success=False,
                    entry_id="",
                    status="rejected",
                    reason=f"Confidence {confidence} below threshold {min_confidence}",
                ))
                rejected += 1
                continue

            if categories and category not in categories:
                results.append(PromotionResult(
                    success=False,
                    entry_id="",
                    status="rejected",
                    reason=f"Category {category} not in filter {categories}",
                ))
                rejected += 1
                continue

            # Determine promotion type
            promotion_type: Literal["immediate", "staged"] = (
                "immediate" if confidence >= self.IMMEDIATE_PROMOTION_THRESHOLD else "staged"
            )

            result = await self.promote_learning(
                source="session-intelligence",
                learning_id=learning.get("id"),
                promotion_type=promotion_type,
            )
            results.append(result)

            if result.status == "promoted":
                promoted += 1
            elif result.status == "staged":
                staged += 1
            else:
                rejected += 1

        return BatchPromotionResult(
            total_learnings=len(learnings),
            promoted_immediately=promoted,
            staged_for_review=staged,
            rejected=rejected,
            details=results,
        )

    async def get_staging_queue(
        self,
        status: Literal["pending", "reviewing", "all"] = "pending",
        limit: int = 50,
    ) -> list[StagedEntry]:
        """Get entries from staging queue.

        Args:
            status: Filter by status.
            limit: Maximum entries to return.

        Returns:
            List of staged entries.
        """
        status_filter = None if status == "all" else status
        entries = await self.database.query_staging_queue(
            status=status_filter,
            limit=limit,
        )

        return [
            StagedEntry(
                id=entry["id"],
                source=entry["source"],
                source_id=entry.get("source_id"),
                content=entry.get("content", {}),
                status=entry.get("status", "pending"),
                created_at=entry.get("created_at", datetime.now()),
                curator_notes=entry.get("curator_notes"),
                promoted_to=entry.get("promoted_to"),
            )
            for entry in entries
        ]

    async def get_staged_entry(self, entry_id: str) -> StagedEntry | None:
        """Get a single staged entry by ID.

        Args:
            entry_id: The entry ID.

        Returns:
            StagedEntry if found, None otherwise.
        """
        entry = await self.database.get_staged_entry(entry_id)
        if not entry:
            return None

        return StagedEntry(
            id=entry["id"],
            source=entry["source"],
            source_id=entry.get("source_id"),
            content=entry.get("content", {}),
            status=entry.get("status", "pending"),
            created_at=entry.get("created_at", datetime.now()),
            curator_notes=entry.get("curator_notes"),
            promoted_to=entry.get("promoted_to"),
        )

    # ===== Retrieval Flow =====

    async def search_for_session(
        self,
        session_id: str,
        query: str,
        context: dict[str, Any] | None = None,
        limit: int = 5,
    ) -> list[KnowledgeMatch]:
        """Search knowledge base for a session.

        Args:
            session_id: Session making the search.
            query: Search query.
            context: Optional context (project type, framework, etc.).
            limit: Maximum results.

        Returns:
            List of knowledge matches.
        """
        context = context or {}

        # Search UCKN
        results = await self.knowledge_store_client.search(query, context, limit)

        # Log the search
        await self.database.save_search({
            "session_id": session_id,
            "query": query,
            "context": context,
            "results_count": len(results),
            "top_result_id": results[0]["knowledge_id"] if results else None,
        })

        # Emit event
        await self.webhook_emitter.emit(
            EventType.KNOWLEDGE_SEARCHED,
            {
                "session_id": session_id,
                "query": query[:100],
                "results_count": len(results),
            },
        )

        return [
            KnowledgeMatch(
                knowledge_id=r["knowledge_id"],
                problem_pattern=r.get("problem_pattern", ""),
                solution=r.get("solution", ""),
                relevance_score=r.get("relevance_score", 0.0),
                success_rate=r.get("success_rate", 0.0),
                times_applied=r.get("times_applied", 0),
                tags=r.get("tags", []),
            )
            for r in results
        ]

    async def prime_session(
        self,
        session_id: str,
        project_context: dict[str, Any],
    ) -> PrimingResult:
        """Prime a session with relevant knowledge.

        Args:
            session_id: Session to prime.
            project_context: Project information (type, tech stack, etc.).

        Returns:
            PrimingResult with loaded patterns.
        """
        project_type = project_context.get("project_type", "unknown")
        tech_stack = project_context.get("tech_stack", [])

        # Build search query from context
        query = f"{project_type} {' '.join(tech_stack)} common patterns"

        # Search for relevant patterns
        matches = await self.search_for_session(
            session_id=session_id,
            query=query,
            context=project_context,
            limit=10,
        )

        # Emit priming event
        await self.webhook_emitter.emit(
            EventType.KNOWLEDGE_APPLIED,
            {
                "session_id": session_id,
                "project_type": project_type,
                "patterns_loaded": len(matches),
            },
        )

        return PrimingResult(
            session_id=session_id,
            patterns_loaded=len(matches),
            top_patterns=matches[:5],  # Return top 5
            project_type_detected=project_type,
        )

    # ===== Feedback Flow =====

    async def report_outcome(
        self,
        session_id: str,
        knowledge_id: str,
        outcome: Literal["success", "failure", "partial"],
        notes: str = "",
    ) -> FeedbackReport:
        """Report outcome of applying knowledge.

        Args:
            session_id: Session reporting.
            knowledge_id: UCKN entry that was applied.
            outcome: Result of applying the knowledge.
            notes: Optional notes.

        Returns:
            FeedbackReport.
        """
        feedback_id = f"fb-{uuid4().hex[:12]}"

        # Save feedback
        await self.database.save_feedback({
            "id": feedback_id,
            "session_id": session_id,
            "knowledge_id": knowledge_id,
            "outcome": outcome,
            "notes": notes,
        })

        # Emit event
        await self.webhook_emitter.emit(
            EventType.OUTCOME_REPORTED,
            {
                "feedback_id": feedback_id,
                "session_id": session_id,
                "knowledge_id": knowledge_id,
                "outcome": outcome,
            },
        )

        return FeedbackReport(
            id=feedback_id,
            session_id=session_id,
            knowledge_id=knowledge_id,
            outcome=outcome,
            notes=notes,
        )

    # ===== Webhook Management =====

    async def register_webhook(
        self,
        subscriber: str,
        events: list[str],
        endpoint: str,
    ) -> WebhookRegistration:
        """Register a webhook subscription.

        Args:
            subscriber: Subscriber name (e.g., "curator", "dashboard").
            events: Event types to subscribe to.
            endpoint: HTTP endpoint for delivery.

        Returns:
            WebhookRegistration.
        """
        webhook_id = f"wh-{uuid4().hex[:12]}"

        await self.database.save_webhook({
            "id": webhook_id,
            "subscriber": subscriber,
            "events": events,
            "endpoint": endpoint,
        })

        return WebhookRegistration(
            id=webhook_id,
            subscriber=subscriber,
            events=events,
            endpoint=endpoint,
        )

    async def unregister_webhook(self, webhook_id: str) -> bool:
        """Unregister a webhook subscription.

        Args:
            webhook_id: Webhook ID to delete.

        Returns:
            True if deleted, False if not found.
        """
        return await self.database.delete_webhook(webhook_id)

    async def list_webhooks(self) -> list[WebhookRegistration]:
        """List all webhook subscriptions.

        Returns:
            List of webhook registrations.
        """
        webhooks = await self.database.query_webhooks(active_only=False)

        return [
            WebhookRegistration(
                id=w["id"],
                subscriber=w["subscriber"],
                events=w.get("events", []),
                endpoint=w["endpoint"],
                active=w.get("active", True),
                failure_count=w.get("failure_count", 0),
                created_at=w.get("created_at", datetime.now()),
                last_called=w.get("last_called"),
            )
            for w in webhooks
        ]

    # ===== Inter-Server Communication =====

    async def request_session_data(
        self,
        session_id: str,
        data_types: list[str] | None = None,
    ) -> SessionData:
        """Request data from session-intelligence.

        Args:
            session_id: Session ID to fetch.
            data_types: Types of data to request.

        Returns:
            SessionData with requested information.
        """
        data_types = data_types or ["learnings", "decisions", "notes"]
        data = await self.session_client.get_session_data(session_id, data_types)

        return SessionData(
            session_id=session_id,
            learnings=data.get("learnings", []),
            decisions=data.get("decisions", []),
            notes=data.get("notes", []),
        )

    # ===== Health & Statistics =====

    async def get_health(self) -> dict[str, Any]:
        """Get service health status.

        Returns:
            Health status dict.
        """
        session_health = await self.session_client.health_check()
        knowledge_store_health = await self.knowledge_store_client.health_check()
        db_stats = await self.database.get_statistics()

        return {
            "status": "healthy" if self.database.is_connected else "degraded",
            "database": {
                "connected": self.database.is_connected,
                **db_stats,
            },
            "session_intelligence": {
                "healthy": session_health,
                "url": self.session_client.base_url,
            },
            "knowledge_store": {
                "healthy": knowledge_store_health,
                "url": self.knowledge_store_client.base_url,
            },
        }
