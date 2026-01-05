# Product Requirements Document: Knowledge-Bridge MCP Server

**Project**: knowledge-bridge
**Version**: 0.1.0
**Status**: Implementation Complete
**Created**: 2026-01-03
**Updated**: 2026-01-04 (Architecture change: UCKN → knowledge-store)
**Template Reference**: `~/ClaudeCode/Servers/mcp-server-template/development/`

---

## Executive Summary

The **knowledge-bridge** MCP server is the orchestration layer between session-intelligence (per-session state, HTTP:4002) and knowledge-store (global knowledge base, ChromaDB, HTTP:4004). It enables cross-session knowledge sharing where Claude Code sessions can both contribute learnings and benefit from accumulated knowledge.

## Related Projects

| Project | Port | Purpose | Status |
|---------|------|---------|--------|
| session-intelligence | 4002 | Per-session state, decisions, learnings | Running |
| **knowledge-bridge** | **4003** | **Orchestration layer (this project)** | **Running** |
| knowledge-store | 4004 | Global knowledge base (ChromaDB) | Running |
| Curator Daemon | N/A | LLM-powered curation (standalone) | Separate project |

## Architecture Change (2026-01-04)

**UCKN has been renamed to knowledge-store**. The functionality remains the same:
- ChromaDB-backed vector store for knowledge patterns
- HTTP API on port 4004
- Semantic search for similar problems/solutions

The client code needs to be updated from `MockUCKNClient` to a real `KnowledgeStoreClient`.

## Architecture Decisions (ADRs)

These decisions were made in the design session and should be followed:

### ADR-001: Separate Knowledge-Bridge Server
- **Decision**: Dedicated MCP server (HTTP:4003) rather than extending session-intelligence or knowledge-store
- **Rationale**: Clean separation of concerns, independent scaling

### ADR-002: Webhook-Based Communication
- **Decision**: Event-driven webhooks + inter-server HTTP requests
- **Rationale**: Loosely coupled, observable, supports multiple subscribers

### ADR-003: HTTP Transport Required
- **Decision**: Enable HTTP transport (not just stdio)
- **Rationale**: Cross-session communication with session-intelligence and knowledge-store

### ADR-004: SQLite for Simplicity (Updated 2026-01-04)
- **Decision**: Use SQLite instead of PostgreSQL
- **Rationale**: Zero external dependencies, auto-creates on first run, simpler deployment

---

## Template Reference

Use the MCP server template at:
```
~/ClaudeCode/Servers/mcp-server-template/development/
```

### Key Template Components to Use

| Component | Template Location | Purpose |
|-----------|-------------------|---------|
| Lean MCP Interface | `src/lean/interface.py` | Meta-tool pattern (3 tools) |
| Ports Pattern | `src/core/ports.py` | Hexagonal architecture contracts |
| Token Limiter | `src/lean/token_limiter.py` | Response size management |
| Base Container | `src/core/base_container.py` | Dependency injection |
| HTTP Transport | `templates/jinja2/src/transport/` | FastAPI-based HTTP server |

### Template Configuration

When generating, use these settings:

```yaml
server_name: knowledge-bridge
version: "0.1.0"
description: "Orchestration layer between session-intelligence and knowledge-store for cross-session knowledge sharing"
domain: knowledge
complexity: comprehensive

# HTTP Transport (REQUIRED for this server)
enable_http_transport: true
http_port: 4003
http_enable_sse: true  # For webhook notifications
http_enable_rest_api: true  # For debugging endpoints
http_security_localhost_only: true
http_security_api_key: false  # Internal server-to-server

# Features
enable_cli_wrapper: true
enable_command_execution: false  # No shell commands needed
```

---

## Functional Requirements

### FR-1: Promotion Flow (session-intelligence → knowledge-store)

Tools that move learnings from sessions to global knowledge.

#### FR-1.1: promote_learning
```python
promote_learning(
    source: Literal["session-intelligence", "direct"],
    learning_id: str | None = None,      # If from session-intelligence
    content: dict | None = None,          # If direct contribution
    promotion_type: Literal["immediate", "staged"] = "staged"
) -> PromotionResult
```

**Behavior**:
- `source="session-intelligence"`: Fetch learning by ID from session-intelligence API
- `source="direct"`: Use provided content (user/LLM direct contribution)
- `promotion_type="immediate"`: High confidence → direct to knowledge-store
- `promotion_type="staged"`: Add to staging queue for curator review

**Response**:
```python
class PromotionResult:
    success: bool
    entry_id: str  # staging_queue ID or knowledge-store entry ID
    status: Literal["promoted", "staged", "rejected"]
    reason: str | None
```

#### FR-1.2: batch_promote
```python
batch_promote(
    session_id: str,
    filter: dict = {}  # e.g., {"min_confidence": 0.8, "categories": ["error_fix"]}
) -> BatchPromotionResult
```

**Behavior**:
- Called on session Stop event (via hook)
- Pulls all learnings from session-intelligence for the session
- Applies filter to select eligible learnings
- Promotes high-confidence immediately, stages others

**Response**:
```python
class BatchPromotionResult:
    total_learnings: int
    promoted_immediately: int
    staged_for_review: int
    rejected: int
    details: list[PromotionResult]
```

#### FR-1.3: get_staging_queue
```python
get_staging_queue(
    status: Literal["pending", "reviewing", "all"] = "pending",
    limit: int = 50
) -> list[StagedEntry]
```

**Response**:
```python
class StagedEntry:
    id: str
    source: str
    source_id: str | None
    content: dict
    status: str
    created_at: datetime
    curator_notes: str | None
```

### FR-2: Retrieval Flow (knowledge-store → sessions)

Tools that fetch relevant knowledge for sessions.

#### FR-2.1: search_for_session
```python
search_for_session(
    session_id: str,
    query: str,
    context: dict = {},  # e.g., {"project_type": "python", "framework": "pytest"}
    limit: int = 5
) -> list[KnowledgeMatch]
```

**Behavior**:
- Searches knowledge-store using query + context for semantic matching
- Logs search to `search_log` table (for gap analysis)
- Returns formatted results suitable for session injection

**Response**:
```python
class KnowledgeMatch:
    knowledge_id: str
    problem_pattern: str
    solution: str
    relevance_score: float
    success_rate: float
    times_applied: int
    tags: list[str]
```

#### FR-2.2: prime_session
```python
prime_session(
    session_id: str,
    project_context: dict  # {"project_type": "python", "tech_stack": ["pytest", "fastapi"]}
) -> PrimingResult
```

**Behavior**:
- Called on session start
- Proactively fetches relevant knowledge based on project context
- Returns top patterns/solutions without explicit query

**Response**:
```python
class PrimingResult:
    session_id: str
    patterns_loaded: int
    top_patterns: list[KnowledgeMatch]
    project_type_detected: str
```

### FR-3: Feedback Loop

Tools that track solution effectiveness.

#### FR-3.1: report_outcome
```python
report_outcome(
    session_id: str,
    knowledge_id: str,  # knowledge-store entry that was applied
    outcome: Literal["success", "failure", "partial"],
    notes: str = ""
) -> None
```

**Behavior**:
- Records feedback in `feedback` table
- Emits `outcome.reported` webhook for curator
- Updates running success/failure counts

### FR-4: Webhook Management

Tools for event subscription management.

#### FR-4.1: register_webhook
```python
register_webhook(
    subscriber: str,  # e.g., "curator", "dashboard"
    events: list[str],  # e.g., ["learning.staged", "outcome.reported"]
    endpoint: str  # HTTP endpoint to call
) -> WebhookRegistration
```

#### FR-4.2: unregister_webhook
```python
unregister_webhook(webhook_id: str) -> bool
```

#### FR-4.3: list_webhooks
```python
list_webhooks() -> list[WebhookRegistration]
```

### FR-5: Inter-Server Communication

Tools for querying other servers.

#### FR-5.1: request_session_data
```python
request_session_data(
    session_id: str,
    data_types: list[str] = ["learnings", "decisions", "notes"]
) -> SessionData
```

**Behavior**:
- Makes HTTP request to session-intelligence (4002)
- Fetches specified data types for session

#### FR-5.2: request_knowledge_store_update
```python
request_knowledge_store_update(
    entry_id: str,
    updates: dict  # e.g., {"success_count": 5, "superseded_by": "entry_xyz"}
) -> UpdateResult
```

**Behavior**:
- Makes HTTP request to knowledge-store (4004)
- Updates entry with provided fields

---

## Non-Functional Requirements

### NFR-1: Performance
- Tool response time: < 200ms for local operations
- knowledge-store search: < 500ms including network
- Webhook delivery: < 100ms to emit

### NFR-2: Reliability
- Webhook retry: 3 attempts with exponential backoff
- Event log retention: 7 days for replay capability
- Database: SQLite with WAL mode for concurrency

### NFR-3: Observability
- All operations logged with session correlation
- Webhook delivery tracked with success/failure counts
- Health endpoint exposes connection status to session-intelligence and knowledge-store

---

## Database Schema

```sql
-- SQLite database: knowledge_bridge.db

-- Staging area for learnings awaiting promotion
CREATE TABLE staging_queue (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,           -- 'session-intelligence' | 'direct'
    source_id TEXT,                 -- Original learning ID if from session
    content JSON NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'pending',  -- 'pending' | 'reviewing' | 'promoted' | 'rejected'
    curator_notes TEXT,
    promoted_to TEXT                -- knowledge-store entry ID if promoted
);

-- Webhook subscriptions
CREATE TABLE webhooks (
    id TEXT PRIMARY KEY,
    subscriber TEXT NOT NULL,
    events JSON NOT NULL,           -- List of event types
    endpoint TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_called TIMESTAMP,
    failure_count INTEGER DEFAULT 0,
    active INTEGER DEFAULT 1
);

-- Event log for debugging and replay
CREATE TABLE event_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    payload JSON NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    delivered_to JSON              -- List of webhook IDs that received it
);

-- Feedback tracking
CREATE TABLE feedback (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    knowledge_id TEXT NOT NULL,     -- knowledge-store entry ID
    outcome TEXT NOT NULL,          -- 'success' | 'failure' | 'partial'
    notes TEXT,
    reported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Search log for analytics and gap analysis
CREATE TABLE search_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    query TEXT NOT NULL,
    context JSON,
    results_count INTEGER,
    top_result_id TEXT,
    searched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX idx_staging_status ON staging_queue(status);
CREATE INDEX idx_staging_created ON staging_queue(created_at);
CREATE INDEX idx_feedback_session ON feedback(session_id);
CREATE INDEX idx_feedback_knowledge ON feedback(knowledge_id);
CREATE INDEX idx_search_session ON search_log(session_id);
CREATE INDEX idx_event_type ON event_log(event_type);
CREATE INDEX idx_webhooks_active ON webhooks(active);
```

---

## Event Types

```python
# Events emitted by knowledge-bridge
BRIDGE_EVENTS = {
    # Promotion events
    "learning.staged": "New learning added to staging queue",
    "learning.promoted": "Learning promoted to knowledge-store",
    "learning.rejected": "Learning rejected from promotion",

    # Retrieval events
    "knowledge.searched": "Session searched for knowledge",
    "knowledge.applied": "Session received knowledge injection",

    # Feedback events
    "outcome.reported": "Solution outcome reported",
    "quality.updated": "Entry quality score changed",

    # Curation events (for curator daemon)
    "curation.requested": "Entry flagged for curator review",
    "curation.completed": "Curator finished processing entry",

    # Health events
    "bridge.health": "Periodic health check",
    "queue.backlog": "Staging queue exceeds threshold (>100 pending)",
}
```

---

## Project Structure

```
~/ClaudeCode/Servers/knowledge-bridge/development/
├── .claude/
│   ├── CLAUDE.md                  # Project-specific instructions
│   └── commands/                  # Linked from template
├── src/
│   └── knowledge_bridge/
│       ├── __init__.py
│       ├── __main__.py            # Entry point
│       ├── core/
│       │   ├── __init__.py
│       │   ├── container.py       # DI container
│       │   ├── service.py         # Domain service
│       │   ├── models.py          # Pydantic models
│       │   └── ports.py           # Port interfaces
│       ├── adapters/
│       │   ├── __init__.py
│       │   ├── database.py        # SQLite adapter
│       │   ├── session_intel_client.py  # Client for 4002
│       │   └── knowledge_store_client.py  # Client for 4004
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── promotion.py       # promote_learning, batch_promote
│       │   ├── retrieval.py       # search_for_session, prime_session
│       │   ├── feedback.py        # report_outcome
│       │   └── webhooks.py        # webhook management
│       ├── webhooks/
│       │   ├── __init__.py
│       │   ├── emitter.py         # Webhook emission logic
│       │   └── events.py          # Event definitions
│       ├── transport/
│       │   ├── __init__.py
│       │   ├── http_server.py     # FastAPI HTTP server
│       │   ├── security.py        # Security middleware
│       │   └── mcp_session_manager.py
│       └── lean/
│           ├── __init__.py
│           └── interface.py       # Lean MCP interface
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_promotion.py
│   ├── test_retrieval.py
│   ├── test_feedback.py
│   └── test_webhooks.py
├── pyproject.toml
├── pixi.lock
├── PRD.md                         # This file
└── knowledge_bridge.db            # SQLite (runtime, gitignored)
```

---

## Implementation Phases

### Phase 1: Foundation (Priority: P0) ✅ COMPLETE
- [x] Generate server skeleton from template
- [x] Implement database adapter with schema (SQLite)
- [x] Implement basic container and service
- [x] Add HTTP transport with health endpoint
- [x] Verify startup with `pixi run http-server`

### Phase 2: Promotion Flow (Priority: P0) ✅ COMPLETE
- [x] Implement `promote_learning` tool
- [x] Implement `batch_promote` tool
- [x] Implement `get_staging_queue` tool
- [x] Add session-intelligence client adapter
- [x] Emit `learning.staged` and `learning.promoted` events

### Phase 3: Retrieval Flow (Priority: P0) ✅ COMPLETE
- [x] Implement `search_for_session` tool
- [x] Implement `prime_session` tool
- [x] Add knowledge-store client adapter
- [x] Implement search logging

### Phase 4: Feedback Loop (Priority: P1) ✅ COMPLETE
- [x] Implement `report_outcome` tool
- [x] Emit `outcome.reported` events
- [x] Add feedback aggregation queries

### Phase 5: Webhook System (Priority: P1) ✅ COMPLETE
- [x] Implement webhook registration tools
- [x] Implement webhook emitter with retry logic
- [x] Add event log for replay capability
- [x] Implement webhook health tracking

### Phase 6: Testing & Polish (Priority: P2) ✅ COMPLETE
- [x] Unit tests for all tools (51 tests passing)
- [x] Integration tests with mock session-intelligence
- [x] Integration tests with mock knowledge-store
- [x] Documentation and examples

---

## Testing Strategy

### Unit Tests
- Each tool function independently testable
- Mock database adapter for isolated tests
- Mock HTTP clients for external services

### Integration Tests
- Test with real SQLite database
- Mock HTTP servers for session-intelligence and knowledge-store
- Verify webhook emission

### Contract Tests
- Verify compatibility with session-intelligence API
- Verify compatibility with knowledge-store API

---

## Configuration

### Environment Variables
```bash
KNOWLEDGE_BRIDGE_PORT=4003
KNOWLEDGE_BRIDGE_DB_PATH=~/.claude/knowledge-bridge/knowledge_bridge.db
SESSION_INTELLIGENCE_URL=http://localhost:4002
KNOWLEDGE_STORE_URL=http://localhost:4004
LOG_LEVEL=INFO
```

### Pixi Tasks
```toml
[tool.pixi.tasks]
# Standard development
test = "pytest tests/ -v"
lint = "ruff check src/"
format = "ruff format src/"

# HTTP Server
http-server = "python -m knowledge_bridge.transport.http_server"
http-server-dev = "python -m knowledge_bridge.transport.http_server --log-level DEBUG"

# Database
db-init = "python -c 'from knowledge_bridge.adapters.database import init_db; init_db()'"
db-reset = "rm -f knowledge_bridge.db && pixi run db-init"
```

---

## Success Criteria

1. **All 10 tools functional** via lean MCP interface ✅
2. **HTTP transport working** on port 4003 ✅
3. **Webhook emission working** with retry logic ✅
4. **Clients for session-intelligence and knowledge-store** functional ✅
5. **Test coverage >80%** ✅ (51 tests)
6. **Health endpoint** reports connectivity to dependent services ✅

---

## Design Document Reference

Full architectural details available at:
```
~/ClaudeCode/design-docs/knowledge-bridge-proposal.md
```

---

## Agent Priming Instructions

When starting implementation in a new session:

```
/0_agent_priming knowledge-bridge MCP server

Context:
- Template: ~/ClaudeCode/Servers/mcp-server-template/development/
- PRD: ~/ClaudeCode/Servers/knowledge-bridge/development/PRD.md
- Design: ~/ClaudeCode/design-docs/knowledge-bridge-proposal.md
- Port: 4003 (HTTP transport required)

Start with Phase 1: Foundation
```

The session should:
1. Read this PRD completely
2. Read the design document for context
3. Use template patterns from mcp-server-template
4. Follow the phased implementation approach
5. Commit after each phase completion
