# ui/widgets/symbol_pick.py
"""
选标的的**共用件**（★用户 2026-10-01 追加需求：*"标的要像 M1 一样 —— 手输 + 额外一个「选择」按钮，
选好后有 M1 同款的文字提示"*）。

M1（`ui/widgets/backtest_flow.select_symbol`）与 🧪 参数研究页（§7-B15）要的是同一件事：
**搜索 → 校验 A 股 → 回一句人话提示**。各写一份 ⇒ 提示文案与校验口径必然漂
（§11.5-112 同族：同一个零件两处两张脸）。所以口径收在这里，两页都调它。

【边界】本件只做"查 + 判 + 组文案"，**不碰任何控件**：调用方拿到 `(symbol, name, hint)` 自己回填
（M1 回填 `txt_symbol / lbl_symbol`；参数研究页回填 `in_symbol / lbl_symbol + 数据回执`）。

【为什么走 `main_win.engine.search_symbol`】那是 DataEngine 门面 —— UI 层不碰 DAO（§10 分层）。
"""
from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox

from data.akshare_feed import is_stock_code

__all__ = ["CACHED_SUFFIX", "pick_symbol", "symbol_hint"]

CACHED_SUFFIX = " · 已缓存"


def symbol_hint(name: str, symbol: str, cached: bool = False) -> str:
    """M1 同款提示文本：`贵州茅台 (600519) · 已缓存`。

    ⚠ 没缓存时**不带后缀**（别谎报"已缓存"—— 用户会以为可以直接跑）。
    """
    return f"{name} ({symbol})" + (CACHED_SUFFIX if cached else "")


def pick_symbol(page, keyword: str, *, lake=None):
    """关键词 → `(symbol, name, hint)`；查不到 / 非 A 股 / 空输入 ⇒ 弹提示并返回 None。

    :param page: 宿主页面（只用作消息框父窗口，以及取 `main_win.engine`）
    :param lake: 数据湖（判"已缓存"）；None = 不判缓存（提示不带后缀）
    """
    keyword = str(keyword or "").strip()
    if not keyword:
        QMessageBox.information(page, "提示", "请输入股票代码或名称。")
        return None
    res_df = page.main_win.engine.search_symbol(keyword)
    if res_df is None or res_df.empty:
        QMessageBox.warning(page, "未找到", f"花名册中没有 '{keyword}'。")
        return None
    symbol = str(res_df.iloc[0]["symbol"])
    name = str(res_df.iloc[0]["name"])
    if not is_stock_code(symbol):
        QMessageBox.warning(page, "仅支持A股", f"'{name} ({symbol})' 不是A股标的。")
        return None
    cached = bool(lake.exists("kline_daily", symbol)) if lake is not None else False
    return symbol, name, symbol_hint(name, symbol, cached)
