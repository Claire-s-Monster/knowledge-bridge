"""Webhook emitter with HTTP POST delivery and retry logic."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

import httpx

from knowledge_bridge.persistence.base import BaseDatabaseBackend

from .events import EventType

logger = logging.getLogger(__name__)


class WebhookEmitter:
    """Emits events to registered webhook subscribers via HTTP POST.

    Features:
    - Retry logic with exponential backoff (3 attempts)
    - Failure tracking and webhook deactivation
    - Event logging for replay capability
    - Async delivery
    """

    MAX_RETRIES = 3
    MAX_FAILURE_COUNT = 10  # Deactivate webhook after this many failures
    RETRY_DELAYS = [1.0, 2.0, 4.0]  # Exponential backoff

    def __init__(
        self,
        database: BaseDatabaseBackend,
        timeout: float = 10.0,
    ) -> None:
        """Initialize webhook emitter.

        Args:
            database: Database backend for webhook queries and event logging.
            timeout: HTTP request timeout in seconds.
        """
        self.database = database
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

    async def emit(
        self,
        event_type: str | EventType,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Emit an event to all subscribed webhooks.

        Args:
            event_type: Type of event.
            payload: Event payload.

        Returns:
            Emission result with delivery statistics.
        """
        if isinstance(event_type, EventType):
            event_type = event_type.value

        # Build event envelope
        event = {
            "type": event_type,
            "data": payload,
            "timestamp": datetime.now().isoformat(),
        }

        # Save event to log
        event_id = await self.database.save_event({
            "event_type": event_type,
            "payload": payload,
            "delivered_to": [],
        })

        # Get subscribed webhooks
        webhooks = await self.database.query_webhooks(
            active_only=True,
            event_type=event_type,
        )

        if not webhooks:
            logger.debug(f"No webhooks subscribed to {event_type}")
            return {
                "event_id": event_id,
                "event_type": event_type,
                "subscribers": 0,
                "delivered": 0,
                "failed": 0,
            }

        # Deliver to each webhook
        delivered_to: list[str] = []
        failed: list[dict[str, Any]] = []

        for webhook in webhooks:
            success = await self._deliver_to_webhook(webhook, event)
            if success:
                delivered_to.append(webhook["id"])
            else:
                failed.append({
                    "webhook_id": webhook["id"],
                    "endpoint": webhook["endpoint"],
                })

        logger.info(
            f"Event {event_type}: delivered to {len(delivered_to)}/{len(webhooks)} webhooks"
        )

        return {
            "event_id": event_id,
            "event_type": event_type,
            "subscribers": len(webhooks),
            "delivered": len(delivered_to),
            "failed": len(failed),
            "failed_details": failed if failed else None,
        }

    async def _deliver_to_webhook(
        self,
        webhook: dict[str, Any],
        event: dict[str, Any],
    ) -> bool:
        """Deliver event to a single webhook with retry.

        Args:
            webhook: Webhook registration.
            event: Event to deliver.

        Returns:
            True if delivered successfully, False otherwise.
        """
        webhook_id = webhook["id"]
        endpoint = webhook["endpoint"]

        for attempt in range(self.MAX_RETRIES):
            try:
                client = await self._get_client()
                response = await client.post(
                    endpoint,
                    json=event,
                    headers={
                        "Content-Type": "application/json",
                        "X-Webhook-Event": event["type"],
                        "X-Webhook-Source": "knowledge-bridge",
                    },
                )

                if response.status_code < 400:
                    # Success - update last_called and reset failure_count
                    await self.database.update_webhook_status(
                        webhook_id,
                        failure_count=0,
                        last_called=datetime.now(),
                    )
                    return True
                else:
                    logger.warning(
                        f"Webhook {webhook_id} returned {response.status_code}: "
                        f"{response.text[:100]}"
                    )

            except httpx.HTTPError as e:
                logger.warning(
                    f"Webhook {webhook_id} delivery failed (attempt {attempt + 1}): {e}"
                )

            # Wait before retry (if not last attempt)
            if attempt < self.MAX_RETRIES - 1:
                await asyncio.sleep(self.RETRY_DELAYS[attempt])

        # All retries failed - increment failure count
        current_failures = webhook.get("failure_count", 0) + 1
        if current_failures >= self.MAX_FAILURE_COUNT:
            # Deactivate webhook
            logger.error(
                f"Webhook {webhook_id} deactivated after {current_failures} failures"
            )
            await self.database.update_webhook_status(
                webhook_id,
                active=False,
                failure_count=current_failures,
            )
        else:
            await self.database.update_webhook_status(
                webhook_id,
                failure_count=current_failures,
            )

        return False

    async def broadcast(
        self,
        event_type: str | EventType,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Broadcast event to all active webhooks regardless of subscription.

        Args:
            event_type: Type of event.
            payload: Event payload.

        Returns:
            Broadcast result.
        """
        if isinstance(event_type, EventType):
            event_type = event_type.value

        # Get all active webhooks
        webhooks = await self.database.query_webhooks(active_only=True)

        # Build event
        event = {
            "type": event_type,
            "data": payload,
            "timestamp": datetime.now().isoformat(),
            "broadcast": True,
        }

        # Deliver to all
        delivered = 0
        for webhook in webhooks:
            if await self._deliver_to_webhook(webhook, event):
                delivered += 1

        return {
            "event_type": event_type,
            "total_webhooks": len(webhooks),
            "delivered": delivered,
        }
