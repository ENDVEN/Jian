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
from core.utils import MINUTE_PERIODS, normalize_period

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
PERIOD_LABELS = {PERIOD_DAILY: "日线", PERIOD_WEEKLY: "周线", PERIOD_MONTHLY: "月线",
                 **{key: f"{key[:-1]}分钟" for key in MINUTE_PERIODS}}


def period_key(value) -> str:
    """任意周期写法 -> 规范键（`daily/weekly/monthly` + **分钟档位 `1m…60m`**）；未知回落 daily。

    ⚠ 分钟档位走 `core.utils.normalize_period`（**全 app 唯一归一入口**），
    否则 `M5` 这种写法在这里会变成 `m5`、在引擎里是 `5m` —— 两套归一必然串档。
    分钟键与日/周/月键天然不同（`5m` vs `daily`），所以「分钟画的线」不会跑到日线上。
    """
    text = str(value or "").strip()
    if not text:
        return PERIOD_DAILY
    alias = PERIOD_ALIASES.get(text.upper())
    if alias:
        return alias
    period = normalize_period(text)
    if period in MINUTE_PERIODS:
        return period
    if period in ("W", "M"):
        return PERIOD_ALIASES[period]
    # 认不出的写法：ASCII 原样小写（保持历史行为），其余回落 daily
    return text.lower() if text.isascii() else PERIOD_DAILY

# 标注类型（kind）
KIND_TREND = "trend"     # 趋势线（两端点，可拖动）
KIND_HLINE = "hline"     # 水平线（一条价格位，可上下拖）
KIND_VLINE = "vline"     # 垂直线（一个日期，可左右拖）
KIND_FIB = "fib"         # 斐波那契回撤（两端点定区间，自动画多档水平位）
KIND_TEXT = "text"       # 文字标注（一个锚点 + 文字内容）
# ---- v6.25（§7-B8 R11「30+ 类型」）：目录里"已登记未实现"的 22 种补齐 ----
#   ⚠ 每加一种，必须同时改三处：本文件的常量三件套 + `annotation_shapes.SHAPES`
#     + `annotation_catalog.ENTRIES` 的 `implemented`（有双向断言钉着）。
KIND_RAY = "ray"                     # 射线（两端点定方向，延伸到数据末尾）
KIND_CHANNEL = "channel"             # 平行通道（两端点定基线 + 第三点定宽度）
KIND_HRAY = "hray"                   # 水平射线（一个起点价位，向右延伸）
KIND_CROSS = "cross"                 # 交叉线（一个锚点，水平 + 垂直两条）
KIND_HBAND = "hband"                 # 价格带（两条价位之间的横向带）
KIND_RECT = "rect"                   # 矩形（两角点）
KIND_TRIANGLE = "triangle"           # 三角形（三个顶点）
KIND_ELLIPSE = "ellipse"             # 椭圆（外接矩形两角点）
KIND_ARROW = "arrow"                 # 箭头（两端点，末端带箭头）
KIND_FIB_EXT = "fib_ext"             # 斐波那契扩展（档位外推到 100% 之外）
KIND_FIB_FAN = "fib_fan"             # 斐波那契扇形（起点发散三条射线）
KIND_FIB_TIME = "fib_time"           # 斐波那契时间（按时间比例画竖线）
KIND_PERCENT = "percent"             # 百分比线（八等分水平位）
KIND_CYCLE = "cycle"                 # 周期线（两端点定间隔，向右等距重复）
KIND_MEASURE = "measure"             # 测量尺（两端点 + 涨跌幅/根数标签）
KIND_PRICE_MEASURE = "price_measure" # 价格测量（同一天的两个价位 + 差值标签）
KIND_TIME_RULER = "time_ruler"       # 时间尺（一个时间区间 + 根数标签）
KIND_TIME_SPAN = "time_span"         # 时间区间（竖向色带）
KIND_PRICE_TAG = "price_tag"         # 价格标签（锚定某价位，文字=价格，跟着走）
KIND_MARKER = "marker"               # 箭头标记（单点 ▲）
KIND_COMMENT = "comment"             # 评论气泡（单点 + 带边框文字）
KIND_DOTS = "dots"                   # 标记点（单点 ●）
# ---- v6.26（§7-B9 STEP 4）：目录里最后 5 种 —— 三种"降级" + 两种"依赖视图" ----
KIND_REG_CHANNEL = "reg_channel"     # 回归通道（两点定区间，对收盘价做最小二乘 + ±2σ）
KIND_FAN = "fan"                     # 甘氏扇形线（固定角度，**随缩放重算**）
KIND_FIB_ARC = "fib_arc"             # 斐波那契弧（按屏幕半径画同心弧，**随缩放重算**）
KIND_WAVE = "wave"                   # 波浪（降级：5 个拐点连成折线，用户自己标浪型）
KIND_HEAD_SHOULDER = "head_shoulder" # 头肩形态（降级：3 点 + 颈线）
KIND_LABELS = {
    KIND_TREND: "趋势线",
    KIND_HLINE: "水平线",
    KIND_VLINE: "垂直线",
    KIND_FIB: "斐波那契",
    KIND_TEXT: "文字",
    KIND_RAY: "射线",
    KIND_CHANNEL: "平行通道",
    KIND_HRAY: "水平射线",
    KIND_CROSS: "交叉线",
    KIND_HBAND: "价格带",
    KIND_RECT: "矩形",
    KIND_TRIANGLE: "三角形",
    KIND_ELLIPSE: "椭圆",
    KIND_ARROW: "箭头",
    KIND_FIB_EXT: "斐波扩展",
    KIND_FIB_FAN: "斐波扇形",
    KIND_FIB_TIME: "斐波时间",
    KIND_PERCENT: "百分比线",
    KIND_CYCLE: "周期线",
    KIND_MEASURE: "测量尺",
    KIND_PRICE_MEASURE: "价格测量",
    KIND_TIME_RULER: "时间尺",
    KIND_TIME_SPAN: "时间区间",
    KIND_PRICE_TAG: "价格标签",
    KIND_MARKER: "箭头标记",
    KIND_COMMENT: "评论气泡",
    KIND_DOTS: "标记点",
    KIND_REG_CHANNEL: "回归通道",
    KIND_FAN: "扇形线",
    KIND_FIB_ARC: "斐波弧",
    KIND_WAVE: "波浪",
    KIND_HEAD_SHOULDER: "头肩形态",
}
SUPPORTED_KINDS = (
    KIND_TREND, KIND_HLINE, KIND_VLINE, KIND_FIB, KIND_TEXT,
    KIND_RAY, KIND_CHANNEL, KIND_HRAY, KIND_CROSS, KIND_HBAND,
    KIND_RECT, KIND_TRIANGLE, KIND_ELLIPSE, KIND_ARROW,
    KIND_FIB_EXT, KIND_FIB_FAN, KIND_FIB_TIME, KIND_PERCENT,
    KIND_CYCLE, KIND_MEASURE, KIND_PRICE_MEASURE, KIND_TIME_RULER, KIND_TIME_SPAN,
    KIND_PRICE_TAG, KIND_MARKER, KIND_COMMENT, KIND_DOTS,
    KIND_REG_CHANNEL, KIND_FAN, KIND_FIB_ARC, KIND_WAVE, KIND_HEAD_SHOULDER,
)
# 每类标注需要的有效锚点数（区间/形态类多点；其余一个锚点）
REQUIRED_POINTS = {
    KIND_TREND: 2, KIND_FIB: 2, KIND_HLINE: 1, KIND_VLINE: 1, KIND_TEXT: 1,
    KIND_RAY: 2, KIND_CHANNEL: 3, KIND_HRAY: 2, KIND_CROSS: 1, KIND_HBAND: 2,
    KIND_RECT: 2, KIND_TRIANGLE: 3, KIND_ELLIPSE: 2, KIND_ARROW: 2,
    KIND_FIB_EXT: 2, KIND_FIB_FAN: 2, KIND_FIB_TIME: 2, KIND_PERCENT: 2,
    KIND_CYCLE: 2, KIND_MEASURE: 2, KIND_PRICE_MEASURE: 2,
    KIND_TIME_RULER: 2, KIND_TIME_SPAN: 2,
    KIND_PRICE_TAG: 1, KIND_MARKER: 1, KIND_COMMENT: 1, KIND_DOTS: 1,
    # 甘氏扇形 = **两点**：起点 + 参考点（这条线就是 1×1，决定方向与陡缓）
    # ★v6.29 回归通道 = **三点**（用户拍板："正常通道线应该分为三端：起点、终点、通道区间"）：
    #   p1/p2 = 拟合区间（决定用哪一段收盘价做回归）→ 中线**吸附**到回归结果上；
    #   p3 = 通道区间（到中线的距离 = 上下轨的带宽，默认 ±2σ，拖它可改）。
    KIND_REG_CHANNEL: 3, KIND_FAN: 2, KIND_FIB_ARC: 2,
    KIND_WAVE: 5, KIND_HEAD_SHOULDER: 3,
}
# 需要**用户填**文字的类型（空文字没有存在意义 → 构造时直接报错，别存一条画不出东西的记录）
TEXT_REQUIRED_KINDS = (KIND_TEXT, KIND_COMMENT)
# 文字**由坐标派生**的类型（价格标签：文字就是那个价位，拖动后自动跟着变）
AUTO_TEXT_KINDS = (KIND_PRICE_TAG,)
# 文字是**固定字形**的类型（箭头标记 / 标记点：画的是一个符号，不需要用户输入）
MARK_GLYPHS = {KIND_MARKER: "▲", KIND_DOTS: "●"}
DEFAULT_COLOR = "#1976D2"

# 斐波那契回撤档位（**语义常量放模型层**：渲染器、未来的导出/统计共用同一份，
# 免得"图上画 7 档、导出写 5 档"这种口径分裂）
FIB_RATIOS = (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0)
# 斐波那契**扩展**档位（回撤只走 0~100%，扩展要外推到 100% 之外）
FIB_EXT_RATIOS = (0.0, 0.618, 1.0, 1.618, 2.618)
# 斐波那契**扇形**的射线（占竖直距离的比例）。
# ★v6.29 用户要求："加个 1×8 的线，现在的线有点少，我个人喜欢再加个 1×8 的"
#   —— 1×8（甘氏记法）= 1/8 = 0.125，也就是**最缓的那条**（扇形外侧、代表更远的支撑/压力）。
FIB_FAN_RATIOS = (0.125, 0.382, 0.5, 0.618)
# 斐波那契**时间**的竖向分割（占时间跨度的比例）
FIB_TIME_RATIOS = (0.382, 0.5, 0.618, 1.0)
# 百分比线：八等分（与通达信"百分比线"同款，含首尾两条边界）
PERCENT_RATIOS = (0.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1.0)
# 回归通道：中线 ± N 倍标准差（**固定 2σ**；将来要给用户调，走 §7-B8 的 ⚙ 参数窗口）
REG_SIGMA = 2.0
# 甘氏扇形线的角度倍率 —— **基准 = 用户自己画的那条参考线（P1→P2 即"1×1"）**。
# 【为什么最终是这个口径（v6.28 · 用户三轮实测逼出来的）】
#   甘氏的 1×1 需要"每点价值 / 时间周期"两个要素，本软件并不知道 ⇒ 只能让**用户画出来**：
#   第 1 点 = 起点（pivot），第 2 点 = 该周期内期望的涨跌幅度 ⇒ 这条线就是 1×1，
#   其余射线按经典倍率铺开。这样：① **方向由用户定**（往上拖 = 未来压力扇形、
#   往下拖 = 未来支撑扇形，不再自动上下对称）；② **陡缓由用户定**（拖第 2 点即改比例）；
#   ③ 落库后仍可随时拖这两个点调整（这就是用户要的"可调整"）。
#   旧版"屏幕 45°"（射线全冲出画面）与"可视区间八等分"（自动对称、无法调整）都已废弃。
GANN_FACTORS = (0.125, 1 / 4, 1 / 3, 0.5, 1.0, 2.0, 3.0, 4.0, 8.0)


def gann_label(factor: float) -> str:
    """甘氏线的经典写法：`1×1` 是基准，更陡写 `N×1`，更缓写 `1×N`（用户看得懂的记号）。"""
    try:
        value = float(factor)
    except (TypeError, ValueError):
        return ""
    if abs(value - 1.0) < 1e-9:
        return "1×1"
    if value > 1:
        return f"{value:g}×1"
    return f"1×{1.0 / value:g}" if value else ""
# 斐波弧：以两点距离为半径的这几档同心弧（**依赖视图**：数据坐标里"圆"会被拉扁）
FIB_ARC_RATIOS = (0.382, 0.5, 0.618)
# 波浪（降级版）：**固定 5 个拐点** —— 刻意不做"不定长右键结束"，
#   否则"右键 = 取消"与"右键 = 结束"两条语义打架（§7-B9 C4 已记录这个取舍）
WAVE_POINTS = 5


def _interpolate(points, ratios) -> list[tuple[float, float]]:
    """两个锚点（日期, 价格）+ 一组比例 → `[(ratio, price), ...]`（各档位共用一套算法）。"""
    clean = [p for p in (_normalize_point(p) for p in (points if points is not None else []))
             if p is not None]
    if len(clean) != 2:
        return []
    start, end = clean[0][1], clean[1][1]
    return [(ratio, start + (end - start) * ratio) for ratio in ratios]


def fib_levels(points, ratios=FIB_RATIOS) -> list[tuple[float, float]]:
    """由两个锚点（日期, 价格）算出各档位：`[(ratio, price), ...]`。

    以**先出现的锚点**为起点、后一个为终点，按 ratio 线性插值。
    锚点非法或不足时返回空列表（调用方据此跳过绘制，绝不画半截）。
    ⚠ `ratios` 只是换一组档位（斐波扩展 / 百分比线走同一套算法），**不要**另写一份插值。
    """
    return _interpolate(points, ratios)


def fib_ext_levels(points) -> list[tuple[float, float]]:
    return _interpolate(points, FIB_EXT_RATIOS)


def percent_levels(points) -> list[tuple[float, float]]:
    return _interpolate(points, PERCENT_RATIOS)


def regression_channel(closes, i0, i1, sigma=REG_SIGMA) -> dict | None:
    """对 `closes[i0..i1]` 做**最小二乘**回归（回归通道的中线与带宽）。

    :return: `{"slope": 每根 bar 的斜率, "start": 区间起点拟合价, "end": 终点拟合价,
               "band": ±sigma 倍残差标准差的带宽}`；数据不够 / 有脏值 → None（本次不画）。
    ⚠ 纯函数零 Qt，放在模型层（与 `fib_levels` 同一条规矩：算法不许散进 UI）。
    """
    try:
        start, end = int(round(float(i0))), int(round(float(i1)))
    except (TypeError, ValueError):
        return None
    series = list(closes or [])
    if not series:
        return None
    if start > end:
        start, end = end, start
    start, end = max(0, start), min(len(series) - 1, end)
    # ⚠ 只要 2 根也画（退化成"两点连线 + 零带宽"）—— 少于 2 根才放弃。
    #   若要求 3 根，用户点了两个相邻的 bar 就会"点了没反应"，那是静默（§9-Q 不许）。
    if end - start < 1:
        return None
    ys = []
    for offset in range(start, end + 1):
        try:
            value = float(series[offset])
        except (TypeError, ValueError):
            return None
        if value != value:          # NaN ⇒ 不猜（§10-4）
            return None
        ys.append(value)
    count = len(ys)
    mean_x = (count - 1) / 2.0
    mean_y = sum(ys) / count
    sxx = sum((index - mean_x) ** 2 for index in range(count))
    if sxx <= 0:
        return None
    slope = sum((index - mean_x) * (y - mean_y) for index, y in enumerate(ys)) / sxx
    fitted = [mean_y + slope * (index - mean_x) for index in range(count)]
    spread = (sum((y - f) ** 2 for y, f in zip(ys, fitted)) / count) ** 0.5
    return {"slope": slope, "start": float(fitted[0]), "end": float(fitted[-1]),
            "band": float(spread * float(sigma or 0.0))}


def price_text(price) -> str:
    """价格标签的**唯一文案口径**（拖动改了价位，标签文字必须跟着变）。"""
    try:
        value = float(price)
    except (TypeError, ValueError):
        return ""
    if value != value:                      # NaN
        return ""
    return f"{value:.2f}"


def requires_text(kind: str) -> bool:
    """这种类型要不要**问用户要文字**（页面据此决定弹不弹输入框）。"""
    return str(kind or "") in TEXT_REQUIRED_KINDS


def glyph_of(kind: str) -> str:
    """固定字形类型的字符（画的是符号，不需要用户输入）；不是这类就返回空串。"""
    return MARK_GLYPHS.get(str(kind or ""), "")


def initial_text(kind: str, price=None) -> str:
    """新建时该带什么文字：用户填的留给页面问、派生的这里算、符号类给字形。"""
    kind = str(kind or "")
    if kind in AUTO_TEXT_KINDS:
        return price_text(price)
    return glyph_of(kind)


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
