"""Security middleware for knowledge-bridge HTTP transport.

Restricts access to localhost only for internal MCP server.
"""

from __future__ import annotations

import logging
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Allowed localhost addresses
LOCALHOST_ADDRESSES = {
    "127.0.0.1",
    "::1",
    "localhost",
}


class LocalhostOnlyMiddleware(BaseHTTPMiddleware):
    """Middleware that restricts access to localhost only.

    This is essential for MCP servers that should only accept
    connections from the local machine.
    """

    def __init__(
        self,
        app: Callable,
        allow_health_check: bool = True,
    ) -> None:
        """Initialize middleware.

        Args:
            app: FastAPI/Starlette app.
            allow_health_check: Whether to allow health checks from any IP.
        """
        super().__init__(app)
        self.allow_health_check = allow_health_check

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Response],
    ) -> Response:
        """Process request and check if from localhost.

        Args:
            request: Incoming request.
            call_next: Next middleware/handler.

        Returns:
            Response.
        """
        # Get client host
        client_host = request.client.host if request.client else None

        # Allow health check from any IP if configured
        if self.allow_health_check and request.url.path == "/health":
            return await call_next(request)

        # Check if localhost
        if client_host not in LOCALHOST_ADDRESSES:
            logger.warning(
                f"Blocked non-localhost request from {client_host} to {request.url.path}"
            )
            return JSONResponse(
                status_code=403,
                content={
                    "error": "Access denied",
                    "detail": "This server only accepts connections from localhost",
                },
            )

        return await call_next(request)


def get_client_ip(request: Request) -> str:
    """Get client IP address from request.

    Args:
        request: FastAPI request.

    Returns:
        Client IP address.
    """
    # Check X-Forwarded-For header first (if behind proxy)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    # Fall back to direct client
    return request.client.host if request.client else "unknown"


def is_localhost(ip: str) -> bool:
    """Check if IP is localhost.

    Args:
        ip: IP address to check.

    Returns:
        True if localhost.
    """
    return ip in LOCALHOST_ADDRESSES
