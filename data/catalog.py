# data/catalog.py
"""数据目录（★2.09 / DATA-PLATFORM P3-1）。

SQLite（stdlib）只存元数据，不存行情：
  datasets(dataset, spec, schema_version, updated_at)
  assets(dataset, symbol, market, asset_type, last_date, rows, source, adjust,
         schema_version, updated_at)

设计边界：
- 首次 `scan_inventory()` 从 parquet footer 扫描，之后由写入方 `record()` 增量更新；
- 不在读路径里全目录 stat；不替代 `MarketDataStore` 的行情读取；
- 坏文件/空文件不阻断整次扫描。
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict

from config import settings
from data.contracts import DATASETS, DatasetSpec, spec_for

logger = logging.getLogger(__name__)

__all__ = ["Catalog", "default_path"]


def default_path() -> str:
    return os.path.join(settings.USER_DATA_DIR, "data_lake", "catalog.sqlite")


class Catalog:
    def __init__(self, path: str = None):
        self.path = path or default_path()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._ensure()

    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _db(self):
        """连接必须显式 close；Windows 上未关闭的 WAL 文件会锁住临时目录。"""
        conn = self._conn()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _ensure(self):
        with self._db() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("""
                CREATE TABLE IF NOT EXISTS datasets (
                    dataset TEXT PRIMARY KEY,
                    spec_json TEXT NOT NULL,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    updated_at REAL NOT NULL
                )""")
            c.execute("""
                CREATE TABLE IF NOT EXISTS assets (
                    dataset TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    market TEXT NOT NULL DEFAULT 'CN',
                    asset_type TEXT NOT NULL DEFAULT 'stock',
                    last_date TEXT,
                    rows INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT '',
                    adjust TEXT NOT NULL DEFAULT 'raw',
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (dataset, symbol)
                )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_assets_dataset_date "
                      "ON assets(dataset, last_date)")

    def register_specs(self) -> None:
        now = time.time()
        with self._db() as c:
            for spec in DATASETS.values():
                c.execute(
                    "INSERT OR REPLACE INTO datasets(dataset, spec_json, schema_version, updated_at) "
                    "VALUES (?, ?, ?, ?)",
                    (spec.name, json.dumps(asdict(spec), ensure_ascii=False),
                     int(spec.schema_version), now))

    def record_many(self, dataset: str, assets: list, *, source: str = "",
                    adjust: str = None, market: str = "CN",
                    asset_type: str = "stock") -> int:
        """批量写入标的元数据（单事务）；`assets` = [(symbol, last_date, rows)]。"""
        spec = spec_for(dataset)
        now = time.time()
        values = []
        for sym, last_date, rows in assets or []:
            date = str(last_date or "").strip()[:10] or None
            values.append((str(dataset), str(sym).strip(), market, asset_type,
                           date, int(rows or 0), str(source or ""),
                           adjust or spec.adjust, int(spec.schema_version), now))
        if not values:
            return 0
        with self._db() as c:
            c.executemany("""
                INSERT INTO assets(dataset, symbol, market, asset_type, last_date,
                                   rows, source, adjust, schema_version, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dataset, symbol) DO UPDATE SET
                    market=excluded.market, asset_type=excluded.asset_type,
                    last_date=excluded.last_date, rows=excluded.rows,
                    source=excluded.source, adjust=excluded.adjust,
                    schema_version=excluded.schema_version, updated_at=excluded.updated_at
                """, values)
        return len(values)

    def record(self, dataset: str, symbol: str, *, last_date: str = None,
               rows: int = 0, source: str = "", adjust: str = None,
               market: str = "CN", asset_type: str = "stock") -> None:
        """写入/更新一个标的元数据；rows 与 last_date 由调用方给。"""
        self.record_many(dataset, [(symbol, last_date, rows)], source=source,
                         adjust=adjust, market=market, asset_type=asset_type)

    def get(self, dataset: str, symbol: str) -> dict | None:
        with self._db() as c:
            row = c.execute(
                "SELECT * FROM assets WHERE dataset=? AND symbol=?",
                (str(dataset), str(symbol))).fetchone()
        return dict(row) if row else None

    def assets(self, dataset: str) -> list[dict]:
        """dataset 下全部标的元数据（供 planner 一次取齐，避免逐只查库）。"""
        with self._db() as c:
            rows = c.execute(
                "SELECT * FROM assets WHERE dataset=? ORDER BY symbol",
                (str(dataset),)).fetchall()
        return [dict(r) for r in rows]

    def asset_map(self, dataset: str) -> dict[str, dict]:
        return {str(r["symbol"]): r for r in self.assets(dataset)}

    def summary(self, dataset: str) -> dict:
        with self._db() as c:
            row = c.execute("""
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN last_date IS NOT NULL THEN 1 ELSE 0 END) AS covered,
                       COALESCE(SUM(rows), 0) AS rows,
                       MAX(last_date) AS last_date
                FROM assets WHERE dataset=?""", (str(dataset),)).fetchone()
            sources = [r[0] for r in c.execute(
                "SELECT DISTINCT source FROM assets WHERE dataset=? AND source<>''",
                (str(dataset),)).fetchall()]
        return {"dataset": str(dataset), "total": int(row["total"] or 0),
                "covered": int(row["covered"] or 0),
                "rows": int(row["rows"] or 0),
                "last_date": row["last_date"] or "",
                "sources": sources}

    def scan_inventory(self, lake, zone: str, dataset: str, *,
                       source: str = "lake", limit: int = 0) -> int:
        """从数据湖 footer 扫描已有文件，写入 catalog；返回扫描条数。

        只读；坏文件跳过。`limit` 仅用于测试/分批，0=全量。
        """
        spec = spec_for(dataset)
        items = lake.inventory(zone, with_dates=True)
        if limit:
            items = items[:int(limit)]
        values = []
        for item in items:
            sym = str(item.get("name") or "").strip()
            if not sym:
                continue
            values.append((sym, item.get("last_date"),
                           int(item.get("rows") or 0)))
        return self.record_many(dataset, values, source=source,
                                adjust=spec.adjust, market=spec.market,
                                asset_type=spec.asset_type)

    def upsert_spec(self, spec: DatasetSpec) -> None:
        with self._db() as c:
            c.execute(
                "INSERT OR REPLACE INTO datasets(dataset, spec_json, schema_version, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (spec.name, json.dumps(asdict(spec), ensure_ascii=False),
                 int(spec.schema_version), time.time()))
