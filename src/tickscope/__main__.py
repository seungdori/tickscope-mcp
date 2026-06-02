"""Console entrypoint: ``tickscope`` / ``uvx tickscope-mcp``."""

from __future__ import annotations

from .config import get_settings
from .server import build_server


def main() -> None:
    """Run the Tickscope MCP server using the configured transport."""
    try:
        import uvloop

        uvloop.install()
    except Exception:  # noqa: BLE001 - uvloop is an optional speedup
        pass

    settings = get_settings()
    mcp = build_server()

    if settings.transport == "http":
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
