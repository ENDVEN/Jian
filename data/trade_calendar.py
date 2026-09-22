# data/trade_calendar.py
"""
A 股交易日历获取件（v6.45 / §7-B10 · 用户拍板引入真交易日历）。

【职责边界（SRP）】
  · 本模块只管"日历的取 / 缓存 / 判定"这一件事；接口细节在 `AkShareFeed.fetch_trade_calendar`，
    收盘定稿判据在 `data.sync_service.is_daily_bar_settled`（唯一真源，不在此重写）。
  · 纯 Python、零 Qt。网络抓取由调用方（`ui/workers.CalendarWorker`）放到后台线程里跑。

【三重兜底，消化"引日历 = 冷启动一次网络"的代价】
  ① 当年缓存命中即零网络（`~/.jian_data/trade_calendar.json`，原子写）；
  ② 抓取失败时回吐旧缓存（若有）；
  ③ 连旧缓存都没有 → 返回 `None`，由调用方回退"本地数据湖最新日"。
     （拿不到日历绝不阻断回测默认值 —— 与偏好文件同源容错理念。）
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date as _date, datetime

from config import settings
from data.akshare_feed import AkShareFeed
from data.sync_service import is_daily_bar_settled

logger = logging.getLogger(__name__)

CALENDAR_PATH = os.path.join(settings.USER_DATA_DIR, "trade_calendar.json")

__all__ = ["load_or_fetch", "latest_settled_trading_day", "previous_trading_day",
           "trading_days_between"]


def _to_date(value) -> _date | None:
    try:
        return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):  # noqa: BLE001
        return None


def _read_cache(path: str) -> list[_date]:
    """读缓存日历（升序 date 列表）；缺失 / 损坏一律回落空列表（不抛）。"""
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
        dates = [_to_date(d) for d in loaded.get("dates", [])]
        return sorted(d for d in dates if d is not None)
    except (OSError, ValueError) as e:  # noqa: BLE001
        logger.warning(f"交易日历缓存读取失败，忽略: {e}")
        return []


def _write_cache(dates: list[_date], path: str) -> None:
    """原子写日历缓存（tmp + os.replace），与偏好 / 策略库同源手法。"""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"updated": datetime.now().strftime("%Y-%m-%d"),
                       "dates": [d.strftime("%Y-%m-%d") for d in dates]},
                      f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as e:  # noqa: BLE001
        logger.warning(f"交易日历缓存写入失败（不影响本次返回）: {e}")


def _covers(dates: list[_date], today: _date) -> bool:
    """缓存是否已覆盖到今天（含今天）—— 覆盖则无需再联网。"""
    return bool(dates) and dates[-1] >= today


def load_or_fetch(fetch_fn=None, now: datetime = None, cache_path: str = CALENDAR_PATH
                  ) -> list[_date] | None:
    """返回升序交易日历（`list[date]`）；彻底拿不到时返回 `None`（触发调用方回退）。

    :param fetch_fn: 可注入的抓取函数（默认 `AkShareFeed.fetch_trade_calendar`），便于测试打桩
    """
    now = now or datetime.now()
    today = now.date()
    cached = _read_cache(cache_path)
    if _covers(cached, today):
        return cached                        # ① 缓存命中，零网络
    fetch = fetch_fn or AkShareFeed.fetch_trade_calendar
    try:
        df = fetch()
    except Exception as e:  # noqa: BLE001 —— 网络 / 接口异常一律回退旧缓存或 None
        logger.warning(f"交易日历抓取失败: {e}")
        return cached or None                # ② 回吐旧缓存 / ③ 无缓存则 None
    dates: list[_date] = []
    if df is not None and not getattr(df, "empty", True) and "date" in df.columns:
        dates = sorted(d for d in (_to_date(x) for x in df["date"]) if d is not None)
    if dates:
        _write_cache(dates, cache_path)
        return dates
    return cached or None                    # 抓回来是空：仍尽量回吐旧缓存


def latest_settled_trading_day(now: datetime = None, calendar: list[_date] | None = None
                               ) -> _date | None:
    """最近一个**已收盘定稿**的交易日。

    - 今天是交易日且已过定稿时刻（默认 15:05）→ 今天；
    - 今天是交易日但盘中（未定稿）→ 上一交易日；
    - 今天休市（周末 / 节假日）→ 自然落到最近一个已过去的交易日。

    日历为 `None`（拿不到）→ 返回 `None`，由调用方回退本地数据湖最新日。
    """
    now = now or datetime.now()
    if not calendar:
        return None
    today = now.date()
    for d in reversed(calendar):            # 升序，从后往前找
        if d <= today and is_daily_bar_settled(d, now):
            return d
    return None


def previous_trading_day(ref: _date, calendar: list[_date] | None) -> _date | None:
    """严格早于 `ref` 的最近交易日；无则 None。"""
    if not calendar:
        return None
    earlier = [d for d in calendar if d < ref]
    return earlier[-1] if earlier else None


def trading_days_between(a: _date | None, b: _date | None,
                         calendar: list[_date] | None) -> int:
    """`(a, b]` 区间内的交易日个数（周末/节假日不计）——供“滞后几个交易日”精确计数。

    - a/b 任一为 None、或无日历、或 `a >= b` → 0（不早于就不算滞后）；
    - 只数日历里的日（不猜、不用 busday），故节假日不会虚报。
    """
    if a is None or b is None or not calendar or a >= b:
        return 0
    return sum(1 for d in calendar if a < d <= b)
