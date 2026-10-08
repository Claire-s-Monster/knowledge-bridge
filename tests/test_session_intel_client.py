"""Tests for SessionIntelligenceClient session handling and response parsing.

FakeSessionIntelligence mirrors session-intelligence's /mcp rules
(src/transport/http_server.py): 400 without MCP-Session-Id, 404 for an unknown
one. Like the real server, it rejects tool parameters a tool does not accept.
Tool results were recorded from a live session-intelligence on 2026-10-08, with
long text trimmed.
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

SESSION_ID = "949b45a9-9b8a-44ee-b7bb-d203d5533da9"
OTHER_SESSION_ID = "session-20261008-095530-4e333f"

# Parameters each tool accepts, from session-intelligence's tool specs.
ACCEPTED_PARAMS: dict[str, set[str]] = {
    "session_get_dashboard": {
        "dashboard_type",
        "session_id",
        "session_name",
        "project_name",
        "project_path",
    },
    "session_recall": {"project_name", "include", "limit", "days"},
    "session_query_notebooks": {
        "project_path",
        "project_name",
        "tags",
        "limit",
        "summary_only",
        "outline",
        "section",
        "offset",
        "max_chars",
        "search",
        "include_key_changes",
    },
    "session_search": {"query", "search_type", "limit"},
}

OVERVIEW_RESULT: dict[str, Any] = {
    "dashboard_type": "overview",
    "session_id": SESSION_ID,
    "metrics": {
        "project_name": "knowledge-bridge",
        "session_status": "completed",
        "started": "2026-10-08T14:55:42.489932+00:00",
        "completed": "2026-10-08T14:56:26.218510+00:00",
        "agents_executed": 9,
        "successful_executions": 8,
        "failed_executions": 0,
        "indeterminate_executions": 0,
        "abandoned_executions": 0,
        "commands_executed": 22,
        "decisions": 2,
        "efficiency_score": 100.0,
    },
    "visualizations": [],
    "insights": [],
    "recommendations": [],
    "real_time_data": False,
}

DECISIONS_RESULT: dict[str, Any] = {
    "dashboard_type": "decisions",
    "session_id": SESSION_ID,
    "metrics": {
        "decisions": 2,
        "recent_decisions": [
            {
                "decision_id": "decision-e8f27550",
                "timestamp": "2026-10-08T15:08:22.187722+00:00",
                "description": "Left out of the issue #8 fix and flagged as a separate issue.",
                "impact_level": "medium",
                "supersedes": None,
            },
            {
                "decision_id": "decision-6e162400",
                "timestamp": "2026-10-08T15:04:58.455762+00:00",
                "description": "Issue #8: SessionIntelligenceClient now initializes lazily.",
                "impact_level": "medium",
                "supersedes": None,
            },
        ],
    },
    "visualizations": [],
    "insights": [],
    "recommendations": [],
    "real_time_data": False,
}

LEARNING_THIS_SESSION: dict[str, Any] = {
    "id": "learn_88866055f6d6",
    "category": "pattern",
    "trigger_context": "Formatting or lint checks in knowledge-bridge",
    "learning_content": "knowledge-bridge: black is the formatter; ruff is lint-only.",
    "project_name": "knowledge-bridge",
    "source_session_id": SESSION_ID,
    "success_count": 1,
    "failure_count": 0,
    "created_at": "2026-10-08T16:01:45.261204+00:00",
    "last_used": "2026-10-08T16:01:45.261204+00:00",
}

LEARNING_OTHER_SESSION: dict[str, Any] = {
    "id": "learn_6eb681d44813",
    "category": "error_fix",
    "trigger_context": "When running focused-code-modifier agent in similar context",
    "learning_content": "Agent focused-code-modifier encountered: toolu_01GKYtvQKZnWVCsgLhKaopTt",
    "project_name": "knowledge-bridge",
    "source_session_id": OTHER_SESSION_ID,
    "success_count": 1,
    "failure_count": 0,
    "created_at": "2026-10-08T15:08:04.898564+00:00",
    "last_used": "2026-10-08T15:08:04.898564+00:00",
}

RECALL_RESULT: dict[str, Any] = {
    "project_name": "knowledge-bridge",
    "recall_window_days": 3650,
    "sessions": [],
    "decisions": [],
    "learnings": [LEARNING_THIS_SESSION, LEARNING_OTHER_SESSION],
    "notebooks": [],
    "counts": {"sessions": 0, "decisions": 0, "learnings": 2, "notebooks": 0},
}

# The live project had no notebook for SESSION_ID; this one is made up in the
# recorded summary shape.
NOTEBOOK_THIS_SESSION: dict[str, Any] = {
    "session_id": SESSION_ID,
    "title": "Issue #8 session handshake",
    "tags": ["knowledge-bridge"],
    "created_at": "2026-10-08T16:20:00+00:00",
    "project_name": "knowledge-bridge",
}

NOTEBOOK_OTHER_SESSION: dict[str, Any] = {
    "session_id": "session-20260112-205137",
    "title": "Knowledge-Bridge Codebase Review & Quality Fixes",
    "tags": ["knowledge-bridge", "code-quality"],
    "created_at": "2026-01-13T16:34:29.137434+00:00",
    "project_name": "knowledge-bridge",
}

SEARCH_RESULT: dict[str, Any] = {
    "query": "black",
    "total_results": 1,
    "results": [
        {
            "session_id": "learn_dca904e9f957",
            "title": "error_fix",
            "snippet": "<b>BLACK</b> IS BROKEN ON shell-runner",
            "relevance": 0.09285612404346466,
            "project_name": "shell-runner",
            "project_path": "_unknown_",
            "started_at": "2026-08-27T16:06:15.216935+00:00",
            "tags": [],
        }
    ],
}


class FakeSessionIntelligence:
    """In-process stand-in for session-intelligence's POST /mcp endpoint."""

    def __init__(self) -> None:
        self.dashboards: dict[str, Any] = {
            "overview": OVERVIEW_RESULT,
            "decisions": DECISIONS_RESULT,
        }
        self.tool_results: dict[str, Any] = {
            "session_recall": RECALL_RESULT,
            "session_query_notebooks": [NOTEBOOK_THIS_SESSION, NOTEBOOK_OTHER_SESSION],
            "session_search": SEARCH_RESULT,
        }
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

    def tool_calls(self) -> list[tuple[str, dict[str, Any]]]:
        calls = []
        for r in self.requests:
            body = json.loads(r.content)
            if body["method"] == "tools/call":
                arguments = body["params"]["arguments"]
                calls.append((arguments["tool_name"], arguments["parameters"]))
        return calls

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

    def _envelope(self, tool: str, params: dict[str, Any]) -> dict[str, Any]:
        if tool not in ACCEPTED_PARAMS:
            return {"error": f"Tool '{tool}' not found", "available_tools": []}

        unexpected = sorted(set(params) - ACCEPTED_PARAMS[tool])
        if unexpected:
            return {
                "tool": tool,
                "status": "error",
                "error": f"Invalid parameters for '{tool}' - unexpected parameter(s): {unexpected}",
            }

        if tool == "session_get_dashboard":
            result = self.dashboards.get(params.get("dashboard_type", ""))
        else:
            result = self.tool_results.get(tool)
        if result is None:
            return {"tool": tool, "status": "error", "error": "Session not found"}
        return {"tool": tool, "status": "success", "result": result}

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
        if session_id not in self.sessions or (self.reject_all_sessions and method == "tools/call"):
            return self._rpc_error(404, req_id, "Session not found")

        if method == "notifications/initialized":
            return httpx.Response(200, json={})

        arguments = body["params"]["arguments"]
        envelope = self._envelope(arguments["tool_name"], arguments["parameters"])
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


def as_learning(record: dict[str, Any]) -> dict[str, Any]:
    return {
        **record,
        "problem": record["trigger_context"],
        "solution": record["learning_content"],
    }


# ===== Session handling =====


@pytest.mark.asyncio
async def test_initializes_before_first_call_and_sends_session_header() -> None:
    server = FakeSessionIntelligence()
    client = make_client(server)

    assert await client.get_session(SESSION_ID) == OVERVIEW_RESULT
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
    server = FakeSessionIntelligence()
    client = make_client(server)

    await client.get_session(SESSION_ID)
    await client.get_session_decisions(SESSION_ID)

    assert server.methods().count("initialize") == 1
    assert server.session_ids_for("tools/call") == ["sid-1", "sid-1"]
    await client.close()


@pytest.mark.asyncio
async def test_concurrent_first_calls_share_one_initialize() -> None:
    server = FakeSessionIntelligence()
    client = make_client(server)

    await asyncio.gather(
        client.get_session(SESSION_ID),
        client.get_session_decisions(SESSION_ID),
    )

    assert server.methods().count("initialize") == 1
    await client.close()


@pytest.mark.asyncio
async def test_reinitializes_once_after_server_restart() -> None:
    server = FakeSessionIntelligence()
    client = make_client(server)
    await client.get_session(SESSION_ID)

    server.restart()

    assert await client.get_session(SESSION_ID) == OVERVIEW_RESULT
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
    server = FakeSessionIntelligence()
    server.reject_all_sessions = True
    client = make_client(server)

    assert await client.get_session(SESSION_ID) is None
    assert server.methods().count("initialize") == 2
    assert server.methods().count("tools/call") == 2
    await client.close()


@pytest.mark.asyncio
async def test_missing_session_header_on_initialize_is_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": "1", "result": {}})

    client = SessionIntelligenceClient()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    assert await client.get_session(SESSION_ID) is None
    await client.close()


# ===== Dashboards =====


@pytest.mark.asyncio
async def test_get_session_sends_only_accepted_parameters() -> None:
    server = FakeSessionIntelligence()
    client = make_client(server)

    assert await client.get_session(SESSION_ID) == OVERVIEW_RESULT
    assert server.tool_calls() == [
        ("session_get_dashboard", {"session_id": SESSION_ID, "dashboard_type": "overview"})
    ]
    await client.close()


@pytest.mark.asyncio
async def test_get_session_returns_none_on_error_envelope() -> None:
    server = FakeSessionIntelligence()
    server.dashboards.clear()
    client = make_client(server)

    assert await client.get_session(SESSION_ID) is None
    await client.close()


@pytest.mark.asyncio
async def test_get_session_decisions_reads_recent_decisions() -> None:
    server = FakeSessionIntelligence()
    client = make_client(server)

    decisions = await client.get_session_decisions(SESSION_ID)

    assert decisions == DECISIONS_RESULT["metrics"]["recent_decisions"]
    assert server.tool_calls() == [
        ("session_get_dashboard", {"session_id": SESSION_ID, "dashboard_type": "decisions"})
    ]
    await client.close()


# ===== Learnings and notes =====


@pytest.mark.asyncio
async def test_get_session_learnings_keeps_only_this_sessions_learnings() -> None:
    server = FakeSessionIntelligence()
    client = make_client(server)

    learnings = await client.get_session_learnings(SESSION_ID)

    assert learnings == [as_learning(LEARNING_THIS_SESSION)]
    assert [tool for tool, _ in server.tool_calls()] == [
        "session_get_dashboard",
        "session_recall",
    ]
    recall_params = server.tool_calls()[1][1]
    assert recall_params["project_name"] == "knowledge-bridge"
    assert recall_params["include"] == ["learnings"]
    await client.close()


@pytest.mark.asyncio
async def test_get_session_learnings_maps_fields_for_promotion() -> None:
    server = FakeSessionIntelligence()
    client = make_client(server)

    [learning] = await client.get_session_learnings(SESSION_ID)

    assert learning["problem"] == LEARNING_THIS_SESSION["trigger_context"]
    assert learning["solution"] == LEARNING_THIS_SESSION["learning_content"]
    assert learning["id"] == LEARNING_THIS_SESSION["id"]
    await client.close()


@pytest.mark.asyncio
async def test_get_session_learnings_empty_when_session_unknown() -> None:
    server = FakeSessionIntelligence()
    server.dashboards.clear()
    client = make_client(server)

    assert await client.get_session_learnings(SESSION_ID) == []
    assert [tool for tool, _ in server.tool_calls()] == ["session_get_dashboard"]
    await client.close()


@pytest.mark.asyncio
async def test_get_session_notes_keeps_only_this_sessions_notebooks() -> None:
    server = FakeSessionIntelligence()
    client = make_client(server)

    notes = await client.get_session_notes(SESSION_ID)

    assert notes == [NOTEBOOK_THIS_SESSION]
    tool, params = server.tool_calls()[1]
    assert tool == "session_query_notebooks"
    assert params["project_name"] == "knowledge-bridge"
    await client.close()


@pytest.mark.asyncio
async def test_get_learning_returns_first_search_hit() -> None:
    # Current behaviour until session-intelligence#207 adds a fetch-by-ID tool.
    server = FakeSessionIntelligence()
    client = make_client(server)

    assert await client.get_learning("learn_dca904e9f957") == SEARCH_RESULT["results"][0]
    await client.close()


@pytest.mark.asyncio
async def test_error_envelopes_yield_empty_results() -> None:
    server = FakeSessionIntelligence()
    server.tool_results.clear()
    client = make_client(server)

    assert await client.get_session_learnings(SESSION_ID) == []
    assert await client.get_session_notes(SESSION_ID) == []
    assert await client.get_learning("learn_dca904e9f957") is None
    await client.close()


@pytest.mark.asyncio
async def test_get_session_data_combines_all_types() -> None:
    server = FakeSessionIntelligence()
    client = make_client(server)

    data = await client.get_session_data(SESSION_ID)

    assert data == {
        "session_id": SESSION_ID,
        "learnings": [as_learning(LEARNING_THIS_SESSION)],
        "decisions": DECISIONS_RESULT["metrics"]["recent_decisions"],
        "notes": [NOTEBOOK_THIS_SESSION],
    }
    await client.close()
