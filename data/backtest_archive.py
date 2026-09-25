# data/backtest_archive.py
"""
回测结果历史存档 (v1.37 / §7-A4) —— 每次回测落一份**不可变快照**。

【存什么：复现 + 留档 都在一份里】
  · 配置快照（`meta` + `config`，都取自 start_backtest 定格的那一刻）→ 可"复用参数 / 重跑"（复现）；
  · 冻结结果（KPI + 逐笔全量 + 净值抽稀）→ 可"载入查看"忠实回放当天结果，
    不受此后行情更新影响（留档）。

【为什么每份一个文件 + 轻量索引】
  单条记录可能含上千笔逐笔，塞进一个大 JSON 会让"每写一条"都重写全表。故：
    · `~/.jian_data/backtest_results/<id>.json` —— 全量记录，**写入后不再变更**（pin 除外）；
    · `_index.json` —— 只存列表/筛选要的元数据（时间/标的/策略/KPI/★），丢失可从各文件重建。

【三条硬口径（改本文件前先读）】
  1. **净值抽稀必须端点保底**：`BacktestResult.cumulative_return == equity[-1] - 1.0`，
     所以抽稀后的**最后一点必须是最新净值**，否则"载入查看"的累计收益会算错。
  2. **买卖点优先于抽稀上限**：抽稀时强制并入所有成交日；成交日本身超过上限时允许超限
     （上限是"省空间"的软目标，另有 `MAX_FILE_BYTES` 硬闸兜底）。
  3. **读路径绝不写盘**：`list()` / `load()` / 索引重建一律只读 —— 否则"开一次运行历史页"
     就会把真实 `~/.jian_data/backtest_results/` 建出来（写盘只发生在 save/delete/pin 真变更时）。

【安全（用户点名"防恶意注入"）】
  · 文件名一律 `<时间戳>_<uuid8>.json`，**绝不把策略名/标的名等用户输入写进路径**（防路径穿越）；
    用户文本只进 JSON 字段，由 `json.dump(ensure_ascii=False)` 转义。
  · 单文件 > 2 MB 拒存（防体积炸弹）；每标的 ≤20、总量 ≤500 滚动淘汰（防 bug 恶性堆积）。
  · `load` 只反序列化，绝不执行任何内容。

【kind】记录带 `kind`（M1 单股回测 / M2 全市场筛选 / M3 广度统计，三种都已启用）：
  · M1 记录 = `meta` + `kpi` + `trades` + `equity`（旧形状，保持不变）；
  · M2/M3 记录 = **显式分组** `scope` / `condition` / `counts` + `day` / `range_start`
    （★v1.46 重做：旧版把命中数塞进 `total_trades`、命中率塞进 `win_rate` —— 一套键两种
    含义，任何按 `win_rate` 的排序/汇总都会混进横截面数据）。
  两种形状统一由 `_entry_of()` **规范化**成索引项 ⇒ 列表/预览层不必再 `if kind`。
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime

import pandas as pd

from config import settings
from core.backtest import BacktestResult, BacktestTrade

logger = logging.getLogger(__name__)

ARCHIVE_DIR = os.path.join(settings.USER_DATA_DIR, "backtest_results")
INDEX_NAME = "_index.json"

PER_SYMBOL_CAP = 20        # 每个 (kind, 标的) 最多保留的**非重点**存档数
TOTAL_CAP = 500            # 全局存档上限（**含重点**；重点豁免自动淘汰）
MAX_FILE_BYTES = 2 * 1024 * 1024   # 单文件 2 MB 上限
EQUITY_MAX_POINTS = 250    # 净值抽稀上限（预览用）

KIND_M1 = "M1"
KIND_M2 = "M2"             # 全市场筛选
KIND_M3 = "M3"             # 广度统计
KIND_LABELS = {KIND_M1: "M1 单股回测", KIND_M2: "M2 全市场筛选", KIND_M3: "M3 广度统计"}

SOURCE_AUTO = "auto"
SOURCE_MANUAL = "manual"
SOURCE_LABELS = {SOURCE_AUTO: "自动", SOURCE_MANUAL: "手动"}

__all__ = [
    "BacktestArchive", "build_record", "build_scan_record", "record_to_result", "sample_equity",
    "formula_summary",
    "ARCHIVE_DIR", "PER_SYMBOL_CAP", "TOTAL_CAP", "MAX_FILE_BYTES", "EQUITY_MAX_POINTS",
    "KIND_M1", "KIND_M2", "KIND_M3", "KIND_LABELS",
    "SOURCE_AUTO", "SOURCE_MANUAL", "SOURCE_LABELS",
]


# ==========================================
# 记录构造 / 还原（纯函数，好测）
# ==========================================
# 元数据白名单：`_last_meta` 已是策展过的快照，这里再兜一层，防止将来有人往里塞大对象
_META_KEYS = ("symbol", "name", "strategy_name", "start_date", "end_date", "segments",
              "params_text", "buy_expr", "sell_expr", "risk", "index", "fill")


def _clean_meta(meta: dict) -> dict:
    return {k: (meta or {}).get(k) for k in _META_KEYS}


def _date_key(value) -> str | None:
    """任意日期 → `YYYY-MM-DD`；不可解析返回 None（单笔坏数据不拖垮整份存档）。"""
    try:
        ts = pd.Timestamp(value)
    except (ValueError, TypeError):  # noqa: BLE001
        return None
    if pd.isna(ts):
        return None
    return ts.strftime("%Y-%m-%d")


def sample_equity(result, max_points: int = EQUITY_MAX_POINTS) -> list:
    """把 `result.equity` 等间隔抽稀到 ≤max_points，且**强制并入所有成交日** + **端点保底**。

    返回 `[{date, equity, in_market, buy_at, sell_at}]`：
      · `buy_at` / `sell_at` = 该日净值（只有成交日才非 None），
        供结果区把买卖点**画在净值曲线上**（不用成交价 —— 量纲不同）。
      · 端点保底 = 必含第一点与最后一点（否则 `cumulative_return` 会算错，见模块 docstring）。
      · 若成交日集合本身就超过 `max_points`，**买卖点优先**，允许超限（有 2MB 硬闸兜底）。
    """
    eq = getattr(result, "equity", None)
    if eq is None or getattr(eq, "empty", True):
        return []
    if "date" not in eq.columns or "equity" not in eq.columns:
        return []

    d = eq.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d = d.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    if d.empty:
        return []
    if "in_market" not in d.columns:
        d["in_market"] = 0
    keys = d["date"].dt.strftime("%Y-%m-%d")

    buy_days, sell_days = set(), set()
    for t in (getattr(result, "trades", None) or []):
        entry = _date_key(getattr(t, "entry_date", None))
        exit_ = _date_key(getattr(t, "exit_date", None))
        if entry:
            buy_days.add(entry)
        if exit_:
            sell_days.add(exit_)

    n = len(d)
    budget = max(int(max_points), 2)
    if n <= budget:
        keep = set(range(n))
    else:
        span = n - 1
        # round 版等间隔天然含 0 与 span；再显式补一次防浮点边界
        keep = {round(i * span / (budget - 1)) for i in range(budget)}
        keep.add(0)
        keep.add(span)
    # 买卖点优先：成交日一律并入（可能使总数超过 budget，见 docstring 第 2 条）
    keep |= {i for i, k in enumerate(keys) if k in buy_days or k in sell_days}

    rows = []
    for i in sorted(keep):
        k = keys.iloc[i]
        eqv = round(float(d["equity"].iloc[i]), 6)
        try:
            in_market = int(d["in_market"].iloc[i] or 0)
        except (TypeError, ValueError):  # noqa: BLE001
            in_market = 0
        rows.append({
            "date": k, "equity": eqv, "in_market": in_market,
            "buy_at": eqv if k in buy_days else None,
            "sell_at": eqv if k in sell_days else None,
        })
    return rows


def build_record(result, meta: dict, config: dict = None, kind: str = KIND_M1,
                 source: str = SOURCE_AUTO) -> dict:
    """把一次回测组装成一条不可变存档记录。

    :param meta: 展示/溯源快照（`_last_meta`，含表达式串/策略名/区间）
    :param config: 编辑器可还原的完整配置（`StrategyBridge.payload()`，含 condition_buy/sell 等）。
                   ⚠ 调用方应传 **发起回测瞬间定格**的那份（`_last_config`），
                   否则"存档里的配置"可能与"跑出来的结果"不是同一次。
    :param source: 'auto'（自动存档）/ 'manual'（手动存），列表"来源"列用。
    """
    trades = []
    for t in (getattr(result, "trades", None) or []):
        trades.append({
            "entry_date": _date_key(getattr(t, "entry_date", None)),
            "exit_date": _date_key(getattr(t, "exit_date", None)),
            "entry_price": round(float(getattr(t, "entry_price", 0.0)), 4),
            "exit_price": round(float(getattr(t, "exit_price", 0.0)), 4),
            "pnl": round(float(getattr(t, "pnl", 0.0)), 4),
            "return_pct": round(float(getattr(t, "return_pct", 0.0)), 6),
            "exit_reason": getattr(t, "exit_reason", "signal"),
            "deferred_t1": bool(getattr(t, "deferred_t1", False)),
        })
    return {
        "id": "", "kind": kind,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "seq": time.time_ns(),                     # 单调排序键（同秒批量不误判新旧）
        "pinned": False, "source": source,
        "meta": _clean_meta(meta),
        "config": config or {},
        "kpi": result.summary(),
        "trades": trades,
        "equity": sample_equity(result),
    }


def formula_summary(formula: str, n_segments: int = 1) -> str:
    """公式 → 列表「条件」列的**一行摘要**：`首行（截断） · N段`。

    【为什么需要】旧版把整段公式的第一行截 40 字当"策略名"，用户看不出
    "函数到底有没有整段存下来"。摘要只负责"够指认"，**全文在预览里给**（可复制）。
    """
    first = next((ln.strip() for ln in str(formula or '').splitlines() if ln.strip()), '')
    if len(first) > 34:
        first = first[:34] + '…'
    return f'{first or "（无条件）"} · {max(1, int(n_segments or 1))}段'


def build_scan_record(config: dict, *, kind: str, scope_label: str = '',
                      scope_code: str = '', counts: dict = None, asof=None,
                      range_label: str = '', condition_label: str = '',
                      source: str = SOURCE_AUTO) -> dict:
    """M2/M3 一次扫描的不可变快照（§7-B12 P4 · v1.46 重做）。

    与 M1 不同：**无逐笔、无净值**（横截面/广度没有这些概念）。
    · `config` = 页面 `current_config()`（可被 `apply_config` 还原 → 复用/重跑）；
    · `counts` = 四态计数 `{total,hit,miss,insufficient,filtered,valid}`；
    · `scope_label` / `scope_code` = 范围名与指数代码（★v1.46：旧版只存「指数成分 300只」，
      **丢掉了是哪个指数** —— 列表/预览/搜索全都没法辨认）；
    · 记录**显式分组**（不再借 M1 的 `meta`/`kpi` 键），规范化交给 `_entry_of()`。
    """
    config = config or {}
    counts = dict(counts or {})
    formula = str(config.get('formula') or '')
    segments = [formula] if formula.strip() else []
    if not condition_label:
        condition_label = formula_summary(formula, len(segments))
    hit = int(counts.get('hit') or 0)
    valid = int(counts.get('valid') or 0)
    counts.update({
        'total': int(counts.get('total') or 0), 'hit': hit, 'valid': valid,
        'miss': counts.get('miss'), 'insufficient': counts.get('insufficient'),
        'filtered': counts.get('filtered'),
        'hit_rate': (hit / valid) if valid else None,
    })
    return {
        'id': '', 'kind': kind,
        'created_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'seq': time.time_ns(), 'pinned': False, 'source': source,
        'scope': {'label': str(scope_label or ''), 'code': str(scope_code or '')},
        'condition': {'label': condition_label, 'formula': formula,
                      'params': str(config.get('params') or ''),
                      'segments': segments,
                      'thresholds': dict(config.get('thresholds') or {})},
        'day': _date_key(asof) or '',
        'range_start': _date_key(range_label) or '',
        'counts': counts,
        'config': config,
    }


def record_to_result(record: dict) -> BacktestResult:
    """从存档记录重建 `BacktestResult`（喂给现有结果区渲染，**不改引擎**）。

    产出的 `equity` 带 `buy_at` / `sell_at` 两列（成交日净值）⇒ 净值曲线可画买卖点。
    ⚠ KPI **不要**用它的 `summary()` 重算（那是抽稀序列），要读存档里的 `record["kpi"]`。
    """
    meta = record.get("meta") or {}
    trades = []
    for t in (record.get("trades") or []):
        try:
            trades.append(BacktestTrade(
                entry_date=pd.Timestamp(t.get("entry_date")),
                exit_date=pd.Timestamp(t.get("exit_date")),
                entry_price=float(t.get("entry_price") or 0.0),
                exit_price=float(t.get("exit_price") or 0.0),
                pnl=float(t.get("pnl") or 0.0),
                return_pct=float(t.get("return_pct") or 0.0),
                exit_reason=t.get("exit_reason", "signal"),
                deferred_t1=bool(t.get("deferred_t1", False))))
        except (ValueError, TypeError):  # noqa: BLE001 —— 单笔坏数据跳过，不拖垮整份
            continue
    rows = record.get("equity") or []
    if rows:
        equity = pd.DataFrame({
            "date": [r.get("date") for r in rows],
            "equity": [r.get("equity") for r in rows],
            "in_market": [int(r.get("in_market") or 0) for r in rows],
            "buy_at": [r.get("buy_at") for r in rows],
            "sell_at": [r.get("sell_at") for r in rows],
        })
    else:
        equity = pd.DataFrame(columns=["date", "equity", "in_market", "buy_at", "sell_at"])
    fill = meta.get("fill") or {}
    return BacktestResult(
        symbol=str(meta.get("symbol") or ""),
        buy_expression=str(meta.get("buy_expr") or ""),
        sell_expression=str(meta.get("sell_expr") or ""),
        start_date=str(meta.get("start_date") or ""),
        end_date=str(meta.get("end_date") or ""),
        trades=trades, equity=equity, risk=meta.get("risk") or {},
        fill_mode=fill.get("fill_mode"), trigger_tick=fill.get("trigger_tick"))


# ==========================================
# 存储层
# ==========================================
class BacktestArchive:
    """回测历史存档门面：save / list / load / set_pinned / delete（+ 淘汰、防注入）。

    `root` 可注入（测试用临时目录）；所有读写都相对 `root`。
    """

    def __init__(self, root: str = ARCHIVE_DIR):
        self.root = root
        self.index_path = os.path.join(root, INDEX_NAME)

    # 上限说明（给"存档设置"面板只读展示用）
    @staticmethod
    def caps() -> dict:
        return {
            "per_symbol": PER_SYMBOL_CAP, "total": TOTAL_CAP,
            "max_mb": MAX_FILE_BYTES // (1024 * 1024),
            "equity_points": EQUITY_MAX_POINTS, "pinned_exempt": True,
        }

    # ---------------- 写 ----------------
    def save(self, record: dict) -> str | None:
        """落一份不可变存档；返回 id。超体积上限返回 None（调用方给回执）。"""
        rid = record.get("id") or self._new_id()
        record["id"] = rid
        record.setdefault("kind", KIND_M1)
        record.setdefault("created_at", time.strftime("%Y-%m-%d %H:%M:%S"))
        record.setdefault("seq", time.time_ns())
        record.setdefault("pinned", False)
        record.setdefault("source", SOURCE_AUTO)
        blob = json.dumps(record, ensure_ascii=False)
        if len(blob.encode("utf-8")) > MAX_FILE_BYTES:      # 防体积炸弹
            logger.warning("回测存档超 %d MB 上限，拒绝写入 [%s]",
                           MAX_FILE_BYTES // (1024 * 1024), rid)
            return None
        os.makedirs(self.root, exist_ok=True)
        self._atomic(self._file(rid), blob)
        index = [e for e in self._read_index() if e.get("id") != rid]   # 幂等：同 id 覆盖
        index.append(self._entry_of(record))
        self._write_index(index)
        self._evict()
        return rid

    def set_pinned(self, rid: str, pinned: bool) -> bool:
        """标/取消「★ 重点」；重点豁免自动淘汰。文件不存在返回 False（不写盘）。"""
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
        """删除一份存档（UI 二次确认后调用）。**没删到文件就不写盘**（不建目录）。"""
        path = self._file(rid)
        removed = False
        if os.path.exists(path):
            try:
                os.remove(path)
                removed = True
            except OSError as e:  # noqa: BLE001
                logger.warning("删除存档失败 [%s]: %s", rid, e)
                return False
        index = self._read_index()
        kept = [e for e in index if e.get("id") != rid]
        if len(kept) != len(index):
            self._write_index(kept)
        return removed

    # ---------------- 读 ----------------
    def list(self, kind: str = None, symbol: str = None, scope: str = None,
             keyword: str = None, only_pinned: bool = False) -> list:
        """按条件过滤的**元数据**列表（时间倒序）。读路径，绝不写盘。

        `symbol` 过滤 M1 标的；`scope` 过滤 M2/M3 范围（键 = `scope_code or scope_label`）；
        关键词覆盖 标的/名称/策略/范围/条件 —— 两页共用同一套搜索框。
        """
        out = []
        kw = (keyword or "").strip().lower()
        for e in self._read_index():          # _read_index 已剔除"文件已消失"的僵尸项
            if kind and e.get("kind") != kind:
                continue
            if symbol and e.get("symbol") != symbol:
                continue
            if scope and (e.get("scope_code") or e.get("scope_label")) != scope:
                continue
            if only_pinned and not e.get("pinned"):
                continue
            if kw:
                hay = " ".join(str(e.get(k) or "") for k in (
                    "symbol", "name", "strategy_name", "scope_label", "condition_label"))
                if kw not in hay.lower():
                    continue
            out.append(e)
        out.sort(key=lambda e: (self._seq(e), str(e.get("created_at") or "")), reverse=True)
        return out

    def filter_options(self, kind: str = None) -> list:
        """过滤下拉的选项 `[(值, 显示名)]`（按显示名排序）。

        M1 = 出现过的**标的**；M2/M3 = 出现过的**范围**（键优先 `scope_code`）。
        ⚠ 旧版对 M2/M3 复用 `symbols()`，而它们 `symbol` 恒为空 ⇒ 下拉永远只有一个
        「全部」——成了不会说话的摆设（v1.46 修）。
        """
        seen = {}
        for e in self.list(kind=kind):
            if e.get("kind") == KIND_M1:
                key, label = e.get("symbol"), e.get("name") or e.get("symbol")
            else:
                key = e.get("scope_code") or e.get("scope_label")
                label = e.get("scope_label") or key
            if key and key not in seen:
                seen[key] = label
        return sorted(seen.items(), key=lambda kv: str(kv[1]))

    def load(self, rid: str):
        """读全量记录（重建 BacktestResult 用）；不存在/损坏返回 None。"""
        path = self._file(rid)
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError) as e:  # noqa: BLE001
            logger.warning("存档读取失败 [%s]: %s", rid, e)
            return None

    def stats(self) -> dict:
        """占用概览（条数 / 重点数 / 磁盘体积）—— 仅供"存档设置"面板只读展示。"""
        entries = self.list()
        total_bytes = 0
        for e in entries:
            try:
                total_bytes += os.path.getsize(self._file(e.get("id")))
            except OSError:  # noqa: BLE001
                pass
        return {"count": len(entries),
                "pinned": sum(1 for e in entries if e.get("pinned")),
                "bytes": total_bytes}

    # ---------------- 内部 ----------------
    def _file(self, rid: str) -> str:
        """id → 文件路径。只保留 [0-9A-Za-z_-]，杜绝路径穿越（不信任外部传入的 rid）。"""
        safe = "".join(c for c in str(rid) if c.isalnum() or c in "_-")
        return os.path.join(self.root, f"{safe}.json")

    @staticmethod
    def _new_id() -> str:
        return f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _seq(entry: dict) -> int:
        try:
            return int(entry.get("seq") or 0)
        except (TypeError, ValueError):  # noqa: BLE001
            return 0

    @staticmethod
    def _entry_of(record: dict) -> dict:
        """一条记录 → **规范化索引项**（列表/预览只认它，不再 `if kind`）。

        ⚠ 两种记录形状在这里收敛：M1 读 `meta`/`kpi`；M2/M3 读 `scope`/`condition`/`counts`。
        """
        kind = record.get("kind", KIND_M1)
        entry = {
            "id": record.get("id"), "kind": kind,
            "created_at": record.get("created_at"),
            "pinned": bool(record.get("pinned")),
            "source": record.get("source", SOURCE_AUTO),
            "seq": record.get("seq", 0),
        }
        if kind == KIND_M1:
            meta = record.get("meta") or {}
            kpi = record.get("kpi") or {}
            entry.update({
                "symbol": meta.get("symbol"), "name": meta.get("name"),
                "strategy_name": meta.get("strategy_name"),
                "start_date": meta.get("start_date"), "end_date": meta.get("end_date"),
                "total_trades": kpi.get("total_trades"), "win_rate": kpi.get("win_rate"),
                "cumulative_return": kpi.get("cumulative_return"),
            })
            return entry
        scope = record.get("scope") or {}
        cond = record.get("condition") or {}
        counts = record.get("counts") or {}
        segments = cond.get("segments") or []
        label = scope.get("label") or ""
        entry.update({
            "scope_label": label, "scope_code": scope.get("code") or "",
            "name": label,                       # 通用列（搜索/排序）沿用 name
            "condition_label": (cond.get("label")
                                or formula_summary(str(cond.get("formula") or ""),
                                                   len(segments))),
            "n_segments": len(segments),
            "day": record.get("day") or "",
            "range_start": record.get("range_start") or "",
            "start_date": record.get("range_start") or record.get("day") or "",
            "end_date": record.get("day") or "",
            "hit": counts.get("hit"), "miss": counts.get("miss"),
            "insufficient": counts.get("insufficient"), "filtered": counts.get("filtered"),
            "valid": counts.get("valid"), "total": counts.get("total"),
            "hit_rate": counts.get("hit_rate"),
        })
        return entry

    def _read_index(self, prune_missing: bool = True) -> list:
        """读索引；索引缺失/损坏 → 从各存档文件**重建（只读，不写盘）**。

        `prune_missing=True`：顺手剔除"索引里有、文件已不在"的僵尸项
        （用户在文件管理器里手删过 / 上次删除中断）。这层自愈只在内存里发生，
        真正的写盘仍留给 save/delete/pin。
        """
        entries = None
        if os.path.exists(self.index_path):
            try:
                with open(self.index_path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    entries = [e for e in data if isinstance(e, dict)]
            except (OSError, ValueError) as e:  # noqa: BLE001
                logger.warning("索引读取失败，重建：%s", e)
        if entries is None:
            entries = self._rebuild_index()
        if prune_missing:
            entries = [e for e in entries if os.path.exists(self._file(e.get("id")))]
        return entries

    def _rebuild_index(self) -> list:
        """从目录里各存档文件重建索引（索引丢失/损坏时的自愈）。⚠ **只读不写**。"""
        entries = []
        if os.path.isdir(self.root):
            for fn in os.listdir(self.root):
                if not fn.endswith(".json") or fn == INDEX_NAME:
                    continue
                rec = self.load(fn[:-5])
                if rec:
                    entries.append(self._entry_of(rec))
        return entries

    def _write_index(self, entries: list) -> None:
        os.makedirs(self.root, exist_ok=True)
        self._atomic(self.index_path, json.dumps(entries, ensure_ascii=False))

    def _evict(self) -> None:
        """滚动淘汰：① 每 (kind,标的) 非重点 ≤ PER_SYMBOL_CAP；② 全局非重点淘汰到总量 ≤ TOTAL_CAP。

        ⚠ 重点（★）**永不自动删除**，但**计入** TOTAL_CAP —— 所以当重点数本身 ≥ 500 时，
        非重点会被清空、总量仍可能超 500（这是"重点豁免"的必然代价，见模块 docstring）。
        """
        index = self._read_index()
        doomed: set = set()

        # ① 分标的/范围：非重点按新→旧保留 PER_SYMBOL_CAP 份
        #   ★v1.46：M2/M3 没有 symbol ⇒ 旧版按 (kind, '') 分组，**所有范围共用一个配额**
        #   （300 只的沪深300 与 12 只的自选互相挤掉），改用 scope 做分组键。
        groups: dict = {}
        for e in index:
            facet = (e.get("symbol") if e.get("kind") == KIND_M1
                     else (e.get("scope_code") or e.get("scope_label")))
            groups.setdefault((e.get("kind"), facet), []).append(e)
        for rows in groups.values():
            rows.sort(key=lambda e: self._seq(e), reverse=True)
            kept = 0
            for e in rows:
                if e.get("pinned"):
                    continue                 # 重点不占配额、也不被删
                kept += 1
                if kept > PER_SYMBOL_CAP:
                    doomed.add(e.get("id"))

        # ② 全局：非重点按旧→新淘汰，直到总量（含重点）≤ TOTAL_CAP
        remaining = [e for e in index if e.get("id") not in doomed]
        over = len(remaining) - TOTAL_CAP
        if over > 0:
            unpinned_old_first = sorted((e for e in remaining if not e.get("pinned")),
                                        key=lambda e: self._seq(e))
            for e in unpinned_old_first[:over]:
                doomed.add(e.get("id"))

        if not doomed:
            return
        for rid in doomed:
            try:
                os.remove(self._file(rid))
            except OSError:  # noqa: BLE001 —— 文件已不在也算淘汰成功
                pass
        self._write_index([e for e in index if e.get("id") not in doomed])

    @staticmethod
    def _atomic(path: str, text: str) -> None:
        """原子写（tmp + os.replace）—— 与 preferences / strategy_store 同款。"""
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
