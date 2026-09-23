# ui/widgets/readiness_flow.py
"""「就绪度体检 + 补齐数据」的**两页共用控制器**（§7-B1/B2 主案 D6 · v6.39）。

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
  ③ 「更新到最新」把**未下载**的补齐（★v1.43：提交给主窗口的**后台下载队列**
    `ui/download_hub.py`，由它编排 `SyncWorker` 走 `MarketSyncService`，温柔抓取可中断）；
    「历史不足」多数补不齐（数据本来就只有这么多）——
    只解释、不假装能修；「文件损坏」指去数据管理重新全量下载（D6-5 问题清单）。

【不越权】体检结果**从不覆盖扫描回执**：扫描进行中 / 已有结果 / 范围已切换时，
迟到的体检回包直接丢弃（JobGuard + 范围吻合双重判定，§9-O5）。
"""
from __future__ import annotations

import logging

import pandas as pd
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QMessageBox

from data.readiness import ReadinessReport, format_stale
from data.scan_store import kline_zone_dir
from data.sync_service import (ZONE_KLINE, abort_reason_text,
                               estimate_seconds, format_duration,
                               friendly_constituent_message)
from data.trade_calendar import latest_settled_trading_day, trading_days_between
from ui.download_hub import download_policy_from_prefs, hub_of
from ui.widgets.custom_widgets import SYNC_ACTION_LABEL
from ui.workers import CalendarWorker, JobGuard, ReadinessWorker

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
        self._probe = None
        # ★v1.43 / §7-B11：批量下载不再在本页起线程，只记自己提交的任务号；
        #   进度/回执从主窗口的下载队列订阅（队列是唯一真源，本页是投影）。
        self._sync_job: int | None = None
        self._syncing = False
        self._sync_label = '补齐'            # 当前后台同步的动词（补齐 / 更新），供回执文案
        # ★v1.43 收口：记下"在跑的那批**是哪批标的**" —— 决定"再点一次"是"中断"还是
        #   "换范围后另开一批"（否则换范围后点它只会把旧那批停掉，用户想更新的新范围永远轮不到）。
        self._sync_scope: tuple | None = None
        hub = hub_of(page)                    # 统一取件：拿不到就降级（假页面/单测不炸）
        if hub is not None:
            hub.job_progress.connect(self._on_fill_progress)
            hub.job_failed.connect(self._on_fill_failed)
            hub.job_finished.connect(self._on_fill_finished)
        self._last_symbols: list = []
        self._last_min_bars = None
        # 交易日历（§7-B10 STEP 3）：滞后判据与 M1 同源，拿不到则不提示滞后
        self._calendar = None                # list[date] | None
        self.trading_target = None           # 最近已定稿交易日 | None
        self._cal_thread = None

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

    def _scan_running(self) -> bool:
        """**扫描**进行中 ⇒ 回执/结果区属于它，体检一律不打扰。

        ⚠ 【v1.43 收口 · §11.5-83】这里**绝不能把"本页的批量下载在跑"也算进来** ——
          旧写法是 `self._syncing or worker.isRunning()`，而 `_syncing` 从提交那一刻起
          一直为真（全市场要几十分钟）⇒ 用户**换个统计范围**后，新范围的就绪度回包被
          整份丢弃 ⇒ 空态永远停在「正在体检本地数据就绪度…」、那个"更新到最新"的
          **空态入口永远不出现**，必须等下载跑完或中断才恢复（换了个触发源的 §11.5-66）。
          后台下载的进度**本来就归底部下载条**（全局唯一真源），它只需"别覆盖回执行"这一条约束
          —— 见 `_render_readiness` 里的 `quiet`。
        """
        worker = getattr(self.page, '_worker', None)
        return worker is not None and worker.isRunning()

    def _on_probe_progress(self, done: int, total: int, note: str, scope: list) -> None:
        p = self.page
        if self._scan_running() or total <= 0 or done >= total:
            return
        if self._current_scope_changed(scope):
            return          # 旧范围的体检进度 —— 范围已切换，闭嘴
        if p._outcome is not None or self._syncing:
            # 回执区此刻属于扫描 / 后台下载的投影；但**占位文案必须跟着动** ——
            # 否则用户盯着一句永远不完成的"正在体检…"以为软件卡死（v6.42 / §11.5-83）
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
        if self._scan_running():
            return          # 扫描进行中 ⇒ 结果区属于它，体检不许打扰
        self._render_readiness()

    def _render_readiness(self) -> None:
        """把就绪度报告 + 滞后提示 + 基准日覆盖诚实提示渲染到回执/空态。

        §7-B10 修正：滞后用**代表性最新日**（中位日）而非全局 max，不被单只刚同步的标的掩盖；
        另加“基准日当天覆盖 N/total”——避免“就绪 299/300”却“扫描 1/300”这种两套口径的困惑。
        体检回包与日历回包都调它；已有扫描结果时不碰扫描回执。
        """
        p = self.page
        r = self.report
        if r is None:
            return
        # 滞后：用代表性最新日（多数文件真正覆盖到的），不被个别最新文件掩盖
        rep = r.representative_latest
        rep_date = pd.Timestamp(rep).date() if rep is not None else None
        stale_days = trading_days_between(rep_date, self.trading_target, self._calendar)
        stale = format_stale(rep_date, self.trading_target, stale_days)
        line = r.summary_line()
        # 基准日覆盖诚实提示（M2 有 date_asof；M3 无则跳过）：基准日当天真正有行的只数
        cov_hint = ''
        need_action = r.gap_count > 0 or stale_days > 0
        edit = getattr(p, 'date_asof', None)
        if edit is not None and r.lasts:
            asof = edit.date()
            cov = r.coverage_at(asof.toPyDate())
            if cov < r.total:
                cov_hint = (f'⚠ 基准日 {asof.toString("yyyy-MM-dd")} 当天仅 {cov}/{r.total} 只有数据'
                            f' —— 多数标的未更新到该日，先「{SYNC_ACTION_LABEL}」或把基准日往前挪')
                need_action = True
        if p._outcome is None:
            # ★v1.43 收口（§11.5-83）：后台下载在跑（`_syncing`）时**只让回执行** ——
            #   它此时显示的正是"更新 x/y · symbol"这份投影；但**空态与入口必须照常渲染**，
            #   否则换范围后会永远卡在「正在体检…」且"更新到最新"入口不出现（用户实测）。
            quiet = self._syncing
            if not quiet:
                # 顶部单行只留“短状态 + 待更新标记”；滞后/覆盖长说明走 tooltip 与结果区（可换行），
                # 不把单行标签撑长 → 窄屏不会被顶宽窗口（§11.5 窄屏不撑窗原则）。
                p.lbl_receipt.setText(line + (' · ⚠ 待更新' if need_action else ''))
                tip = '\n'.join(x for x in (stale, cov_hint, r.detail_text()) if x)
                p.lbl_receipt.setToolTip(tip)
            if need_action:
                body = line + '\n' + r.gap_preview()
                if stale:
                    body += '\n' + stale
                if cov_hint:
                    body += '\n' + cov_hint
                if r.unreadable:
                    body += '\n文件损坏的标的请到「🗄 数据管理」重新全量下载。'
                if self._syncing and self._same_batch(getattr(p, '_symbols', None)):
                    # 这一批正在更新 ⇒ 主按钮仍是"停止"（同一批再点 = 中断，别把停止入口藏掉）
                    p._result.set_empty(body, f'⏹ 停止{self._sync_label}', self.stop_fill)
                else:
                    # 范围已换 / 没在跑 ⇒ 入口就该是"更新到最新"（哪怕旧那批还在后台排队）
                    p._result.set_empty(body, SYNC_ACTION_LABEL, self.update_latest)
            elif r.unreadable:
                # ★v1.41 / §11.5-80：**有坏文件也是"需要动作"** —— 旧版只给一句话
                # （"请到数据管理重新全量下载"）却**不给入口**，用户只能自己找路。
                # 判据是"要不要用户动手"，不是"有没有缺口"。
                n_bad = len(r.problem_symbols())
                p._result.set_empty(
                    line + f'\n有 {n_bad} 个文件读不出来（损坏）—— '
                           f'去「🗄 数据管理」对它们重新全量下载。',
                    '去数据管理', self._go_data_manager)
            else:
                p._result.set_empty(line + ' —— 点「▶ 开始扫描」。')
        else:
            # ★v6.42：已有扫描结果 ⇒ **回执不动**（它是扫描的，不是体检的），
            #   但"正在体检"的占位必须换掉 —— 旧版在这里直接 return，
            #   占位文案永远停在那里，用户以为体检了 3 分钟没完成。
            # ★v1.41 / §11.5-80：这里**绝不能调 set_empty** —— 那会 `empty_box.show()` +
            #   `table.hide()`，把用户刚扫出来的结果**藏起来**（比"没按钮"严重得多）。
            #   所以本分支只改空态文字（不可见时无副作用），而"补数据的入口"由
            #   **摘要条常驻按钮** `btn_sync` 提供 —— 任何状态下都在，不再依赖空态。
            if '正在体检' in p.lbl_empty.text():
                p.lbl_empty.setText(f'就绪度体检：{line}')
                p.lbl_empty.setToolTip(r.detail_text())

    def _go_data_manager(self) -> None:
        """跳到「🗄 数据管理」页（跨页导航收在主窗口，两页同款，别各写一遍）。"""
        win = getattr(self.page, 'main_win', None)
        if win is not None:
            win.switch_to('data')

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
        # 基准日诚实化（§7-B10 STEP 4）：上限=本地最新，要更少先“更新到最新”；复检后自动抬升并回显
        hint = getattr(p, 'lbl_asof_hint', None)
        if hint is not None:
            hint.setText(f'上限=本地最新 {qd.toString("yyyy-MM-dd")}；'
                         f'要选更近先「{SYNC_ACTION_LABEL}」')

    def _on_probe_failed(self, job_id: int, reason: str, scope: list) -> None:
        if not self._guard.accept(job_id) or self._current_scope_changed(scope):
            return
        self.page.lbl_receipt.setText('就绪度体检失败 —— ' + str(reason)[:100])
        self.page.lbl_receipt.setToolTip(str(reason))

    # ==========================================
    # 交易日历（§7-B10 STEP 3）：与 M1 同源，喂滞后判据
    # ==========================================
    def start_calendar_fetch(self) -> None:
        """页面初始化时后台拉一次交易日历（缓存命中即零网络）。结果喂滞后提示；
        拿不到（离线）→ trading_target 保持 None → 不提示滞后（诚实降级，不猜）。"""
        self._cal_thread = CalendarWorker(parent=self.page)
        self._cal_thread.finished_signal.connect(self._on_calendar)
        self._cal_thread.start()

    def _on_calendar(self, calendar) -> None:
        self._calendar = calendar or None
        self.trading_target = latest_settled_trading_day(calendar=calendar)
        if self.report is not None and not self._scan_running():
            self._render_readiness()          # 日历后到 ⇒ 把滞后提示补上

    # ==========================================
    # ② 更新到最新 / 补齐数据（★v1.43：提交给主窗口的后台下载队列）
    # ==========================================
    def update_latest(self) -> None:
        """一键「⬆ 更新到最新交易日」（§7-B10 STEP 2 · 用户拍板与"补齐"动作合并）：
        对**整批当前范围**跑增量 —— 没下过的补、下过但滞后的拉到最近交易日；
        已新鲜的被 _is_fresh 自然 skipped。中断/断点续传/二次确认同补齐。

        ★v1.43 收口（§11.5-83）：**"再点一次 = 中断"只对"同一批标的"成立**。
        用户换了统计范围后再点，语义应当是"把新范围也交后台"（串行排队），
        而不是把旧那批停掉 —— 否则新范围永远轮不到更新。
        """
        p = self.page
        symbols = [str(s) for s in (self._last_symbols or []) if str(s).strip()]
        if self._syncing and self._same_batch(symbols):
            self.stop_fill()                  # 同一批再点一次 = 中断
            return
        if not symbols:
            p.lbl_receipt.setText('范围还是空的 —— 先选好统计范围。')
            return
        self._launch_sync(symbols, '更新', note='· 已最新的自动跳过')

    def fill_missing(self) -> None:
        """只补 missing（保留方法；空态主入口已合并到 update_latest）。"""
        p = self.page
        report = self.report
        if report is None or not report.gap_count:
            p.lbl_receipt.setText('没有可补的缺口 —— 本地数据是齐的。')
            return
        gaps = report.gap_symbols()
        if self._syncing and self._same_batch(gaps):
            self.stop_fill()                  # 同一批再点一次 = 中断
            return
        self._launch_sync(gaps, '补齐')

    def _same_batch(self, symbols) -> bool:
        """这些标的是不是**正在后台跑的那一批**？（决定"再点一次"是中断还是另开一批）"""
        if self._sync_scope is None:
            return False
        want = tuple(str(s) for s in (symbols or []) if str(s).strip())
        return bool(want) and self._sync_scope == want

    def _estimate_stale(self, n: int):
        """估算「真正需要联网」的只数与耗时（★v1.40/§7-E5）。

        【为什么要算】旧版一律按"每只都要跑"估时（`n // 60` 分钟），于是哪怕本地全是最新的，
        二次确认框也照样说"要很久"——**等于把用户劝退**；而体检报告里其实已经拿着
        每只文件的最后日期（`lasts`，只读 parquet footer，代价早付过了），
        拿它与 `trading_target`（最近已收盘定稿的交易日）一比就知道谁已新鲜。

        【什么时候不敢用】名单与体检范围**不一致**（如「补齐」只传 missing）时口径不符，
        按覆盖率硬减会**低估**耗时 ⇒ 退回上限估算。拿不到日历（`trading_target is None`）
        或没有日期分布时同理退回上限 —— 宁可说得保守，不可骗用户。

        :return: `(stale_count, estimate_seconds)`；stale_count = n 表示"按全部都要跑"的上限。
        """
        report = self.report
        target = self.trading_target
        if report is None or target is None or not report.lasts or n != report.total:
            return n, estimate_seconds(n, download_policy_from_prefs())
        covered = report.coverage_at(target)          # 已到该日的只数（>= 目标日）
        stale = max(0, n - covered)
        return stale, estimate_seconds(n, download_policy_from_prefs(), stale_count=stale)

    def _launch_sync(self, symbols, label: str, note: str = '') -> None:
        """共享的后台增量启动（update_latest / fill_missing 都走它，勿各写一份）。

        ★v1.43 / §7-B11：任务**提交给主窗口的下载队列**，本页不再自己起线程 ——
        旧版页面私有一个 `SyncWorker`（而且没给 parent），切页就看不见进度、
        多个入口各自为政。现在进度真源在队列，本页的回执与进度条只是它的**投影**
        （只认自己那个 `job_id`）。
        """
        p = self.page
        self._sync_label = label
        n = len(symbols)
        if n > CONFIRM_FILL_COUNT:
            stale, est = self._estimate_stale(n)
            answer = QMessageBox.question(
                p, f'{label}数据',
                f'本次要逐只温柔抓取 {n} 只的日线数据'
                f'（其中约 {stale} 只需要真正联网、约 {format_duration(est)}；'
                f'已是最新的 {max(0, n - stale)} 只会自动跳过），随时可中断，'
                f'已下载的部分会保留。\n\n现在开始{label}吗？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                p.lbl_receipt.setText(f'已取消{label} —— 本地数据未动。')
                return
        hub = hub_of(p)
        if hub is None:
            p.lbl_receipt.setText('后台下载队列不可用 —— 无法提交下载任务。')
            return
        self._sync_job = hub.submit(self._job_name(label), symbols, zone=ZONE_KLINE,
                                    origin=getattr(p, 'hub_origin', 'm2m3'))
        if not self._sync_job:
            # 去重命中 ⇒ 诚实说清楚（不假装又跑了一轮）
            p.lbl_receipt.setText('同样的任务已经在队列里了 —— 进度见窗口底部的下载条。')
            return
        self._syncing = True
        self._sync_scope = tuple(str(s) for s in symbols)   # 记住"跑的是哪一批"（§11.5-83）
        p._result.set_empty(f'{label}中…（{n} 只 · 温柔抓取 {note}）',
                            f'⏹ 停止{label}', self.stop_fill)
        p.lbl_receipt.setText(f'{label} 0/{n} · 已提交后台（任务 #{self._sync_job}）…')

    def _job_name(self, label: str) -> str:
        """任务名：带上当前统计范围，让用户在队列里认得出是谁提交的。"""
        cmb = getattr(self.page, 'cb_scope', None)
        tag = str(cmb.currentText() or '').strip() if cmb is not None else ''
        return f'{label}数据 · {tag}' if tag else f'{label}数据'

    def stop_fill(self) -> None:
        hub = hub_of(self.page)
        if self._sync_job and hub is not None:
            hub.cancel(self._sync_job)
            self.page.lbl_receipt.setText('中断中…（已下载的保留，断点续传）')

    def _on_fill_progress(self, job_id: int, done: int, total: int, symbol: str) -> None:
        if job_id != self._sync_job:
            return                                  # 别的任务不许抢本页回执（§9-O5 同族）
        p = self.page
        p.bar_progress.show()
        p.bar_progress.setRange(0, max(1, int(total)))
        p.bar_progress.setValue(int(done))
        p.lbl_receipt.setText(f'{self._sync_label} {done}/{total} · {symbol}')

    def _on_fill_failed(self, job_id: int, symbol: str, reason: str) -> None:
        """单只失败**出声不中断**（队列自己有熔断）；明细进 tooltip（问题清单）。"""
        if job_id != self._sync_job:
            return
        logger.warning(f"补齐数据失败 [{symbol}]: {reason}")

    def _on_fill_finished(self, job_id: int, stats: dict) -> None:
        if job_id != self._sync_job:
            return
        p = self.page
        self._syncing = False
        self._sync_job = None
        self._sync_scope = None
        p.bar_progress.hide()
        stats = stats or {}
        ok = int(stats.get('ok', 0))
        skipped = int(stats.get('skipped', 0))
        fail = int(stats.get('fail', 0))
        aborted = bool(stats.get('aborted'))
        text = f'{self._sync_label}结束：成功 {ok} · 已最新 {skipped} · 失败 {fail}'
        if aborted:
            # 中断原因要说清（§7-E2）：代理全灭 ⇒ "请检查代理软件"；否则只是"被限流/已中断"
            _why = abort_reason_text(stats)
            text += f' · 已中断（{_why}；可再点「{SYNC_ACTION_LABEL}」续传）'
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
