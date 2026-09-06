# core/utils.py
"""
通用无副作用工具函数集合 (Pure Helpers)。
只放置被多个模块复用的、与业务状态无关的纯函数，避免出现循环依赖。
"""
import re

import pandas as pd


def extract_root_symbol(symbol) -> str:
    """
    从完整合约代码中提取“品种主体”。
    例: "RB2410" -> "RB"；"600519" -> "600519"；"IF2309" -> "IF"
    """
    text = str(symbol)
    match = re.match(r'^[A-Za-z]+', text)
    return match.group().upper() if match else text.upper()


def format_trade_time(value) -> str:
    """
    将交易时间渲染成可读文本 (v1.1 数据契约)。
    - 交割单只有日期 (当天零点) -> 显示 "YYYY-MM-DD"，避免出现虚假的 00:00
    - 手工/外部数据带有具体时分 -> 显示 "YYYY-MM-DD HH:MM"
    """
    if value is None:
        return "-"
    try:
        t = pd.to_datetime(value)
    except Exception:
        return "-"
    if pd.isna(t):
        return "-"
    if t.hour or t.minute or t.second:
        return t.strftime("%Y-%m-%d %H:%M")
    return t.strftime("%Y-%m-%d")


def format_price(value) -> str:
    """
    渲染成交价 (v1.2)。

    【诚实原则】过月遗留单没有开仓价，一律渲染为 "—"，
    绝不显示 0.00 —— 那会让用户误以为自己是在 0 元开的仓。
    """
    if value is None:
        return "—"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "—"
    if pd.isna(num) or num == 0:
        return "—"
    # 按实际精度显示（最多 4 位小数），避免 6012.40 这类画蛇添足的补零
    return f"{num:,.4f}".rstrip('0').rstrip('.')


def format_points(value) -> str:
    """渲染点数盈亏（带正负号）；开仓价缺失时返回 "—" """
    if value is None:
        return "—"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "—"
    if pd.isna(num):
        return "—"
    return f"{num:+,.1f}"


def row_points(record) -> float | None:
    """
    从一条记录（Series / dict / TradeRecord 均可）计算点数盈亏。
    LONG : 平仓价 - 开仓价；SHORT : 开仓价 - 平仓价。
    开仓价缺失时返回 None，交由上层渲染成 "—"。
    """
    entry = record.get('entry_price') if hasattr(record, 'get') else getattr(record, 'entry_price', None)
    exit_ = record.get('exit_price') if hasattr(record, 'get') else getattr(record, 'exit_price', None)
    if entry is None or exit_ is None:
        return None
    try:
        entry, exit_ = float(entry), float(exit_)
    except (TypeError, ValueError):
        return None
    if pd.isna(entry) or pd.isna(exit_) or not entry or not exit_:
        return None
    diff = exit_ - entry
    direction = record.get('direction') if hasattr(record, 'get') else getattr(record, 'direction', 'LONG')
    return diff if direction == 'LONG' else -diff


def format_fill_time(value) -> str:
    """渲染成交时刻；无时分信息时返回空串（配合主时间列显示纯日期）"""
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() in ('nan', 'nat', 'none'):
        return ""
    return text[:5]  # HH:MM 足够，秒级精度对复盘意义不大
