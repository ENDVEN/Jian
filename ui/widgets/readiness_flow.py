# ui/widgets/readiness_flow.py
"""「就绪度体检 + ⬇ 补齐缺失」的**两页共用控制器**（§7-B1/B2 主案 D6 · v6.39）。

【为什么收成一个类】D6 的铁律是"**就绪度模型只有一份**、两页口径一致"——
否则必然出现"管理页说最新、扫描页说缺数据"这种让用户失去信任的矛盾。
M2（全市场筛选）与 M3（广度统计）的范围解析完成后各调一次 `start(symbols)`，
之后的"后台体检 → 回执 → 空态给动作 → 补齐（联网走门面）→ 复检"全在这里，
两页**零复制**（§11.5-11「同类防护要做就做全套」的正解）。

【诚实的三段链路】（用户 2026-09-19 STEP 6 要求：必须真正拿到股票，出问题必须说清）
  ① 范围解析给出**名单**（自选 / 成分股 / 花名册）——成分股失败时页面用
    `friendly_constituent_message` 分类说清原因（网络 / 源未收录 / 代码有误）；
  ② 本控制器体检给出**名单里本地真正有多少**（就绪 N/M · 未下载 X · 历史不足 Y
    · 文件损坏 Z · 本地最新到几号）；
  ③ 「⬇ 补齐缺失」把**未下载**的补齐（`SyncWorker` 走 `MarketSyncService`，
    温柔抓取可中断）；「历史不足」多数补不齐（数据本来就只有这么多）——
    只解释、不假装能修；「文件损坏」指去数据管理重新全量下载（D6-5 问题清单）。

【不越权】体检结果**从不覆盖扫描回执**：扫描进行中 / 已有结果 / 范围已切换时，
迟到的体检回包直接丢弃（JobGuard + 范围吻合双重判定，§9-O5）。
"""
from __future__ import annotations

import logging

import pandas as pd
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QMessageBox

from data.readiness import ReadinessReport
from data.scan_store import kline_zone_dir
from data.sync_service import ZONE_KLINE, friendly_constituent_message
from ui.workers import JobGuard, ReadinessWorker, SyncWorker

__all__ = ['ReadinessFlow', 'constituent_failure_text', 'constituent_snapshot_text']

logger = logging.getLogger(__name__)

# 超过这个数的补齐先二次确认（全 A 首次补齐 = 长任务，§10-10 危险/耗时动作）
CONFIRM_FILL_COUNT = 50


def constituent_failure_text(index_code: str, payload: dict) -> str:
    """成分股解析失败的**人话诊断**（唯一出口，两页共用 —— 别再裸甩接口原始 message）。"""
    return friendly_constituent_message(index_code, payload)


def constituent_snapshot_text(index_name: str, payload: dict) -> str:
    """成分股名单解析成功的**诚实一行**（v6.42，两页共用）：

    ① 快照日期 —— 成分股每个季度调换，用户必须知道名单是哪天的；
    ② 名义只数核对 —— 指数名里的数字（沪深300→300）就是名义数；来源回少了
       （旧接口实测 288/429）必须当场说出来，不能让用户拿"缺了 12 只的 300"当全的用。
    名字里没有数字（如"上证180"之外的"创业板指"）⇒ 不做猜测，只报快照。"""
    import re

    count = int((payload or {}).get('count') or len((payload or {}).get('symbols') or []))
    snap = str((payload or {}).get('snapshot_date') or '')
    parts = [f'{count} 只']
    parts.append(f'名单快照 {snap}' if snap else '名单快照日期未知')
    m = re.search(r'(\d{2,5})', str(index_name or ''))
    if m and count:
        expected = int(m.group(1))
        if expected > count:
            parts.append(f'⚠ 来源只给了 {count}/{expected} 只'
                         f'（缺的 {expected - count} 只在数据源名单里就没有，不是软件丢的）')
    return ' · '.join(parts)


class ReadinessFlow:
    """体检 + 补齐（只读写 `p.X`；页面持有一个实例，范围变化时调 `start()`）。"""

    def __init__(self, page):
        self.page = page
        self.report: ReadinessReport | None = None
        self._guard = JobGuard()              # 体检回包守卫
        self._sync_guard = JobGuard()         # 补齐回包守卫（与体检互不踢）
        self._probe = None
        self._sync = None
        self._syncing = False
        self._last_symbols: list = []
        self._last_min_bars = None

    # ==========================================
    # ① 体检（后台 footer 探测；范围解析完成后调用）
    # ==========================================
    def start(self, symbols, *, min_bars=None) -> None:
        self._last_symbols = [str(s) for s in (symbols or [])]
        self._last_min_bars = min_bars
        if not self._last_symbols:
            return
        self.report = None
        job = self._guard.next()
        scope = list(self._last_symbols)      # 本次体检自己的名单 —— 回调**绑定它**做校验，
        self._probe = ReadinessWorker(job, kline_zone_dir('kline_daily'),  # 防被后续 start 重赋值穿透
                                      scope, min_bars=min_bars)
        self._probe.progress.connect(
            lambda d, t, n, s=scope: self._on_probe_progress(d, t, n, s))
        self._probe.finished.connect(
            lambda j, r, s=scope: self._on_probed(j, r, s))
        self._probe.failed.connect(
            lambda j, m, s=scope: self._on_probe_failed(j, m, s))
        self._probe.start()

    def _current_scope_changed(self, scope: list) -> bool:
        """这份体检/进度是否已过时（页面当前的范围 ≠ 它体检时的范围）。"""
        return [str(s) for s in (self.page._symbols or [])] != [str(s) for s in scope]

    def _busy_elsewhere(self) -> bool:
        """扫描 / 补齐进行中 ⇒ 回执区属于它们，体检不许打扰。"""
        p = self.page
        worker = p._worker
        return self._syncing or (worker is not None and worker.isRunning())

    def _on_probe_progress(self, done: int, total: int, note: str, scope: list) -> None:
        p = self.page
        if self._busy_elsewhere() or total <= 0 or done >= total:
            return
        if self._current_scope_changed(scope):
            return          # 旧范围的体检进度 —— 范围已切换，闭嘴
        if p._outcome is not None:
            # 已有扫描结果 ⇒ 回执区属于扫描；但占位文案里的"正在体检"要跟着动，
            # 否则用户盯着一句永远不完成的"正在体检…"以为软件卡死（v6.42）
            if '正在体检' in p.lbl_empty.text():
                p.lbl_empty.setText(f'正在体检本地数据就绪度… {done}/{total}')
            return
        p.lbl_receipt.setText(f'体检 {done}/{total} · {note}')

    def _on_probed(self, job_id: int, report, scope: list) -> None:
        p = self.page
        if not self._guard.accept(job_id):    # 迟到的旧体检回包直接丢（§9-O5）
            return
        if report is None:                    # 用户取消 / 页面切换（无半截结果）
            return
        # 页面当前的范围已经不是我体检的那份（用户切了范围）⇒ 这份结果属于过去，
        # **连报告都不入库**（更不能写回执/空态 —— 否则旧范围的就绪度会覆盖新范围的提示）
        if self._current_scope_changed(scope):
            return
        self.report = report
        self._calibrate_asof_date(report)               # 基准日默认值 = 本地最新交易日（v6.42）
        if self._busy_elsewhere():
            return          # 扫描/补齐进行中 ⇒ 回执区属于它们，体检不许打扰
        line = report.summary_line()
        if p._outcome is None:
            p.lbl_receipt.setText(line)
            p.lbl_receipt.setToolTip(report.detail_text())
            if report.gap_count or report.unreadable:   # 空态给下一步动作
                action = (f'⬇ 补齐缺失（{report.gap_count} 只）' if report.gap_count else '')
                p._result.set_empty(line + '\n' + report.gap_preview()
                                    + ('' if report.gap_count
                                       else '\n文件损坏的标的请到「🗄 数据管理」重新全量下载。'),
                                    action, self.fill_missing if action else None)
            else:
                p._result.set_empty(line + ' —— 点「▶ 开始扫描」。')
        elif '正在体检' in p.lbl_empty.text():
            # ★ v6.42：已有扫描结果 ⇒ 回执不动，但"正在体检"的占位必须换掉 ——
            #   旧版在这里直接 return，占位文案永远停在那里，用户以为体检了 3 分钟没完成
            #   （实际早就完了，只是没人把真话挂上去）。表格在场时这段不可见，但下次露出
            #   （切范围/清空结果）时它必须说实话。
            p.lbl_empty.setText(f'就绪度体检：{line}')
            p.lbl_empty.setToolTip(report.detail_text())

    def _calibrate_asof_date(self, report) -> None:
        """把 M2 的基准日控件校准到**本地最新交易日**（先选后扫的"默认值"环节）。

        只在用户**没动过控件**时生效（不覆盖用户意图）；M3 页没有 date_asof，自然跳过。
        上限也一起收紧：本地没有的 future 日子选了就扫不出东西，不如不给选。"""
        p = self.page
        edit = getattr(p, 'date_asof', None)
        if edit is None or getattr(p, '_date_touched', False):
            return
        latest = getattr(report, 'latest', None)
        if latest is None:
            return
        qd = QDate.fromString(str(pd.Timestamp(latest).date()), 'yyyy-MM-dd')
        if not qd.isValid():
            return
        edit.blockSignals(True)
        try:
            edit.setMaximumDate(qd)
            edit.setDate(qd)
        finally:
            edit.blockSignals(False)

    def _on_probe_failed(self, job_id: int, reason: str, scope: list) -> None:
        if not self._guard.accept(job_id) or self._current_scope_changed(scope):
            return
        self.page.lbl_receipt.setText('就绪度体检失败 —— ' + str(reason)[:100])
        self.page.lbl_receipt.setToolTip(str(reason))

    # ==========================================
    # ② 补齐缺失（只补 missing；联网走 SyncWorker ⇒ MarketSyncService，§9-H）
    # ==========================================
    def fill_missing(self) -> None:
        p = self.page
        if self._syncing:                     # 再点一次 = 中断（断点续传，已下载的保留）
            self.stop_fill()
            return
        report = self.report
        if report is None or not report.gap_count:
            p.lbl_receipt.setText('没有可补的缺口 —— 本地数据是齐的。')
            return
        gap = report.gap_symbols()
        if len(gap) > CONFIRM_FILL_COUNT:
            answer = QMessageBox.question(
                p, '补齐缺失',
                f'本地缺 {len(gap)} 只的日线数据，逐只温柔抓取预计需要较长时间'
                f'（默认间隔下约 {max(1, len(gap) // 60)} 分钟），随时可中断，'
                f'已下载的部分会保留。\n\n现在开始补齐吗？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                p.lbl_receipt.setText('已取消补齐 —— 本地数据未动。')
                return
        self._syncing = True
        job = self._sync_guard.next()
        self._sync = SyncWorker(gap, zone=ZONE_KLINE)
        self._sync.progress.connect(self._on_fill_progress)
        self._sync.failed.connect(self._on_fill_failed)
        self._sync.finished.connect(self._on_fill_finished)
        self._sync.start()
        p._result.set_empty(f'补齐中…（{len(gap)} 只 · 温柔抓取 · 已下载的自动跳过）',
                            '⏹ 停止补齐', self.stop_fill)
        p.lbl_receipt.setText(f'补齐 0/{len(gap)} · 准备中…')

    def stop_fill(self) -> None:
        if self._sync is not None:
            self._sync.cancel()
            self.page.lbl_receipt.setText('中断中…（已下载的保留，断点续传）')

    def _on_fill_progress(self, done: int, total: int, symbol: str) -> None:
        p = self.page
        p.bar_progress.show()
        p.bar_progress.setRange(0, max(1, int(total)))
        p.bar_progress.setValue(int(done))
        p.lbl_receipt.setText(f'补齐 {done}/{total} · {symbol}')

    def _on_fill_failed(self, symbol: str, reason: str) -> None:
        """单只失败**出声不中断**（SyncWorker 自己有熔断）；明细进 tooltip（问题清单）。"""
        logger.warning(f"补齐缺失失败 [{symbol}]: {reason}")

    def _on_fill_finished(self, stats: dict) -> None:
        p = self.page
        self._syncing = False
        p.bar_progress.hide()
        stats = stats or {}
        ok = int(stats.get('ok', 0))
        skipped = int(stats.get('skipped', 0))
        fail = int(stats.get('fail', 0))
        aborted = bool(stats.get('aborted'))
        text = f'补齐结束：成功 {ok} · 已最新 {skipped} · 失败 {fail}'
        if aborted:
            text += ' · 已中断（可再点「补齐缺失」续传）'
        p.lbl_receipt.setText(text)
        failed_symbols = list(stats.get('symbols_failed') or [])
        if failed_symbols:
            text_all = (text + '\n\n仍失败的标的（不是你的错 —— 可能次新/退市/源未收录，'
                        '可稍后重试或到「🗄 数据管理」单独处理）：\n'
                        + '、'.join(failed_symbols[:20])
                        + ('…' if len(failed_symbols) > 20 else ''))
            p.lbl_receipt.setToolTip(text_all)
        else:
            p.lbl_receipt.setToolTip('')
        # 复检：把补齐后的真实就绪度再报一遍（两页口径仍只有一份）
        if self._last_symbols:
            self.start(self._last_symbols, min_bars=self._last_min_bars)
