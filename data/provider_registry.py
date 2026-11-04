# data/provider_registry.py
"""Provider 能力注册表（★2.06 / DATA-PLATFORM P2）。

只登记**实测状态**，不做运行时取数；真正调用仍在 `em_market` / `akshare_feed`。
后续 P3 的 planner 可据此选主源/备源。
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ProviderSpec", "PROVIDERS", "providers_for"]


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    datasets: tuple
    auth: str                 # anon / login / both
    bulk: str                 # snapshot / history / none
    status: str               # measured / limited / unavailable / not_installed
    note: str = ""


PROVIDERS = (
    ProviderSpec("eastmoney", ("quote_snapshot", "bar_daily", "industry"),
                 "both", "snapshot", "measured",
                 "clist 全市场 52s；ulist 100 只/批；单只匿名 RST；"
                 "登录直连实测可用但默认关闭（加法前复权≠新浪比例前复权）"),
    ProviderSpec("sina", ("quote_snapshot", "bar_daily", "bar_minute"),
                 "anon", "per_symbol", "measured",
                 "批量报价 100 只/批（备源）；单只日线/分钟，吞吐约 1 只/秒"),
    ProviderSpec("tencent", ("bar_daily",), "anon", "per_symbol",
                 "limited", "单次最多 640 根；匿名实测可用"),
    ProviderSpec("netease", ("bar_daily",), "anon", "per_symbol",
                 "unavailable", "2026-11-04 实测 502 Bad Gateway"),
    ProviderSpec("baostock", ("bar_daily",), "anon", "per_symbol",
                 "not_installed", "未安装；候选源，待引入后实测"),
)


def providers_for(dataset: str) -> list[ProviderSpec]:
    """按注册顺序返回能提供该 dataset 的 provider（不做网络探测）。"""
    key = str(dataset or "").strip()
    return [p for p in PROVIDERS if key in p.datasets]
