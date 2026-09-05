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
