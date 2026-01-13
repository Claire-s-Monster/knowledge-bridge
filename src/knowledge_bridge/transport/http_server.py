"""FastAPI HTTP server for knowledge-bridge MCP server.

Exposes the lean MCP interface via HTTP endpoints:
- POST /mcp - JSON-RPC 2.0 MCP requests (for Claude Code)
- POST /mcp/discover_tools - REST endpoint
- POST /mcp/get_tool_spec - REST endpoint
- POST /mcp/execute_tool - REST endpoint
- GET /health
- GET /api/statistics
"""

from __future__ import annotations

import dataclasses
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any


class DatetimeJSONEncoder(json.JSONEncoder):
    """JSON encoder that handles datetime and dataclass objects."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return dataclasses.asdict(obj)
        if hasattr(obj, "model_dump"):  # Pydantic v2
            return obj.model_dump()
        if hasattr(obj, "dict"):  # Pydantic v1
            return obj.dict()
        return super().default(obj)

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from knowledge_bridge.clients.knowledge_store import KnowledgeStoreClient
from knowledge_bridge.clients.session_intel import SessionIntelligenceClient
from knowledge_bridge.core.service import KnowledgeBridgeService
from knowledge_bridge.lean.interface import LeanMCPInterface
from knowledge_bridge.persistence.sqlite import SQLiteBackend
from knowledge_bridge.webhooks.emitter import WebhookEmitter

from .security import LocalhostOnlyMiddleware

logger = logging.getLogger(__name__)

# MCP Protocol version
MCP_PROTOCOL_VERSION = "2024-11-05"

# Simple in-memory MCP session storage (for lightweight session tracking)
_mcp_sessions: dict[str, dict[str, Any]] = {}


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


class CurationDecisionRequest(BaseModel):
    """Request from curator daemon with curation decision."""

    entry_id: str
    decision: str  # "promote" | "reject" | "merge" | "flag_human"
    reason: str
    confidence: float = 0.8
    merged_content: dict[str, Any] | None = None
    similar_entries: list[str] = []


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
        expose_headers=["MCP-Session-Id", "MCP-Protocol-Version"],
    )

    # ===== JSON-RPC MCP Endpoint (for Claude Code) =====

    @app.post("/mcp")
    async def handle_mcp_jsonrpc(
        request: Request,
        mcp_session_id: str | None = Header(None, alias="MCP-Session-Id"),
    ) -> JSONResponse:
        """Handle MCP JSON-RPC 2.0 requests from Claude Code."""
        interface = state.get("interface")
        if not interface:
            return JSONResponse(
                status_code=503,
                content={
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32603, "message": "Server not ready"},
                },
            )

        try:
            body = await request.json()
        except json.JSONDecodeError:
            return JSONResponse(
                status_code=400,
                content={
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error"},
                },
            )

        method = body.get("method")
        params = body.get("params", {})
        req_id = body.get("id")

        # Handle initialize - create MCP session
        if method == "initialize":
            new_session_id = str(uuid.uuid4())
            _mcp_sessions[new_session_id] = {
                "created": True,
                "client_info": params.get("clientInfo"),
            }
            response = JSONResponse(
                content={
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "capabilities": {
                            "tools": {"listChanged": True},
                        },
                        "serverInfo": {"name": "knowledge-bridge", "version": "0.1.0"},
                    },
                }
            )
            response.headers["MCP-Session-Id"] = new_session_id
            response.headers["MCP-Protocol-Version"] = MCP_PROTOCOL_VERSION
            return response

        # For other methods, validate session (optional - be lenient)
        if mcp_session_id and mcp_session_id not in _mcp_sessions:
            # Create session on-the-fly for lenient handling
            _mcp_sessions[mcp_session_id] = {"created": True}

        try:
            result = await _handle_mcp_method(method, params, interface, req_id)
            return JSONResponse(content=result)
        except Exception as e:
            logger.exception(f"Error handling MCP method {method}")
            return JSONResponse(
                status_code=500,
                content={
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32603, "message": str(e)},
                },
            )

    async def _handle_mcp_method(
        method: str,
        params: dict[str, Any],
        interface: LeanMCPInterface,
        req_id: Any,
    ) -> dict[str, Any]:
        """Handle individual MCP methods."""
        # tools/list - return the 3 meta-tools
        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [
                        {
                            "name": "discover_tools",
                            "description": (
                                "Discover knowledge-bridge tools for learning promotion, "
                                "knowledge retrieval, outcome feedback, and webhook management (11 tools). "
                                "TRIGGERS: 'promote learning', 'search knowledge', 'staging queue', "
                                "'prime session', 'report outcome', 'webhooks'. "
                                "USE WHEN: starting session, finding promotion/retrieval tools, "
                                "exploring knowledge bridge capabilities"
                            ),
                            "inputSchema": {
                                "type": "object",
                                "properties": {"pattern": {"type": "string", "default": ""}},
                            },
                        },
                        {
                            "name": "get_tool_spec",
                            "description": (
                                "Get full parameter schema for knowledge-bridge tools including "
                                "promotion workflows, search contexts, and webhook configurations. "
                                "USE WHEN: need exact parameters for promote_learning, "
                                "search_for_session, register_webhook, or other knowledge tools"
                            ),
                            "inputSchema": {
                                "type": "object",
                                "properties": {"tool_name": {"type": "string"}},
                                "required": ["tool_name"],
                            },
                        },
                        {
                            "name": "execute_tool",
                            "description": (
                                "Execute knowledge-bridge operations: promote learnings to UCKN, "
                                "search knowledge base, prime sessions with context, report outcomes, "
                                "manage webhooks. "
                                "USE WHEN: promoting session learnings, searching for solutions, "
                                "reporting knowledge application results, setting up event subscriptions"
                            ),
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "tool_name": {"type": "string"},
                                    "parameters": {"type": "object"},
                                },
                                "required": ["tool_name", "parameters"],
                            },
                        },
                    ]
                },
            }

        # tools/call - execute a tool
        if method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})

            if tool_name == "discover_tools":
                pattern = arguments.get("pattern", "")
                tool_result = await interface.discover_tools(pattern)
            elif tool_name == "get_tool_spec":
                target = arguments.get("tool_name", "")
                tool_result = await interface.get_tool_spec(target)
            elif tool_name == "execute_tool":
                target = arguments.get("tool_name", "")
                tool_params = arguments.get("parameters", {})
                tool_result = await interface.execute_tool(target, tool_params)
            else:
                tool_result = {"error": f"Unknown tool: {tool_name}"}

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {"type": "text", "text": json.dumps(tool_result, cls=DatetimeJSONEncoder)}
                    ]
                },
            }

        # notifications/initialized - acknowledge
        if method == "notifications/initialized":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}

        # resources/list, prompts/list - empty for this server
        if method in ("resources/list", "resources/templates/list"):
            return {"jsonrpc": "2.0", "id": req_id, "result": {"resources": []}}

        if method == "prompts/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"prompts": []}}

        # Unknown method
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

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
        """Discover knowledge-bridge tools (11 tools).

        Categories: promotion (4), retrieval (2), feedback (1), webhooks (3), inter_server (1).
        USE WHEN: starting session, finding promotion/retrieval tools, exploring capabilities.
        """
        interface = state.get("interface")
        if not interface:
            raise HTTPException(status_code=503, detail="Server not ready")
        return await interface.discover_tools(request.pattern)

    @app.post("/mcp/get_tool_spec")
    async def get_tool_spec(request: GetToolSpecRequest) -> dict[str, Any]:
        """Get full parameter schema for a knowledge-bridge tool.

        USE WHEN: need exact parameters for promote_learning, search_for_session, etc.
        """
        interface = state.get("interface")
        if not interface:
            raise HTTPException(status_code=503, detail="Server not ready")
        return await interface.get_tool_spec(request.tool_name)

    @app.post("/mcp/execute_tool")
    async def execute_tool(request: ExecuteToolRequest) -> dict[str, Any]:
        """Execute a knowledge-bridge tool.

        Supports: promote_learning, batch_promote, get_staging_queue, search_for_session,
        prime_session, report_outcome, register_webhook, and more.
        """
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

    # ===== Curator Callback Endpoint =====

    @app.post("/curator/decision")
    async def curator_decision(request: CurationDecisionRequest) -> dict[str, Any]:
        """Receive curation decision from curator daemon.

        Updates the staging queue entry status based on curator's decision.
        Emits curation.completed webhook event.
        """
        database = state.get("database")
        webhook_emitter = state.get("webhook_emitter")

        if not database:
            raise HTTPException(status_code=503, detail="Database not ready")

        # Map decision to status
        decision_to_status = {
            "promote": "promoted",
            "reject": "rejected",
            "merge": "merged",
            "flag_human": "flagged",
        }
        status = decision_to_status.get(request.decision, "reviewed")

        # Build curator notes
        curator_notes = f"{request.decision}: {request.reason} (confidence: {request.confidence:.2f})"
        if request.similar_entries:
            curator_notes += f"\nSimilar entries: {', '.join(request.similar_entries)}"

        try:
            # Update staging entry
            success = await database.update_staged_entry_status(
                entry_id=request.entry_id,
                status=status,
                curator_notes=curator_notes,
                promoted_to=None,  # Will be set if actually promoted to UCKN
            )

            if not success:
                logger.warning(f"Entry {request.entry_id} not found in staging queue")
                raise HTTPException(status_code=404, detail=f"Entry {request.entry_id} not found")

            # Emit webhook event
            if webhook_emitter:
                await webhook_emitter.emit(
                    "curation.completed",
                    {
                        "entry_id": request.entry_id,
                        "decision": request.decision,
                        "reason": request.reason,
                        "confidence": request.confidence,
                        "status": status,
                    },
                )

            logger.info(f"Curator decision for {request.entry_id}: {request.decision}")
            return {
                "success": True,
                "entry_id": request.entry_id,
                "status": status,
                "message": f"Entry updated to {status}",
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"Error processing curator decision for {request.entry_id}")
            raise HTTPException(status_code=500, detail=str(e))

    return app
