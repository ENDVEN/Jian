# data/planner.py
"""数据补全计划器（★2.09 / DATA-PLATFORM P3-2）。

只做“该做什么”的纯决策：不联网、不写盘、不启动线程。
输入 catalog + 交易日历 + 花名册 + 当天快照代码；输出 bootstrap/daily/repair/minute 任务。

边界：
- 计划器不猜 provider，不碰预算；执行由 P3-3 scheduler 负责；
- 新股/北交所/停牌只做分类，不伪造数据；
- 现有 `data/backfill.plan_startup` 仍保留给旧启动检查，后续统一迁到本模块。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Iterable

__all__ = ["PlanTask", "PlanResult", "Planner"]


def _day(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):          # pandas Timestamp / datetime 都是 date 子类
        return value.date()
    if isinstance(value, date):
        return value
    try:
        if hasattr(value, "date"):
            return value.date()
    except Exception:  # noqa: BLE001
        pass
    text = str(value).strip()[:10]
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


@dataclass(frozen=True)
class PlanTask:
    action: str                       # bootstrap / daily / repair / minute
    symbols: tuple
    reason: str = ""
    dataset: str = "bar_daily"
    priority: int = 50
    meta: dict = field(default_factory=dict, compare=False)

    def __post_init__(self):
        object.__setattr__(self, "symbols", tuple(str(s) for s in self.symbols))


@dataclass
class PlanResult:
    tasks: tuple = ()
    ready: tuple = ()
    skipped: tuple = ()
    expected: str = ""
    previous: str = ""

    def by_action(self, action: str) -> list:
        return [t for t in self.tasks if t.action == action]

    def task_count(self) -> int:
        return sum(len(t.symbols) for t in self.tasks)

    def summary_line(self) -> str:
        parts = [f"{t.action} {len(t.symbols)}" for t in self.tasks if t.symbols]
        return (f"计划 {self.task_count()} 只（" + " · ".join(parts or ["无任务"])
                + f"）· 已就绪 {len(self.ready)} · 跳过 {len(self.skipped)}")


class Planner:
    def __init__(self, catalog=None, dataset: str = "bar_daily",
                 min_rows: int = 250):
        self.catalog = catalog
        self.dataset = str(dataset)
        self.min_rows = max(0, int(min_rows))

    def plan(self, expected=None, previous=None, *, roster: Iterable[str] = (),
             snapshot_symbols: Iterable[str] = (), records: dict = None,
             minute_symbols: Iterable[str] = ()) -> PlanResult:
        expected_d = _day(expected)
        previous_d = _day(previous)
        roster = [str(s).strip() for s in (roster or []) if str(s).strip()]
        snapshot = {str(s).strip() for s in (snapshot_symbols or [])
                    if str(s).strip()}
        if records is None:
            records = (self.catalog.asset_map(self.dataset)
                       if self.catalog is not None else {})
        records = {str(k): v for k, v in (records or {}).items()}
        universe = list(dict.fromkeys(roster + list(snapshot) + list(records)))

        buckets = {"bootstrap": [], "daily": [], "repair": []}
        ready, skipped = [], []
        for sym in universe:
            rec = records.get(sym)
            last = _day((rec or {}).get("last_date"))
            rows = int((rec or {}).get("rows") or 0)
            new = sym in snapshot and sym not in set(roster)
            # 只有 1 行的新股/残缺文件不算“已就绪”，要补全历史
            if last is None or rows < self.min_rows:
                buckets["bootstrap"].append(sym)
                continue
            if expected_d is None:
                skipped.append(sym)
                continue
            if last < expected_d:
                if previous_d is not None and last < previous_d:
                    buckets["repair"].append(sym)
                else:
                    buckets["daily"].append(sym)
            else:
                ready.append(sym)

        # 新股：即使 catalog 已有一根，也要后台补全历史（不是每天的一根）
        for sym in list(buckets["daily"]):
            if sym in snapshot and sym not in set(roster):
                buckets["daily"].remove(sym)
                buckets["bootstrap"].append(sym)

        tasks = []
        if buckets["daily"]:
            tasks.append(PlanTask("daily", buckets["daily"], "只缺当天", priority=10))
        if buckets["repair"]:
            tasks.append(PlanTask("repair", buckets["repair"], "缺口 >1 个交易日", priority=20))
        if buckets["bootstrap"]:
            tasks.append(PlanTask("bootstrap", buckets["bootstrap"],
                                  "无历史/新股/新入册", priority=30))
        minutes = [str(s) for s in (minute_symbols or []) if str(s).strip()]
        if minutes:
            tasks.append(PlanTask("minute", minutes, "用户/自选按需",
                                  dataset="bar_minute", priority=5))
        return PlanResult(
            tasks=tuple(tasks), ready=tuple(ready), skipped=tuple(skipped),
            expected=expected_d.isoformat() if expected_d else "",
            previous=previous_d.isoformat() if previous_d else "",
        )

    def plan_minute(self, symbols: Iterable[str]) -> PlanTask:
        return PlanTask("minute", [str(s).strip() for s in symbols if str(s).strip()],
                        "用户/自选按需", dataset="bar_minute", priority=5)
