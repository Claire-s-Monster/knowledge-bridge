#!/usr/bin/env bash
#
# Daemon management for knowledge-bridge HTTP server.
#
# Usage:
#   ./knowledge-bridge-daemon.sh start [options]
#   ./knowledge-bridge-daemon.sh stop
#   ./knowledge-bridge-daemon.sh status
#   ./knowledge-bridge-daemon.sh restart [options]
#
# Options:
#   --port PORT           Port to bind to (default: 4003)
#   --dsn DSN             PostgreSQL connection string
#   --session-intel URL   Session-intelligence server URL
#   --uckn URL            UCKN server URL
#
# Environment Variables:
#   KNOWLEDGE_BRIDGE_PORT         Server port
#   KNOWLEDGE_BRIDGE_DB_DSN       PostgreSQL connection string
#   SESSION_INTELLIGENCE_URL      Session-intelligence URL (default: http://127.0.0.1:4002)
#   UCKN_URL                      UCKN server URL (default: http://127.0.0.1:4004)
#
# The server runs as a background daemon, providing the orchestration layer
# between session-intelligence and UCKN for cross-session knowledge sharing.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Global state directory (cross-project)
STATE_DIR="${HOME}/.claude/knowledge-bridge"
PID_FILE="${STATE_DIR}/server.pid"
LOG_FILE="${STATE_DIR}/server.log"
DEFAULT_PORT=4003

# Ensure state directory exists
mkdir -p "$STATE_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

is_running() {
    if [ -f "$PID_FILE" ]; then
        local pid
        pid=$(cat "$PID_FILE")
        if ps -p "$pid" > /dev/null 2>&1; then
            return 0
        fi
    fi
    return 1
}

get_pid() {
    if [ -f "$PID_FILE" ]; then
        cat "$PID_FILE"
    else
        echo ""
    fi
}

start_server() {
    local port="${1:-$DEFAULT_PORT}"
    local dsn="${2:-}"
    local session_intel_url="${3:-}"
    local uckn_url="${4:-}"

    # Check if already running
    if is_running; then
        local pid
        pid=$(get_pid)
        log "Server already running with PID $pid"
        exit 1
    fi

    # Clean up stale PID file
    if [ -f "$PID_FILE" ]; then
        rm -f "$PID_FILE"
    fi

    # Build command
    local cmd="pixi run http-server --port $port"

    if [ -n "$dsn" ]; then
        cmd="$cmd --db-dsn $dsn"
    fi

    if [ -n "$session_intel_url" ]; then
        cmd="$cmd --session-intel-url $session_intel_url"
    fi

    if [ -n "$uckn_url" ]; then
        cmd="$cmd --uckn-url $uckn_url"
    fi

    # Get values for logging
    local display_dsn="${dsn:-${KNOWLEDGE_BRIDGE_DB_DSN:-postgresql://localhost/knowledge_bridge}}"
    local display_session="${session_intel_url:-${SESSION_INTELLIGENCE_URL:-http://127.0.0.1:4002}}"
    local display_uckn="${uckn_url:-${UCKN_URL:-http://127.0.0.1:4004}}"

    log "Starting knowledge-bridge HTTP server..."
    log "  Port: $port"
    log "  Database: ${display_dsn##*@}"  # Hide credentials
    log "  Session-Intelligence: $display_session"
    log "  UCKN: $display_uckn"

    # Start server in background
    cd "$PROJECT_DIR"
    nohup $cmd >> "$LOG_FILE" 2>&1 &
    local pid=$!

    echo "$pid" > "$PID_FILE"

    # Wait briefly for startup
    sleep 2

    # Verify it's running
    if is_running; then
        log "Server started successfully (PID: $pid)"
        log "Log file: $LOG_FILE"
        log ""
        log "Endpoints:"
        log "  POST http://127.0.0.1:$port/mcp/discover_tools"
        log "  POST http://127.0.0.1:$port/mcp/get_tool_spec"
        log "  POST http://127.0.0.1:$port/mcp/execute_tool"
        log "  GET  http://127.0.0.1:$port/health"
        log "  GET  http://127.0.0.1:$port/api/statistics"
    else
        log "ERROR: Server failed to start. Check log file: $LOG_FILE"
        rm -f "$PID_FILE"
        exit 1
    fi
}

stop_server() {
    if ! is_running; then
        log "Server not running"
        rm -f "$PID_FILE"
        exit 0
    fi

    local pid
    pid=$(get_pid)

    log "Stopping server (PID: $pid)..."

    # Graceful shutdown
    kill "$pid" 2>/dev/null || true

    # Wait for graceful shutdown (up to 10 seconds)
    local count=0
    while is_running && [ $count -lt 10 ]; do
        sleep 1
        count=$((count + 1))
    done

    # Force kill if still running
    if is_running; then
        log "Force killing..."
        kill -9 "$pid" 2>/dev/null || true
        sleep 1
    fi

    rm -f "$PID_FILE"
    log "Server stopped"
}

status_server() {
    if ! is_running; then
        log "Server not running"
        if [ -f "$PID_FILE" ]; then
            log "(Stale PID file found, cleaning up)"
            rm -f "$PID_FILE"
        fi
        exit 1
    fi

    local pid
    pid=$(get_pid)

    log "Server running (PID: $pid)"

    # Try health check
    local health_url="http://127.0.0.1:$DEFAULT_PORT/health"
    if command -v curl > /dev/null 2>&1; then
        if curl -s "$health_url" > /dev/null 2>&1; then
            log "Health check: OK"
            curl -s "$health_url" | python3 -m json.tool 2>/dev/null || true
        else
            log "Health check: FAILED (server may be starting up)"
        fi
    else
        log "Health check: curl not available"
    fi

    log ""
    log "Log file: $LOG_FILE"
    log "Recent log entries:"
    tail -5 "$LOG_FILE" 2>/dev/null || echo "  (no log entries)"
}

restart_server() {
    log "Restarting server..."
    stop_server
    sleep 1
    start_server "$@"
}

show_logs() {
    local lines="${1:-50}"
    if [ -f "$LOG_FILE" ]; then
        tail -"$lines" "$LOG_FILE"
    else
        log "No log file found"
    fi
}

# Parse arguments
PORT="$DEFAULT_PORT"
DSN=""
SESSION_INTEL_URL=""
UCKN_URL=""
LINES="50"
ACTION=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        start|stop|status|restart|logs)
            ACTION="$1"
            shift
            ;;
        --port)
            PORT="$2"
            shift 2
            ;;
        --dsn|--db-dsn)
            DSN="$2"
            shift 2
            ;;
        --session-intel|--session-intel-url)
            SESSION_INTEL_URL="$2"
            shift 2
            ;;
        --uckn|--uckn-url)
            UCKN_URL="$2"
            shift 2
            ;;
        --lines)
            LINES="$2"
            shift 2
            ;;
        -h|--help)
            cat << 'EOF'
Usage: knowledge-bridge-daemon.sh {start|stop|restart|status|logs} [options]

Commands:
  start     Start the HTTP server as a daemon
  stop      Stop the running server
  restart   Restart the server
  status    Check server status and health
  logs      Show recent log entries

Options:
  --port PORT                Port to bind to (default: 4003)
  --dsn DSN                  PostgreSQL connection string
  --session-intel URL        Session-intelligence server URL (default: http://127.0.0.1:4002)
  --uckn URL                 UCKN server URL (default: http://127.0.0.1:4004)
  --lines N                  Number of log lines to show (default: 50)

Environment Variables:
  KNOWLEDGE_BRIDGE_PORT      Server port
  KNOWLEDGE_BRIDGE_DB_DSN    PostgreSQL connection string
  SESSION_INTELLIGENCE_URL   Session-intelligence server URL
  UCKN_URL                   UCKN server URL

Examples:
  # Start with defaults
  ./knowledge-bridge-daemon.sh start

  # Start with custom DSN
  ./knowledge-bridge-daemon.sh start --dsn "postgresql://user:pass@localhost/kb"

  # Start with all options
  ./knowledge-bridge-daemon.sh start --port 4003 --dsn "postgresql://..." --session-intel http://localhost:4002

  # Check status
  ./knowledge-bridge-daemon.sh status

  # View logs
  ./knowledge-bridge-daemon.sh logs --lines 100
EOF
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Execute action
case "${ACTION:-}" in
    start)
        start_server "$PORT" "$DSN" "$SESSION_INTEL_URL" "$UCKN_URL"
        ;;
    stop)
        stop_server
        ;;
    restart)
        restart_server "$PORT" "$DSN" "$SESSION_INTEL_URL" "$UCKN_URL"
        ;;
    status)
        status_server
        ;;
    logs)
        show_logs "$LINES"
        ;;
    "")
        echo "Usage: $0 {start|stop|restart|status|logs} [options]"
        echo "Use --help for more information"
        exit 1
        ;;
    *)
        echo "Unknown command: $ACTION"
        exit 1
        ;;
esac
