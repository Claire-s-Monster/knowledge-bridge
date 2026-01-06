# Knowledge-Bridge MCP Server

## Quick Start

**Read the PRD first**: `PRD.md`

```bash
# Run tests
PYTHONPATH=src pixi run -e dev test

# Start server (SQLite auto-creates)
pixi run http-server

# Restart via systemd
systemctl --user restart knowledge-bridge
```

## Project Context

| Item | Value |
|------|-------|
| **Port** | 4003 (HTTP) |
| **Purpose** | Orchestration layer between session-intelligence (4002) and knowledge-store (4004) |
| **Template** | `~/ClaudeCode/Servers/mcp-server-template/development/` |
| **Design Doc** | `~/ClaudeCode/design-docs/knowledge-bridge-proposal.md` |

## Architecture

```
session-intelligence (4002) <-> knowledge-bridge (4003) <-> knowledge-store (4004)
                                       |
                                  Curator Daemon
```

## Implementation Status: COMPLETE

All 6 phases implemented with 51 tests passing:

| Phase | Status | Components |
|-------|--------|------------|
| Foundation | ✅ | 19 source files, SQLite backend |
| Promotion | ✅ | promote_learning, batch_promote, get_staging_queue, get_staged_entry |
| Retrieval | ✅ | search_for_session, prime_session |
| Feedback | ✅ | report_outcome |
| Webhooks | ✅ | register/unregister/list webhooks |
| Testing | ✅ | 51 tests across 5 test files |

## Tools (11)

| Category | Tools |
|----------|-------|
| **Promotion** | `promote_learning`, `batch_promote`, `get_staging_queue`, `get_staged_entry` |
| **Retrieval** | `search_for_session`, `prime_session` |
| **Feedback** | `report_outcome` |
| **Webhooks** | `register_webhook`, `unregister_webhook`, `list_webhooks` |
| **Inter-Server** | `request_session_data` |

## Key Patterns

### 1. Lean MCP Interface
```python
discover_tools(pattern) -> list tools
get_tool_spec(name) -> get schema
execute_tool(name, params) -> run tool
```

### 2. HTTP Transport Required
FastAPI server on port 4003 with localhost-only security middleware.

### 3. Webhook-Based Events
HTTP POST delivery with retry logic for event subscribers.

**Webhook payloads include `content` field** for LEARNING_STAGED and LEARNING_PROMOTED events.

## Database (SQLite)

Tables: `staging_queue`, `webhooks`, `event_log`, `feedback`, `search_log`, `schema_version`

Location: `~/.claude/knowledge-bridge/knowledge_bridge.db` (auto-created on first run)

## Commands

```bash
pixi run http-server      # Start on port 4003 (SQLite auto-creates)
pixi run http-server-dev  # With debug logging
pixi run db-init          # Create data directory (optional)
PYTHONPATH=src pixi run -e dev test  # Run 51 tests
pixi run lint             # Check code quality

# Systemd management
systemctl --user status knowledge-bridge
systemctl --user restart knowledge-bridge
journalctl --user -u knowledge-bridge -f
```

## Clients

| Client | File | Target |
|--------|------|--------|
| `SessionIntelligenceClient` | `clients/session_intel.py` | port 4002 |
| `KnowledgeStoreClient` | `clients/knowledge_store.py` | port 4004 (JSON-RPC) |
| `MockUCKNClient` | `clients/uckn.py` | Deprecated, for tests only |

## Session Notes (2026-01-05)

### Decisions Made

1. **Implemented real KnowledgeStoreClient** replacing MockUCKNClient
   - Uses JSON-RPC over HTTP to call MCP tools on knowledge-store (4004)
   - Methods: `search()`, `promote()`, `update_entry()`, `get_entry()`, `health_check()`

2. **Added `get_staged_entry` tool**
   - Curator daemon needs to fetch individual entries by ID
   - Returns full StagedEntry with content

3. **Added `content` field to webhook payloads**
   - LEARNING_STAGED and LEARNING_PROMOTED events now include content
   - Required by curator's StagedLearningPayload validator

### Learnings

- knowledge-store uses lean 3-meta-tool pattern with JSON-RPC (`tools/call` method)
- Webhook payloads must match subscriber's Pydantic validators exactly
- Health endpoint now shows `knowledge_store` (not `uckn`) with real health status

## Next Steps

1. **Integration Testing**: Full end-to-end with curator daemon
2. **Curator Daemon**: Complete standalone curation process
3. **Monitoring**: Add metrics and dashboard integration
