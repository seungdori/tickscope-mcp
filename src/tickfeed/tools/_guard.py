"""Structured-error guard for tool handlers.

Wraps a coroutine so any exception (ccxt or otherwise) is converted into the
standard ``{"error": {...}}`` envelope instead of leaking a stack trace.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypeVar

from ..utils import error_payload

T = TypeVar("T")


def guard(
    *, exchange_arg: str = "exchange", symbol_arg: str = "symbol"
) -> Callable[[Callable[..., Awaitable[dict[str, Any]]]], Callable[..., Awaitable[dict[str, Any]]]]:
    """Decorator returning a structured error payload on any failure."""

    def decorator(
        fn: Callable[..., Awaitable[dict[str, Any]]],
    ) -> Callable[..., Awaitable[dict[str, Any]]]:
        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            try:
                return await fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - convert to structured error
                return error_payload(
                    exc,
                    exchange=kwargs.get(exchange_arg),
                    symbol=kwargs.get(symbol_arg),
                )

        return wrapper

    return decorator
