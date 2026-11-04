# data/em_history.py
"""东财单只历史直连（登录档，★2.06 / DATA-PLATFORM P2）。

为什么需要它：`akshare.stock_zh_a_hist` **不带我们的登录 Cookie**，登录档仍被 RST；
本模块走 `em_market._http_get`（唯一 HTTP 出口，自动带 Cookie/代理策略/预算记账）。

口径：
- `push2his` 一次可拿全历史（实测 100 只 × 2010 起 / K=16 = 7.06s、0 错误）；
- 成交量 `f56` = 手 ⇒ ×100 成股；amount `f57` = 元；
- **每日预算 300 次**：预算用完返回空表，由上层回退；绝不绕过风控。
"""
from __future__ import annotations

import logging

import pandas as pd

from data import em_auth, em_market
from data.quality import check_ohlcv

logger = logging.getLogger(__name__)

__all__ = ["fetch_daily", "parse_klines"]

_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
_F1 = "f1,f2,f3,f4,f5,f6"
_F2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"


def parse_klines(rows, symbol: str) -> pd.DataFrame:
    """`klines` 字符串列表 → 标准 OHLCV；坏行跳过。"""
    out = []
    for line in rows or []:
        parts = str(line).split(",")
        if len(parts) < 7:
            continue
        try:
            out.append({
                "date": pd.Timestamp(parts[0]),
                "open": float(parts[1]),
                "close": float(parts[2]),
                "high": float(parts[3]),
                "low": float(parts[4]),
                "volume": float(parts[5]) * 100.0,   # 手 → 股
                "amount": float(parts[6]),
                "symbol": str(symbol).strip(),
            })
        except (TypeError, ValueError):
            continue
    if not out:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close",
                                     "volume", "amount", "symbol"])
    return pd.DataFrame(out).sort_values("date").reset_index(drop=True)


def fetch_daily(symbol: str, start_date: str | None = None,
                end_date: str | None = None, adjust: str = "qfq",
                allow_over_budget: bool = False) -> pd.DataFrame:
    """登录档单只历史；未登录/预算用完/接口失败一律回空表。

    `allow_over_budget=True` 只给一次性 bootstrap 脚本用；请求不计入日预算，
    且脚本必须先通过 `data.bootstrap_once` 的 arm/consume 授权。
    """
    if not em_auth.is_logged_in():
        return pd.DataFrame()
    if not allow_over_budget:
        try:
            if em_auth.budget_left("auth") <= 0:
                logger.info("东财登录预算已用完，跳过直连历史 [%s]", symbol)
                return pd.DataFrame()
        except Exception:  # noqa: BLE001
            pass
    params = {
        "secid": em_market.secid(symbol),
        "ut": em_market.EM_UT,
        "fields1": _F1,
        "fields2": _F2,
        "klt": 101,
        "fqt": 1 if str(adjust) == "qfq" else 0,
        "beg": str(start_date or "20100101").replace("-", ""),
        "end": str(end_date or "20500101").replace("-", ""),
        "lmt": 10000,
    }
    try:
        obj = em_market._http_get(_URL, params, kind="kline_hist",
                                  billable=not allow_over_budget)
        rows = (((obj or {}).get("data") or {}).get("klines") or [])
        out = parse_klines(rows, symbol)
        problems = check_ohlcv(out)
        if problems:
            logger.warning("东财历史质量拒收 [%s]: %s", symbol, "；".join(problems[:3]))
            return pd.DataFrame()
        return out
    except Exception as e:  # noqa: BLE001 —— 直连失败由上层降级
        logger.info("东财直连历史失败 [%s]: %s", symbol, e)
        return pd.DataFrame()
