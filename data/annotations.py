# data/annotations.py
"""用户手绘标注：对象模型 + 持久化 CRUD（§7-B3 ④ · P6）。

【两条管线，绝不混用】（§7-B3 C / §10-12）
  管线 A · 公式叠层：引擎求值出的 `DrawData`，随数据/参数**重算且不持久**
    （落点 `core/formula/draw.py` → `ui/widgets/draw_overlay.py`）；
  管线 B · 用户标注：用户鼠标手绘，**持久化到 (标的, 周期)**、**逐个可独立删除**
    —— 就是本模块 + `ui/widgets/annotation_layer.py`。
  二者**只共用「图表宿主」这块舞台**（`ChartPane`），禁止同一数据结构、禁止同一生命周期。

【为什么先 JSON、且对外 API 与存储解耦】
  §7-B3 D3 拍板：存储先用 JSON（原子写 tmp + `os.replace`，与 `preferences` /
  `strategy_store` 同源）；但**对外 API 一律按 `(symbol, period, id)` 抽象**
  （`list` / `get` / `upsert` / `delete` / `clear`）。
  将来数据量大要迁 DB 附表时，**只换实现、不动任何调用方** —— UI 只认这几个方法名。

【坐标为什么存「日期」而不是「bar 序号」】
  行情页的 x 是 bar 序号，而序号会随**增量同步 / 前复权修正**整体漂移
  （新增一根 bar，后面所有序号 +1）—— 存序号等于"标注过几天自己跑偏"。
  因此持久化的是**日期字符串**（ISO，天然可按字典序排序），渲染时再用
  `DateAxis` 映射回序号；y 存真实价格（数据坐标），与缩放/数据量无关。
  这与回测页"排序后位置→原始行号映射"是同一套防漂移思路。

【零 Qt 依赖】可被离线脚本 / 未来的复盘页回放复用，也可纯 Python 单测。
"""
from __future__ import annotations

import bisect
import json
import os
import time
import uuid
from datetime import date as _date

from config import settings

ANNOTATION_FILE = "annotations.json"
SCHEMA_VERSION = 1

# 周期键：标注按 `(标的, 周期)` 分开存（§7-B3 P6 的既定设计）。
# 存进 JSON 的是**可读的规范键**（daily/weekly/monthly），而不是 UI 里的 'D'/'W'/'M'；
# 两者由 `period_key()` 双向兜住 —— 任何写法都能吃，避免"日线的线跑到周线上"这类串档。
PERIOD_DAILY = "daily"
PERIOD_WEEKLY = "weekly"
PERIOD_MONTHLY = "monthly"
PERIOD_ALIASES = {
    "D": PERIOD_DAILY, "DAY": PERIOD_DAILY, "DAILY": PERIOD_DAILY, "日": PERIOD_DAILY,
    "日线": PERIOD_DAILY,
    "W": PERIOD_WEEKLY, "WEEK": PERIOD_WEEKLY, "WEEKLY": PERIOD_WEEKLY, "周": PERIOD_WEEKLY,
    "周线": PERIOD_WEEKLY,
    "M": PERIOD_MONTHLY, "MONTH": PERIOD_MONTHLY, "MONTHLY": PERIOD_MONTHLY, "月": PERIOD_MONTHLY,
    "月线": PERIOD_MONTHLY,
}
PERIOD_LABELS = {PERIOD_DAILY: "日线", PERIOD_WEEKLY: "周线", PERIOD_MONTHLY: "月线"}


def period_key(value) -> str:
    """任意周期写法 -> 规范键（daily/weekly/monthly）；未知回落 daily。"""
    text = str(value or "").strip()
    if not text:
        return PERIOD_DAILY
    return PERIOD_ALIASES.get(text.upper(), text.lower() if text.isascii() else PERIOD_DAILY)

# 标注类型（kind）
KIND_TREND = "trend"     # 趋势线（两端点，可拖动）
KIND_HLINE = "hline"     # 水平线（一条价格位，可上下拖）
KIND_VLINE = "vline"     # 垂直线（一个日期，可左右拖）
KIND_FIB = "fib"         # 斐波那契回撤（两端点定区间，自动画多档水平位）
KIND_TEXT = "text"       # 文字标注（一个锚点 + 文字内容）
KIND_LABELS = {
    KIND_TREND: "趋势线",
    KIND_HLINE: "水平线",
    KIND_VLINE: "垂直线",
    KIND_FIB: "斐波那契",
    KIND_TEXT: "文字",
}
SUPPORTED_KINDS = (KIND_TREND, KIND_HLINE, KIND_VLINE, KIND_FIB, KIND_TEXT)
# 每类标注需要的有效锚点数（区间类两端点；其余一个锚点）
REQUIRED_POINTS = {KIND_TREND: 2, KIND_FIB: 2, KIND_HLINE: 1, KIND_VLINE: 1, KIND_TEXT: 1}
# 需要文字内容的类型（空文字没有存在意义 → 构造时直接报错，别存一条画不出东西的记录）
TEXT_REQUIRED_KINDS = (KIND_TEXT,)
DEFAULT_COLOR = "#1976D2"

# 斐波那契回撤档位（**语义常量放模型层**：渲染器、未来的导出/统计共用同一份，
# 免得"图上画 7 档、导出写 5 档"这种口径分裂）
FIB_RATIOS = (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0)


def fib_levels(points) -> list[tuple[float, float]]:
    """由两个锚点（日期, 价格）算出各档位：`[(ratio, price), ...]`。

    以**先出现的锚点**为起点、后一个为终点，按 ratio 线性插值。
    锚点非法或不足时返回空列表（调用方据此跳过绘制，绝不画半截）。
    """
    clean = [p for p in (_normalize_point(p) for p in (points if points is not None else []))
             if p is not None]
    if len(clean) != 2:
        return []
    start, end = clean[0][1], clean[1][1]
    return [(ratio, start + (end - start) * ratio) for ratio in FIB_RATIOS]


# ==========================================
# 纯函数：构造 / 归一化 / 日期工具
# ==========================================
def new_id() -> str:
    """标注 id（8 位十六进制，够短可读、够长不撞）"""
    return uuid.uuid4().hex[:8]


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def normalize_date(value) -> str:
    """任意时间表示 -> 'YYYY-MM-DD'；无法识别返回空串（调用方据此丢弃该点）。

    容忍 pandas Timestamp / datetime / 'YYYY-MM-DD HH:MM:SS' / 'YYYY-MM-DDTHH:MM'，
    一律截取前 10 个字符 —— 标注只关心"哪一天"。
    """
    text = str(value or "").strip()
    if text.lower() in ("nan", "nat", "none"):
        return ""
    return text[:10]


def _to_ordinal(value) -> int | None:
    """'YYYY-MM-DD' -> 序数（用于"最近一根 bar"的距离比较）"""
    text = normalize_date(value)
    if not text:
        return None
    try:
        return _date.fromisoformat(text).toordinal()
    except ValueError:
        return None


def _normalize_point(point) -> tuple[str, float] | None:
    """把 `[日期, 价格]` 归一化；非法返回 None（脏数据绝不入库）"""
    try:
        x, y = point
    except (TypeError, ValueError):
        return None
    label = normalize_date(x)
    try:
        price = float(y)
    except (TypeError, ValueError):
        return None
    if price != price:          # NaN
        return None
    return (label, price)


def make_annotation(symbol: str, kind: str, points, *, period: str = PERIOD_DAILY,
                    color: str = DEFAULT_COLOR, text: str = "",
                    item_id: str = "") -> dict:
    """构造一条**已归一化**的标注对象（这是全 app 唯一的构造入口）。

    :raises ValueError: 类型不支持 / 有效锚点数不符 —— 由调用方决定怎么提示，
                        绝不"静默塞一条画不出来的记录"（§10-4 诚实原则）。
    """
    kind = str(kind or "")
    if kind not in SUPPORTED_KINDS:
        raise ValueError(f"不支持的标注类型: {kind or '(空)'}")
    # ⚠ 用 `is not None` 而不是 `or []`：调用方可能直接传 pandas Series，
    # 而 Series 的布尔求值会抛 "truth value is ambiguous"（真实踩过的坑）。
    clean = [p for p in (_normalize_point(p) for p in (points if points is not None else []))
             if p is not None]
    need = REQUIRED_POINTS[kind]
    if len(clean) != need:
        raise ValueError(
            f"{KIND_LABELS[kind]}需要 {need} 个有效锚点，实际收到 {len(clean)} 个")
    text = str(text or "").strip()
    if kind in TEXT_REQUIRED_KINDS and not text:
        raise ValueError(f"{KIND_LABELS[kind]}标注需要填写内容")
    now = _now()
    return {
        "id": str(item_id) or new_id(),
        "symbol": str(symbol or "").strip(),
        "period": period_key(period),
        "kind": kind,
        "color": str(color or DEFAULT_COLOR),
        "points": [[label, price] for label, price in clean],
        "text": text,
        "created_at": now,
        "updated_at": now,
    }


class DateAxis:
    """「日期字符串 ↔ bar 序号」互转器（图表 x 轴是序号，标注按日期持久化）。

    - `date_to_index(d)`：命中同一天返回其序号；遇**停牌/缺失日**返回时间上最接近的
      那一根（保证标注仍落在可见区间内）；完全无效返回 None。
    - `index_to_date(i)`：夹到合法范围内（缩放越界时的保护），非法输入返回 ""。
    ISO 日期可按字典序/序数排序，所以内部用 `bisect`，不需要 pandas。
    """

    def __init__(self, dates=None):
        # ⚠ 不能用 `dates or []`：`dates` 常直接来自 `df['date']`（pandas Series），
        # Series 的布尔求值会抛 ValueError: truth value is ambiguous。
        self._labels = [normalize_date(d) for d in (dates if dates is not None else [])]
        self._ordinals = [_to_ordinal(label) for label in self._labels]
        pairs = sorted((ordinal, index) for index, ordinal in enumerate(self._ordinals)
                       if ordinal is not None)
        self._sorted = pairs
        self._key_ordinals = [ordinal for ordinal, _ in pairs]
        self._index_by_ordinal: dict[int, int] = {}
        for ordinal, index in pairs:
            self._index_by_ordinal.setdefault(ordinal, index)

    def __len__(self) -> int:
        return len(self._labels)

    @property
    def size(self) -> int:
        return len(self._labels)

    def date_to_index(self, value) -> float | None:
        ordinal = _to_ordinal(value)
        if ordinal is None or not self._sorted:
            return None
        exact = self._index_by_ordinal.get(ordinal)
        if exact is not None:
            return float(exact)
        pos = bisect.bisect_left(self._key_ordinals, ordinal)
        if pos <= 0:
            return float(self._sorted[0][1])
        if pos >= len(self._key_ordinals):
            return float(self._sorted[-1][1])
        low_ordinal, low_index = self._sorted[pos - 1]
        high_ordinal, high_index = self._sorted[pos]
        return float(low_index if (ordinal - low_ordinal) <= (high_ordinal - ordinal)
                     else high_index)

    def index_to_date(self, index) -> str:
        if not self._labels:
            return ""
        try:
            position = int(round(float(index)))
        except (TypeError, ValueError):
            return ""
        position = max(0, min(len(self._labels) - 1, position))
        return self._labels[position]


# ==========================================
# 仓库：按 (symbol, period, id) 组织的 JSON CRUD
# ==========================================
class AnnotationStore:
    """用户标注仓库。

    【API 与存储解耦】对外只有 list/get/upsert/delete/clear/count 这几个方法，
    调用方**不需要知道**底下是 JSON 还是 DB（§7-B3 D3：迁库只换实现）。
    """

    def __init__(self, path: str = None):
        self.path = path or os.path.join(settings.USER_DATA_DIR, ANNOTATION_FILE)
        self.items: list[dict] = []
        self.load()

    # ---------------- 持久化 ----------------
    def load(self) -> None:
        """读盘。单条坏数据只跳过它自己，绝不拖垮整库（用户数据主权优先）。"""
        self.items = []
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError) as e:
            print(f"标注库读取失败: {e}")
            return
        raw = payload.get("items") if isinstance(payload, dict) else payload
        for entry in (raw or []):
            if not isinstance(entry, dict):
                continue
            try:
                item = make_annotation(
                    entry.get("symbol"), entry.get("kind"), entry.get("points"),
                    period=entry.get("period"), color=entry.get("color"),
                    text=entry.get("text"), item_id=entry.get("id"))
            except (ValueError, TypeError, AttributeError):
                continue
            item["created_at"] = str(entry.get("created_at") or item["created_at"])
            item["updated_at"] = str(entry.get("updated_at") or item["updated_at"])
            self.items.append(item)

    def save(self) -> bool:
        """原子写：先写 `.tmp` 再 `os.replace`，崩溃/断电也不会留下半份文件。"""
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump({"version": SCHEMA_VERSION, "items": self.items},
                          handle, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
            return True
        except OSError as e:
            print(f"标注库写入失败: {e}")
            return False

    # ---------------- 查询 ----------------
    def all(self) -> list[dict]:
        return list(self.items)

    def list(self, symbol: str, period: str = PERIOD_DAILY) -> list[dict]:
        symbol, period = str(symbol or ""), period_key(period)
        return [item for item in self.items
                if item["symbol"] == symbol and item["period"] == period]

    def get(self, symbol: str, period: str, item_id: str) -> dict | None:
        symbol, period = str(symbol or ""), period_key(period)
        for item in self.items:
            if (item["id"] == item_id and item["symbol"] == symbol
                    and item["period"] == period):
                return item
        return None

    def count(self, symbol: str, period: str = PERIOD_DAILY) -> int:
        return len(self.list(symbol, period))

    def symbols(self) -> list[str]:
        """已经存过标注的标的（供"标注总览 / 复盘页复用"）"""
        return sorted({item["symbol"] for item in self.items if item["symbol"]})

    # ---------------- 写入 ----------------
    def upsert(self, item: dict) -> dict:
        """新建或更新（命中同 `(symbol, period, id)` 即覆盖）。返回落库后的对象。"""
        incoming = dict(item or {})
        clean = make_annotation(
            incoming.get("symbol"), incoming.get("kind"), incoming.get("points"),
            period=incoming.get("period"), color=incoming.get("color"),
            text=incoming.get("text"), item_id=incoming.get("id"))
        for index, existing in enumerate(self.items):
            if (existing["id"] == clean["id"]
                    and existing["symbol"] == clean["symbol"]
                    and existing["period"] == clean["period"]):
                clean["created_at"] = existing.get("created_at", clean["created_at"])
                self.items[index] = clean
                self.save()
                return clean
        self.items.append(clean)
        self.save()
        return clean

    def delete(self, symbol: str, period: str, item_id: str) -> bool:
        """删除**单个**对象 —— 这是管线 B 相对管线 A 的核心差异（§7-B3 C）。"""
        symbol, period = str(symbol or ""), period_key(period)
        before = len(self.items)
        self.items = [item for item in self.items
                      if not (item["id"] == item_id and item["symbol"] == symbol
                              and item["period"] == period)]
        removed = len(self.items) < before
        if removed:
            self.save()
        return removed

    def clear(self, symbol: str, period: str = PERIOD_DAILY) -> int:
        """清空某标的某周期的全部标注，返回删除条数。"""
        symbol, period = str(symbol or ""), period_key(period)
        keep = [item for item in self.items
                if not (item["symbol"] == symbol and item["period"] == period)]
        removed = len(self.items) - len(keep)
        if removed:
            self.items = keep
            self.save()
        return removed
