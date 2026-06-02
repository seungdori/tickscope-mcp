"""DuckDB-backed persistent cache for historical OHLCV candles.

A single table keyed by ``(exchange, symbol, timeframe, ts)`` lets repeated
range requests hit the cache and avoid redundant exchange calls / rate limits.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb


class OHLCVStore:
    """Thin wrapper around a DuckDB file holding cached candles."""

    def __init__(self, path: Path):
        self._conn = duckdb.connect(str(path))
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ohlcv (
                exchange  VARCHAR NOT NULL,
                symbol    VARCHAR NOT NULL,
                timeframe VARCHAR NOT NULL,
                ts        BIGINT  NOT NULL,
                open      DOUBLE,
                high      DOUBLE,
                low       DOUBLE,
                close     DOUBLE,
                volume    DOUBLE,
                PRIMARY KEY (exchange, symbol, timeframe, ts)
            )
            """
        )

    def upsert(self, exchange: str, symbol: str, timeframe: str, rows: list[list[float]]) -> None:
        """Insert or replace candle rows (``[ts, o, h, l, c, v]``)."""
        if not rows:
            return
        payload = [
            (exchange.lower(), symbol.upper(), timeframe, int(r[0]), r[1], r[2], r[3], r[4], r[5])
            for r in rows
        ]
        self._conn.executemany(
            """
            INSERT OR REPLACE INTO ohlcv
                (exchange, symbol, timeframe, ts, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )

    def query(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        *,
        since_ms: int | None = None,
        limit: int = 200,
    ) -> list[list[float]]:
        """Return up to ``limit`` most-recent candles (ascending ts)."""
        params: list[Any] = [exchange.lower(), symbol.upper(), timeframe]
        where = "exchange = ? AND symbol = ? AND timeframe = ?"
        if since_ms is not None:
            where += " AND ts >= ?"
            params.append(since_ms)
        params.append(limit)
        result = self._conn.execute(
            f"""
            SELECT ts, open, high, low, close, volume FROM (
                SELECT ts, open, high, low, close, volume FROM ohlcv
                WHERE {where}
                ORDER BY ts DESC
                LIMIT ?
            ) ORDER BY ts ASC
            """,
            params,
        ).fetchall()
        return [[row[0], row[1], row[2], row[3], row[4], row[5]] for row in result]

    def latest_ts(self, exchange: str, symbol: str, timeframe: str) -> int | None:
        row = self._conn.execute(
            "SELECT MAX(ts) FROM ohlcv WHERE exchange = ? AND symbol = ? AND timeframe = ?",
            [exchange.lower(), symbol.upper(), timeframe],
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else None

    def row_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM ohlcv").fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        self._conn.close()
