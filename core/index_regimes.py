# core/index_regimes.py
"""
参数稳健性研究（§7-B15）· 上证指数切块（SW-2）。

把上证指数日线切成「单边上涨 / 单边下跌 / 震荡箱体」段，再配成**成对区间**
（样本内段 → 样本外段），给参数研究的"区间预设"下拉与切块时间轴用
（方案书 §3 步4 / §4 图①；默认预设 = 震荡→震荡，§11 决议 4）。

口径（与 docs/JIAN_SWEEP_PLAN.md 同源，改动必须两边同步）：
- **切块算法（透明、可复现，§8-14）**：滚动 window 日涨跌幅 r = close/close.shift(window)−1；
  r ≥ up_thr ⇒ up，r ≤ down_thr ⇒ down，其余 ⇒ sideways；前 window 天无窗口 ⇒ 不标记；
  同状态连续日合并成段，**短于 min_len 的毛刺整段丢弃**（诚实：不成段就不进预设）。
  四个参数写进缓存 payload —— 同一份数据 + 同一组参数 ⇒ 段边界逐字一致。
- **配对规则**：① 同状态相邻两次出现（R_k → R_{k+1}，如 震荡→震荡）；② 跨状态 =
  IS 段结束后**第一个**对应状态的段（牛→紧随的熊 / 熊→紧随的牛）。
  任何配对 OOS 都严格晚于 IS（不发生时间穿越；SW-0 的 validate_interval 有跨模块断言）。
- **缓存**：`~/.jian_data/index_regimes.json`（tmp + os.replace 原子写）；命中判据 =
  数据末日 + 参数全等。路径可注入 —— 冒烟必须重定向到临时目录（§11.5-70 防污染）。
- 本模块**零 Qt 零网络**；指数序列由调用方喂（脚本 / UI 从数据湖 `index_daily` 分区读，
  符号 = 带前缀的 `sh000001`，§11.5-62 两套代码约定里的日线侧）。
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from config import settings

#: 指数日线的分区名与上证指数文件名（`data/market_db.py` zones / `INDEX_PRESETS` 同源）
ZONE_INDEX = "index_daily"
SHANGHAI_INDEX_SYMBOL = "sh000001"

#: 默认切块参数（脚本可用命令行覆盖；改参数 ⇒ 缓存键变 ⇒ 必然重算）
DEFAULT_WINDOW = 60        # 滚动窗口（交易日）
DEFAULT_UP_THR = 0.10      # 窗口涨跌幅 ≥ +10% ⇒ 单边上涨
DEFAULT_DOWN_THR = -0.10   # 窗口涨跌幅 ≤ −10% ⇒ 单边下跌
DEFAULT_MIN_LEN = 40       # 段最短交易日数（更短的毛刺不成段）

REGIME_LABELS = {"up": "单边上涨", "down": "单边下跌", "sideways": "震荡箱体"}

CACHE_FILENAME = "index_regimes.json"


@dataclass(frozen=True)
class RegimeSegment:
    """一段连续同状态区间（日期均为 'YYYY-MM-DD'，n_days 含首尾）。"""

    regime: str
    start: str
    end: str
    n_days: int


@dataclass(frozen=True)
class IntervalPreset:
    """一个成对区间预设（喂给 sweep_plan.StudyInterval 前不再换算）。"""

    key: str          # 机器键，如 "sideways>sideways" / "fold" / "year"
    label: str        # 人话（§10-10：动作动词 + 用户能猜到的对象）
    is_start: str
    is_end: str
    oos_start: str
    oos_end: str
    default: bool = False


# ==========================================
# 切块（纯计算）
# ==========================================
def classify_regimes(close, *, window: int = DEFAULT_WINDOW,
                     up_thr: float = DEFAULT_UP_THR,
                     down_thr: float = DEFAULT_DOWN_THR,
                     min_len: int = DEFAULT_MIN_LEN) -> list[RegimeSegment]:
    """收盘价序列 → 状态段列表（可复现：同序列同参数 ⇒ 同边界）。"""
    if window < 2:
        raise ValueError(f"滚动窗口必须 ≥ 2 个交易日（收到 {window}）")
    if min_len < 1:
        raise ValueError(f"段最短交易日数必须 ≥ 1（收到 {min_len}）")
    if up_thr <= down_thr:
        raise ValueError(f"上涨阈值（{up_thr}）必须大于下跌阈值（{down_thr}）")
    s = pd.Series(close, dtype=float).dropna()
    s.index = pd.to_datetime(s.index)
    s = s.sort_index()
    if len(s) <= window:
        return []                      # 不够一个窗口：诚实空，不硬切
    r = (s / s.shift(window) - 1.0).to_numpy()
    labels = np.where(r >= up_thr, "up", np.where(r <= down_thr, "down", "sideways"))
    labels[~np.isfinite(r)] = ""       # 前 window 天（NaN）不标记
    dates = s.index
    segments: list[RegimeSegment] = []
    i, n = 0, len(s)
    while i < n:
        lb = labels[i]
        if not lb:
            i += 1
            continue
        j = i
        while j + 1 < n and labels[j + 1] == lb:
            j += 1
        if j - i + 1 >= min_len:
            segments.append(RegimeSegment(lb, str(dates[i].date()),
                                          str(dates[j].date()), int(j - i + 1)))
        i = j + 1
    return segments


def build_regime_pairs(segments) -> list[IntervalPreset]:
    """状态段 → 成对区间预设（见模块 docstring 的配对规则）。"""
    segs = list(segments)
    by_regime: dict[str, list[RegimeSegment]] = {}
    for s in segs:
        by_regime.setdefault(s.regime, []).append(s)
    pairs: list[IntervalPreset] = []

    def _pair(key_regime: str, other: str, a: RegimeSegment, b: RegimeSegment) -> IntervalPreset:
        return IntervalPreset(
            key=f"{a.regime}>{b.regime}",
            label=f"{REGIME_LABELS[a.regime]}里调 · "
                  f"{'下一段' if key_regime == other else '紧随的'}{REGIME_LABELS[b.regime]}里验",
            is_start=a.start, is_end=a.end, oos_start=b.start, oos_end=b.end)

    # ① 同状态相邻两次出现（震荡→震荡 / 牛→牛 / 熊→熊）
    for regime, lst in by_regime.items():
        for a, b in zip(lst, lst[1:]):
            pairs.append(_pair(regime, regime, a, b))
    # ② 跨状态：牛→紧随的熊 / 熊→紧随的牛
    for a_regime, b_regime in (("up", "down"), ("down", "up")):
        for a in by_regime.get(a_regime, []):
            nxt = next((b for b in by_regime.get(b_regime, []) if b.start > a.end), None)
            if nxt is not None:
                pairs.append(_pair(a_regime, b_regime, a, nxt))

    # 默认 = 最近一段「震荡→震荡」（常态研究，§11 决议 4）；没有就退最近的其他配对
    same = [p for p in pairs if p.key == "sideways>sideways"]
    pool = same or pairs
    if pool:
        latest = max(pool, key=lambda p: (p.oos_end, p.oos_start))
        pairs = [p if p is not latest else replace_default(p) for p in pairs]
    return pairs


# ==========================================
# 预设的"组织"（★R2：下拉不许再平铺几十条）
# ==========================================
#: **口径**（类型下拉的条目）：(机器键, 人话标签, 为什么选它)。
#: 键就是 `build_regime_pairs` 产出的成对键（`up>down` / `down>up` / `sideways>sideways`）。
#: 用户 2026-10-01 口径："单边上涨 / 单边下跌 / 震荡 / 取近 N 组 / 自定义时间就好"。
PAIR_KINDS: tuple[tuple[str, str, str], ...] = (
    ("up>down", "单边上涨 → 紧随的下跌段（压力测试）",
     "牛市里赚钱的参数，熊市还灵吗"),
    ("down>up", "单边下跌 → 紧随的上涨段（反转测试）",
     "熊市里扛住的参数，反弹时先起来吗"),
    ("sideways>sideways", "震荡箱体 → 下一段震荡箱体（常态）",
     "同样环境、不同时点，最贴近平时"),
)
DEFAULT_KIND = "sideways>sideways"      # 首次打开的口径 = 常态研究（§11 决议 4）


def windows_of(presets, kind: str, recent_n: int | None = None) -> list[IntervalPreset]:
    """某**口径**下的窗口列表（**按时间倒序**：`oos_end` 新的在前），可只取最近 N 个。

    ⚠ 顺序 = "取近 N 组"的语义：第一条永远是**最近**的那对窗口。
    `recent_n=None` / ≤0 = 全部。
    ⚠ 一律**按对象筛、按日期排**，绝不按 `key` 反查 —— key 在缓存里重复几十条
      （`sideways>sideways` × 40+），按 key 找永远命中第一条（§11.5-112 ③）。
    """
    rows = [p for p in (presets or []) if str(getattr(p, "key", "")) == str(kind)]
    rows.sort(key=lambda p: (str(p.oos_end), str(p.oos_start)), reverse=True)
    try:
        n = int(recent_n) if recent_n is not None else 0
    except (TypeError, ValueError):
        n = 0
    return rows[:n] if n > 0 else rows


def preset_for_kind(presets, kind: str) -> IntervalPreset | None:
    """该口径**最近的一对**窗口（没有 ⇒ None，调用方必须诚实提示而不是硬套）。"""
    rows = windows_of(presets, kind)
    return rows[0] if rows else None


def kind_entries(presets) -> list[dict]:
    """口径下拉的条目（3 类；"自定义"由 UI 追加）—— 每类带"最近一对"与一句 `why`。"""
    return [{"kind": kind, "label": label, "why": why,
             "preset": preset_for_kind(presets, kind)}
            for kind, label, why in PAIR_KINDS]


def close_series(df) -> pd.Series | None:
    """指数日线 DataFrame → 收盘价 Series（索引 = 日期，升序）；缺 date/close 或缺数据 ⇒ None。

    诚实空：**绝不造数据**（§10-4）。列名判定与 `scripts/analyze_index_regimes.py` 同一口径。
    """
    if df is None or getattr(df, "empty", True):
        return None
    if "date" not in df.columns or "close" not in df.columns:
        return None
    s = pd.Series(df["close"].to_numpy(dtype=float),
                  index=pd.to_datetime(df["date"])).sort_index()
    return s.dropna()


def index_close_from_lake(lake, zone: str = ZONE_INDEX,
                          symbol: str = SHANGHAI_INDEX_SYMBOL) -> pd.Series | None:
    """从数据湖取上证指数收盘 Series（**页面与离线脚本共用这一个取口**）。

    `lake` 用**鸭子类型**（只要 `exists` / `load_data`）—— 这样 core 不 import data 层，
    方向不变（§10 分层）；没有数据 / 缺列 ⇒ None，调用方负责说人话（指引去预下载）。
    """
    try:
        if not lake.exists(zone, symbol):
            return None
    except Exception:  # noqa: BLE001 —— 数据湖不可用 ⇒ 当作没有（诚实空）
        return None
    return close_series(lake.load_data(zone, symbol))


def replace_default(p: IntervalPreset) -> IntervalPreset:
    """把一个预设标记为默认（dataclass frozen ⇒ 重建）。"""
    return IntervalPreset(p.key, p.label, p.is_start, p.is_end, p.oos_start, p.oos_end, True)


def fold_pair(data_start: str, data_end: str) -> IntervalPreset | None:
    """内置预设「时间对折」：数据范围按日历中点拆两半（前半调 / 后半验）。"""
    try:
        a = date.fromisoformat(str(data_start))
        b = date.fromisoformat(str(data_end))
    except ValueError:
        return None
    if b <= a:
        return None
    mid = a + (b - a) / 2
    return IntervalPreset("fold", "时间对折：前半段调 · 后半段验",
                          str(a), str(mid), str(mid + timedelta(days=1)), str(b))


def year_pair(year: int) -> IntervalPreset | None:
    """内置预设「某一年份」：上半年调 / 下半年验（是否落在数据范围内由 validate_interval 把关）。"""
    try:
        y = int(year)
    except (TypeError, ValueError):
        return None
    return IntervalPreset("year", f"{y} 年：上半年调 · 下半年验",
                          f"{y}-01-01", f"{y}-06-30", f"{y}-07-01", f"{y}-12-31")


# ==========================================
# 缓存（本地 JSON，原子写；路径可注入以便冒烟隔离）
# ==========================================
def cache_path() -> str:
    return os.path.join(settings.USER_DATA_DIR, CACHE_FILENAME)


def compute_payload(close, *, window: int = DEFAULT_WINDOW,
                    up_thr: float = DEFAULT_UP_THR,
                    down_thr: float = DEFAULT_DOWN_THR,
                    min_len: int = DEFAULT_MIN_LEN) -> dict:
    """切块 + 配对 + 参数/数据末日，一并装进可落盘的 payload。"""
    segments = classify_regimes(close, window=window, up_thr=up_thr,
                                down_thr=down_thr, min_len=min_len)
    s = pd.Series(close, dtype=float).dropna()
    s.index = pd.to_datetime(s.index)
    s = s.sort_index()
    return {
        "version": 1,
        "params": {"window": int(window), "up_thr": float(up_thr),
                   "down_thr": float(down_thr), "min_len": int(min_len)},
        "data_start": str(s.index.min().date()) if len(s) else "",
        "data_end": str(s.index.max().date()) if len(s) else "",
        "segments": [asdict(x) for x in segments],
        "presets": [asdict(x) for x in build_regime_pairs(segments)],
    }


def load_cache(path: str | None = None) -> dict | None:
    """读缓存；缺文件 / 坏 JSON ⇒ None（诚实降级，绝不抛给调用方）。"""
    p = path or cache_path()
    try:
        with open(p, encoding="utf-8") as f:
            payload = json.load(f)
        return payload if isinstance(payload, dict) else None
    except (OSError, ValueError):
        return None


def save_cache(payload: dict, path: str | None = None) -> None:
    """tmp + os.replace 原子写（全站唯一的落盘姿势）。"""
    p = path or cache_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = f"{p}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _params_key(params: dict) -> str:
    return json.dumps(json.loads(json.dumps(dict(params))), sort_keys=True)


def cache_hit(payload, data_end: str, params: dict) -> bool:
    """命中判据 = 数据末日 + 参数全等（§8-14：参数一变 ⇒ 键变 ⇒ 必然重算）。"""
    if not isinstance(payload, dict):
        return False
    if str(payload.get("data_end") or "") != str(data_end or ""):
        return False
    try:
        return _params_key(payload.get("params") or {}) == _params_key(params)
    except (TypeError, ValueError):
        return False


def ensure_payload(close, *, path: str | None = None, force: bool = False,
                   window: int = DEFAULT_WINDOW, up_thr: float = DEFAULT_UP_THR,
                   down_thr: float = DEFAULT_DOWN_THR,
                   min_len: int = DEFAULT_MIN_LEN) -> tuple[dict, bool]:
    """带缓存的取件口：命中直接返回，未命中现算 + 落盘。返回 (payload, 是否命中缓存)。"""
    params = {"window": int(window), "up_thr": float(up_thr),
              "down_thr": float(down_thr), "min_len": int(min_len)}
    data_end = ""
    if not force:
        s = pd.Series(close, dtype=float).dropna()
        if len(s):
            data_end = str(pd.to_datetime(s.index).max().date())
            cached = load_cache(path)
            if cache_hit(cached, data_end, params):
                return cached, True
    payload = compute_payload(close, **params)
    save_cache(payload, path)
    return payload, False
