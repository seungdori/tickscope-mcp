"""Process-wide service singleton.

The background WebSocket ingestion must outlive individual MCP sessions, so the
:class:`MarketDataService` is held here as a module singleton rather than in the
per-session FastMCP lifespan context (lifespan runs per connection over HTTP).
"""

from __future__ import annotations

from .config import get_settings
from .core.service import MarketDataService

_service: MarketDataService | None = None


def get_service() -> MarketDataService:
    """Return the lazily-created service singleton."""
    global _service
    if _service is None:
        _service = MarketDataService(get_settings())
    return _service


async def shutdown_service() -> None:
    """Tear down the singleton (close exchanges, stop watch tasks)."""
    global _service
    if _service is not None:
        await _service.aclose()
        _service = None
