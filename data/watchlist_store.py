# data/watchlist_store.py
"""自选股（Watchlist）—— 用户关心的标的清单，JSON 原子写（§7-B3 P8）。

【为什么单独一份】"我关注哪些票"是**用户资产**，与"行情数据"完全无关：
  · 不放进数据湖（那是行情本身，体积大、可重建）；
  · 不放进花名册 `market_symbols`（那是**全市场**名单，几万条、由 `scripts/sync_roster.py` 覆写）；
  · 单独一个 `~/.jian_data/watchlist.json`，与 `preferences` / `strategy_store` /
    `annotations` / `formula_store` 同款：原子写（tmp + os.replace）、坏数据行只跳过自己。

【为什么存 dict 而不是纯代码列表】顺手存名称，用户看到的是"贵州茅台 600519"而不是"600519"；
  名称在每次载入/命中花名册时会被刷新（不把旧名当真相）。

【零 Qt 依赖】可被未来的复盘页/回测页复用（"我的自选"一键跑回测）。
"""
from __future__ import annotations

import json
import os
import time

from config import settings

WATCHLIST_FILE = "watchlist.json"
SCHEMA_VERSION = 1
MAX_ITEMS = 300          # 防呆：自选股不该是"全市场清单"（那用花名册）


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def normalize_symbol(value) -> str:
    """统一成大写、无空白的代码（`sh600000` / `600519` / `RB2410`）。"""
    return str(value or "").strip().upper()


def make_entry(symbol, name: str = "", added_at: str = "") -> dict:
    """构造一条自选记录（全 app 唯一构造入口）。"""
    symbol = normalize_symbol(symbol)
    if not symbol:
        raise ValueError("标的代码不能为空")
    return {"symbol": symbol, "name": str(name or "").strip(),
            "added_at": str(added_at) or _now()}


class WatchlistStore:
    """自选股仓库。对外只有 add/remove/move/symbols/entries —— 换存储不动调用方。"""

    def __init__(self, path: str = None):
        self.path = path or os.path.join(settings.USER_DATA_DIR, WATCHLIST_FILE)
        self.entries: list[dict] = []
        self.load()

    # ---------------- 持久化 ----------------
    def load(self) -> None:
        self.entries = []
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError) as e:
            print(f"自选股读取失败: {e}")
            return
        raw = payload.get("entries") if isinstance(payload, dict) else payload
        seen = set()
        for item in (raw or []):
            try:
                entry = make_entry(
                    (item or {}).get("symbol") if isinstance(item, dict) else item,
                    (item or {}).get("name", "") if isinstance(item, dict) else "",
                    (item or {}).get("added_at", "") if isinstance(item, dict) else "")
            except (ValueError, TypeError, AttributeError):
                continue
            if entry["symbol"] in seen:        # 坏数据/手工编辑可能造出重复项
                continue
            seen.add(entry["symbol"])
            self.entries.append(entry)

    def save(self) -> bool:
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump({"version": SCHEMA_VERSION, "entries": self.entries},
                          handle, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
            return True
        except OSError as e:
            print(f"自选股写入失败: {e}")
            return False

    # ---------------- 查询 ----------------
    def symbols(self) -> list[str]:
        """按用户排序返回代码（列表顺序 = 用户拖出来的顺序）"""
        return [entry["symbol"] for entry in self.entries]

    def entries_all(self) -> list[dict]:
        return list(self.entries)

    def names_map(self) -> dict:
        return {entry["symbol"]: entry["name"] for entry in self.entries}

    def display_name(self, symbol) -> str:
        symbol = normalize_symbol(symbol)
        for entry in self.entries:
            if entry["symbol"] == symbol:
                return entry["name"] or symbol
        return symbol

    def contains(self, symbol) -> bool:
        return normalize_symbol(symbol) in self.symbols()

    def count(self) -> int:
        return len(self.entries)

    # ---------------- 写入 ----------------
    def add(self, symbol, name: str = "") -> bool:
        """加入自选；已存在则只刷新名称。返回"是否新增"（False = 本来就在）。"""
        entry = make_entry(symbol, name)
        for existing in self.entries:
            if existing["symbol"] == entry["symbol"]:
                if entry["name"] and existing["name"] != entry["name"]:
                    existing["name"] = entry["name"]
                    self.save()
                return False
        if len(self.entries) >= MAX_ITEMS:
            raise ValueError(f"自选股最多 {MAX_ITEMS} 只，请先清理")
        self.entries.append(entry)
        self.save()
        return True

    def remove(self, symbol) -> bool:
        symbol = normalize_symbol(symbol)
        before = len(self.entries)
        self.entries = [e for e in self.entries if e["symbol"] != symbol]
        removed = len(self.entries) < before
        if removed:
            self.save()
        return removed

    def clear(self) -> int:
        removed = len(self.entries)
        if removed:
            self.entries = []
            self.save()
        return removed

    def update_name(self, symbol, name: str) -> bool:
        """花名册刷新后同步名称（旧名不当真相）。"""
        symbol = normalize_symbol(symbol)
        name = str(name or "").strip()
        if not symbol or not name:
            return False
        for existing in self.entries:
            if existing["symbol"] == symbol and existing["name"] != name:
                existing["name"] = name
                self.save()
                return True
        return False

    def move(self, symbol, delta: int) -> bool:
        """上移(-1)/下移(+1)。返回是否有位置变化（已到边界则 False）。"""
        symbol = normalize_symbol(symbol)
        index = next((i for i, e in enumerate(self.entries) if e["symbol"] == symbol), -1)
        if index < 0:
            return False
        target = index + int(delta)
        if target < 0 or target >= len(self.entries) or target == index:
            return False
        self.entries.insert(target, self.entries.pop(index))
        self.save()
        return True
