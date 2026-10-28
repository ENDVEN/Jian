# data/portfolio_store.py
"""🧺 组合的**存储层**（★1.85 / §7-B17 P0）。

【它是什么】一个组合 = 名字 + **来源自选股组** + 权重 + 现金 + 基准 + 再平衡规则。
**成分不复制**：只存 `source_group`（组名），每次要用成分时去
`data/watchlist_store.WatchlistStore.entries_in(group)` **现取** —— 这样"行情页改了组/移了票"
组合自动跟随，不会出现"同一份名单两处不同"（§11.5-112 同族）。

【为什么落盘要原子写】偏好那种"丢了就丢一条"的东西可以随便覆盖；组合是**用户资产**（他自己组的），
写一半断电 = 整个文件坏掉 ⇒ 一律 `写临时文件 + os.replace`（同盘 rename 是原子的）。

【容错原则】读坏了**不崩**：备份坏文件为 `.bad-<时间戳>`、返回空表并记日志（与 `preferences` 同风格）。

【与回测的关系】P0 只存储与展示；回测在 P3（同一引擎、**同一佣金口径** `core.backtest`）。
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from copy import deepcopy

from config import settings

logger = logging.getLogger(__name__)

PORTFOLIOS_FILE = "portfolios.json"
SCHEMA_VERSION = 1

#: 权重模式（用户 2026-10-26 拍板：**等权默认**，但必须给"市值/自定义"）
WEIGHT_MODES = ("equal", "cap", "custom")
WEIGHT_LABELS = {"equal": "等权", "cap": "流通市值", "custom": "自定义"}

#: 再平衡（用户拍板：**买入持有 + 按月**）
REBALANCE_MODES = ("buy_hold", "monthly")
REBALANCE_LABELS = {"buy_hold": "买入持有", "monthly": "按月再平衡"}

#: 基准默认沪深300（用户拍板：可选其它指数，甚至个股）
DEFAULT_BASE = {"kind": "index", "code": "000300", "name": "沪深300"}
DEFAULT_WEIGHT_MODE = "equal"
DEFAULT_REBALANCE = "monthly"
DEFAULT_CASH = 0.0
MAX_MEMBERS = 300


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def new_portfolio(name: str = "", source_group: str = "", members=None,
                  cash: float = DEFAULT_CASH) -> dict:
    """造一条**空组合**（内容更可靠：字段一次给全，别让调用方各处补）。"""
    return {
        "id": "pf-" + uuid.uuid4().hex[:10],
        "name": str(name or "未命名组合").strip() or "未命名组合",
        "source_group": str(source_group or "").strip(),
        "members": [dict(m) for m in (members or [])],
        "weight_mode": DEFAULT_WEIGHT_MODE,
        "cash": float(cash or 0.0),
        "base": dict(DEFAULT_BASE),
        "rebalance": DEFAULT_REBALANCE,
        "created_at": _now(),
        # ★1.90：**成分变更史**（谁在什么时候把哪只票从 X% 改到 Y%）—— 「调仓记录」卡读它。
        #   与"月末再平衡"是两件事：这里记**用户手动改的**，再平衡记**回测口径算出来的**。
        "changes": [],
        "schema_version": SCHEMA_VERSION,
    }


# ★1.90（用户 2026-10-28）：**调仓记录永久保存，不设上限** —— 只有删组合才消失。
#   列表渲染侧靠 `ChangeList` 限高 + 滚动，不靠丢数据来解决"太长"（§11.5-137）。


def diff_members(before, before_cash: float, after, after_cash: float) -> dict:
    """比较两份成分表 → `{added, removed, moved, cash_before, cash_after, has_change}`。

    · `added`   = 新加的票（带 weight）· `removed` = 删掉的票（带原 weight）
    · `moved`   = **权重变了**的票（`before` / `after` / `delta`）
    · 没变化 ⇒ `has_change=False`（调用方据此**不写记录**，别造空账）
    """
    _b = {str(m.get("symbol")): m for m in (before or []) if str(m.get("symbol") or "").strip()}
    _a = {str(m.get("symbol")): m for m in (after or []) if str(m.get("symbol") or "").strip()}
    added, removed, moved = [], [], []
    for s, m in _a.items():
        if s not in _b:
            added.append({"symbol": s, "name": str(m.get("name") or ""),
                          "weight": round(float(m.get("weight") or 0.0), 2)})
            continue
        w0 = round(float(_b[s].get("weight") or 0.0), 2)
        w1 = round(float(m.get("weight") or 0.0), 2)
        if abs(w1 - w0) >= 0.005:
            moved.append({"symbol": s, "name": str(m.get("name") or ""),
                          "before": w0, "after": w1, "delta": round(w1 - w0, 2)})
    for s, m in _b.items():
        if s not in _a:
            removed.append({"symbol": s, "name": str(m.get("name") or ""),
                            "weight": round(float(m.get("weight") or 0.0), 2)})
    c0, c1 = round(float(before_cash or 0.0), 2), round(float(after_cash or 0.0), 2)
    return {"added": added, "removed": removed, "moved": moved,
            "cash_before": c0, "cash_after": c1,
            "has_change": bool(added or removed or moved or abs(c1 - c0) >= 0.005)}


def append_change(portfolio: dict, entry: dict) -> dict:
    """把一次成分变更**追加**进 `changes`（**不截断** —— 用户要求永久保存），返回该组合。"""
    rows = list(portfolio.get("changes") or [])
    rows.append(dict(entry))
    portfolio["changes"] = rows
    return portfolio


def members_from_entries(entries, mode: str = DEFAULT_WEIGHT_MODE) -> list:
    """把自选股条目（`[{symbol, name}]`）变成组合成分；**等权**（`100/n`，最后的余数补到第一个）。

    ⚠ 市值/自定义模式在 P1 接数据后才有意义 ⇒ P0 只做等权，其余模式**保留字段但不假装算过**。
    """
    rows = [{"symbol": str(e.get("symbol") or ""), "name": str(e.get("name") or "")}
            for e in (entries or []) if str(e.get("symbol") or "").strip()]
    rows = rows[:MAX_MEMBERS]
    n = len(rows)
    if not n:
        return []
    each = round(100.0 / n, 2)
    out = [{"symbol": r["symbol"], "name": r["name"], "weight": each} for r in rows]
    out[0]["weight"] = round(100.0 - each * (n - 1), 2)      # 余数补第一个，保证合计 100.00
    return out


def normalize_weights(members, cash: float = 0.0) -> list:
    """把成分权重归一到 `100 - cash`（并夹掉负数/NaN）—— **改现金时按比例缩放**。"""
    rows = [dict(m) for m in (members or [])]
    if not rows:
        return []
    total = sum(max(0.0, float(m.get("weight") or 0.0)) for m in rows) or 0.0
    target = max(0.0, 100.0 - float(cash or 0.0))
    if total <= 0:
        return members_from_entries(rows)
    for m in rows:
        m["weight"] = round(max(0.0, float(m.get("weight") or 0.0)) / total * target, 2)
    return rows


class PortfolioStore:
    """组合的读写门面（**唯一落盘出口**：页面不许自己 open/json.dump）。"""

    def __init__(self, path: str = None):
        self.path = path or os.path.join(settings.USER_DATA_DIR, PORTFOLIOS_FILE)
        self._items = []
        self.load()

    # ---------------- 读 ----------------
    def load(self) -> list:
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            items = raw.get("portfolios") if isinstance(raw, dict) else None
            self._items = [self._normalize(p) for p in (items or []) if isinstance(p, dict)]
        except FileNotFoundError:
            self._items = []
        except Exception as e:                     # noqa: BLE001 —— 坏文件不许拖垮启动
            logger.warning("组合文件读不出来（已隔离，按空表继续）：%s", e)
            self._quarantine()
            self._items = []
        return self.list()

    def list(self) -> list:
        """按创建时间**倒序**（新→旧）返回（深拷贝：调用方改了不会污染内存）。"""
        return sorted((deepcopy(p) for p in self._items),
                      key=lambda p: str(p.get("created_at") or ""), reverse=True)

    def load_one(self, pid: str):
        for p in self._items:
            if str(p.get("id")) == str(pid):
                return deepcopy(p)
        return None

    def exists(self, pid: str) -> bool:
        return any(str(p.get("id")) == str(pid) for p in self._items)

    # ---------------- 写 ----------------
    def save(self, portfolio: dict) -> bool:
        """新增或更新（按 `id`）；**整文件原子写**。坏数据 ⇒ 抛 `ValueError`（不静默吞）。

        ⚠ 这里**不猜**：权重合计必须 ≈ 100（含现金），否则说明调用方算错了 ——
        P0 只会由 `members_from_entries` 生成，所以这条断言等于"防我自己写错"。
        """
        p = self._normalize(portfolio)
        if not str(p.get("name") or "").strip():
            raise ValueError("组合必须有名字")
        total = sum(float(m.get("weight") or 0.0) for m in p["members"]) + float(p["cash"] or 0.0)
        if p["members"] and abs(total - 100.0) > 0.05:
            raise ValueError(f"权重合计必须 = 100%（实测 {total:.2f}）")
        for i, old in enumerate(self._items):
            if str(old.get("id")) == str(p["id"]):
                self._items[i] = p
                break
        else:
            self._items.append(p)
        return self.flush()

    def delete(self, pid: str) -> bool:
        before = len(self._items)
        self._items = [p for p in self._items if str(p.get("id")) != str(pid)]
        if len(self._items) == before:
            return False
        return self.flush()

    def flush(self) -> bool:
        """原子落盘：`<file>.tmp` → `os.replace`（断电不会留半个 JSON）。"""
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        payload = {"schema_version": SCHEMA_VERSION, "portfolios": self._items}
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
            return True
        except Exception as e:                     # noqa: BLE001
            logger.error("组合文件写入失败：%s", e)
            return False

    # ---------------- 内部 ----------------
    @staticmethod
    def _normalize(p: dict) -> dict:
        out = new_portfolio(p.get("name"), p.get("source_group"), p.get("members"), p.get("cash"))
        out.update({k: p[k] for k in ("id", "created_at") if p.get(k)})
        mode = str(p.get("weight_mode") or DEFAULT_WEIGHT_MODE)
        out["weight_mode"] = mode if mode in WEIGHT_MODES else DEFAULT_WEIGHT_MODE
        reb = str(p.get("rebalance") or DEFAULT_REBALANCE)
        out["rebalance"] = reb if reb in REBALANCE_MODES else DEFAULT_REBALANCE
        base = p.get("base")
        if isinstance(base, dict) and base.get("kind") in ("index", "symbol"):
            out["base"] = {"kind": base["kind"], "code": str(base.get("code") or ""),
                           "name": str(base.get("name") or base.get("code") or "")}
        out["members"] = [{"symbol": str(m.get("symbol") or ""),
                           "name": str(m.get("name") or ""),
                           "weight": round(float(m.get("weight") or 0.0), 2)}
                          for m in (out.get("members") or []) if str(m.get("symbol") or "").strip()]
        out["cash"] = round(max(0.0, min(100.0, float(out.get("cash") or 0.0))), 2)
        # ★1.90/1.92：成分变更史（只认 dict；坏项跳过自己，不拖垮整库；**不截断**）
        out["changes"] = [dict(c) for c in (p.get("changes") or []) if isinstance(c, dict)]
        return out

    def _quarantine(self) -> None:
        try:
            bad = self.path + ".bad-" + time.strftime("%Y%m%d%H%M%S")
            os.replace(self.path, bad)
            logger.warning("坏文件已隔离为 %s", os.path.basename(bad))
        except OSError:
            pass


__all__ = ["PortfolioStore", "new_portfolio", "members_from_entries", "normalize_weights",
           "diff_members", "append_change",
           "WEIGHT_MODES", "WEIGHT_LABELS", "REBALANCE_MODES", "REBALANCE_LABELS",
           "DEFAULT_BASE", "DEFAULT_WEIGHT_MODE", "DEFAULT_REBALANCE", "SCHEMA_VERSION"]
