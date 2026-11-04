# data/backfill.py
"""历史补全计划（★2.05 / DATA-PLATFORM P1）。

`ReadinessReport` 回答“谁缺/谁短/谁坏”；本模块把它变成：
  · 一份可按批取的任务名单（missing → partial → unreadable）；
  · 一个覆盖率口径（给人话/UI 用）。
纯函数、零 IO、零 Qt；真正的取数仍由 `SyncWorker` / `refresh_one` 做。
"""
from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["BackfillPlan", "StartupPlan", "plan_from_report", "plan_startup"]


@dataclass
class BackfillPlan:
    total: int = 0
    ready: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    partial: list = field(default_factory=list)
    unreadable: list = field(default_factory=list)

    @property
    def symbols(self) -> list:
        """需要补的名单（去重保序：missing → partial → unreadable）。"""
        seen = set()
        out = []
        for sym in list(self.missing) + list(self.partial) + list(self.unreadable):
            s = str(sym)
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        return out

    @property
    def coverage(self) -> float:
        return round(len(self.ready) / self.total, 4) if self.total else 0.0

    @property
    def need_count(self) -> int:
        return len(self.symbols)

    def batches(self, size: int = 200) -> list[list]:
        size = max(1, int(size or 1))
        syms = self.symbols
        return [syms[i:i + size] for i in range(0, len(syms), size)]

    def summary_line(self) -> str:
        if not self.total:
            return "范围是空的 —— 先选好统计范围"
        parts = [f"就绪 {len(self.ready)}/{self.total}（{self.coverage:.1%}）"]
        if self.missing:
            parts.append(f"未下载 {len(self.missing)}")
        if self.partial:
            parts.append(f"历史不足 {len(self.partial)}")
        if self.unreadable:
            parts.append(f"坏文件 {len(self.unreadable)}")
        return " · ".join(parts)


def plan_from_report(report) -> BackfillPlan:
    """从 `ReadinessReport`（duck type）生成补全计划；不修改原报告。"""
    if report is None:
        return BackfillPlan()
    return BackfillPlan(
        total=int(getattr(report, "total", 0) or 0),
        ready=list(getattr(report, "ready", []) or []),
        missing=list(getattr(report, "missing", []) or []),
        partial=list((getattr(report, "partial", {}) or {}).keys()),
        unreadable=list((getattr(report, "unreadable", {}) or {}).keys()),
    )


@dataclass
class StartupPlan:
    """启动检查的结论：none / snapshot（只缺一天）/ backfill（缺口更大）。"""
    action: str = "none"
    symbols: list = field(default_factory=list)
    reason: str = ""
    latest: object = None
    expected: object = None


def plan_startup(report, expected, previous) -> StartupPlan:
    """根据体检报告决定启动时做什么。

    - 没有 expected（日历不可用）⇒ none（不猜）；
    - 代表性最新日已 >= expected ⇒ none；
    - 代表性最新日 == 上一交易日（或更新）⇒ snapshot（只补当天一根）；
    - 更旧 ⇒ backfill（低优先级补历史，绝不逐只 5000 次拖垮启动）。
    """
    if expected is None:
        return StartupPlan(action="none", reason="没有可用交易日历", expected=None)
    latest = getattr(report, "representative_latest", None) if report is not None else None
    if latest is None:
        return StartupPlan(action="snapshot", reason="本地无有效末日",
                           latest=None, expected=expected)
    try:
        import pandas as pd
        latest_ts = pd.Timestamp(latest).normalize()
        expected_ts = pd.Timestamp(expected).normalize()
        prev_ts = pd.Timestamp(previous).normalize() if previous is not None else None
    except Exception:  # noqa: BLE001
        return StartupPlan(action="snapshot", reason="日期解析失败，先补当天",
                           latest=latest, expected=expected)
    if latest_ts >= expected_ts:
        return StartupPlan(action="none", reason="已最新",
                           latest=latest, expected=expected)
    if prev_ts is not None and latest_ts >= prev_ts:
        return StartupPlan(action="snapshot", reason="只缺当天",
                           latest=latest, expected=expected)
    # 缺口 > 1 个交易日：只补 stale，不走全市场单只
    stale = []
    for sym, last in (getattr(report, "last_by_symbol", {}) or {}).items():
        try:
            if pd.Timestamp(last).normalize() < expected_ts:
                stale.append(str(sym))
        except Exception:  # noqa: BLE001
            stale.append(str(sym))
    for sym in (getattr(report, "missing", []) or []):
        if str(sym) not in stale:
            stale.append(str(sym))
    return StartupPlan(action="backfill" if stale else "none",
                       symbols=stale, reason="缺口大于 1 个交易日",
                       latest=latest, expected=expected)
