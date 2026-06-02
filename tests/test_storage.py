"""DuckDB OHLCV store: persistence and graceful lock fallback."""

from __future__ import annotations

import duckdb

from tickscope.core.storage import OHLCVStore


def test_store_is_persistent_when_file_is_free(tmp_path):
    store = OHLCVStore(tmp_path / "free.duckdb")
    try:
        assert store.persistent is True
        store.upsert("binance", "BTC/USDT", "1h", [[1000, 1.0, 2.0, 0.5, 1.5, 10.0]])
        assert store.row_count() == 1
    finally:
        store.close()


def test_store_falls_back_to_memory_when_locked(tmp_path, monkeypatch):
    # DuckDB's write lock is cross-process; simulate "file locked" by making the
    # file connection raise (a real second OS process would hit this), while the
    # in-memory fallback still succeeds.
    real_connect = duckdb.connect
    lock_error = getattr(duckdb, "IOException", duckdb.Error)

    def fake_connect(target, *args, **kwargs):
        if target != ":memory:":
            raise lock_error("Conflicting lock is held")
        return real_connect(":memory:")

    monkeypatch.setattr(duckdb, "connect", fake_connect)
    store = OHLCVStore(tmp_path / "locked.duckdb")  # must not raise
    try:
        assert store.persistent is False  # fell back to in-memory
        store.upsert("binance", "ETH/USDT", "1h", [[2000, 1.0, 2.0, 0.5, 1.5, 9.0]])
        assert store.row_count() == 1  # in-memory cache still works
    finally:
        store.close()
