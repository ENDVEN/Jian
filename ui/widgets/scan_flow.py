# ui/widgets/scan_flow.py
"""🌐 M2「全市场筛选」—— 运行流程（范围解析 / 后台线程 / 进度回执 / 切日期 / 跳行情）。

【为什么这里只有"调度"】读盘、掩码、求值在 `core/cross_section`（纯计算），
缓存在 `data/scan_store`（纯内存），线程在 `ui/workers.py`（§9-O2）——
本模块只做"把用户的动作接到那条管线上"，并负责**回执的一行人话化**（§10-10）。

【竞态守卫】所有异步回包（扫描 / 成分股解析）一律过 `JobGuard.accept(job_id)`，
迟到的旧回包**直接丢弃**（§9-O5）—— 否则"快速连续操作"会出现旧结果覆盖新结果。

【切日期为什么零成本】一次扫描的矩阵本来就是**全日期**的（`asof` 不参与求值，D2/D3），
所以切日期只调 `outcome.status_on(date)` / `counts_on(date)`（纯切片），
**不进线程、不读盘、不求值**。⚠ 代价（D3 的使用纪律）：
切日期后**只显示状态**，数值快照与"为什么"明细只在扫描基准日有效 —— 不许拿旧的冒充新的。
"""
from __future__ import annotations

import logging

import pandas as pd
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QMessageBox

from core.cross_section import ScanThresholds
from core.preferences import preferences
from core.utils import parse_params_text
from data.backtest_archive import KIND_M2, SOURCE_AUTO, BacktestArchive, build_scan_record
from data.industry_store import get_industry_store
from data.scan_store import kline_zone_dir
from data.sync_service import MarketSyncService
from data.watchlist_store import WatchlistStore
from ui.widgets.custom_widgets import SYNC_ACTION_LABEL
from ui.widgets.readiness_flow import (constituent_failure_text,
                                       constituent_snapshot_text, mark_archived,
                                       scope_snapshot)
from ui.workers import (ConstituentsWorker, CrossSectionWorker, IndustryMapWorker,
                        JobGuard, SpotValuationWorker)

__all__ = ['ScanFlow', 'SCAN_UI_KEY']

logger = logging.getLogger(__name__)

SCAN_UI_KEY = 'scan_ui'          # 页面偏好键（core/preferences.DEFAULTS 里登记）


def _stamp_of(qdate: QDate) -> pd.Timestamp:
    """QDate → pd.Timestamp（午夜，与内核日期轴同口径）。"""
    return pd.Timestamp(qdate.toString('yyyy-MM-dd'))


def _nearest_on_axis(dates, stamp: pd.Timestamp):
    """轴外日期就近落位（与内核 scan() 的落位规则一致：平手取前一日）。

    轴上的日子原样返回；没轴返回 None（调用方自己兜底）。"""
    if dates is None or len(dates) == 0:
        return None
    stamp = pd.Timestamp(stamp)
    idx = int(dates.searchsorted(stamp))
    if idx < len(dates) and dates[idx] == stamp:
        return stamp
    cand = [c for c in (idx - 1, idx) if 0 <= c < len(dates)]
    if not cand:
        return None
    near = min(cand, key=lambda c: abs((dates[c] - stamp).days))
    return pd.Timestamp(dates[near])


class ScanFlow:
    """M2 页的运行流程（只读写 `p.X`，不存状态）。"""

    def __init__(self, page):
        self.page = page
        p = self.page
        p.cb_scope.currentIndexChanged.connect(self.on_scope_changed)
        p.cb_index.currentIndexChanged.connect(self.on_index_changed)
        p.btn_config.clicked.connect(self.open_config)
        p.btn_run.clicked.connect(self.on_run_clicked)
        # ★v1.41 / §11.5-80：常驻「更新到最新」入口 —— 晚绑定（点击时才取 `p._readiness`），
        # 避免依赖"构造顺序"（本页的就绪度控制器在视图里装配，晚于本类）。
        p.btn_sync.clicked.connect(lambda: p._readiness.update_latest())
        p.btn_prev_day.clicked.connect(lambda: self.shift_date(-1))
        p.btn_next_day.clicked.connect(lambda: self.shift_date(1))
        p.btn_latest_day.clicked.connect(self.jump_latest)
        p.date_asof.dateChanged.connect(self._on_date_changed)
        p.table.itemDoubleClicked.connect(self.on_row_double_clicked)
        p.table.horizontalHeader().sectionClicked.connect(self.on_header_clicked)   # ★P1 点表头排序
        p.table.horizontalHeader().sectionMoved.connect(self._on_section_moved)     # ★P7 拖拽换列序→持久化
        p._filter_pane.btn_reset.clicked.connect(self.reset_thresholds)
        # ★v1.46：历史页「重跑」用 —— 等名单 + 体检都就绪再自动开扫（见 request_run）
        self._pending_run = False
        self._probe_done = False

    # ==========================================
    # 范围（自选 / 指数成分 / 全 A）
    # ==========================================
    def on_scope_changed(self) -> None:
        p = self.page
        p.cb_index.setVisible(p.cb_scope.currentIndex() == 1)
        self.resolve_scope()

    def on_index_changed(self) -> None:
        if self.page.cb_scope.currentIndex() == 1:
            self.resolve_scope()

    def _drop_stale_result(self, scope_key) -> None:
        """范围变了 ⇒ 丢掉上一范围的扫描结果（★v1.41 / §11.5-80）。

        【为什么必须丢】旧版从不清 `_outcome`：用户把范围从沪深300 换成中证500 后，
        结果区上方仍挂着**沪深300 的统计**（命中 6 · 300 只 / 有效样本 295/300），
        而结果区里写的是**中证500 的就绪度**（未下载 456/500）—— **两套数字同屏打架**，
        用户不知道该信哪个（用户实测截图复现）。更隐蔽的后果：`_render_readiness`
        会因此以为"已有当前范围的结果"，走"回执不动"分支、**不再给下载入口**。
        判据用 `(范围选择, 指数代码)`：**同一范围**重新解析（例如成分股解析重试）不清 ——
        否则会把用户已经跑出来的结果白丢掉。
        """
        p = self.page
        if getattr(p, '_scope_key', None) == scope_key:
            return
        p._scope_key = scope_key
        p._outcome = None
        p._asof = None
        p._result.clear()

    def resolve_scope(self) -> None:
        """把"统计范围"落成 `{标的: 名称}`。自选 / 全A 同步；指数成分**异步**（§9-H：联网走门面）。

        名单落定后**自动触发一次就绪度体检**（D6-1：告诉用户"本地能真正拿到多少只"，
        缺口给「更新到最新」动作）—— 实现只在 `ReadinessFlow`，两页共用一份。
        """
        p = self.page
        p._names = {}
        choice = p.cb_scope.currentIndex()
        # ★v1.41：范围真的变了 ⇒ 旧结果作废（见 `_drop_stale_result` 的说明）
        self._drop_stale_result(
            (choice, str(p.cb_index.currentData() or '') if choice == 1 else ''))
        if choice == 0:                                   # 我的自选
            p._cons_meta = None                           # 非成分股范围 ⇒ 无快照语义
            p._symbols = list(WatchlistStore().symbols())
            p._names = dict(WatchlistStore().names_map())
            if not p._symbols:
                p._result.set_empty('自选清单是空的 —— 先去「行情工作台」加几只自选，再来扫描。',
                                    '去行情工作台', lambda: p.main_win.switch_to('market'))
            p.lbl_scope.setText(f'{len(p._symbols)} 只')
        elif choice == 1:                                 # 指数成分（异步）
            code = str(p.cb_index.currentData() or '')
            if not code:
                return
            p._symbols = []
            p.lbl_scope.setText('解析成分股中…')
            p._result.set_empty(
                f'正在解析 {p.cb_index.currentText()} 的成分股…\n'
                f'（名单接口较慢，实测约 8~15 秒；解析完会自动体检本地数据就绪度）')
            job = p._guard.next()
            p._cons_worker = ConstituentsWorker(code, p)
            p._cons_worker.finished_signal.connect(
                lambda result, token=job: self._on_constituents(result, token))
            p._cons_worker.start()
            return
        else:                                             # 全 A 花名册
            p._cons_meta = None
            p._symbols = list(p.main_win.engine.list_stock_symbols())
            p._names = dict(p.main_win.engine.roster_names())
            if not p._symbols:
                p._result.set_empty(
                    '花名册是空的 —— 请先跑 `py scripts/sync_roster.py` 同步全市场代码。',
                    '重试', self.resolve_scope)
            p.lbl_scope.setText(f'{len(p._symbols)} 只')
        self._refresh_chips()
        if p._symbols:
            p._result.set_empty(f'范围就绪（{len(p._symbols)} 只）—— 正在体检本地数据就绪度…')
            p._readiness.start(p._symbols,
                               min_bars=p._filter_pane.to_thresholds().min_bars)
        self._maybe_run_pending()          # ★v1.46：重跑等的是"名单 + 体检都就绪"

    def _on_constituents(self, result, token: int) -> None:
        p = self.page
        if not p._guard.accept(token):                    # 迟到的旧解析直接丢
            return
        payload = result or {}
        if not payload.get('ok'):
            # ★ 人话诊断（D6/§10-10）：不再裸甩"接口未返回成分股"—— 分类说清
            #   网络挂了 / 源未收录该指数 / 代码有误，并给出替代路径（两页同款）。
            friendly = constituent_failure_text(str(payload.get('index_code') or ''),
                                                payload)
            p._result.set_empty(friendly, '重试', self.resolve_scope)
            p.lbl_scope.setText('解析失败')
            p.lbl_receipt.setText('成分股解析失败 —— '
                                  + str(payload.get('message') or payload.get('reason') or '未知原因')[:80])
            p.lbl_receipt.setToolTip(friendly)
            return
        p._symbols = [str(s) for s in (payload.get('symbols') or [])]
        # ★ 快照元信息（v6.42）：成分股每季度调换 —— 必须记住"名单是哪天的"，
        #   扫描历史基准日时才能把"幸存者偏差"说给用户，而不是默默拿今天的名单算旧日子
        p._cons_meta = {'name': str(p.cb_index.currentText()),
                        'count': len(p._symbols),
                        'snapshot_date': str(payload.get('snapshot_date') or '')}
        snap_line = constituent_snapshot_text(p.cb_index.currentText(), payload)
        # ★ 名称映射必须在这里补齐（v6.41 修复）：成分股回包只给**代码**，而自选/全A 两个
        #   分支都各自装配了 `_names` —— 漏了它 ⇒ ①结果表名称列全空；②**更隐蔽**：
        #   花名册为空 ⇒ 内核的「剔除 ST / 退市」整轮失效（内核会出警告，UI 此前把警告吞了）。
        #   名称来源与全A 同源 = `DataEngine.roster_names()`（§9-H：UI 不碰 DatabaseManager）。
        _roster = p.main_win.engine.roster_names()
        p._names = {sym: str(_roster.get(sym) or '') for sym in p._symbols}
        p.lbl_scope.setText(f'{len(p._symbols)} 只')
        p.lbl_scope.setToolTip(snap_line)
        self._refresh_chips()
        p._result.set_empty(
            f'名单就绪（{p.cb_index.currentText()} · {snap_line}）'
            f'—— 正在体检本地数据就绪度…')
        p._readiness.start(p._symbols,
                           min_bars=p._filter_pane.to_thresholds().min_bars)
        self._maybe_run_pending()          # ★v1.46：成分股是异步解析的，重跑在此接着走

    def _refresh_chips(self) -> None:
        p = self.page
        scope = p.cb_scope.currentText().replace('…', '')
        p.chip_scope.setText(f'🌐 {scope} {len(p._symbols)} 只')

    # ==========================================
    # 基准日选择器（先选后扫，v6.42）
    # ==========================================
    def _on_date_changed(self, qdate) -> None:
        """用户动日期控件（日历弹窗/键入/方向键）。

        没结果 ⇒ 只更新展示，扫描时再真的传；有结果 ⇒ 按**就近交易日**零成本重切。
        ⚠ 不把选择器**改回去**到落位日：键入过程中逐段发信号，强改会打断输入；
        真正生效的日子以 lbl_day / 回执为准（程序化移动才同步控件，见 _sync_date_edit）。
        """
        p = self.page
        p._date_touched = True
        stamp = _stamp_of(qdate)
        p.lbl_day.setText(str(stamp.date()))
        if p._outcome is None:
            p.lbl_receipt.setText(f'基准日 {stamp.date()} —— 点「▶ 开始扫描」按这一天取截面。')
            return
        dates = p._outcome.result.dates
        eff = _nearest_on_axis(dates, stamp) or stamp
        p._asof = eff
        self.refresh()
        if eff != stamp:
            p.lbl_receipt.setText(f'{stamp.date()} 不是本地交易日，已就近显示 {eff.date()}。')

    def _sync_date_edit(self, stamp) -> None:
        """程序化把控件拨到某天（不发 dateChanged，不跟用户抢输入）。"""
        p = self.page
        qd = QDate.fromString(str(pd.Timestamp(stamp).date()), 'yyyy-MM-dd')
        if not qd.isValid():
            return
        latest = pd.Timestamp(stamp)
        dates = p._outcome.result.dates if p._outcome is not None else None
        if dates is not None and len(dates):
            latest = max(latest, pd.Timestamp(dates[-1]))
        p.date_asof.blockSignals(True)
        try:
            if qd > p.date_asof.maximumDate():
                p.date_asof.setMaximumDate(qd)
            if latest > p.date_asof.maximumDate():
                p.date_asof.setMaximumDate(QDate.fromString(str(latest.date()), 'yyyy-MM-dd'))
            p.date_asof.setDate(qd)
        finally:
            p.date_asof.blockSignals(False)

    # ==========================================
    # 扫描前闸门：缺数据必须**告知 + 二次确认**（用户 2026-09-21 拍板：
    # 不许"名单 429 → 有效样本 27"这种不声不响的落差）
    # ==========================================
    def _confirm_scan_with_gaps(self) -> bool:
        """→ True = 可以继续扫。体检已知有缺口 / 体检还没完成 ⇒ 弹窗让用户拍板。"""
        p = self.page
        report = p._readiness.report if getattr(p, '_readiness', None) is not None else None
        if report is not None and report.gap_count == 0:
            return True                       # 本地齐了 ⇒ 不打扰（闸门只在**有问题时**出现）
        yes = QMessageBox.StandardButton.Yes
        if report is not None:
            answer = QMessageBox.question(
                p, '本地数据不完整',
                f'统计范围 {report.total} 只里，本地缺 {report.gap_count} 只的日线文件\n'
                f'（体检：{report.summary_line()}）\n\n'
                '缺的会被记成「数据不足」，命中/有效样本只基于现有数据算 ——\n'
                f'这种结果只能看局部，不能当全市场结论。建议先「{SYNC_ACTION_LABEL}」再扫。\n\n'
                '仍要现在就基于现有数据扫描吗？',
                yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != yes:
                p.lbl_receipt.setText(f'已取消 —— 点「{SYNC_ACTION_LABEL}」把缺的数据下载齐，'
                                      f'或再点「▶ 开始扫描」。')
                return False
            return True
        answer = QMessageBox.question(
            p, '就绪度体检还没完成',
            f'范围 {len(p._symbols)} 只的本地数据体检还没跑完，可能有一大半没下载。\n'
            '现在就扫（缺的会记「数据不足」并在回执出声），还是等体检完成？',
            yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != yes:
            p.lbl_receipt.setText('等就绪度体检完成后再扫 —— 体检结果会自己出现在这里。')
            return False
        return True

    # ==========================================
    # 扫描（后台线程 + 竞态守卫 + 进度回执）
    # ==========================================
    def on_run_clicked(self) -> None:
        p = self.page
        if p._worker is not None and p._worker.isRunning():
            p._worker.cancel()                            # 再点一次 = 取消（E 节：按钮态互换）
            p.lbl_receipt.setText('取消中…')
            return
        if not p._symbols:
            p.lbl_receipt.setText('范围是空的 —— 先选好统计范围。')
            return
        formula = p._formula_pane.txt_formula.toPlainText().strip()
        if not formula:
            p.lbl_receipt.setText('筛选条件是空的 —— 点「⚙ 配置」写一段条件。')
            return
        p._thresholds = p._filter_pane.to_thresholds()
        problems = p._thresholds.problems()
        if problems:
            p.lbl_receipt.setText('配置有笔误：' + '；'.join(problems))
            return
        try:
            params = parse_params_text(p._formula_pane.txt_params.text())
        except Exception as e:  # noqa: BLE001
            p.lbl_receipt.setText(f'参数写法不对：{e}')
            return
        if not self._confirm_scan_with_gaps():
            return                            # 闸门拦下：什么都没发生（不留下半截状态）

        p._asof = None                                    # 结果出来后回填（= 控件所选日，轴外由内核就近落位）
        asof = _stamp_of(p.date_asof.date())              # 先选后扫：把用户选的基准日真的传下去
        p._result.set_busy('扫描中…（读盘 → 粗筛 → 逐标的求值）')
        p.btn_run.setText('✕ 取消扫描')
        p.bar_progress.show()
        p.bar_progress.setRange(0, 1)
        p.bar_progress.setValue(0)
        p.lbl_cached.setText('')
        p.lbl_receipt.setText('准备扫描…')
        p.save_scan_ui()

        job = p._guard.next()                             # 取号：迟到的旧回包会被丢弃（§9-O5）
        p._worker = CrossSectionWorker(
            job, kline_zone_dir('kline_daily'), formula, symbols=list(p._symbols),
            params=params, thresholds=p._thresholds, asof=asof,
            names=dict(p._names), snapshot_columns=('close', 'amount', 'turnover',
                                                     'volume', 'outstanding_share'),
            store=p._store)
        p._worker.progress.connect(self._on_progress)
        p._worker.finished.connect(self._on_finished)
        p._worker.failed.connect(self._on_failed)
        p._worker.start()

    # ==========================================
    # ★v1.46：历史页「重跑」—— 等名单 + 体检都就绪再自动开扫
    # ==========================================
    def request_run(self) -> None:
        """外部（运行历史页「▶ 重跑」）请求"复用参数后立刻扫一次"。

        【为什么不能直接 `start_scan()`】旧版是 `apply_config()` + `start_scan()` 连招，两头都坏：
          ① 「指数成分」范围是**异步**解析的，`p._symbols` 此刻还是空 ⇒ `on_run_clicked`
             早退（回执"范围是空的"），用户点了重跑什么都没发生；
          ② 同步范围虽能起跑，但 `resolve_scope` 刚把体检报告清空 ⇒ 必弹
             "就绪度体检还没完成"的闸门框（重跑不该被自己的体检拦下）。
        这里改成：置一个"待跑"标记，等**名单到位**且**体检结束**后由 `_maybe_run_pending()`
        接手；**闸门照常生效**（真缺数据时仍会二次确认 —— 不绕过安全阀）。
        """
        p = self.page
        self._pending_run = True
        self._probe_done = False
        p._readiness.on_probe_done = self._on_probe_done_for_run
        p.lbl_receipt.setText('已复用参数 —— 正在解析范围 / 体检本地数据，就绪后自动开始扫描…')
        self._maybe_run_pending()

    def _on_probe_done_for_run(self) -> None:
        self._probe_done = True
        self._maybe_run_pending()

    def _maybe_run_pending(self) -> None:
        """名单 + 体检都就绪 ⇒ 真正开跑；否则等下一次回调。"""
        if not self._pending_run:
            return
        p = self.page
        if not p._symbols:
            return                              # 成分股还在异步解析
        if p._readiness.report is None and not self._probe_done:
            return                              # 体检还没结束
        self._pending_run = False
        p._readiness.on_probe_done = None
        self.on_run_clicked()

    def _on_progress(self, done: int, total: int, note: str) -> None:
        p = self.page
        if total > 0:
            p.bar_progress.setRange(0, total)
            p.bar_progress.setValue(done)
            p.lbl_receipt.setText(f'扫描 {done}/{total} · {note}')
        else:
            p.lbl_receipt.setText(str(note))

    def _restore_buttons(self) -> None:
        p = self.page
        p.btn_run.setText('▶ 开始扫描')
        p.bar_progress.hide()

    def _on_finished(self, job_id: int, outcome) -> None:
        p = self.page
        if not p._guard.accept(job_id):                   # 竞态守卫：迟到回包丢弃
            return
        self._restore_buttons()
        if outcome is None:                               # 用户取消（内核明确不回半成品）
            p.lbl_receipt.setText('已取消 —— 没有留下任何半成品结果。')
            if p._outcome is not None:
                self.refresh()                            # 回到上一次的有效结果
            else:
                p._result.set_empty('已取消。')
            return
        p._outcome = outcome
        p._asof = outcome.asof
        self._sync_date_edit(outcome.asof)                # 控件跟上真正算的那天（含就近落位）
        seconds = outcome.elapsed_ms / 1000.0
        counts = outcome.counts_on(p._asof)
        text = (f"扫描 {counts.get('total', 0)} 只 · 命中 {counts.get('hit', 0)}"
                f" · 有效样本 {counts.get('valid', 0)} · 用时 {seconds:.2f} s"
                + ('（缓存命中，未重算）' if outcome.cached else ''))
        # ★ 内核警告必须有出口（v6.41）：内核对"剔除 ST 未生效"这类口径残缺**出过声**，
        #   但 UI 此前把 warnings 整个吞掉 —— 静默 ≠ 没发生（§10-10：禁止静默）。
        warns = list(getattr(outcome.result, 'warnings', None) or [])
        if warns and not outcome.cached:
            text += ' · ⚠ ' + warns[0] + ('' if len(warns) == 1 else f'（等 {len(warns)} 条）')
        # ★ 幸存者偏差提示（v6.42）：成分股是**当前快照**，基准日更早 ⇒ 名单不是那时的
        meta = getattr(p, '_cons_meta', None)
        if (meta and p.cb_scope.currentIndex() == 1 and meta.get('snapshot_date')
                and outcome.result.asof is not None
                and pd.Timestamp(outcome.result.asof)
                < pd.Timestamp(meta['snapshot_date'])):
            text += (f' · ⚠ 成分是 {meta["snapshot_date"]} 的当前名单，'
                     f'基准日更早 ⇒ 幸存者偏差（非时点名单）')
        tip = ('⚠ ' + '\n⚠ '.join(warns)) if warns else ''
        p.lbl_receipt.setText(text)
        p.lbl_receipt.setToolTip(tip)
        self._refresh_chips()
        self.refresh(resize=True)          # ★新扫描 ⇒ 重测一次列宽（排序/切日期不再重测）
        self._auto_archive(outcome)         # ★P4：非缓存的新扫描落一份 kind=M2 快照
        self._maybe_fetch_valuation(outcome)  # ★P5：看的是最新交易日时，后台拉当前估值填 B 层列
        self._maybe_fetch_industry()        # ★P6：行业映射为空时后台抓一次（持久缓存）

    def _auto_archive(self, outcome) -> None:
        """扫描完成落一份 `kind=M2` 不可变快照（§7-B12 P4 · v1.46 重做）。

        受「每次回测 / 扫描自动存档」开关（`backtest_archive.auto`）控制；
        **缓存命中不重复落**（没新东西）；成功后补一行**可见回执**（旧版纯静默，
       用户根本不知道存了）；存档失败只记日志，**绝不拖挂扫描回执**（与 M1 同款容错）。
        """
        p = self.page
        if outcome is None or outcome.cached:
            return
        if not bool((preferences.get('backtest_archive') or {}).get('auto', True)):
            return
        try:
            counts = outcome.counts_on(outcome.asof)
            label, code = scope_snapshot(p, counts.get('total', 0))   # ★带指数名（旧版会丢）
            rid = BacktestArchive().save(build_scan_record(
                p.current_config(), kind=KIND_M2, scope_label=label, scope_code=code,
                counts=counts, asof=outcome.asof, source=SOURCE_AUTO))
            if rid:
                p._last_archive_id = rid
                mark_archived(p, label)
        except Exception as e:  # noqa: BLE001
            logger.warning('M2 自动存档失败（忽略）: %s', e)

    # ==========================================
    # ★P5 B 层估值（当前值：仅基准日==数据最新交易日才取/才显，否则 '—'）
    # ==========================================
    def _valuation_for(self, stamp):
        """当前查看日与已取估值对应日一致才回估值（否则 None ⇒ 那三列 '—'）。"""
        p = self.page
        if not p._valuation or p._valuation_date is None:
            return None
        return p._valuation if pd.Timestamp(stamp).normalize() == p._valuation_date else None

    def _maybe_fetch_valuation(self, outcome) -> None:
        """新扫描且看的就是数据最新交易日 ⇒ 后台拉一次全市场当前估值（非阻塞、不连累扫描）。"""
        p = self.page
        dates = getattr(outcome.result, 'dates', None)
        if dates is None or len(dates) == 0:
            return
        latest = pd.Timestamp(dates[-1]).normalize()
        if outcome.asof is None or pd.Timestamp(outcome.asof).normalize() != latest:
            p._valuation, p._valuation_date = None, None   # 历史基准日：不取、不显
            return
        if p._valuation_date == latest:                     # 这份最新日已取过，不重复请求
            return
        if p._valuation_worker is not None and p._valuation_worker.isRunning():
            return
        job = p._valuation_guard.next()
        p._valuation_worker = SpotValuationWorker(parent=p)
        p._valuation_worker.finished.connect(
            lambda data, token=job: self._on_valuation_ready(data, token))
        p._valuation_worker.start()

    def _on_valuation_ready(self, data, token: int) -> None:
        """估值回包：过守卫后存下并重画（带上 B 层列）；None ⇒ 诚实留 '—'。"""
        p = self.page
        if not p._valuation_guard.accept(token):
            return                                          # 迟到的旧回包丢弃
        if data:
            dates = getattr(p._outcome.result, 'dates', None) if p._outcome else None
            p._valuation = data
            p._valuation_date = (pd.Timestamp(dates[-1]).normalize()
                                 if dates is not None and len(dates) else None)
            self.refresh()                                  # 重画带上估值（不重测列宽）

    # ==========================================
    # ★P6 细分行业（本地缓存 industry_map.json；为空时后台抓一次，扫描只读缓存）
    # ==========================================
    def _maybe_fetch_industry(self) -> None:
        """行业映射为空 ⇒ 后台抓一次全市场行业（~80+ 请求，一次性、持久缓存）；已有则跳过。"""
        p = self.page
        if get_industry_store().is_loaded():
            return
        if p._industry_worker is not None and p._industry_worker.isRunning():
            return
        job = p._industry_guard.next()
        p._industry_worker = IndustryMapWorker(parent=p)
        p._industry_worker.finished.connect(
            lambda data, token=job: self._on_industry_ready(data, token))
        p._industry_worker.start()

    def _on_industry_ready(self, data, token: int) -> None:
        """行业映射回包：过守卫 → 存盘 + 重画（带上行业列）；**拿不到就出声**（绝不静默）。

        ★v6.68（用户 2026-09-26 实测："M2 结果里行业一直是空的，是不是我下载没弄好？"）：
          **旧版这个分支什么都不做** ⇒ 界面上只有一列 '—'，用户只会怀疑自己操作有问题。
          实测真因在**数据源**：东财 `clist/get` 端点对本机**直接断连**（同域名单点报价却 HTTP 200），
          而细分板块唯一来源就是它 ⇒ 映射永远为空、`industry_map.json` 从不落盘 —— **不是下载没弄好、
          也不是这里代码错**。⇒ 修法：**把失败与出路写在回执上**（追加而非覆盖）。
        """
        p = self.page
        if not p._industry_guard.accept(token):
            return
        if data:
            get_industry_store().replace(data)
            self.refresh()
            return
        # 失败（None / 空表）：**可见回执 + 出路**（"再点一次开始扫描"就会重试 ——
        #   `_maybe_fetch_industry` 在缓存为空时**每次扫描完成都跑**，缓存命中也算）
        _note = (' · ⚠ 行业映射未取到（东财板块接口不可用或返回空）—— 该列暂显 \'—\'；'
                 '再点一次「▶ 开始扫描」会重试')
        if '行业映射未取到' not in (p.lbl_receipt.text() or ''):
            p.lbl_receipt.setText((p.lbl_receipt.text() or '') + _note)
        _tip = ('行业 = 细分板块，来自东财「行业板块成分」接口（约 80+ 次请求，抓一次长期缓存）。\n'
                '抓不到就诚实留 \'—\'，**绝不拿别的口径瞎猜板块**。\n'
                '常见原因：东财该接口对本机临时不可用（限流/风控）—— 过一会儿再点一次「▶ 开始扫描」即可重试。')
        p.lbl_receipt.setToolTip(((p.lbl_receipt.toolTip() or '') + '\n' + _tip).strip())

    def _on_failed(self, job_id: int, reason: str) -> None:
        p = self.page
        if not p._guard.accept(job_id):
            return
        self._restore_buttons()
        p.lbl_receipt.setText('扫描失败 —— ' + reason[:120])
        p.lbl_receipt.setToolTip(reason)
        p._result.set_empty('扫描失败。常见原因：公式语法 / 函数名写错；分区读不出来。',
                            '查看原因', lambda: p.lbl_receipt.setToolTip(reason))

    # ==========================================
    # 结果刷新（含**切日期零成本**）
    # ==========================================
    def refresh(self, resize: bool = False) -> None:
        p = self.page
        outcome = p._outcome
        if outcome is None:
            return
        date = p._asof or outcome.asof
        stamp = pd.Timestamp(date)
        # 只有扫描基准日才有"数值/明细"；早退路径（整份名单无文件）的 asof 是 None，
        # 它产出的 status/detail **就是那天该展示的全部内容** ⇒ 同样按基准日处理（v6.42）
        same_day = (stamp == outcome.result.asof) or outcome.result.asof is None
        counts = outcome.counts_on(stamp)
        status = outcome.status_on(stamp)
        p._result.render(
            counts, status,
            detail=outcome.result.detail if same_day else None,
            snapshot=outcome.result.snapshot if same_day else None,
            names=p._names, elapsed_ms=outcome.elapsed_ms, cached=outcome.cached,
            date_label=str(stamp.date()), scope_label=p.cb_scope.currentText().replace('…', ''),
            valuation=self._valuation_for(stamp), industry=get_industry_store().as_map(),
            resize=resize)
        p.lbl_day.setText(str(stamp.date()))
        p.lbl_cached.setText('缓存命中（未重算）' if outcome.cached else '')
        p.lbl_day.setToolTip('在交易日轴上 ◀ ▶ 移动是**零成本**的（读缓存矩阵，D3）。\n'
                             '⚠ 只有扫描基准日才有当日数值与"为什么"明细。')

    def shift_date(self, delta: int) -> None:
        p = self.page
        if p._outcome is None or p._outcome.result.dates is None:
            p.lbl_receipt.setText('没有可切换的交易日轴 —— 范围内标的本地多半没有日线，'
                                  f'先「{SYNC_ACTION_LABEL}」再扫。')
            return
        dates = p._outcome.result.dates
        current = p._asof or p._outcome.result.asof
        stamp = pd.Timestamp(current)
        idx = int(dates.searchsorted(stamp))
        if idx >= len(dates) or dates[idx] != stamp:
            idx = max(0, min(idx, len(dates) - 1))        # 轴上没有的那天 ⇒ 就近落位
        target = int(min(max(idx + delta, 0), len(dates) - 1))
        if dates[target] == stamp:
            return
        p._asof = pd.Timestamp(dates[target])
        self.refresh()                                    # 纯切片，零成本
        self._sync_date_edit(p._asof)                     # 控件跟着 ◀▶ 走

    def jump_latest(self) -> None:
        p = self.page
        if p._outcome is None:
            return
        p._asof = pd.Timestamp(p._outcome.result.dates[-1])
        self.refresh()
        self._sync_date_edit(p._asof)

    # ==========================================
    # 配置 / 跳转
    # ==========================================
    def open_config(self) -> None:
        p = self.page
        p.open_pane(p._last_pane or 'fn')

    def reset_thresholds(self) -> None:
        p = self.page
        p._filter_pane.from_thresholds(ScanThresholds())   # 「↺ 恢复默认」（D5）
        p._thresholds = ScanThresholds()
        p.save_scan_ui()
        p.lbl_receipt.setText('已恢复默认粗筛 —— 点「▶ 开始扫描」生效。')

    # ==========================================
    # ★P3 配置打包 / 还原（供筛选方案库与偏好加载共用 —— 单一事实源）
    # ==========================================
    def current_config(self) -> dict:
        """把当前筛选配置打包成可持久化快照（与 scan_ui 偏好同形，另加 adjust）。"""
        p = self.page
        return {
            'scope': p.cb_scope.currentIndex(),
            'index_code': str(p.cb_index.currentData() or ''),
            'formula': p._formula_pane.txt_formula.toPlainText(),
            'params': p._formula_pane.txt_params.text(),
            'thresholds': p._filter_pane.to_thresholds().to_dict(),
            'adjust': 'qfq',
        }

    def apply_config(self, cfg: dict) -> None:
        """把一份配置快照整体还原进页面（缺字段逐个回落默认；与 `_load_scan_ui` 共用同一口径）。

        还原后手动触发一次 `resolve_scope`（范围/指数可能变了 ⇒ 重新解析名单与体检）。
        """
        cfg = cfg or {}
        p = self.page
        p._ui_restoring = True
        try:
            try:
                index = int(cfg.get('scope') or 0)
            except (TypeError, ValueError):
                index = 0
            p.cb_scope.setCurrentIndex(index if 0 <= index < p.cb_scope.count() else 0)
            p.cb_index.setVisible(p.cb_scope.currentIndex() == 1)
            code = str(cfg.get('index_code') or '')
            if code:
                idx = p.cb_index.findData(code)
                if idx >= 0:
                    p.cb_index.setCurrentIndex(idx)
            p._formula_pane.txt_formula.setPlainText(str(cfg.get('formula') or ''))
            p._formula_pane.txt_params.setText(str(cfg.get('params') or ''))
            thresholds = ScanThresholds.from_dict(cfg.get('thresholds'))
            p._thresholds = thresholds
            p._filter_pane.from_thresholds(thresholds)
        finally:
            p._ui_restoring = False
        p.resolve_scope()

    def on_header_clicked(self, col: int) -> None:
        """★P1 点表头 → 切换排序态后重画（排序是展示层，四态计数仍走 `tally_status` 唯一口径）。

        默认命中置顶；点数值/文本列 = 全局排序；点状态列 = 复位。未扫描（无结果）时不响应。
        ★P7：拖拽换列序后 visual≠logical，sectionClicked 传的是**视觉列号**，需转回逻辑列号。
        """
        p = self.page
        if p._outcome is None:
            return
        logical = p.table.horizontalHeader().logicalIndex(col)
        if p._result.toggle_sort(logical):
            self.refresh()

    # ==========================================
    # ★P7 列顺序拖拽自定义（visual→logical 持久化到 scan_ui）
    # ==========================================
    def current_column_order(self) -> list:
        """当前列视觉顺序（每个视觉位上的 logical 索引），供 scan_ui 持久化。"""
        header = self.page.table.horizontalHeader()
        return [header.logicalIndex(v) for v in range(self.page.table.columnCount())]

    def apply_column_order(self, order) -> None:
        """恢复列序（visual→logical）。非法/长度不符（旧档）→ 保持默认不动。"""
        p = self.page
        header = p.table.horizontalHeader()
        n = p.table.columnCount()
        if not order or len(order) != n or sorted(order) != list(range(n)):
            return
        p._restoring_order = True
        try:
            for visual, logical in enumerate(order):
                if header.logicalIndex(visual) != logical:
                    header.moveSection(header.visualIndex(logical), visual)
        finally:
            p._restoring_order = False

    def _on_section_moved(self, *_a) -> None:
        """拖拽换列序后持久化（加载期抑制，避免恢复时回写）。"""
        p = self.page
        if getattr(p, '_restoring_order', False):
            return
        p.save_scan_ui()

    def on_row_double_clicked(self, item) -> None:
        """双击结果行 → 行情工作台打开该股（E 节：**不另做看图器**）。

        ⚠ 首列 `#` 行号入表后，代码/名称列索引各 +1（代码=1、名称=2）。
        """
        p = self.page
        row = item.row()
        sym_item = p.table.item(row, 1)
        if sym_item is None:
            return
        symbol = str(sym_item.text())
        name = str(p.table.item(row, 2).text()) if p.table.item(row, 2) else ''
        if not symbol:
            return
        p.main_win.page_market.load_symbol(symbol, name)
        p.main_win.switch_to('market')
