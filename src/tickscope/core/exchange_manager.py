"""Create, cache and close ccxt exchange instances.

A single instance per exchange is reused for both REST (``fetch_*``) and
WebSocket (``watch_*``) calls. ``ccxt.pro`` instances extend the async REST
client, so one object covers both transports.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import ccxt
import ccxt.async_support as accxt
import ccxt.pro as ccxtpro

from ..utils import TickscopeError


class ExchangeManager:
    """Lazily build and cache one ccxt instance per exchange id."""

    def __init__(self, allowed: list[str]):
        self._allowed = {e.lower() for e in allowed}
        self._instances: dict[str, Any] = {}
        self._markets_loaded: set[str] = set()
        self._lock = asyncio.Lock()

    @property
    def configured(self) -> list[str]:
        return sorted(self._allowed)

    def _build(self, exchange_id: str) -> Any:
        if exchange_id not in self._allowed:
            raise TickscopeError(
                {
                    "error": {
                        "type": "ExchangeNotConfigured",
                        "message": (
                            f"Exchange '{exchange_id}' is not enabled. "
                            f"Configured: {sorted(self._allowed)}"
                        ),
                        "exchange": exchange_id,
                        "symbol": None,
                        "retryable": False,
                    }
                }
            )
        factory = getattr(ccxtpro, exchange_id, None) or getattr(accxt, exchange_id, None)
        if factory is None:
            raise TickscopeError(
                {
                    "error": {
                        "type": "BadExchange",
                        "message": f"ccxt has no exchange named '{exchange_id}'.",
                        "exchange": exchange_id,
                        "symbol": None,
                        "retryable": False,
                    }
                }
            )
        return factory({"enableRateLimit": True})

    async def get(self, exchange_id: str) -> Any:
        """Return (and lazily create) the cached instance for ``exchange_id``."""
        key = exchange_id.lower()
        async with self._lock:
            inst = self._instances.get(key)
            if inst is None:
                inst = self._build(key)
                self._instances[key] = inst
            return inst

    async def load_markets(self, exchange_id: str, *, reload: bool = False) -> dict[str, Any]:
        """Load and cache the market map for ``exchange_id`` (once per process)."""
        key = exchange_id.lower()
        inst = await self.get(key)
        if reload or key not in self._markets_loaded:
            await inst.load_markets(reload)
            self._markets_loaded.add(key)
        return inst.markets or {}

    async def close(self) -> None:
        """Close all open exchange connections (call on shutdown)."""
        for inst in self._instances.values():
            with contextlib.suppress(Exception):  # best-effort cleanup
                await inst.close()
        self._instances.clear()
        self._markets_loaded.clear()


def ccxt_version() -> str:
    return ccxt.__version__
