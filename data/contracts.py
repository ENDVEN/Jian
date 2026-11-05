# data/contracts.py
"""数据平台契约（★2.09 / DATA-PLATFORM P3-1）。

这一层只定义“数据是什么”，不取数、不写盘、不依赖 Qt。
以后加 ETF/港股/期货/财报/分钟，只注册 DatasetSpec，不在 UI 里写资产 if。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

__all__ = ["AssetId", "DatasetSpec", "QualityReport", "DATASETS",
           "spec_for"]


@dataclass(frozen=True)
class AssetId:
    """跨市场资产标识；code 保持原市场写法（A 股 6 位，港股 5 位等）。"""
    code: str
    market: str = "CN"
    asset_type: str = "stock"

    def normalized(self) -> "AssetId":
        return AssetId(str(self.code).strip(),
                       str(self.market or "CN").strip().upper(),
                       str(self.asset_type or "stock").strip().lower())

    def __str__(self) -> str:
        return f"{self.market}:{self.asset_type}:{self.code}"


@dataclass(frozen=True)
class DatasetSpec:
    """一个数据集的声明式契约；不把不同资产塞进同一张宽表。"""
    name: str
    market: str = "CN"
    asset_type: str = "stock"
    partition: str = "symbol"          # symbol / date / month
    required: tuple = ("date", "open", "high", "low", "close", "volume")
    optional: tuple = ("amount",)
    adjust: str = "raw"                # raw / qfq / none
    calendar: str = "CN"
    currency: str = "CNY"
    schema_version: int = 1

    def validate_columns(self, columns: Iterable[str]) -> list[str]:
        have = set(columns or ())
        return [c for c in self.required if c not in have]


@dataclass
class QualityReport:
    """provider 取数结果的质量回执；区分“没数据”和“请求失败/被限流”。"""
    provider: str
    requested: int = 0
    returned: int = 0
    errors: list = field(default_factory=list)
    latency: float = 0.0
    throttled: bool = False

    @property
    def ok(self) -> bool:
        return self.returned > 0 and not self.throttled

    def summary_line(self) -> str:
        tail = f" · {self.latency:.2f}s" if self.latency else ""
        if self.throttled:
            return f"{self.provider}: 限流/冷却（{self.returned}/{self.requested}）{tail}"
        if self.errors:
            return (f"{self.provider}: 错误 {len(self.errors)} 条"
                    f"（{self.returned}/{self.requested}）{tail}")
        return f"{self.provider}: {self.returned}/{self.requested}{tail}"


# 当前已落地的数据集；P4 只往这里加，不在页面写资产分支。
DATASETS = {
    "bar_daily": DatasetSpec(
        "bar_daily", partition="symbol", adjust="qfq",
        optional=("amount", "turnover", "outstanding_share")),
    "quote_snapshot": DatasetSpec(
        "quote_snapshot", partition="date", adjust="raw",
        required=("symbol", "close", "volume"),
        optional=("open", "high", "low", "prev_close", "amount", "turnover")),
    "bar_minute": DatasetSpec(
        "bar_minute", partition="month", adjust="raw",
        required=("date", "open", "high", "low", "close", "volume")),
    "etf_daily": DatasetSpec(
        "etf_daily", asset_type="etf", partition="symbol", adjust="qfq",
        optional=("amount", "turnover")),
    "hk_daily": DatasetSpec(
        "hk_daily", market="HK", asset_type="stock", partition="symbol",
        adjust="qfq", calendar="HK", currency="HKD",
        optional=("amount", "turnover")),
    "futures_daily": DatasetSpec(
        "futures_daily", asset_type="future", partition="symbol", adjust="none",
        optional=("open_interest",)),
    "fin_report": DatasetSpec(
        "fin_report", partition="month", adjust="raw",
        required=("symbol", "report_date"),
        optional=("announce_date", "roe", "revenue", "net_profit")),
    "valuation_daily": DatasetSpec(
        "valuation_daily", partition="date", adjust="raw",
        required=("symbol", "date"),
        optional=("pe", "pb", "total_mktcap")),
}


def spec_for(name: str) -> DatasetSpec:
    key = str(name or "").strip()
    if key not in DATASETS:
        raise KeyError(f"未注册的数据集: {key}")
    return DATASETS[key]
