# Knowledge-Bridge MCP Server

## Quick Start

**Read the PRD first**: `../PRD.md`

```bash
# Run tests
PYTHONPATH=src pixi run -e dev test

# Start server (SQLite auto-creates on first run)
pixi run http-server
```

## Project Context

| Item | Value |
|------|-------|
| **Port** | 4003 (HTTP) |
| **Purpose** | Orchestration layer between session-intelligence (4002) and UCKN (4004) |
| **Template** | `~/ClaudeCode/Servers/mcp-server-template/development/` |
| **Design Doc** | `~/ClaudeCode/design-docs/knowledge-bridge-proposal.md` |

## Architecture

```
session-intelligence (4002) <-> knowledge-bridge (4003) <-> UCKN (4004)
                                       |
                                  Curator Daemon
```

## Implementation Status

| Phase | Status | Details |
|-------|--------|---------|
| Phase 1: Foundation | ✅ COMPLETE | All 19 source files |
| Phase 2: Promotion Flow | ✅ COMPLETE | promote_learning, batch_promote, get_staging_queue |
| Phase 3: Retrieval Flow | ✅ COMPLETE | search_for_session, prime_session |
| Phase 4: Feedback Loop | ✅ COMPLETE | report_outcome |
| Phase 5: Webhook System | ✅ COMPLETE | register/unregister/list webhooks |
| Phase 6: Testing | ✅ COMPLETE | 51 tests passing |

## Source Files (19)

```
src/
├── http_lean_server.py              # Entry point
└── knowledge_bridge/
    ├── __init__.py
    ├── core/
    │   ├── __init__.py
    │   ├── models.py                # 9 Pydantic models
    │   └── service.py               # Domain service (569 lines)
    ├── persistence/
    │   ├── __init__.py
    │   ├── base.py                  # Abstract backend
    │   └── sqlite.py                # SQLite adapter
    ├── clients/
    │   ├── __init__.py
    │   ├── session_intel.py         # HTTP client for 4002
    │   └── uckn.py                  # Mock client for 4004
    ├── webhooks/
    │   ├── __init__.py
    │   ├── events.py                # Event types
    │   └── emitter.py               # HTTP POST delivery
    ├── lean/
    │   ├── __init__.py
    │   └── interface.py             # 10 MCP tools (598 lines)
    └── transport/
        ├── __init__.py
        ├── http_server.py           # FastAPI server
        └── security.py              # LocalhostOnlyMiddleware
```

## Test Files (5)

```
tests/
├── __init__.py
├── conftest.py                      # MockDatabaseBackend + fixtures
├── test_promotion.py                # 14 tests
├── test_retrieval.py                # 9 tests
├── test_feedback.py                 # 6 tests
├── test_webhooks.py                 # 9 tests
└── test_interface.py                # 13 tests
```

## Tools Implemented (10)

| Category | Tool | Status |
|----------|------|--------|
| Promotion | `promote_learning` | ✅ |
| Promotion | `batch_promote` | ✅ |
| Promotion | `get_staging_queue` | ✅ |
| Retrieval | `search_for_session` | ✅ |
| Retrieval | `prime_session` | ✅ |
| Feedback | `report_outcome` | ✅ |
| Webhooks | `register_webhook` | ✅ |
| Webhooks | `unregister_webhook` | ✅ |
| Webhooks | `list_webhooks` | ✅ |
| Inter-Server | `request_session_data` | ✅ |

## Key Patterns

### 1. Lean MCP Interface
```python
discover_tools(pattern) -> list tools
get_tool_spec(name) -> get schema
execute_tool(name, params) -> run tool
```

### 2. HTTP Transport
FastAPI server on port 4003 with localhost-only security.

### 3. Webhook Events
HTTP POST delivery with retry logic for event subscribers.

## Database (SQLite)

Tables:
- `staging_queue` - Learnings awaiting promotion
- `webhooks` - Event subscriptions
- `event_log` - Emitted events
- `feedback` - Solution outcomes
- `search_log` - Query analytics
- `schema_version` - Schema tracking

Location: `~/.claude/knowledge-bridge/knowledge_bridge.db` (auto-created on first run)

## Commands

```bash
pixi run http-server      # Start on port 4003 (SQLite auto-creates)
pixi run http-server-dev  # With debug logging
pixi run db-init          # Create data directory (optional)
PYTHONPATH=src pixi run -e dev test  # Run tests
pixi run lint             # Check code quality
```

## Next Steps

1. **Integration Testing**: Test with real session-intelligence server
2. **UCKN Integration**: Replace mock client when UCKN is ready
3. **Curator Daemon**: Implement standalone curation process
4. **Monitoring**: Add metrics and dashboard integration

## User Decisions (from design session)

- **Database**: SQLite (simplified from PostgreSQL for zero external dependencies)
- **UCKN**: Mock client until UCKN server ready
- **Webhooks**: HTTP POST with retry (not just SSE)
