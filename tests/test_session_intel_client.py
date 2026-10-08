"""Tests for SessionIntelligenceClient session handling and response parsing.

FakeSessionIntelligence mirrors session-intelligence's /mcp rules
(src/transport/http_server.py): 400 without MCP-Session-Id, 404 for an
unknown one. Tool results use its execute_tool envelope
(src/lean_mcp_interface.py). The shapes come from that source, not from a
recording of a live server.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from knowledge_bridge.clients.session_intel import (
    SESSION_HEADER,
    SessionIntelligenceClient,
)

SEARCH_RESULT: dict[str, Any] = {
    "query": "sess-abc123",
    "total_results": 1,
    "results": [
        {
            "session_id": "sess-abc123",
            "title": None,
            "snippet": "use sqlite for the staging queue",
            "relevance": 0.85,
            "project_name": "knowledge-bridge",
            "project_path": "/home/user/knowledge-bridge",
            "started_at": "2026-10-07T10:30:00Z",
            "tags": ["storage"],
        }
    ],
}

OVERVIEW_RESULT: dict[str, Any] = {
    "dashboard_type": "overview",
    "session_id": "sess-abc123",
    "metrics": {
        "project_name": "knowledge-bridge",
        "session_status": "completed",
        "started": "2026-10-07T10:30:00Z",
        "completed": "2026-10-07T11:00:00Z",
        "agents_executed": 1,
        "successful_executions": 1,
        "failed_executions": 0,
        "abandoned_executions": 0,
        "indeterminate_executions": 0,
        "decisions": 1,
        "efficiency_score": 0.92,
    },
    "visualizations": [],
    "insights": [],
    "recommendations": [],
    "real_time_data": False,
}

DECISIONS_RESULT: dict[str, Any] = {
    "dashboard_type": "decisions",
    "session_id": "sess-abc123",
    "metrics": {
        "decisions": 1,
        "recent_decisions": [
            {
                "description": "use sqlite for the staging queue",
                "timestamp": "2026-10-07T10:45:00Z",
            }
        ],
    },
    "visualizations": [],
    "insights": [],
    "recommendations": [],
    "real_time_data": False,
}

NOTEBOOKS_RESULT: list[dict[str, Any]] = [
    {
        "session_id": "sess-abc123",
        "title": "Staging queue storage",
        "tags": ["storage"],
        "created_at": "2026-10-07T11:00:00Z",
        "project_name": "knowledge-bridge",
    }
]

ALL_TOOLS: dict[str, Any] = {
    "session_search": SEARCH_RESULT,
    "session_query_notebooks": NOTEBOOKS_RESULT,
}


class FakeSessionIntelligence:
    """In-process stand-in for session-intelligence's POST /mcp endpoint."""

    def __init__(
        self,
        tool_results: dict[str, Any] | None = None,
        dashboards: dict[str, Any] | None = None,
    ) -> None:
        self.tool_results = tool_results or {}
        self.dashboards = dashboards or {}
        self.sessions: set[str] = set()
        self.requests: list[httpx.Request] = []
        self.reject_all_sessions = False
        self._issued = 0

    def restart(self) -> None:
        """Drop all sessions, as a session-intelligence restart does."""
        self.sessions.clear()

    def methods(self) -> list[str]:
        return [json.loads(r.content)["method"] for r in self.requests]

    def session_ids_for(self, method: str) -> list[str | None]:
        return [
            r.headers.get(SESSION_HEADER)
            for r in self.requests
            if json.loads(r.content)["method"] == method
        ]

    @staticmethod
    def _rpc_error(status: int, req_id: Any, message: str) -> httpx.Response:
        return httpx.Response(
            status,
            json={
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32600, "message": message},
            },
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content)
        method = body["method"]
        req_id = body.get("id")

        if method == "initialize":
            self._issued += 1
            session_id = f"sid-{self._issued}"
            self.sessions.add(session_id)
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"protocolVersion": "2024-11-05"},
                },
                headers={SESSION_HEADER: session_id},
            )

        session_id = request.headers.get(SESSION_HEADER)
        if session_id is None:
            return self._rpc_error(400, req_id, "Missing MCP-Session-Id")
        if session_id not in self.sessions or (
            self.reject_all_sessions and method == "tools/call"
        ):
            return self._rpc_error(404, req_id, "Session not found")

        if method == "notifications/initialized":
            return httpx.Response(200, json={})

        arguments = body["params"]["arguments"]
        tool = arguments["tool_name"]
        if tool == "session_get_dashboard":
            dashboard_type = arguments["parameters"]["dashboard_type"]
            if dashboard_type in self.dashboards:
                envelope: dict[str, Any] = {
                    "tool": tool,
                    "status": "success",
                    "result": self.dashboards[dashboard_type],
                }
            else:
                envelope = {
                    "tool": tool,
                    "status": "error",
                    "error": "Session sess-abc123 not found",
                }
        elif tool in self.tool_results:
            envelope = {
                "tool": tool,
                "status": "success",
                "result": self.tool_results[tool],
            }
        else:
            envelope = {
                "error": f"Tool '{tool}' not found",
                "available_tools": [],
            }

        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(envelope)}]},
            },
        )


def make_client(server: FakeSessionIntelligence) -> SessionIntelligenceClient:
    client = SessionIntelligenceClient()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(server.handler))
    return client


# ===== Session handling =====


@pytest.mark.asyncio
async def test_initializes_before_first_call_and_sends_session_header() -> None:
    server = FakeSessionIntelligence(tool_results=ALL_TOOLS)
    client = make_client(server)

    learnings = await client.get_session_learnings("sess-abc123")

    assert learnings == SEARCH_RESULT["results"]
    assert server.methods() == [
        "initialize",
        "notifications/initialized",
        "tools/call",
    ]
    assert server.session_ids_for("initialize") == [None]
    assert server.session_ids_for("tools/call") == ["sid-1"]
    await client.close()


@pytest.mark.asyncio
async def test_reuses_session_across_calls() -> None:
    server = FakeSessionIntelligence(tool_results=ALL_TOOLS)
    client = make_client(server)

    await client.get_session_learnings("sess-abc123")
    await client.get_session_notes("sess-abc123")

    assert server.methods().count("initialize") == 1
    assert server.session_ids_for("tools/call") == ["sid-1", "sid-1"]
    await client.close()


@pytest.mark.asyncio
async def test_concurrent_first_calls_share_one_initialize() -> None:
    server = FakeSessionIntelligence(tool_results=ALL_TOOLS)
    client = make_client(server)

    await asyncio.gather(
        client.get_session_learnings("sess-abc123"),
        client.get_session_notes("sess-abc123"),
    )

    assert server.methods().count("initialize") == 1
    await client.close()


@pytest.mark.asyncio
async def test_reinitializes_once_after_server_restart() -> None:
    server = FakeSessionIntelligence(tool_results=ALL_TOOLS)
    client = make_client(server)
    await client.get_session_learnings("sess-abc123")

    server.restart()
    learnings = await client.get_session_learnings("sess-abc123")

    assert learnings == SEARCH_RESULT["results"]
    assert server.methods() == [
        "initialize",
        "notifications/initialized",
        "tools/call",
        "tools/call",
        "initialize",
        "notifications/initialized",
        "tools/call",
    ]
    assert server.session_ids_for("tools/call") == ["sid-1", "sid-1", "sid-2"]
    await client.close()


@pytest.mark.asyncio
async def test_retries_only_once_when_new_session_is_also_rejected() -> None:
    server = FakeSessionIntelligence(tool_results=ALL_TOOLS)
    server.reject_all_sessions = True
    client = make_client(server)

    learnings = await client.get_session_learnings("sess-abc123")

    assert learnings == []
    assert server.methods().count("initialize") == 2
    assert server.methods().count("tools/call") == 2
    await client.close()


@pytest.mark.asyncio
async def test_missing_session_header_on_initialize_is_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": "1", "result": {}})

    client = SessionIntelligenceClient()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    assert await client.get_session_learnings("sess-abc123") == []
    await client.close()


# ===== Response parsing =====


@pytest.mark.asyncio
async def test_get_session_returns_overview_dashboard() -> None:
    server = FakeSessionIntelligence(dashboards={"overview": OVERVIEW_RESULT})
    client = make_client(server)

    assert await client.get_session("sess-abc123") == OVERVIEW_RESULT
    await client.close()


@pytest.mark.asyncio
async def test_get_session_returns_none_on_error_envelope() -> None:
    server = FakeSessionIntelligence()
    client = make_client(server)

    assert await client.get_session("sess-missing") is None
    await client.close()


@pytest.mark.asyncio
async def test_get_session_decisions_reads_recent_decisions() -> None:
    server = FakeSessionIntelligence(dashboards={"decisions": DECISIONS_RESULT})
    client = make_client(server)

    decisions = await client.get_session_decisions("sess-abc123")

    assert decisions == DECISIONS_RESULT["metrics"]["recent_decisions"]
    await client.close()


@pytest.mark.asyncio
async def test_get_session_notes_reads_bare_list() -> None:
    server = FakeSessionIntelligence(tool_results=ALL_TOOLS)
    client = make_client(server)

    assert await client.get_session_notes("sess-abc123") == NOTEBOOKS_RESULT
    await client.close()


@pytest.mark.asyncio
async def test_get_learning_returns_first_search_hit() -> None:
    server = FakeSessionIntelligence(tool_results=ALL_TOOLS)
    client = make_client(server)

    assert await client.get_learning("sess-abc123") == SEARCH_RESULT["results"][0]
    await client.close()


@pytest.mark.asyncio
async def test_unknown_tool_envelope_yields_empty_results() -> None:
    server = FakeSessionIntelligence()
    client = make_client(server)

    assert await client.get_session_learnings("sess-abc123") == []
    assert await client.get_session_notes("sess-abc123") == []
    assert await client.get_learning("sess-abc123") is None
    await client.close()


@pytest.mark.asyncio
async def test_get_session_data_combines_all_types() -> None:
    server = FakeSessionIntelligence(
        tool_results=ALL_TOOLS, dashboards={"decisions": DECISIONS_RESULT}
    )
    client = make_client(server)

    data = await client.get_session_data("sess-abc123")

    assert data == {
        "session_id": "sess-abc123",
        "learnings": SEARCH_RESULT["results"],
        "decisions": DECISIONS_RESULT["metrics"]["recent_decisions"],
        "notes": NOTEBOOKS_RESULT,
    }
    await client.close()
