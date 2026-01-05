#!/usr/bin/env python3
"""HTTP server entry point for knowledge-bridge MCP server.

Usage:
    python src/http_lean_server.py [--port PORT] [--log-level LEVEL]

Environment variables:
    KNOWLEDGE_BRIDGE_PORT: Server port (default: 4003)
    KNOWLEDGE_BRIDGE_DB_PATH: SQLite database path (default: ~/.claude/knowledge-bridge/knowledge_bridge.db)
    SESSION_INTELLIGENCE_URL: Session-intelligence server URL (default: http://127.0.0.1:4002)
    UCKN_URL: UCKN server URL (default: http://127.0.0.1:4004)
    LOG_LEVEL: Logging level (default: INFO)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

import uvicorn

# Add src to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from knowledge_bridge.persistence.base import DEFAULT_SQLITE_PATH
from knowledge_bridge.transport.http_server import create_app

# Default configuration
DEFAULT_PORT = 4003
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_SESSION_INTEL_URL = "http://127.0.0.1:4002"
DEFAULT_UCKN_URL = "http://127.0.0.1:4004"


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="knowledge-bridge MCP server",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("KNOWLEDGE_BRIDGE_PORT", DEFAULT_PORT)),
        help="Server port",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Server host (use 127.0.0.1 for localhost only)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=os.environ.get("LOG_LEVEL", DEFAULT_LOG_LEVEL),
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=os.environ.get("KNOWLEDGE_BRIDGE_DB_PATH"),
        help="SQLite database path (default: ~/.claude/knowledge-bridge/knowledge_bridge.db)",
    )
    parser.add_argument(
        "--session-intel-url",
        type=str,
        default=os.environ.get("SESSION_INTELLIGENCE_URL", DEFAULT_SESSION_INTEL_URL),
        help="Session-intelligence server URL",
    )
    parser.add_argument(
        "--uckn-url",
        type=str,
        default=os.environ.get("UCKN_URL", DEFAULT_UCKN_URL),
        help="UCKN server URL",
    )
    parser.add_argument(
        "--allow-external",
        action="store_true",
        help="Allow connections from external IPs (not recommended)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development",
    )

    return parser.parse_args()


def setup_logging(level: str) -> None:
    """Configure logging.

    Args:
        level: Log level string.
    """
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )

    # Reduce noise from uvicorn access logs
    if level.upper() != "DEBUG":
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def main() -> None:
    """Main entry point."""
    args = parse_args()

    # Setup logging
    setup_logging(args.log_level)
    logger = logging.getLogger(__name__)

    # Log configuration
    db_path_display = args.db_path or str(DEFAULT_SQLITE_PATH)
    logger.info("Starting knowledge-bridge MCP server")
    logger.info(f"  Port: {args.port}")
    logger.info(f"  Host: {args.host}")
    logger.info(f"  Database: {db_path_display}")
    logger.info(f"  Session-intelligence: {args.session_intel_url}")
    logger.info(f"  UCKN: {args.uckn_url}")
    logger.info(f"  Log level: {args.log_level}")
    logger.info(f"  Localhost only: {not args.allow_external}")

    # Create app
    app = create_app(
        db_path=args.db_path,
        session_intel_url=args.session_intel_url,
        uckn_url=args.uckn_url,
        localhost_only=not args.allow_external,
    )

    # Run server
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=args.log_level.lower(),
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
