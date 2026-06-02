"""Server wiring tests: lifespan teardown policy, disclaimer surfaces."""

from __future__ import annotations

from tickfeed import runtime, server
from tickfeed.utils import DISCLAIMER

# asyncio_mode = "auto" (pyproject) runs async tests automatically; no mark needed.


async def test_stdio_lifespan_tears_down_singleton(monkeypatch):
    calls = {"shutdown": 0}

    async def fake_shutdown() -> None:
        calls["shutdown"] += 1

    monkeypatch.setattr(server, "get_service", lambda: None)
    monkeypatch.setattr(server, "shutdown_service", fake_shutdown)

    lifespan = server._make_lifespan(teardown_on_exit=True)
    async with lifespan(None):  # type: ignore[arg-type]
        pass
    assert calls["shutdown"] == 1


async def test_http_lifespan_keeps_singleton_alive(monkeypatch):
    calls = {"shutdown": 0}

    async def fake_shutdown() -> None:
        calls["shutdown"] += 1

    monkeypatch.setattr(server, "get_service", lambda: None)
    monkeypatch.setattr(server, "shutdown_service", fake_shutdown)

    lifespan = server._make_lifespan(teardown_on_exit=False)
    async with lifespan(None):  # type: ignore[arg-type]
        pass
    # Per-connection HTTP lifespan must NOT tear down the process-wide singleton.
    assert calls["shutdown"] == 0


def test_disclaimer_constant_is_not_advice():
    assert "not financial" in DISCLAIMER.lower()
    assert runtime is not None
