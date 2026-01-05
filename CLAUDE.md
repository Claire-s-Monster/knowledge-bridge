# Knowledge-Bridge MCP Server

## Quick Start

**Read the PRD first**: `PRD.md`

```bash
# Run tests
PYTHONPATH=src pixi run -e dev test

# Start server (requires PostgreSQL)
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

## Implementation Status: COMPLETE

All 6 phases implemented with 51 tests passing:

| Phase | Status | Components |
|-------|--------|------------|
| Foundation | ✅ | 19 source files, PostgreSQL backend |
| Promotion | ✅ | promote_learning, batch_promote, get_staging_queue |
| Retrieval | ✅ | search_for_session, prime_session |
| Feedback | ✅ | report_outcome |
| Webhooks | ✅ | register/unregister/list webhooks |
| Testing | ✅ | 51 tests across 5 test files |

## Tools (10)

| Category | Tools |
|----------|-------|
| **Promotion** | `promote_learning`, `batch_promote`, `get_staging_queue` |
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
```

## Next Steps

1. **Integration Testing**: Test with real session-intelligence server
2. **UCKN Integration**: Replace mock client when UCKN is ready
3. **Curator Daemon**: Implement standalone curation process
