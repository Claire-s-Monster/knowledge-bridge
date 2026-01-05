"""FastAPI HTTP server for knowledge-bridge MCP server.

Exposes the lean MCP interface via HTTP endpoints:
- POST /mcp/discover_tools
- POST /mcp/get_tool_spec
- POST /mcp/execute_tool
- GET /health
- GET /api/statistics
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from knowledge_bridge.clients.knowledge_store import KnowledgeStoreClient
from knowledge_bridge.clients.session_intel import SessionIntelligenceClient
from knowledge_bridge.core.service import KnowledgeBridgeService
from knowledge_bridge.lean.interface import LeanMCPInterface
from knowledge_bridge.persistence.sqlite import SQLiteBackend
from knowledge_bridge.webhooks.emitter import WebhookEmitter

from .security import LocalhostOnlyMiddleware

logger = logging.getLogger(__name__)


# ===== Request/Response Models =====


class DiscoverToolsRequest(BaseModel):
    """Request for discover_tools."""

    pattern: str = ""


class GetToolSpecRequest(BaseModel):
    """Request for get_tool_spec."""

    tool_name: str


class ExecuteToolRequest(BaseModel):
    """Request for execute_tool."""

    tool_name: str
    parameters: dict[str, Any] = {}


# ===== Application Factory =====


def create_app(
    db_path: str | None = None,
    session_intel_url: str = "http://127.0.0.1:4002",
    uckn_url: str = "http://127.0.0.1:4004",
    localhost_only: bool = True,
) -> FastAPI:
    """Create FastAPI application.

    Args:
        db_path: SQLite database path. Defaults to ~/.claude/knowledge-bridge/knowledge_bridge.db.
        session_intel_url: Session-intelligence server URL.
        uckn_url: UCKN server URL.
        localhost_only: Whether to restrict to localhost.

    Returns:
        Configured FastAPI app.
    """
    # Application state holders
    state: dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        """Application lifespan manager."""
        # Startup
        logger.info("Starting knowledge-bridge server...")

        # Initialize database
        database = SQLiteBackend(db_path=db_path)
        await database.initialize()
        state["database"] = database

        # Initialize clients
        session_client = SessionIntelligenceClient(base_url=session_intel_url)
        knowledge_store_client = KnowledgeStoreClient(base_url=uckn_url)
        state["session_client"] = session_client
        state["knowledge_store_client"] = knowledge_store_client

        # Initialize webhook emitter
        webhook_emitter = WebhookEmitter(database=database)
        state["webhook_emitter"] = webhook_emitter

        # Initialize service
        service = KnowledgeBridgeService(
            database=database,
            session_client=session_client,
            knowledge_store_client=knowledge_store_client,
            webhook_emitter=webhook_emitter,
        )
        state["service"] = service

        # Initialize lean interface
        interface = LeanMCPInterface(service=service)
        state["interface"] = interface

        logger.info("knowledge-bridge server started")

        yield

        # Shutdown
        logger.info("Shutting down knowledge-bridge server...")
        await webhook_emitter.close()
        await session_client.close()
        await knowledge_store_client.close()
        await database.close()
        logger.info("knowledge-bridge server stopped")

    app = FastAPI(
        title="knowledge-bridge",
        description="Orchestration layer between session-intelligence and UCKN",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Store state reference
    app.state.kb_state = state

    # Add middleware
    if localhost_only:
        app.add_middleware(LocalhostOnlyMiddleware, allow_health_check=True)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:*", "http://127.0.0.1:*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ===== Health Endpoints =====

    @app.get("/health")
    async def health() -> dict[str, Any]:
        """Health check endpoint."""
        service = state.get("service")
        if service:
            return await service.get_health()
        return {"status": "starting"}

    @app.get("/api/statistics")
    async def statistics() -> dict[str, Any]:
        """Get server statistics."""
        database = state.get("database")
        if database:
            return await database.get_statistics()
        return {"error": "Database not initialized"}

    # ===== MCP Endpoints =====

    @app.post("/mcp/discover_tools")
    async def discover_tools(request: DiscoverToolsRequest) -> dict[str, Any]:
        """Discover available tools."""
        interface = state.get("interface")
        if not interface:
            raise HTTPException(status_code=503, detail="Server not ready")
        return await interface.discover_tools(request.pattern)

    @app.post("/mcp/get_tool_spec")
    async def get_tool_spec(request: GetToolSpecRequest) -> dict[str, Any]:
        """Get tool specification."""
        interface = state.get("interface")
        if not interface:
            raise HTTPException(status_code=503, detail="Server not ready")
        return await interface.get_tool_spec(request.tool_name)

    @app.post("/mcp/execute_tool")
    async def execute_tool(request: ExecuteToolRequest) -> dict[str, Any]:
        """Execute a tool."""
        interface = state.get("interface")
        if not interface:
            raise HTTPException(status_code=503, detail="Server not ready")
        return await interface.execute_tool(request.tool_name, request.parameters)

    # ===== Convenience REST Endpoints =====

    @app.get("/api/staging-queue")
    async def get_staging_queue(status: str = "pending", limit: int = 50) -> dict[str, Any]:
        """Get staging queue entries (REST convenience)."""
        interface = state.get("interface")
        if not interface:
            raise HTTPException(status_code=503, detail="Server not ready")
        result = await interface.execute_tool(
            "get_staging_queue",
            {"status": status, "limit": limit},
        )
        return result

    @app.get("/api/webhooks")
    async def list_webhooks() -> dict[str, Any]:
        """List webhooks (REST convenience)."""
        interface = state.get("interface")
        if not interface:
            raise HTTPException(status_code=503, detail="Server not ready")
        result = await interface.execute_tool("list_webhooks", {})
        return result

    @app.post("/api/search")
    async def search(
        session_id: str,
        query: str,
        limit: int = 5,
    ) -> dict[str, Any]:
        """Search knowledge (REST convenience)."""
        interface = state.get("interface")
        if not interface:
            raise HTTPException(status_code=503, detail="Server not ready")
        result = await interface.execute_tool(
            "search_for_session",
            {"session_id": session_id, "query": query, "limit": limit},
        )
        return result

    return app
