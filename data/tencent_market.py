# data/tencent_market.py
"""腾讯历史日线备源（★2.06 / DATA-PLATFORM P2）。

只用于**增量/近年**（接口单次最多 640 根）；全历史仍走新浪/东财。
实测：`qfqday` 行 = [date, open, close, high, low, volume(手)]；
成交量 ×100 成股，amount 该源不提供（保持缺列，绝不填 0）。
"""
from __future__ import annotations

import logging

import pandas as pd
import requests

logger = logging.getLogger(__name__)

__all__ = ["fetch_daily", "parse_payload"]

_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
_LIMIT = 640


def _key(symbol: str) -> str:
    code = str(symbol).strip()
    if code.startswith(("920", "43", "83", "87", "88")):
        return "bj" + code
    return ("sh" if code[:1] in ("5", "6", "9") else "sz") + code


def _iso(day: str) -> str:
    text = str(day or "").strip()
    if "-" in text:
        return text[:10]
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}" if len(text) >= 8 else ""


def parse_payload(obj: dict, symbol: str, adjust: str = "qfq") -> pd.DataFrame:
    """解析腾讯 JSON；行长度可能 6/7，多余列忽略。"""
    key = _key(symbol)
    node = ((obj or {}).get("data") or {}).get(key) or {}
    rows = node.get("qfqday") if str(adjust) == "qfq" else node.get("day")
    rows = rows or []
    out = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        try:
            out.append({
                "date": pd.Timestamp(str(row[0])),
                "open": float(row[1]),
                "close": float(row[2]),
                "high": float(row[3]),
                "low": float(row[4]),
                "volume": float(row[5]) * 100.0,   # 腾讯 = 手
                "symbol": str(symbol).strip(),
            })
        except (TypeError, ValueError):
            continue
    if not out:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close",
                                     "volume", "symbol"])
    return pd.DataFrame(out).sort_values("date").reset_index(drop=True)


def fetch_daily(symbol: str, start_date: str = None, end_date: str = None,
                adjust: str = "qfq", timeout: float = 15.0) -> pd.DataFrame:
    """腾讯历史日线；失败返回空表（由调用方继续降级）。"""
    key = _key(symbol)
    start = _iso(start_date) if start_date else ""
    end = _iso(end_date) if end_date else ""
    adj = "qfq" if str(adjust) == "qfq" else ""
    url = f"{_URL}?param={key},day,{start},{end},{_LIMIT},{adj}"
    try:
        r = requests.get(url, timeout=timeout,
                         headers={"Referer": "https://gu.qq.com/"})
        r.raise_for_status()
        df = parse_payload(r.json(), symbol, adjust)
    except Exception as e:  # noqa: BLE001 —— 备源失败不抛
        logger.info("腾讯日线备源失败 [%s]: %s", symbol, e)
        return pd.DataFrame()
    if df.empty:
        return df
    if start_date:
        df = df[df["date"] >= pd.Timestamp(_iso(start_date))]
    if end_date:
        df = df[df["date"] <= pd.Timestamp(_iso(end_date))]
    return df.reset_index(drop=True)
