# core/scan_filters.py
"""扫描阈值 / 帧准备 / 读数人话（★2.04 / P2 拆件）。

从 `core/cross_section.py` 抽出：`ScanThresholds`、读列、帧准备、金额/市值展示。
粗筛的逐行掩码仍在 `cross_section.py`（与状态码/结果类强耦合）；本模块零 UI、零 IO。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

__all__ = ["ScanThresholds", "prepare_frame", "columns_for",
           "human_amount", "human_mktcap", "_BASE_COLUMNS"]

# 读数基线列（`amount` 恒读：既是最常用的阈值，也是最常用的展示列）
_BASE_COLUMNS = ('date', 'open', 'high', 'low', 'close', 'volume', 'amount')


@dataclass
class ScanThresholds:
    """粗筛阈值。**关掉 = 不参与漏斗**：数值项填 `None`、布尔项填 `False`。

    ⚠ `min_bars` / 缺列 的失败算「**数据不足**」，其余算「**被粗筛剔除**」——
      这条分界是 §三态铁律的落地：新上市股不是"没命中"，是"没法判定"。
    """

    min_amount: float | None = 5e7          # 成交额 ≥（元）
    min_price: float | None = 2.0           # 收盘价 ≥（元）
    min_bars: int | None = 250              # 有效数据 ≥（个交易日）
    exclude_suspended: bool = True          # 剔除停牌（volume > 0）
    exclude_st: bool = True                 # 剔除 ST / 退市（按**当前**名称，历史不可追溯）
    exclude_limit: bool = True              # 剔除一字板（high == low）
    min_turnover: float | None = None       # 换手率 ≥（**小数口径**：0.0093 = 0.93%）
    min_float_mktcap: float | None = None   # 流通市值 ≥（元）
    max_float_mktcap: float | None = None   # 流通市值 ≤（元）
    min_change_pct: float | None = None     # 涨跌幅 ≥（小数：0.05 = +5%）
    max_change_pct: float | None = None     # 涨跌幅 ≤（小数）

    # ---------- 序列化（preferences 落盘 / 还原） ----------
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw) -> 'ScanThresholds':
        """从偏好还原。**坏数据逐字段回落默认**（§9-D：一条坏偏好不能拖垮整页）。

        ⚠ 数值项显式 `None` = **"关掉这一项"**，必须能存回来（`min_bars` 默认 250 也允许变 None，
          否则用户"关掉上市天数过滤"下次打开又自己长回来 —— 这类"记不住"最招人烦）。
        """
        out = cls()
        if not isinstance(raw, dict):
            return out
        for key, default in out.to_dict().items():
            if key not in raw:
                continue
            value = raw[key]
            if isinstance(default, bool):          # 注意：bool 是 int 的子类，必须先判
                setattr(out, key, bool(value))
                continue
            if value is None:
                setattr(out, key, None)            # 显式关闭（数值项）
                continue
            convert = int if isinstance(default, int) else float
            try:
                setattr(out, key, convert(value))
            except (TypeError, ValueError):
                continue                           # 转不动 ⇒ 保留默认，绝不抛
        return out

    def problems(self) -> list[str]:
        """自检：给界面用的**非阻断**提示（不抛异常，避免一个笔误让整页打不开）。"""
        bad = []
        if self.min_price is not None and self.min_price < 0:
            bad.append('价格下限不能为负')
        if self.min_amount is not None and self.min_amount < 0:
            bad.append('成交额下限不能为负')
        if self.min_bars is not None and self.min_bars < 0:
            bad.append('有效数据天数不能为负')
        if (self.min_change_pct is not None and self.max_change_pct is not None
                and self.min_change_pct > self.max_change_pct):
            bad.append('涨跌幅下限大于上限')
        if (self.min_float_mktcap is not None and self.max_float_mktcap is not None
                and self.min_float_mktcap > self.max_float_mktcap):
            bad.append('流通市值下限大于上限')
        return bad

    def reset(self) -> 'ScanThresholds':
        """「↺ 恢复默认」（界面按钮的后端；返回新对象，不改调用方）"""
        return ScanThresholds()


def prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    """日线 df → 引擎可直接吃的帧。

    ★ **与 `core/backtest.py:BacktestEngine.run` 的数据准备一字不差** —— M1/M2/M3 必须同口径，
      改这里就要同步改那里（`tests/smoke_chart.py` 有一致性断言钉住）。
    """
    if df is None or len(df) == 0 or 'date' not in df.columns:
        return pd.DataFrame()
    data = df.copy()
    data['date'] = pd.to_datetime(data['date'])
    data = data.sort_values('date').reset_index(drop=True)
    for col in ('open', 'high', 'low', 'close', 'volume'):
        if col in data.columns:
            data[col] = pd.to_numeric(data[col], errors='coerce')
    data = data.dropna(subset=['close', 'open'])
    return data


def columns_for(thresholds: ScanThresholds, snapshot_columns=()) -> tuple[str, ...]:
    """本次扫描要从湖里读哪些列（**按需裁剪**；缺列由逐标的判定兜住，§9.1）"""
    cols = list(_BASE_COLUMNS)
    if thresholds.min_turnover is not None:
        cols.append('turnover')
    if thresholds.min_float_mktcap is not None or thresholds.max_float_mktcap is not None:
        cols.append('outstanding_share')
    cols.extend(snapshot_columns or ())
    return tuple(dict.fromkeys(cols))


def human_amount(value: float) -> str:
    value = float(value)
    if abs(value) >= 1e8:
        return f'{value / 1e8:g} 亿元'
    if abs(value) >= 1e4:
        return f'{value / 1e4:g} 万元'
    return f'{value:g} 元'


def human_mktcap(value: float) -> str:
    return human_amount(value)
