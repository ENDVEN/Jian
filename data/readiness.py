# data/readiness.py
"""就绪度体检（§7-B1/B2 主案 D6-1 · v6.39）—— 扫描之前，先告诉用户
"**你选的范围里，本地能真正拿到多少只股票**"。

【为什么必须有这一层】范围解析（自选 / 指数成分 / 全A 花名册）只给出**名单**；
名单上的股票本地有没有数据、够不够公式要求的历史长度，扫描前谁都没说 ⇒
用户点了扫描才发现一大半「数据不足」，既浪费几十秒也不知道该怪谁。
体检把这件事**前置**并**量化**（用户 2026-09-19 STEP 6 要求："必须保证用户能
真正获取对应的股票，有问题必须说清是什么问题"）：

    ready        本地有文件且行数 ≥ min_bars（够公式历史）
    partial      有文件但行数不足（新上市 / 下载起点晚 —— 多数**补不齐**，不算缺口）
    missing      本地没有文件 —— **真正的缺口**，「补齐数据」动作的对象
    unreadable   文件打不开（坏文件）—— 问题清单，绝不静默跳过

【只读 footer】行数与 date 统计来自 parquet **footer**（实测 0.66 ms/只 ⇒
全市场 5400 只 ≈3.6 s，后台线程 + 进度）—— **不读数据行**，体检永远不成为
扫描的性能负担。【本地最新到几号】= date 列 footer 统计的 max（实测 368/368
可用；个别文件没写统计就诚实记 None，不猜）。

【纪律】零 UI、零网络、零写入（与 `core/cross_section` 同一层；只读不落盘 ⇒
无需进防污染自检名单）。
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field

import pandas as pd
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

__all__ = [
    'ReadinessReport', 'ReadinessCancelled', 'probe_readiness', 'DEFAULT_CHUNK',
    'format_stale',
]

# 与 core.cross_section.DEFAULT_CHUNK 同款口径：全市场 ≈27 次回调，进度条自然又不 harass
DEFAULT_CHUNK = 200


class ReadinessCancelled(Exception):
    """体检被取消 —— 与 `ScanCancelled` 同一哲学：**绝不把半截结果当成品**回给页面。"""


@dataclass
class ReadinessReport:
    """一次体检的产出。`summary_line()` 是给人看的**一行人话**（§10-10）。"""

    total: int = 0
    ready: list = field(default_factory=list)          # 行数达标
    partial: dict = field(default_factory=dict)        # 标的 → 行数（不足 min_bars）
    missing: list = field(default_factory=list)        # 本地无文件（真缺口）
    unreadable: dict = field(default_factory=dict)     # 标的 → 打不开的原因（问题清单）
    latest: object = None                              # 本地日线全局最新日期（Timestamp | None）
    lasts: list = field(default_factory=list)          # 每只文件的最后日期（升序 Timestamp）——供覆盖率/代表日
    # ★v1.45 / §7-B11 后续：`symbol -> 本地末日` 映射（与 `lasts` 同时算出，零额外 I/O）。
    #   `lasts` 排序后丢了标的关联，只能数个数；本映射能按只判定“只差当天”⇒ 供二次确认
    #   更准地估“多少只走快照秒补、多少只需真拉”（不阻塞主流程，缺时安全降级）。
    last_by_symbol: dict = field(default_factory=dict)
    elapsed_ms: float = 0.0

    # ---------- 查询 ----------
    @property
    def gap_count(self) -> int:
        """真缺口数 = 本地没有文件的（`partial` 是"有但不够长"，多数补不齐，不算缺口）。"""
        return len(self.missing)

    def gap_symbols(self) -> list:
        """「补齐数据」要下载的名单（= missing，按花名册顺序）。"""
        return list(self.missing)

    @property
    def representative_latest(self):
        """**代表性最新日**（多数文件真正覆盖到的中位日）——不被个别最新文件掩盖。

        区别于 `latest`（全局最大值，会被单只刚同步的标的拉到今天）：拿不到分布时退回 `latest`。
        滞后提示用它，才能诚实反映“多数标的其实还没更新到最近交易日”。
        """
        if not self.lasts:
            return self.latest
        s = sorted(self.lasts)
        return s[len(s) // 2]

    def coverage_at(self, date) -> int:
        """基准日 `date` 当天**真正有行**（最后日期 >= 该日）的只数。无分布 → 0。"""
        if not self.lasts or date is None:
            return 0
        d = pd.Timestamp(date).normalize()
        return sum(1 for x in self.lasts if pd.Timestamp(x).normalize() >= d)

    def problem_symbols(self) -> list:
        """问题清单（D6-5）：打不开的坏文件 —— 补齐救不了它，要「重新全量下载」。"""
        return list(self.unreadable)

    # ---------- 展示 ----------
    def summary_line(self) -> str:
        if self.total == 0:
            return '范围是空的 —— 先选好统计范围'
        parts = [f'就绪 {len(self.ready)}/{self.total}']
        if self.missing:
            parts.append(f'未下载 {len(self.missing)}')
        if self.partial:
            parts.append(f'历史不足 {len(self.partial)}')
        if self.unreadable:
            parts.append(f'文件损坏 {len(self.unreadable)}')
        if self.latest is not None:
            parts.append(f'本地最新 {pd.Timestamp(self.latest).date()}')
        return ' · '.join(parts)

    def gap_preview(self, n: int = 10) -> str:
        """缺口预览（前 n 个 + 总数）—— 缺口要**看得见名字和规模**，不许只给一个数字。"""
        if not self.missing:
            return ''
        cells = self.missing[:n]
        more = len(self.missing) - len(cells)
        text = '缺：' + '、'.join(cells)
        if more > 0:
            return text + f' …等共 {len(self.missing)} 只'
        return text + f'（共 {len(self.missing)} 只）'

    def detail_text(self) -> str:
        """tooltip / 详情：分类说清"为什么没就绪"（§10-10：报错要能定位，不许一句没数据）。"""
        lines = [self.summary_line()]
        if self.partial:
            shown = list(self.partial.items())[:5]
            head = '、'.join(f'{sym}({rows}行)' for sym, rows in shown)
            lines.append(f'历史不足（新上市或起点晚，一般不是缺陷）：{head}'
                         + ('…' if len(self.partial) > 5 else ''))
        if self.unreadable:
            head = '、'.join(list(self.unreadable)[:5])
            lines.append(f'文件损坏（建议重新全量下载）：{head}'
                         + ('…' if len(self.unreadable) > 5 else ''))
        lines.append('「历史不足」多数补不齐（数据本来就只有这么多）；「未下载」可用页面的下载入口一键补齐。')
        return '\n'.join(lines)


def format_stale(latest, target, stale_days: int) -> str:
    """滞后提示文案（零 UI、可单测）。三参任一缺/无滞后 → 空串（诚实不打扰、不猜）。

    :param stale_days: `(latest, target]` 的**交易日**数（调用方用日历精确算，非 busday 估）
    """
    if latest is None or target is None or int(stale_days or 0) <= 0:
        return ''
    # ⚠ 本模块在 `data/` 层 ⇒ **不写 UI 按钮的确切文字**（只描述动作）：
    #   写死按钮名就会在改名后失联（§11.5-80 的真实成因）。
    return (f'⚠ 数据滞后约 {int(stale_days)} 个交易日 · 本地到 '
            f'{pd.Timestamp(latest).date()}，最近交易日 {target} · '
            f'点页面的「更新到最新」入口把数据拉齐')


def probe_readiness(zone_dir: str, symbols, min_bars: int = None,
                    progress=None, should_stop=None,
                    chunk: int = DEFAULT_CHUNK) -> ReadinessReport:
    """就绪度体检：**只读 parquet footer**，逐只回答"有没有 / 够不够 / 最新到几号"。

    :param min_bars: 公式需要的历史长度（来自粗筛阈值；None ⇒ 行数 > 0 即算就绪）
    :param progress: `f(done, total, note)` —— 每 `chunk` 只报一次
    :param should_stop: `f() -> bool` —— **块边界**轮询；为真抛 `ReadinessCancelled`
    :returns: `ReadinessReport`（没有任何全局状态；重复调用安全）

    ⚠ 单个文件打不开**只记问题清单、不中断整轮**（一个坏文件不该让体检全废）；
      但它**必须出现在报告里**（unreadable）—— 不许静默跳过（D6-5 / §9-V 精神）。
    """
    from data.scan_store import kline_zone_dir  # 复用同一份"分区名 → 目录"映射

    t0 = time.perf_counter()
    if not zone_dir:                                  # 缺省走唯一映射（防两处口径漂移）
        from data.scan_store import kline_zone_dir
        zone_dir = kline_zone_dir('kline_daily')
    symbols = [str(s).strip() for s in (symbols or []) if str(s).strip()]
    chunk = max(1, int(chunk or 1))
    report = ReadinessReport(total=len(symbols))
    if not symbols:
        report.elapsed_ms = (time.perf_counter() - t0) * 1000
        return report

    latest = None
    lasts: list = []
    last_by_symbol: dict = {}
    for k, sym in enumerate(symbols):
        if should_stop is not None and k % chunk == 0 and should_stop():
            raise ReadinessCancelled(f'体检已取消（已查 {k}/{len(symbols)} 只）')
        path = os.path.join(zone_dir, f'{sym}.parquet')
        if not os.path.exists(path):
            report.missing.append(sym)
        else:
            try:
                pf = pq.ParquetFile(path)
                rows = int(pf.metadata.num_rows)
                last = _footer_last_date(pf)
                if last is not None:
                    if latest is None or last > latest:
                        latest = last
                    lasts.append(last)          # 收集分布（供代表日/覆盖率）
                    last_by_symbol[sym] = last  # ★v1.45：按只保留（供秒补估算）
                if rows <= 0:
                    report.partial[sym] = rows        # 空文件 = 数据不足，不是"没下载"
                elif min_bars is not None and rows < int(min_bars):
                    report.partial[sym] = rows
                else:
                    report.ready.append(sym)
            except Exception as e:  # noqa: BLE001 —— 坏文件进问题清单，不废整轮
                logger.warning(f"就绪度体检：文件打不开 [{sym}]: {e}")
                report.unreadable[sym] = str(e)
        if progress is not None and (k % chunk == chunk - 1 or k == len(symbols) - 1):
            progress(k + 1, len(symbols), sym)

    report.latest = latest
    report.lasts = sorted(lasts)
    report.last_by_symbol = last_by_symbol
    report.elapsed_ms = (time.perf_counter() - t0) * 1000
    return report


def _footer_last_date(pf: pq.ParquetFile):
    """从 footer 统计里取 date 列的最大值（**不读数据行**）；没有统计就诚实返回 None。"""
    idx = pf.schema_arrow.get_field_index('date')
    if idx < 0:
        return None
    best = None
    for rg in range(pf.metadata.num_row_groups):
        try:
            stats = pf.metadata.row_group(rg).column(idx).statistics
        except Exception:  # noqa: BLE001 —— 个别 row group 没统计不致命
            continue
        if stats is not None and stats.has_min_max and stats.max is not None:
            value = stats.max
            if best is None or value > best:
                best = value
    if best is None:
        return None
    try:
        return pd.Timestamp(best)
    except (ValueError, TypeError):  # noqa: BLE001 —— 统计类型异常就别用了
        return None
