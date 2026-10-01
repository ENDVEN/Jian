# data/sweep_archive.py
"""
参数研究快照存档（§7-B15 SW-4）· 照抄 `data/backtest_archive.py` 范式。

- 目录 `~/.jian_data/sweep_results/`（**根可注入**，冒烟一律临时目录）；索引 `_index.json`；
  tmp + os.replace 原子写；单文件体积上限防炸弹。
- **快照 = 可复现的最小集合（§8-9）**：策略**整体内联**（segments / params_text /
  conditions / risk / fill + asset_id + 文本指纹，v3.1 勘误①：真源 strategy_store，
  内联当时的文本，将来总库出现"更新版"也能诚实回放）+ 网格 + 区间（预设 key + 四日期）
  + 门槛 + APP_VERSION + 统计结果（IC / PBO / 候选表前 N）。
- **落盘折中（v3.1 勘误③）**：段矩阵（S=12 聚合，全部完成组）+ Top-N 组合的逐日收益
  —— 体积与"重开快照换 S 重算 PBO"兼顾。
- **OOS 诚实计数器（v3.1 勘误⑧）**：快照索引按
  `(标的, 策略指纹, 样本外起, 样本外止)` 记账；`oos_usage()` 返回同一窗口已被
  多少项研究引用（**含本次**）—— 不阻断（合法研究可共享样本外窗），但把
  "样本外正在变成样本内"摆在明面上。红线①的硬闸（同网格重跑拦截）在页面流程。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid

import numpy as np

from config import settings
from core.param_sweep import SweepSpec, combo_key
from core.sweep_plan import GridPlan, StudyInterval
from core.sweep_stats import (SweepMetrics, apply_gate, candidate_order,  # noqa: N812
                              platform_spike_flags)

logger = logging.getLogger(__name__)

SWEEP_DIR = os.path.join(settings.USER_DATA_DIR, "sweep_results")
INDEX_NAME = "_index.json"
MAX_FILE_BYTES = 8 * 1024 * 1024   # 单文件 8MB（段矩阵 + Top-N 逐日，比 M1 存档宽裕）
N_SEGMENTS = 12                    # 落盘段矩阵的段数 S（统计期可换，见 sweep_stats.pbo_cscv）
TOP_N_DAILY = 50                   # 快照里保留逐日收益的组合数
TOP_N_CANDIDATES = 50              # 候选表落盘行数

__all__ = ["SweepArchive", "build_snapshot", "top_candidate_rows",
           "strategy_fingerprint", "oos_key_of", "segment_matrix",
           "SWEEP_DIR", "MAX_FILE_BYTES", "N_SEGMENTS", "TOP_N_DAILY", "TOP_N_CANDIDATES"]


# ==========================================
# 纯函数：指纹 / 计数键 / 段矩阵 / 候选行 / 快照组装
# ==========================================
def strategy_fingerprint(spec: SweepSpec) -> str:
    """策略文本指纹（MD5 短码）：segments + params_text + 条件 —— OOS 记账与复现校验用。

    ★1.66：条件用**归一后的表达式**（`spec.buy_expr/sell_expr`，`core.conditions` 产出），
    不用 `str(dict)` —— dict 的键序会抖，而"同一套条件"必须永远同一个指纹
    （表达式正是它的规范形；旧档单条件形状与新档条件组也能对到同一处）。
    """
    raw = "\x1f".join([*spec.segments, str(spec.params_text or ""),
                       spec.buy_expr, spec.sell_expr])
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:10]


def oos_key_of(symbol: str, fingerprint: str, oos_start: str, oos_end: str) -> str:
    """OOS 诚实计数器的记账键：同一 (标的, 策略, 样本外窗口) 跨研究累计。"""
    return f"{symbol}|{fingerprint}|{oos_start}|{oos_end}"


def segment_matrix(matrix: np.ndarray, s: int = N_SEGMENTS) -> list[list[float]]:
    """逐日收益矩阵 (n, T) → 每组 s 段的段收益（段内复利 Π(1+r)−1，按天轴连续等分）。"""
    m = np.asarray(matrix, dtype=float)
    if m.ndim != 2 or m.shape[1] == 0:
        return [[] for _ in range(m.shape[0] if m.ndim else 0)]
    blocks = np.array_split(np.arange(m.shape[1]), max(2, int(s)))
    out = []
    for row in m:
        segs = [float(np.prod(1.0 + row[b]) - 1.0) if len(b) else 0.0 for b in blocks]
        out.append(segs)
    return out


def top_candidate_rows(metrics: SweepMetrics, items: list[tuple[str, dict]],
                       trades: list[int], min_trades: int,
                       top: int = TOP_N_CANDIDATES,
                       include_gated: bool = False) -> list[dict]:
    """候选表行（排序/门槛口径全在 sweep_stats，这里只组装）。

    `include_gated=False`（默认，快照与既有调用不变的形状）⇒ 只给**过门槛**的，按排序键取前 top。
    `include_gated=True`（★R5 界面口径）⇒ 按排序键取前 top **全部列出**，每条带：
      · `"kept"` 过没过门槛（门槛**只筛不排** ⇒ 没过的灰显保留，用户能看见"被筛掉了什么"）；
      · `"flag"` 平台/尖峰判定（`"平"` / `"尖"` / `""`）—— 判据与热力图圈注**同一个函数**；
      · `"idx"` 该行在 metrics 里的下标（行悬停要用它去查邻居）。
    """
    order = candidate_order(metrics.is_annual, metrics.oos_annual, metrics.nb_mean)
    taken = (np.asarray(order) if include_gated
             else apply_gate(order, trades, min_trades,
                             metrics.is_annual, metrics.oos_annual))
    kept_set = set(apply_gate(order, trades, min_trades,
                              metrics.is_annual, metrics.oos_annual).tolist())
    plat, spike = platform_spike_flags(metrics.oos_annual, metrics.nb_mean, metrics.nb_worst)
    rows = []
    for rank, idx in enumerate(taken[:max(0, int(top))], 1):
        i = int(idx)
        key, combo = items[i]
        flag = ("平" if (i < plat.size and bool(plat[i]))
                else "尖" if (i < spike.size and bool(spike[i])) else "")
        rows.append({
            "rank": rank, "key": key, "combo": dict(combo), "idx": i,
            "is_annual": float(metrics.is_annual[i]),
            "oos_annual": float(metrics.oos_annual[i]),
            "delta": float(metrics.delta[i]),
            "nb_mean": float(metrics.nb_mean[i]),
            "nb_worst": float(metrics.nb_worst[i]),
            "trades": int(trades[i]),
            "kept": i in kept_set,
            "flag": flag,
        })
    return rows


def build_snapshot(*, spec: SweepSpec, strategy_name: str, asset_id: str,
                   grid: GridPlan, interval: StudyInterval, preset_key: str,
                   min_trades: int, stats: dict, matrix: np.ndarray,
                   daily: dict, source: str = "manual") -> dict:
    """组装一份可复现快照（不含 id/seq —— save 时补）。

    stats = {"rank_ic": float|None, "pbo": float|None, "items": [(key, combo)...],
             "trades": [int...], "metrics": SweepMetrics, "n_done": int, "n_failed": int}
    daily = {"keys": [...], "is_dates": [...], "oos_dates": [...],
             "is_returns": {key: [...]}, "oos_returns": {key: [...]}}   # Top-N 已选好
    """
    fp = strategy_fingerprint(spec)
    return {
        "kind": "SWEEP",
        "app_version": settings.APP_VERSION,
        "symbol": spec.symbol,
        "strategy": {
            "name": str(strategy_name or ""),
            "asset_id": str(asset_id or ""),
            "fingerprint": fp,
            "segments": list(spec.segments),
            "params_text": str(spec.params_text or ""),
            "condition_buy": str(spec.condition_buy or ""),
            "condition_sell": str(spec.condition_sell or ""),
            "risk": dict(spec.risk or {}),
            "fill": {"fill_mode": spec.fill_mode, "trigger_tick": spec.trigger_tick},
        },
        "grid": {"dims": [{"name": d.name, "values": list(d.values)} for d in grid.dims],
                 "n_combos": int(grid.n_combos)},
        "interval": {"preset_key": str(preset_key or "custom"),
                     "is_start": interval.is_start, "is_end": interval.is_end,
                     "oos_start": interval.oos_start, "oos_end": interval.oos_end},
        "gate": {"min_trades": int(min_trades)},
        "stats": {
            "rank_ic": stats.get("rank_ic"),
            "pbo": stats.get("pbo"),
            "n_done": int(stats.get("n_done", 0)),
            "n_failed": int(stats.get("n_failed", 0)),
            # `candidates` = **过门槛**的候选（§8-12 口径，语义与形状一字不改）。
            "candidates": top_candidate_rows(stats["metrics"], stats["items"],
                                             stats["trades"], min_trades),
            # ★R5b：另存一份**展示行**（连没过门槛的也带 `kept`/`flag`）—— 回看时要能复原
            #   当时**同一张**表；否则"全为负收益时过门槛 0 组 ⇒ 回看只有空表"（实测踩过）。
            #   两者分开存：`candidates` 的既有口径不动（冒烟有断言钉着），展示行是新增字段。
            "rows": top_candidate_rows(stats["metrics"], stats["items"],
                                       stats["trades"], min_trades,
                                       include_gated=True),
        },
        "segment_matrix": segment_matrix(matrix, N_SEGMENTS),
        "daily_top": daily,
        "pinned": False,
        "source": str(source or "manual"),
    }


# ==========================================
# 存档门面（范式照抄 BacktestArchive：root 可注入 / 原子写 / 幂等索引 / 重点豁免）
# ==========================================
class SweepArchive:
    """save / list / load / set_pinned / delete / oos_usage。"""

    def __init__(self, root: str = SWEEP_DIR):
        self.root = root
        self.index_path = os.path.join(root, INDEX_NAME)

    # ---------------- 写 ----------------
    def save(self, snapshot: dict) -> str | None:
        """落一份不可变快照；返回 id。超体积上限返回 None（调用方给回执）。"""
        rid = snapshot.get("id") or f"SW_{uuid.uuid4().hex[:10].upper()}"
        snapshot["id"] = rid
        snapshot.setdefault("kind", "SWEEP")
        snapshot.setdefault("created_at", time.strftime("%Y-%m-%d %H:%M:%S"))
        snapshot.setdefault("seq", time.time_ns())
        snapshot.setdefault("pinned", False)
        snapshot.setdefault("source", "manual")
        blob = json.dumps(snapshot, ensure_ascii=False)
        if len(blob.encode("utf-8")) > MAX_FILE_BYTES:
            logger.warning("参数研究快照超 %d MB 上限，拒绝写入 [%s]",
                           MAX_FILE_BYTES // (1024 * 1024), rid)
            return None
        os.makedirs(self.root, exist_ok=True)
        self._atomic(self._file(rid), blob)
        index = [e for e in self._read_index() if e.get("id") != rid]   # 幂等：同 id 覆盖
        index.append(self._entry_of(snapshot))
        self._write_index(index)
        return rid

    def set_pinned(self, rid: str, pinned: bool) -> bool:
        """标/取消「★ 重点」。文件不存在返回 False（不写盘）。"""
        record = self.load(rid)
        if record is None:
            return False
        record["pinned"] = bool(pinned)
        self._atomic(self._file(rid), json.dumps(record, ensure_ascii=False))
        index = self._read_index()
        hit = False
        for e in index:
            if e.get("id") == rid:
                e["pinned"] = bool(pinned)
                hit = True
        if not hit:
            index.append(self._entry_of(record))
        self._write_index(index)
        return True

    def delete(self, rid: str) -> bool:
        """删除一份快照。没删到文件就不写盘（不建目录）。"""
        path = self._file(rid)
        removed = False
        if os.path.exists(path):
            try:
                os.remove(path)
                removed = True
            except OSError as e:  # noqa: BLE001
                logger.warning("删除参数研究快照失败 [%s]: %s", rid, e)
                return False
        index = self._read_index()
        kept = [e for e in index if e.get("id") != rid]
        if len(kept) != len(index):
            self._write_index(kept)
        return removed

    # ---------------- 读 ----------------
    def list(self, symbol: str | None = None) -> list[dict]:
        """索引条目（seq 新→旧）；symbol 可过滤。"""
        entries = self._read_index()
        if symbol:
            entries = [e for e in entries if e.get("symbol") == symbol]
        return sorted(entries, key=lambda e: e.get("seq", 0), reverse=True)

    def load(self, rid: str) -> dict | None:
        """读回完整快照；缺文件/坏 JSON ⇒ None（诚实，不抛）。"""
        try:
            with open(self._file(rid), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def oos_usage(self, key: str) -> int:
        """OOS 诚实计数器：同一 (标的, 策略, 样本外窗口) 已被多少项研究引用（查索引）。"""
        return sum(1 for e in self._read_index() if e.get("oos_key") == key)

    # ---------------- 内部 ----------------
    def _file(self, rid: str) -> str:
        return os.path.join(self.root, f"{rid}.json")

    def _entry_of(self, snapshot: dict) -> dict:
        interval = snapshot.get("interval") or {}
        strategy = snapshot.get("strategy") or {}
        return {
            "id": snapshot.get("id"),
            "kind": snapshot.get("kind"),
            "symbol": snapshot.get("symbol"),
            "name": strategy.get("name"),
            "fingerprint": strategy.get("fingerprint"),
            "preset_key": interval.get("preset_key"),
            "is_start": interval.get("is_start"), "is_end": interval.get("is_end"),
            "oos_start": interval.get("oos_start"), "oos_end": interval.get("oos_end"),
            "oos_key": oos_key_of(snapshot.get("symbol") or "",
                                  strategy.get("fingerprint") or "",
                                  interval.get("oos_start") or "",
                                  interval.get("oos_end") or ""),
            "n_combos": (snapshot.get("grid") or {}).get("n_combos"),
            # ★R5b：快照卡要这两项 —— 门槛（列表行要显示）与版本（判"旧版本存档"标签）。
            #   索引里**不存**它们的话，卡片只能显示 None / 永远不出标签（实测踩过）。
            "min_trades": (snapshot.get("gate") or {}).get("min_trades"),
            "app_version": snapshot.get("app_version"),
            "rank_ic": (snapshot.get("stats") or {}).get("rank_ic"),
            "pbo": (snapshot.get("stats") or {}).get("pbo"),
            "created_at": snapshot.get("created_at"),
            "seq": snapshot.get("seq"),
            "pinned": bool(snapshot.get("pinned")),
            "source": snapshot.get("source"),
        }

    def _read_index(self) -> list[dict]:
        try:
            with open(self.index_path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def _write_index(self, entries: list[dict]) -> None:
        os.makedirs(self.root, exist_ok=True)
        self._atomic(self.index_path, json.dumps(entries, ensure_ascii=False))

    def _atomic(self, path: str, blob: str) -> None:
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(blob)
        os.replace(tmp, path)
