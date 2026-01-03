# Knowledge-Bridge MCP Server

**Version**: 0.1.0
**Port**: 4003 (HTTP)
**Status**: Phase 1 Implementation

## Overview

Orchestration layer between session-intelligence (4002) and UCKN (4004) for cross-session knowledge sharing.

## Quick Start

```bash
# Initialize database
pixi run db-init

# Start HTTP server
pixi run http-server

# Run tests
pixi run test

# Quality checks
pixi run lint
pixi run type-check
```

## Architecture

```
session-intelligence (4002) ←→ knowledge-bridge (4003) ←→ UCKN (4004)
                                       ↓
                                  Curator Daemon
```

## Documentation

- **PRD**: `PRD.md` - Full requirements and specifications
- **Design**: `~/ClaudeCode/design-docs/knowledge-bridge-proposal.md`
- **Template**: `~/ClaudeCode/Servers/mcp-server-template/development/`

## Features

### Promotion Flow (→ UCKN)
- `promote_learning` - Single learning promotion
- `batch_promote` - Session-end batch promotion
- `get_staging_queue` - View pending entries

### Retrieval Flow (← UCKN)
- `search_for_session` - Query knowledge for session
- `prime_session` - Proactive knowledge injection

### Feedback Loop
- `report_outcome` - Track solution success/failure

### Webhooks
- `register_webhook` - Subscribe to events
- `unregister_webhook` - Unsubscribe
- `list_webhooks` - List subscriptions

## Implementation Status

Phase 1 Progress: 16/22 files completed

### Completed
- ✅ Database schema (PostgreSQL)
- ✅ Core models (Pydantic)
- ✅ Persistence layer (PostgreSQL adapter)
- ✅ HTTP clients (session-intelligence, UCKN mock)
- ✅ Webhook system (events, emitter)

### In Progress
- ⏳ Lean MCP interface (10 tools)
- ⏳ HTTP transport server
- ⏳ Domain service
- ⏳ Test fixtures

## License

MIT
