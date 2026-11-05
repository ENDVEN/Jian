# data/sina_market.py
"""新浪批量报价（★2.06 / DATA-PLATFORM P2 备源）。

只做**当前报价**（不是历史），用于东财 `ulist` 失败时的匿名回退：
  `https://hq.sinajs.cn/list=sh600000,sz000001,...`
实测 2026-11-05：HTTP 200、GBK 编码、100 只/批可用。

字段口径（新浪顺序）：
  name, open, prev_close, close, high, low, bid, ask, volume, amount, ..., date, time
单位：volume = 股、amount = 元（与数据湖标准列一致）。
"""
from __future__ import annotations

import logging
import os
import re

import pandas as pd
import requests

logger = logging.getLogger(__name__)

__all__ = ["fetch_batch_quotes", "parse_batch"]

_HEADERS = {"Referer": "https://finance.sina.com.cn/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
_CHUNK = 100
_RE = re.compile(r'var hq_str_([a-z]{2}\d{6})="(.*?)";')
_SCHED = None


def _fetch_scheduled(url, timeout):
    """新浪 HTTP 边界；JIAN_SCHEDULER=0 回退裸 requests。"""
    global _SCHED
    if os.environ.get("JIAN_SCHEDULER", "1") == "0":
        return requests.get(url, headers=_HEADERS, timeout=timeout)
    if _SCHED is None:
        from data.scheduler import ChannelPolicy, Scheduler
        _SCHED = Scheduler(policies=[ChannelPolicy("sina", max_concurrency=2)])
    return _SCHED.call(
        "sina", lambda: requests.get(url, headers=_HEADERS, timeout=timeout),
        max_wait=1.0)


def _sina_key(symbol: str) -> str:
    code = str(symbol).strip()
    # 北交所：920 新段 + 43/83/87/88 老段；不能按首位 9 当沪市
    if code.startswith(("920", "43", "83", "87", "88")):
        return "bj" + code
    return ("sh" if code[:1] in ("5", "6", "9") else "sz") + code


def _num(value):
    try:
        out = float(value)
        return out if out == out else None
    except (TypeError, ValueError):
        return None


def parse_batch(text: str) -> pd.DataFrame:
    """解析新浪返回文本（已解码）→ 标准报价列；坏行跳过。"""
    rows = []
    for key, body in _RE.findall(text or ""):
        parts = body.split(",")
        if len(parts) < 10 or not parts[0]:
            continue
        sym = key[2:]
        rows.append({
            "symbol": sym,
            "name": parts[0],
            "open": _num(parts[1]),
            "prev_close": _num(parts[2]),
            "close": _num(parts[3]),
            "high": _num(parts[4]),
            "low": _num(parts[5]),
            "volume": _num(parts[8]),
            "amount": _num(parts[9]),
        })
    if not rows:
        return pd.DataFrame(columns=["symbol", "name", "open", "prev_close", "close",
                                     "high", "low", "volume", "amount"])
    df = pd.DataFrame(rows)
    df = df[df["close"].fillna(0) > 0]
    return df.reset_index(drop=True)


def fetch_batch_quotes(symbols, chunk: int = _CHUNK, timeout: float = 15.0,
                       should_stop=None) -> pd.DataFrame:
    """按 100 只/批取当前报价；失败返回已拿到的部分（空表 = 一个都没拿到）。"""
    codes = [str(s).strip() for s in (symbols or []) if str(s).strip()]
    codes = list(dict.fromkeys(codes))
    frames = []
    for i in range(0, len(codes), max(1, int(chunk))):
        if should_stop is not None and should_stop():
            break
        batch = codes[i:i + chunk]
        url = "https://hq.sinajs.cn/list=" + ",".join(_sina_key(s) for s in batch)
        try:
            r = _fetch_scheduled(url, timeout)
            r.raise_for_status()
            text = r.content.decode("gbk", errors="replace")
            df = parse_batch(text)
            if not df.empty:
                frames.append(df)
        except Exception as e:  # noqa: BLE001 —— 备源失败不影响主路径
            logger.info("新浪批量报价失败（%d 只）: %s", len(batch), e)
            break
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).drop_duplicates(
        subset=["symbol"], keep="last").reset_index(drop=True)
