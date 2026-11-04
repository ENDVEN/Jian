# data/quality.py
"""日线数据质量闸门（★2.07 修复 bootstrap 污染）。

只做本地数值/结构校验，不联网、不猜复权口径。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["check_ohlcv"]

_REQUIRED = ("date", "open", "high", "low", "close", "volume")


def check_ohlcv(df: pd.DataFrame) -> list[str]:
    """返回问题清单；空列表 = 通过。

    拒收条件（任一）：
    - 缺列 / 空表；
    - OHLC 非正（负价会让涨跌幅/广度彻底失真）；
    - high < low / high < max(open,close) / low > min(open,close)；
    - date 重复或无法解析。
    """
    problems = []
    if df is None or df.empty:
        return ["空表"]
    missing = [c for c in _REQUIRED if c not in df.columns]
    if missing:
        return ["缺列: " + ",".join(missing)]
    data = df.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    if data["date"].isna().any():
        problems.append("date 有无法解析的值")
    if data["date"].duplicated().any():
        problems.append("date 重复")
    for col in ("open", "high", "low", "close"):
        vals = pd.to_numeric(data[col], errors="coerce")
        if vals.isna().any():
            problems.append(f"{col} 有非数值")
        if (vals <= 0).any():
            problems.append(f"{col} 有非正值")
    high = pd.to_numeric(data["high"], errors="coerce")
    low = pd.to_numeric(data["low"], errors="coerce")
    open_ = pd.to_numeric(data["open"], errors="coerce")
    close = pd.to_numeric(data["close"], errors="coerce")
    if (high < low).any():
        problems.append("high < low")
    if (high < pd.concat([open_, close], axis=1).max(axis=1)).any():
        problems.append("high 低于 open/close")
    if (low > pd.concat([open_, close], axis=1).min(axis=1)).any():
        problems.append("low 高于 open/close")
    return list(dict.fromkeys(problems))
