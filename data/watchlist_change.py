# data/watchlist_change.py
"""自选分组的「组合当日涨跌」（§7-B8 R3）—— **零 Qt**：纯函数 + 一层带 TTL 的快照缓存。

【口径（用户 2026-09-17 拍板 · 写在这里以免以后被"顺手优化"掉）】
  · **等权平均**：把组里每只股票的当日涨跌幅**直接平均**。
    不是市值加权、也不是价格加权 —— 用户要的是"当成一只**自建基金**"，
    而在还没设权重时，"每只占 1/N"是**唯一不引入隐含假设**的选择；
  · **缺数据的票不算它**：停牌 / 还没下载 / 已退市 ⇒ **从分母里剔除**，
    **绝不拿 0% 混进去**。为什么这条必须硬：4 只票里 1 只没数据时，
    按 0% 算会把 +1.20% 冲成 +0.90% —— 用户**完全看不出来**这是假的（§5 假口径红线）；
    同时给标签打 ⚠，鼠标移上去看"是哪一只、为什么"；
  · **设了权重就按权重算**：`weights` 参数已留好，「组合配置」（R4）直接接。

【"最近一天"怎么定】= 快照里所有票里**最新的那个最后交易日**（让数据自己说话）。
  ⚠ **不用系统时钟**：那是"今天"的猜测，周末 / 节假日 / 当日 bar 未发布都会错。
  ⚠ 已知边界：整个自选只有一只票、且它已长期停牌时，"最近一天"会退化成它自己的最后一天
    ⇒ 会显示它那天的涨跌。这是"只有一只票"时的信息不足 —— **宁可有偏差也不造假**，
    不做"猜一个基准日"的伪处理。
"""
from __future__ import annotations

import time

import pandas as pd

MAX_CACHE_ENTRIES = 400          # 略大于 WatchlistStore.MAX_ITEMS(300)
DEFAULT_TTL_SECONDS = 60         # 同一分钟内反复刷新（加票/调序/切分组）零 IO

NO_DATA_REASON = "没有行情数据（还没下载？）"
TOO_SHORT_REASON = "数据不足 2 根，算不出涨跌"


# ==========================================
# 纯函数：单只 / 组合
# ==========================================
def last_bar(df):
    """最后一根日线的 `(日期字符串, 涨跌幅 or None)`。

    · 日期取 `YYYY-MM-DD`（多取一位就截掉）；
    · 涨跌幅 = 末根收盘 / 前一根收盘 − 1，**自算**（不依赖数据源给不给 pct 列）；
    · 行数不足 2 根 / 收盘价非正 ⇒ 涨跌幅为 None（**"算不出来"≠"0%"**）。
    """
    if df is None or len(df) == 0 or "close" not in getattr(df, "columns", []):
        return "", None
    closes = pd.to_numeric(df["close"], errors="coerce")
    valid = closes.notna()
    if not bool(valid.any()):
        return "", None
    frame = df.loc[valid]
    closes = closes.loc[valid]
    date = str(frame["date"].iloc[-1])[:10] if "date" in frame.columns else ""
    if len(closes) < 2:
        return date, None
    previous, last = float(closes.iloc[-2]), float(closes.iloc[-1])
    if previous <= 0:
        return date, None
    return date, (last / previous - 1.0) * 100.0


def snapshot_one(df) -> dict:
    """把一只票的日线变成快照条目：`{date, pct, reason}`（`pct is None` 时 `reason` 必有值）。"""
    date, pct = last_bar(df)
    if not date:
        return {"date": "", "pct": None, "reason": NO_DATA_REASON}
    if pct is None:
        return {"date": date, "pct": None, "reason": TOO_SHORT_REASON}
    return {"date": date, "pct": pct, "reason": ""}


def baseline_date(snapshot) -> str:
    """"最近一天" = 快照里所有票里最新的最后交易日（**空快照返回空串**，不猜）。"""
    return max((str(info.get("date") or "") for info in (snapshot or {}).values()), default="")


def group_summary(snapshot, symbols, weights=None, baseline=None) -> dict:
    """把各成员的当日涨跌合成"这个组合今天涨跌了多少"。

    :return: ``{"pct": float|None, "counted": int, "total": int, "missing": [(symbol, 原因), ...]}``
             `pct is None` ⇒ **一个都没算出来**（与"涨跌 0%"是两件事，必须能分辨）
    """
    symbols = [str(s) for s in (symbols or [])]
    snapshot = snapshot or {}
    base = baseline_date(snapshot) if baseline is None else baseline
    values, weights_used, missing = [], [], []
    for symbol in symbols:
        info = snapshot.get(symbol) or {}
        pct = info.get("pct")
        if pct is None:
            missing.append((symbol, str(info.get("reason") or NO_DATA_REASON)))
            continue
        date = str(info.get("date") or "")
        if base and date != base:
            # 停牌 / 尚未下载到最新一天 ⇒ **不算它**（绝不用"它上一次的涨跌"冒充今天的）
            missing.append((symbol, f"最后一天是 {date or '—'}（不是 {base}）"))
            continue
        values.append(float(pct))
        weights_used.append(float((weights or {}).get(symbol, 1.0)))
    if not values:
        return {"pct": None, "counted": 0, "total": len(symbols), "missing": missing}
    total_weight = sum(weights_used)
    if weights and total_weight > 0:
        pct = sum(value * weight for value, weight in zip(values, weights_used)) / total_weight
    else:
        pct = sum(values) / len(values)          # ★ 等权：每只占 1/N
    return {"pct": pct, "counted": len(values), "total": len(symbols), "missing": missing}


def format_pct(pct) -> str:
    """`+0.82%` / `−0.31%` / `0.00%`；`None` ⇒ **空串**。

    ⚠ `None` 绝不用 "0.00%" 代替 —— 那是把"算不出来"伪装成"没涨没跌"。
    负号用 U+2212（等宽，不会与数字挤在一起）。
    """
    if pct is None:
        return ""
    value = float(pct)
    if abs(value) < 0.005:
        return "0.00%"
    return f"{'+' if value > 0 else '−'}{abs(value):.2f}%"


def direction_of(pct):
    """给颜色用：`True` 涨 / `False` 跌 / `None` 平。

    ⚠ 平**不是涨**：把 0.00% 画成绿的会让人以为它在涨。
    """
    if pct is None:
        return None
    value = float(pct)
    if abs(value) < 0.005:
        return None
    return value > 0


# ==========================================
# 快照缓存（避免每次刷新都读一遍 N 份日线）
# ==========================================
class ChangeSnapshot:
    """"每只票当日涨跌"的带 TTL 快照。

    【为什么必须有这层】`_refresh_watchlist` 会被**很多用户动作**触发
    （加票 / 删票 / 调序 / 切分组 / 双击切标的），每次都重读 N 份日线 ⇒ 面板一顿一顿的。
    这层把"同一分钟内反复刷新"变成零 IO。
    ⚠ 缓存**按 symbol 存**、不按分组存：切分组换的是"取哪些票"，不是"每只多少"。
    """

    def __init__(self, loader, ttl_seconds: float = DEFAULT_TTL_SECONDS):
        self._loader = loader
        self._ttl = float(ttl_seconds)
        self._cache: dict = {}

    def clear(self) -> None:
        """外部数据更新过（同步完成 / 换复权）时清一次 —— 否则会拿旧读数。"""
        self._cache.clear()

    def cached_count(self) -> int:
        return len(self._cache)

    def build(self, symbols, force: bool = False) -> dict:
        """取这些票的快照（命中缓存则零 IO）。返回 `{symbol: {date, pct, reason}}`。"""
        now = time.time()
        result = {}
        for symbol in symbols:
            symbol = str(symbol)
            hit = self._cache.get(symbol)
            if hit is not None and not force and (now - hit[0]) < self._ttl:
                result[symbol] = hit[1]
                continue
            result[symbol] = self._load_one(symbol)
            self._cache[symbol] = (now, result[symbol])
        self._prune(set(result), now)
        return result

    def _load_one(self, symbol: str) -> dict:
        try:
            return snapshot_one(self._loader(symbol))
        except Exception as e:          # noqa: BLE001 —— 单只读失败不该让整页刷不出来
            return {"date": "", "pct": None, "reason": f"读取失败：{e}"}

    def _prune(self, alive: set, now: float) -> None:
        """清掉"既不在本次名单里、又已过期"的条目（防缓存无限长胖）。"""
        self._cache = {key: value for key, value in self._cache.items()
                       if key in alive or (now - value[0]) < self._ttl}
        if len(self._cache) > MAX_CACHE_ENTRIES:
            newest = sorted(self._cache.items(), key=lambda kv: kv[1][0], reverse=True)
            self._cache = dict(newest[:MAX_CACHE_ENTRIES])
