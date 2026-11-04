# data/provider_caps.py
"""匿名 / 登录能力表（★2.06 / DATA-PLATFORM P2）。

【口径】只描述**已实测**或**明确未接入**的能力；不把“未验证”写成“不可用”。
当前 A 股主源是新浪单只历史（匿名可通）；东财单只历史匿名被 RST，登录档尚未实测。
页面只读这里，不各自猜“登录能干什么”。
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = ["CapsRow", "rows", "current_mode", "summary_line", "detail_text"]


@dataclass(frozen=True)
class CapsRow:
    key: str
    label: str
    anonymous: str
    logged_in: str
    note: str = ""


_ROWS = (
    CapsRow("market_snapshot", "全市场日快照", "可用（实测约 52s）", "可用（可更快）",
            "东财 clist；匿名实测 5563 行 / 52s"),
    CapsRow("pool_quote", "按池报价 / 估值", "可用", "可用",
            "东财 ulist，100 只/批"),
    CapsRow("sina_history", "A 股单只历史（新浪主源）", "可用", "可用",
            "当前默认主源，不依赖登录"),
    CapsRow("em_history", "东财单只历史（直连）", "受限（匿名被 RST）",
            "可用（实测 K=16）",
            "登录档 100 只全历史 7.06s；受每日 300 次预算保护，仅近年/增量直连"),
    CapsRow("industry_page", "行业分页", "可用（慢速 3 页/批）", "可用（常速 10 页/批）",
            "登录档也不做全市场高频轮询"),
    CapsRow("fundamentals", "财报 / ROE 批量", "未接入", "未接入", "P4 计划"),
    CapsRow("other_assets", "ETF / 港股 / 期货", "未接入", "未接入", "P4 计划"),
)


def rows() -> tuple[CapsRow, ...]:
    return _ROWS


def current_mode() -> str:
    """`logged_in` / `anonymous`；判据不可用按匿名（最保守）。"""
    try:
        from data import em_auth
        return "logged_in" if em_auth.status().get("logged_in") else "anonymous"
    except Exception:  # noqa: BLE001
        return "anonymous"


def summary_line() -> str:
    mode = "已登录" if current_mode() == "logged_in" else "匿名"
    if mode == "匿名":
        return "匿名：快照/报价/新浪历史可用；东财单只历史受限"
    return "已登录：东财单只历史直连可用（受预算保护）；行业分页更快"


def detail_text() -> str:
    lines = [f"当前档位：{summary_line()}", ""]
    for row in _ROWS:
        lines.append(f"{row.label}")
        lines.append(f"  匿名：{row.anonymous}")
        lines.append(f"  登录：{row.logged_in}")
        if row.note:
            lines.append(f"  说明：{row.note}")
    lines.append("")
    lines.append("未登录不会让软件不可用；仅东财单只历史兜底受限，主源新浪仍可用。")
    return "\n".join(lines)
