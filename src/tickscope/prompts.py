"""MCP prompts — user-invoked, guided analysis workflows.

Prompts are the *user-controlled* MCP primitive (tools are model-controlled,
resources are addressable data). In clients like Claude Code they surface as
slash commands (e.g. ``/mcp__tickscope__deep_analyze``), letting a user
explicitly trigger a heavier, structured analysis instead of relying on the
agent to infer which tools to chain.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    @mcp.prompt(
        name="deep_analyze",
        description="Guided deep multi-timeframe analysis of a crypto symbol.",
    )
    def deep_analyze(symbol: str, timeframe: str = "4h") -> str:
        """Drive a full, evidence-backed read of ``symbol`` via the deep_analyze tool."""
        return (
            f"Use the Tickscope `deep_analyze` tool on {symbol} with the execution "
            f"timeframe {timeframe} (let it read its default higher-timeframe ladder "
            "for context). Then give a concise read:\n"
            "1. Multi-timeframe trend alignment — do the timeframes agree or conflict?\n"
            "2. The execution-timeframe market state (trending vs ranging, volatility) "
            "and what it implies for how much to trust momentum signals.\n"
            "3. Any divergences, plus the historical forward-return stats of that "
            "signal on this symbol/timeframe (sample size, win rate, median).\n"
            "4. A clear bias with its confidence and the explicit caveats.\n"
            "Base every claim on the tool output, cite the numbers (including the "
            "source/age_ms freshness), and state plainly that this is not financial advice."
        )
