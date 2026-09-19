# ui/widgets/breadth_flow.py
"""📊 M3「广度统计」—— 运行流程（范围解析 / 扫描 / ⚡增量 / ⟳全量重算 / 区间切片 / 指数链）。

【为什么这里只有"调度"】读盘、掩码、求值在 `core/cross_section`（纯计算），
缓存在 `data/scan_store`（纯内存；⚡增量与 ⟳全量重算的差别也在那一层落地），
线程在 `ui/workers.py`（§9-O2）—— 本模块只做"把用户的动作接到那条管线上"，
并负责**回执的一行人话化**（§10-10）。

【⚡ 增量到最新（主案 D7）】`breadth[date]` 只依赖 ≤ date 的数据 ⇒ 增量 =
"同配置旧矩阵 + 新交易日尾段"（`scan_cached(incremental=True)`），**历史一天都不动**；
数据被修订 / 换了复权口径不走这里 —— 那是「⟳ 全量重算」（危险动作：低调呈现 +
QMessageBox 二次确认，§10-10）的职责。

【区间切换为什么零成本】一次扫描的矩阵本来就是**全日期**的（D3）⇒ 换区间只是
`breadth_frame()` 上的纯切片，不进线程、不读盘、不求值。

【指数副图】读 `index_daily` 分区；缺数据**自动补拉一次**（后台 `SingleSyncWorker`，
联网走 `MarketSyncService`，§9-H）—— 失败只出声，**绝不连累主图广度**。
"""
from __future__ import annotations

import logging

import pandas as pd
from PyQt6.QtWidgets import QMessageBox

from core.cross_section import ScanThresholds
from core.utils import parse_params_text
from data.market_db import DataLakeManager
from data.scan_store import kline_zone_dir
from data.sync_service import ZONE_INDEX
from data.watchlist_store import WatchlistStore
from ui.widgets.breadth_layout import DEFAULT_INDEX_CODE, DEFAULT_RANGE, RANGE_PRESETS
from ui.widgets.readiness_flow import constituent_failure_text
from ui.workers import ConstituentsWorker, CrossSectionWorker, JobGuard, SingleSyncWorker

__all__ = ['BreadthFlow', 'BREADTH_UI_KEY']

logger = logging.getLogger(__name__)

BREADTH_UI_KEY = 'breadth_ui'    # 页面偏好键（core/preferences.DEFAULTS 里登记）

# 区间 key → pd.DateOffset（'all' 不截断）
_RANGE_OFFSET = {
    '3m': pd.DateOffset(months=3), '6m': pd.DateOffset(months=6),
    '1y': pd.DateOffset(months=12), '3y': pd.DateOffset(years=3),
    '5y': pd.DateOffset(years=5),
}
_RANGE_LABELS = dict(RANGE_PRESETS)


class BreadthFlow:
    """M3 页的运行流程（只读写 `p.X`，不存状态）。"""

    def __init__(self, page):
        self.page = page
        p = self.page
        p.cb_scope.currentIndexChanged.connect(self.on_scope_changed)
        p.cb_index.currentIndexChanged.connect(self.on_index_changed)
        p.cb_range.currentIndexChanged.connect(self.on_range_changed)
        p.btn_config.clicked.connect(self.open_config)
        p.btn_run.clicked.connect(self.on_run_clicked)
        p.btn_incr.clicked.connect(self.on_incremental_clicked)
        p.btn_full.clicked.connect(self.on_full_clicked)
        p._filter_pane.btn_reset.clicked.connect(self.reset_thresholds)
        p._display_pane.chk_smooth.toggled.connect(self.on_display_changed)
        p._display_pane.chk_ratio.toggled.connect(self.on_display_changed)
        p._display_pane.chk_overlay.toggled.connect(self.on_display_changed)
        p._display_pane.cb_overlay_code.currentIndexChanged.connect(self.on_overlay_code_changed)

    # ==========================================
    # 范围（自选 / 指数成分 / 全 A）—— 与 M2 同一套语义
    # ==========================================
    def on_scope_changed(self) -> None:
        p = self.page
        p.cb_index.setVisible(p.cb_scope.currentIndex() == 1)
        self.resolve_scope()

    def on_index_changed(self) -> None:
        if self.page.cb_scope.currentIndex() == 1:
            self.resolve_scope()

    def resolve_scope(self) -> None:
        """把"统计范围"落成 `{标的: 名称}`。自选 / 全A 同步；指数成分**异步**（§9-H）。"""
        p = self.page
        p._names = {}
        choice = p.cb_scope.currentIndex()
        if choice == 0:                                   # 我的自选
            p._symbols = list(WatchlistStore().symbols())
            p._names = dict(WatchlistStore().names_map())
            if not p._symbols:
                p._result.set_empty('自选清单是空的 —— 先去「行情工作台」加几只自选，再来看广度。',
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

    def _on_constituents(self, result, token: int) -> None:
        p = self.page
        if not p._guard.accept(token):                    # 迟到的旧解析直接丢
            return
        payload = result or {}
        if not payload.get('ok'):
            # ★ 人话诊断（D6/§10-10）：与 M2 同款 —— 分类说清失败原因与替代路径。
            friendly = constituent_failure_text(str(payload.get('index_code') or ''),
                                                payload)
            p._result.set_empty(friendly, '重试', self.resolve_scope)
            p.lbl_scope.setText('解析失败')
            p.lbl_receipt.setText('成分股解析失败 —— '
                                  + str(payload.get('message') or payload.get('reason') or '未知原因')[:80])
            p.lbl_receipt.setToolTip(friendly)
            return
        p._symbols = [str(s) for s in (payload.get('symbols') or [])]
        # ★ 名称映射必须在这里补齐（v6.41 修复，与 scan_flow 同款）：漏了它 ⇒ 「剔除 ST」
        #   在广度统计里整轮失效（ST 股会被算进家数）。
        _roster = p.main_win.engine.roster_names()
        p._names = {sym: str(_roster.get(sym) or '') for sym in p._symbols}
        p.lbl_scope.setText(f'{len(p._symbols)} 只')
        self._refresh_chips()
        p._result.set_empty(
            f'名单就绪（{len(p._symbols)} 只，{p.cb_index.currentText()}）'
            f'—— 正在体检本地数据就绪度…')
        p._readiness.start(p._symbols,
                           min_bars=p._filter_pane.to_thresholds().min_bars)

    def _refresh_chips(self) -> None:
        p = self.page
        scope = p.cb_scope.currentText().replace('…', '')
        p.chip_scope.setText(f'🌐 {scope} {len(p._symbols)} 只')

        formula = p._formula_pane.txt_formula.toPlainText().strip()
        p.chip_formula.setText('ƒ 条件 ✓' if formula else 'ƒ 条件 —')

        th = p._filter_pane.to_thresholds()
        n_th = sum(1 for value in (th.min_amount, th.min_price, th.min_bars,
                                   th.min_turnover, th.min_float_mktcap) if value is not None)
        n_bool = sum(1 for flag in (th.exclude_suspended, th.exclude_st, th.exclude_limit)
                     if flag)
        p.chip_filter.setText(f'🎚 粗筛 {n_th + n_bool} 项')

        pane = p._display_pane
        parts = []
        if pane.chk_smooth.isChecked():
            parts.append('MA5')
        if pane.chk_ratio.isChecked():
            parts.append('占比%')
        if pane.chk_overlay.isChecked():
            parts.append(str(pane.cb_overlay_code.currentText()).split(' ')[0])
        p.chip_display.setText('📈 展示 ' + ('·'.join(parts) if parts else '家数'))

    # ==========================================
    # 扫描（后台线程 + 竞态守卫 + 进度回执）
    # ==========================================
    def _start_worker(self, *, force: bool = False, incremental: bool = False,
                      busy_text: str) -> bool:
        p = self.page
        if p._worker is not None and p._worker.isRunning():
            p._worker.cancel()                            # 再点 = 取消（与 M2 同款交互）
            p.lbl_receipt.setText('取消中…')
            return False
        if not p._symbols:
            p.lbl_receipt.setText('范围是空的 —— 先选好统计范围。')
            return False
        formula = p._formula_pane.txt_formula.toPlainText().strip()
        if not formula:
            p.lbl_receipt.setText('筛选条件是空的 —— 点「⚙ 配置」写一段条件。')
            return False
        p._thresholds = p._filter_pane.to_thresholds()
        problems = p._thresholds.problems()
        if problems:
            p.lbl_receipt.setText('配置有笔误：' + '；'.join(problems))
            return False
        try:
            params = parse_params_text(p._formula_pane.txt_params.text())
        except Exception as e:  # noqa: BLE001
            p.lbl_receipt.setText(f'参数写法不对：{e}')
            return False

        p._result.set_busy(busy_text)
        p.btn_run.setText('✕ 取消扫描')
        p.bar_progress.show()
        p.bar_progress.setRange(0, 1)
        p.bar_progress.setValue(0)
        p.lbl_cached.setText('')
        p.lbl_receipt.setText(busy_text)
        p.save_breadth_ui()

        job = p._guard.next()                             # 取号：迟到的旧回包会被丢弃（§9-O5）
        p._worker = CrossSectionWorker(
            job, kline_zone_dir('kline_daily'), formula, symbols=list(p._symbols),
            params=params, thresholds=p._thresholds, asof=None,
            names=dict(p._names), force=force, incremental=incremental,
            store=p._store)
        p._worker.progress.connect(self._on_progress)
        p._worker.finished.connect(self._on_finished)
        p._worker.failed.connect(self._on_failed)
        p._worker.start()
        return True

    def on_run_clicked(self) -> None:
        self._start_worker(busy_text='扫描中…（读盘 → 粗筛 → 逐标的求值）')

    def on_incremental_clicked(self) -> None:
        """⚡ 增量到最新：历史矩阵一天都不重算，只续算新交易日（D7）。"""
        p = self.page
        if p._outcome is None:
            p.lbl_receipt.setText('还没有可增量的结果 —— 先点「▶ 开始扫描」跑一次。')
            return
        self._start_worker(incremental=True,
                           busy_text='增量计算中…（历史沿用原矩阵，只算新交易日）')

    def on_full_clicked(self) -> None:
        """⟳ 全量重算：危险动作 = 低调呈现 + 二次确认（§10-10）；只有修订 / 换口径才需要。"""
        p = self.page
        answer = QMessageBox.question(
            p, '全量重算',
            '全量重算会按**当前数据**把整段历史重新算一遍（历史广度可能整体变化）。\n\n'
            '只有两种情况需要它：① 怀疑历史行情被修订过；② 换了复权口径。\n'
            '日常补最新交易日请用「⚡ 增量到最新」，它只算新交易日、历史不动。\n\n'
            '确定现在全量重算吗？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            p.lbl_receipt.setText('已取消全量重算 —— 原结果未动。')
            return
        self._start_worker(force=True, busy_text='全量重算中…（历史将按最新数据整体重算）')

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
            return
        p._outcome = outcome
        seconds = outcome.elapsed_ms / 1000.0
        if outcome.note:
            text = outcome.note
            if not outcome.cached and seconds >= 0.005:
                text += f' · 用时 {seconds:.2f} s'
        elif outcome.cached:
            text = '缓存命中（未重算）'
        else:
            counts = outcome.result.counts
            text = (f"扫描 {counts.get('total', 0)} 只 · 最新命中 {counts.get('hit', 0)}"
                    f" · 有效样本 {counts.get('valid', 0)} · 用时 {seconds:.2f} s")
        # ★ 内核警告必须有出口（v6.41，与 scan_flow 同款）：吞掉 warnings = "剔除 ST 未生效"
        #   这类口径残缺永远没人看见（§10-10：禁止静默）。
        warns = list(getattr(outcome.result, 'warnings', None) or [])
        if warns and not outcome.cached:
            text += ' · ⚠ ' + warns[0] + ('' if len(warns) == 1 else f'（等 {len(warns)} 条）')
        p.lbl_receipt.setText(text)
        p.lbl_receipt.setToolTip(
            ('\n'.join(filter(None, [outcome.note or '',
                                     *('⚠ ' + w for w in warns)]))))
        self._refresh_chips()
        self.refresh()

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
    # 结果刷新（区间切换 = 纯切片，零成本）
    # ==========================================
    def on_range_changed(self) -> None:
        p = self.page
        index = max(0, min(p.cb_range.currentIndex(), len(RANGE_PRESETS) - 1))
        p._range_key = RANGE_PRESETS[index][0]
        self.refresh()                                    # 纯切片，零成本
        p.save_breadth_ui()

    def set_range(self, key: str) -> None:
        """程序化切区间（测试 / 快捷键用）；key 不认识就退回默认。"""
        p = self.page
        if key not in _RANGE_LABELS:
            key = DEFAULT_RANGE
        p._range_key = key
        p.cb_range.setCurrentIndex([k for k, _ in RANGE_PRESETS].index(key))

    def on_display_changed(self) -> None:
        p = self.page
        self._refresh_chips()
        self.refresh()                                    # 重画是纯渲染；数据不动
        p.save_breadth_ui()

    def on_overlay_code_changed(self) -> None:
        p = self.page
        p._index_df = None                                # 换指数 ⇒ 重新走取数链
        self.on_display_changed()

    def refresh(self) -> None:
        """用缓存矩阵重画当前区间（**零成本**：不进线程、不读盘，D3）。"""
        p = self.page
        outcome = p._outcome
        if outcome is None:
            return
        full = outcome.breadth_frame()
        if full.empty:
            p._result.set_empty('这次扫描没有产出任何广度数据 —— 检查统计范围内是否有可用日线。',
                                '重新扫描', self.on_run_clicked)
            return
        offset = _RANGE_OFFSET.get(p._range_key)
        frame = full if offset is None else full[full.index >= full.index[-1] - offset]
        if frame.empty:
            frame = full
        self._render(frame)
        if p._display_pane.chk_overlay.isChecked():
            self._ensure_index()

    def _render(self, frame: pd.DataFrame) -> None:
        p = self.page
        overlay_wanted = p._display_pane.chk_overlay.isChecked()
        overlay_code = str(p._display_pane.cb_overlay_code.currentData() or '')
        index_df = p._index_df if (overlay_wanted and p._index_code == overlay_code) else None
        index_label = str(p._display_pane.cb_overlay_code.currentText()).split(' ')[0]
        painted = p.chart.render(
            frame, index_df, index_label=index_label,
            smooth=p._display_pane.chk_smooth.isChecked(),
            ratio=p._display_pane.chk_ratio.isChecked())
        if painted:
            p.chart.show()
            p.empty_box.hide()
        else:
            p.chart.hide()
            p.empty_box.show()
        p.btn_incr.setEnabled(True)
        p.lbl_cached.setText('缓存命中（未重算）' if p._outcome.cached else '')
        self._render_caption(frame)
        self._render_mini(frame)

    def _render_caption(self, frame: pd.DataFrame) -> None:
        """口径印在标题行上（E 节）：范围 · 前复权 · 有效 N/M · 区间。"""
        p = self.page
        scope = p.cb_scope.currentText().replace('…', '')
        last = frame.iloc[-1]
        total = int(last.get('valid', 0) + last.get('filtered', 0)
                    + last.get('insufficient', 0))
        p.lbl_cal.setText(f'口径：{scope} · 前复权 · 有效 {int(last.get("valid", 0))}/{total}'
                          f' · {_RANGE_LABELS.get(p._range_key, p._range_key)}')
        p.lbl_cal.setToolTip('「有效」= 命中 + 未命中（广度占比的分母）；数据不足与被粗筛剔除'
                             '的标的**不进分母**（三态铁律，E 节）')

    def _render_mini(self, frame: pd.DataFrame) -> None:
        """近 5 日迷你读数（原型 foot）：`MM-DD · N 只 / x%`。"""
        p = self.page
        tail = frame.tail(5).iloc[::-1]
        cells = []
        for day, row in tail.iterrows():
            valid = int(row.get('valid', 0))
            hits = int(row.get('hits', 0))
            ratio = (hits / valid * 100) if valid > 0 else 0.0
            cells.append(f'{pd.Timestamp(day).strftime("%m-%d")} · {hits} 只 / {ratio:.1f}%')
        p.lbl_mini.setText(('近5日：' + ' ｜ '.join(cells)) if cells else '')

    # ==========================================
    # 指数副图数据链（读湖 → 缺了自动补拉一次；失败不连累主图）
    # ==========================================
    def _ensure_index(self) -> None:
        p = self.page
        code = str(p._display_pane.cb_overlay_code.currentData() or DEFAULT_INDEX_CODE)
        if p._index_code == code and p._index_df is not None and not p._index_df.empty:
            return
        df = p._lake.load_data(ZONE_INDEX, code)
        if df is not None and not df.empty:
            p._index_df = df
            p._index_code = code
            self.refresh()                                # 拿到了 ⇒ 带上副图重画
            return
        if p._index_fetching == code:
            return                                        # 已经在拉了，别重复发车
        name = str(p._display_pane.cb_overlay_code.currentText()).split(' ')[0]
        p.lbl_receipt.setText(f'副图缺 {name} 日线 —— 后台拉取中…（失败不影响主图广度）')
        p._index_fetching = code
        job = p._index_guard.next()
        p._index_worker = SingleSyncWorker(code, zone=ZONE_INDEX, parent=p)
        p._index_worker.finished.connect(
            lambda _result, token=job, c=code: self._on_index_fetched(c, token))
        p._index_worker.start()

    def _on_index_fetched(self, code: str, token: int) -> None:
        """拉取回包：过守卫 + 重读湖。拿到了就重画；拿不到就出声（绝不静默）。"""
        p = self.page
        if not p._index_guard.accept(token):
            return
        p._index_fetching = ''
        df = p._lake.load_data(ZONE_INDEX, code)
        if df is not None and not df.empty:
            p._index_df = df
            p._index_code = code
            self.refresh()
        else:
            name = str(p._display_pane.cb_overlay_code.currentText()).split(' ')[0]
            p.lbl_receipt.setText(f'副图的 {name} 日线没拉到 —— 主图广度不受影响；'
                                  '可稍后重试或去「数据管理」检查。')

    # ==========================================
    # 配置 / 阈值
    # ==========================================
    def open_config(self) -> None:
        p = self.page
        p.open_pane(p._last_pane or 'fn')

    def reset_thresholds(self) -> None:
        p = self.page
        p._filter_pane.from_thresholds(ScanThresholds())   # 「↺ 恢复默认」（D5）
        p._thresholds = ScanThresholds()
        p.save_breadth_ui()
        self._refresh_chips()
        p.lbl_receipt.setText('已恢复默认粗筛 —— 点「▶ 开始扫描」生效。')
