# Knowledge-Bridge MCP Server

## Quick Start

**Read the PRD first**: `../PRD.md`

## Project Context

| Item | Value |
|------|-------|
| **Port** | 4003 (HTTP) |
| **Purpose** | Orchestration layer between session-intelligence (4002) and UCKN (4004) |
| **Template** | `~/ClaudeCode/Servers/mcp-server-template/development/` |
| **Design Doc** | `~/ClaudeCode/design-docs/knowledge-bridge-proposal.md` |

## Architecture

```
session-intelligence (4002) ←→ knowledge-bridge (4003) ←→ UCKN (4004)
                                       ↓
                                  Curator Daemon
```

## Key Patterns

### 1. Lean MCP Interface (from template)
```python
# Only 3 tools exposed
discover_tools(pattern) → list tools
get_tool_spec(name) → get schema
execute_tool(name, params) → run tool
```

### 2. HTTP Transport Required
This server MUST use HTTP transport for cross-session communication.

### 3. Webhook-Based Events
Emit events to subscribers (curator daemon, dashboard).

## Implementation Checklist

- [x] Phase 1: Foundation (skeleton, database, HTTP) **IN PROGRESS**
- [ ] Phase 2: Promotion Flow (promote_learning, batch_promote)
- [ ] Phase 3: Retrieval Flow (search_for_session, prime_session)
- [ ] Phase 4: Feedback Loop (report_outcome)
- [ ] Phase 5: Webhook System
- [ ] Phase 6: Testing

## Phase 1 Progress (2026-01-03)

**Plan file**: `~/.claude/plans/splendid-foraging-anchor.md`

### User Decisions
- **Database**: PostgreSQL (not SQLite) - consistent with session-intelligence
- **UCKN**: Mock client until UCKN server ready
- **Webhooks**: HTTP POST with retry (not just SSE)
- **Template**: Backport patterns to template later

### Completed Files (16/22)
```
✅ pyproject.toml
✅ src/knowledge_bridge/__init__.py
✅ src/knowledge_bridge/core/__init__.py
✅ src/knowledge_bridge/core/models.py          # Pydantic models
✅ src/knowledge_bridge/persistence/__init__.py
✅ src/knowledge_bridge/persistence/base.py     # Abstract backend
✅ src/knowledge_bridge/persistence/postgresql.py  # Full PostgreSQL adapter
✅ src/knowledge_bridge/clients/__init__.py
✅ src/knowledge_bridge/clients/session_intel.py   # HTTP client for 4002
✅ src/knowledge_bridge/clients/uckn.py            # Mock client for 4004
✅ src/knowledge_bridge/webhooks/__init__.py
✅ src/knowledge_bridge/webhooks/events.py         # Event types
✅ src/knowledge_bridge/webhooks/emitter.py        # HTTP POST delivery
✅ src/knowledge_bridge/lean/__init__.py
✅ src/knowledge_bridge/transport/__init__.py
✅ tests/__init__.py
```

### Remaining Files (6)
```
⏳ src/knowledge_bridge/core/service.py         # Domain service
⏳ src/knowledge_bridge/lean/interface.py       # 10 MCP tools (WAS WRITING)
⏳ src/knowledge_bridge/transport/http_server.py  # FastAPI server
⏳ src/knowledge_bridge/transport/security.py   # LocalhostOnlyMiddleware
⏳ src/http_lean_server.py                      # Entry point
⏳ tests/conftest.py                            # Test fixtures
```

### Resume Instructions
To continue implementation:
1. Create `src/knowledge_bridge/lean/interface.py` with 10 tools
2. Create `src/knowledge_bridge/transport/http_server.py`
3. Create `src/knowledge_bridge/transport/security.py`
4. Create `src/http_lean_server.py` (entry point)
5. Create `tests/conftest.py`
6. Run `git init && git add . && git commit`
7. Test with `pixi run http-server`

## Tools to Implement

### Promotion (→ UCKN)
- `promote_learning` - Single learning promotion
- `batch_promote` - Session-end batch promotion
- `get_staging_queue` - View pending entries

### Retrieval (← UCKN)
- `search_for_session` - Query knowledge for session
- `prime_session` - Proactive knowledge injection

### Feedback
- `report_outcome` - Track solution success/failure

### Webhooks
- `register_webhook` - Subscribe to events
- `unregister_webhook` - Unsubscribe
- `list_webhooks` - List subscriptions

### Inter-Server
- `request_session_data` - Query session-intelligence
- `request_uckn_update` - Update UCKN entries

## Database

SQLite with tables:
- `staging_queue` - Learnings awaiting promotion
- `webhooks` - Event subscriptions
- `event_log` - Emitted events
- `feedback` - Solution outcomes
- `search_log` - Query analytics

## Commands

```bash
pixi run http-server      # Start on port 4003
pixi run http-server-dev  # With debug logging
pixi run test             # Run tests
pixi run lint             # Check code quality
```

## Session Intelligence Notes

Decisions logged in session-intelligence:
- `decision-e2abc300`: Separate bridge server architecture
- `decision-3608f0c6`: Standalone curator daemon
- `decision-a9236545`: Webhook-based communication
- `decision-f3e37064`: Sonnet for curator model
