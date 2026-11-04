# data/provider_router.py
"""历史取数 provider 顺序（★2.06 / DATA-PLATFORM P2）。

只做纯决策；真正取数仍在 `akshare_feed` / `tencent_market`。
腾讯历史单次最多 640 根，只适合**增量/近年**；全历史仍走新浪/东财。
"""
from __future__ import annotations

from datetime import date, timedelta

__all__ = ["history_order", "is_recent_start"]


def _parse_day(value) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if "-" in text:
            return date.fromisoformat(text[:10])
        if len(text) >= 8:
            return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None
    return None


def is_recent_start(start_date, today: date = None, days: int = 900) -> bool:
    """起点在最近 N 天内 ⇒ 腾讯 640 根足够覆盖增量。"""
    parsed = _parse_day(start_date)
    if parsed is None:
        return False
    return (today or date.today()) - parsed <= timedelta(days=days)


def history_order(start_date, auth_mode: str = None, today: date = None) -> list[str]:
    """按优先级返回 history provider；登录态目前不改变顺序（待实测）。"""
    order = ["sina"]
    if is_recent_start(start_date, today=today):
        order.append("tencent")
    order.append("eastmoney")
    return order
