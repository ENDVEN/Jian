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

【指数副图】读 `index_daily` 分区；**缺数据 或 落后于主图广度轴** ⇒ 自动补拉到最新
（后台 `SingleSyncWorker`，联网走 `MarketSyncService`，§9-H）—— 失败只出声，
**绝不连累主图广度**；同一目标日只自动补一次，补不动也不空转刷网络（★v1.46/方案A）。
"""
from __future__ import annotations

import logging

import os
import datetime as _dt

import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from core.cross_section import ScanThresholds
from core.preferences import preferences
from core.utils import parse_params_text
from data.backtest_archive import KIND_M3, SOURCE_AUTO, BacktestArchive, build_scan_record
from data.market_db import DataLakeManager
from data.scan_store import kline_zone_dir
from data.sync_service import ZONE_INDEX
from data.watchlist_store import WatchlistStore
from ui.download_jobs import SingleSyncGate   # ★1.59：真源直连（不再经 hub 再导出）
from ui.widgets.breadth_chart import DEFAULT_CHART_TYPE, DEFAULT_INDEX_STYLE
from ui.widgets.breadth_layout import (DEFAULT_INDEX_CODE, DEFAULT_RANGE,  # noqa: E501
                                       RANGE_PRESETS, VIEW_CARD, VIEW_EVENT,
                                       VIEW_INDEX, VIEW_ROWS)
# ★1.73 / §7-B16 期 1：多行小图（每统计项一行）—— 柱口径常量与配色取自控件件（同一真源）
from ui import settings_registry                       # ★1.74 期 2：阈值写入走**注册表**（唯一写入点）
from dataclasses import asdict                             # ★1.74 期 2：判据 dataclass → 可渲染 dict
from core.relation_stats import (MODE_UNKNOWN, PREF_KEY,   # ★1.74 期 2：三道闸判据（唯一真源）
                                 clamp_thresholds, conditional_forward_returns,  # ★1.75 期 3
                                 event_study, gate_decision, hit_day_stats,
                                 lead_lag_corr, permutation_p, rank_ic_of,
                                 thresholds_from_prefs)
from ui.widgets.relation_card import WINDOWS as RELATION_WINDOWS   # ★1.75 期 3：与卡/导出同源
from ui.widgets.breadth_rows import BAR_MODE_HITS, BAR_MODE_RATIO, ROW_COLORS
from ui.widgets.custom_widgets import SYNC_ACTION_LABEL
from ui.widgets.summary_chip import set_chip_state   # ★1.64：胶囊高亮（三页同一份 chip）
from ui.widgets.readiness_flow import (constituent_failure_text,
                                       constituent_snapshot_text, mark_archived,
                                       scope_snapshot)
from ui.workers import ConstituentsWorker, CrossSectionWorker, JobGuard, SingleSyncWorker

from ui.widgets.breadth_plan_flow import BreadthPlanFlowMixin
from ui.widgets.breadth_relation_flow import BreadthRelationFlowMixin

__all__ = ['BreadthFlow', 'BREADTH_UI_KEY']

logger = logging.getLogger(__name__)

BREADTH_UI_KEY = 'breadth_ui'    # 页面偏好键（core/preferences.DEFAULTS 里登记）

# 区间 key → pd.DateOffset（'all' 不截断）
_RANGE_LABELS = dict(RANGE_PRESETS)


class BreadthFlow(BreadthRelationFlowMixin, BreadthPlanFlowMixin):
    """M3 页的运行流程（只读写 `p.X`，不存状态）。"""

    def __init__(self, page):
        self.page = page
        # ★v1.43 / §7-B11：指数补拉与后台队列的互斥占位（唯一公共件，别再手写 token）
        self._index_gate = SingleSyncGate(page)
        # ★v1.46 / 方案A：已自动补拉过的「(指数代码, 目标日)」—— 同一目标日只补一次，
        #   补不动（离线 / 当天指数尚未发布）就保留旧副图，绝不在 refresh 里空转刷网络。
        self._index_synced_to = None
        # ★v1.46：历史页「重跑」用 —— 等名单解析完再自动开扫（见 request_run）
        self._pending_run = False
        p = self.page
        p.cb_scope.currentIndexChanged.connect(self.on_scope_changed)
        p.cb_index.currentIndexChanged.connect(self.on_index_changed)
        p.cb_range.currentIndexChanged.connect(self.on_range_changed)
        p.btn_config.clicked.connect(self.open_config)
        p.btn_run.clicked.connect(self.on_run_clicked)
        p.btn_incr.clicked.connect(self.on_incremental_clicked)
        p.btn_full.clicked.connect(self.on_full_clicked)
        # ★v1.41 / §11.5-80：常驻「更新到最新」入口（晚绑定，不与构造顺序耦合）
        p.btn_sync.clicked.connect(lambda: p._readiness.update_latest())
        p._filter_pane.btn_reset.clicked.connect(self.reset_thresholds)
        p._display_pane.chk_smooth.toggled.connect(self.on_display_changed)
        p._display_pane.chk_ratio.toggled.connect(self.on_display_changed)
        p._display_pane.chk_overlay.toggled.connect(self.on_display_changed)
        p._display_pane.cb_overlay_code.currentIndexChanged.connect(self.on_overlay_code_changed)
        p._display_pane.cb_chart.currentIndexChanged.connect(self.on_display_changed)
        p._display_pane.cb_index_style.currentIndexChanged.connect(self.on_display_changed)
        # ★1.73 / §7-B16 期 1：**统计项面板**（唯一的编辑入口）—— 面板只发请求，
        #   本模块落地改动（`p._items` 是唯一真源），改完回灌 + 重画。**一律不重扫**。
        _panel = p._items_pane.panel
        _panel.add_requested.connect(self.on_item_add)
        _panel.remove_requested.connect(self.on_item_remove)
        _panel.toggle_visible_requested.connect(self.on_item_toggle_visible)
        _panel.focus_requested.connect(self.on_item_focus)
        _panel.import_requested.connect(self.on_import_item)   # ★1.76 期 4：从其他方案借一项
        # 公式一改，"可选判定变量"就变了 ⇒ 面板跟着刷新（解析很轻，逐键调用无压力）
        p._formula_pane.txt_formula.textChanged.connect(
            lambda: self.sync_items_panel(p))
        # ★1.73 收尾：首次引导条（可关）+ 常驻说明入口 + 副图高度（改完立即重画、不重扫）
        p.btn_hint_ok.clicked.connect(self.on_hint_dismissed)
        p.btn_gates_help.clicked.connect(self.show_gates_help)
        p._display_pane.spin_index_h.valueChanged.connect(self.on_display_changed)
        # ★1.74 期 2：均线窗口（改完重画、不重扫）+ 三道闸阈值（就地可调，与设置页同一份偏好）
        p._display_pane.spin_ma.valueChanged.connect(self.on_display_changed)
        p._display_pane.gate_row.changed.connect(self.on_thresholds_changed)
        p._display_pane.gate_row.set_values(thresholds_from_prefs(), silent=True)  # 开局回灌真值
        p.gate_bar.fix_requested.connect(self.on_gate_fix_clicked)
        p.gate_bar.why_requested.connect(self.show_gates_help)
        p.gate_bar.dismissed.connect(self.on_gate_dismissed)   # ★1.81 可手动收起
        # ★1.75 期 3：三视图切换 + 关系卡导出（按钮只发信号，落盘在本模块 —— widgets 不碰文件系统）
        p.seg_view.sigChanged.connect(self.on_view_changed)
        p.relation_card.export_png_requested.connect(self.on_export_png)
        p.relation_card.export_csv_requested.connect(self.on_export_csv)
        p._display_pane.chk_bands.toggled.connect(self.on_display_changed)   # 色带只换画法
        self.sync_items_panel(p)                 # 装配完成先喂一次（面板不该是空白下拉）

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

    def _drop_stale_result(self, scope_key) -> None:
        """范围变了 ⇒ 丢掉上一范围的展示痕迹（★v1.41 / §11.5-80，与 M2 同款）。

        【为什么必须丢】旧范围的口径摘要（"口径：沪深300 · 有效 295/300"）继续挂着，
        会与**新范围**的就绪度提示同屏打架；且 `_render_readiness` 会误以为
        "已有当前范围的结果"而走"回执不动"分支、不再给下载入口。
        判据用 `(范围选择, 指数代码)`：同一范围重新解析不清楚（别白丢用户的结果）。
        """
        p = self.page
        if getattr(p, '_scope_key', None) == scope_key:
            return
        p._scope_key = scope_key
        p._outcome = None
        p._result.clear()

    def resolve_scope(self) -> None:
        """把"统计范围"落成 `{标的: 名称}`。自选 / 全A 同步；指数成分**异步**（§9-H）。"""
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
        self._maybe_run_pending()          # ★v1.46：历史页重跑等的是"名单就绪"

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
        # ★ 快照元信息（v6.42，与 M2 同款）：记住"名单是哪天的"，区间更早时出声
        p._cons_meta = {'name': str(p.cb_index.currentText()),
                        'count': len(p._symbols),
                        'snapshot_date': str(payload.get('snapshot_date') or '')}
        snap_line = constituent_snapshot_text(p.cb_index.currentText(), payload)
        # ★ 名称映射必须在这里补齐（v6.41 修复，与 scan_flow 同款）：漏了它 ⇒ 「剔除 ST」
        #   在广度统计里整轮失效（ST 股会被算进家数）。
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
        self._maybe_run_pending()          # ★v1.46：成分股异步解析回来 ⇒ 重跑在此接着走

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

        # ★1.73：统计项胶囊（上屏几项 + 哪一项是焦点）
        _items = self.active_items(p)
        _focus = self.focus_key(p)
        _focus_label = next((str(it.get('label') or '') for it in _items
                             if str(it.get('key') or '') == _focus), '')
        p.chip_items.setText(f'📋 统计项 {len(_items)}' + (f'·焦点 {_focus_label}' if _focus_label else ''))
        p.chip_items.setToolTip(
            '上屏的判定变量（每项一行）：' + ('、'.join(str(it.get('label') or '') for it in _items)
                                          or '（空 —— 用公式最后一条）')
            + ' —— 点击打开「📋 统计项」卡')

        pane = p._display_pane
        parts = []
        chart_label = str(pane.cb_chart.currentText()).split('（')[0].strip()
        parts.append(chart_label or '柱状')
        if pane.chk_smooth.isChecked():
            parts.append('均线')
        parts.append('占比%' if pane.chk_ratio.isChecked() else '家数')
        if pane.chk_overlay.isChecked():
            parts.append(str(pane.cb_overlay_code.currentText()).split(' ')[0])
            style_text = str(pane.cb_index_style.currentText() or '')
            if style_text and str(pane.cb_index_style.currentData()) != 'line':
                parts[-1] = parts[-1] + style_text   # 如「中证500K线」（默认折线不占字）
        p.chip_display.setText('📈 展示 ' + '·'.join(parts))

    def sync_chip_states(self) -> None:
        """★1.64：摘要条胶囊的**高亮**跟着抽屉走（开着的那张 = `sel`，其余 = `on`）。

        ⚠ 与 M1/M2 同一口径：点胶囊打开配置后，胶囊自己必须"亮着"，否则看不出"现在开的是哪张"。
        """
        p = self.page
        for chip, key in ((p.chip_formula, 'fn'), (p.chip_filter, 'filter'),
                          (p.chip_scope, 'scope'), (p.chip_display, 'display')):
            set_chip_state(chip, 'sel' if p._open_key == key else 'on')

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
        # ★1.70 / §11.5-126：**前置检测闸**（与 M1/M2 同款）—— 语法 / 可判定变量 / 缺参先拦下，
        #   回执与抽屉里「🩺 检测条件」那行**同一条**（同一实现，不另写文案）。
        if not p._formula_pane.check_formula():
            p.lbl_receipt.setText('筛选条件没通过检测 —— 看配置抽屉里「🩺 检测条件」旁边那行说明。')
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

        # ★1.76 期 4：**多方案** —— 先排队（第一项恒为本页方案：条件/参数/阈值就是本页那一套），
        #   然后逐个跑（一次只起一个线程；跑完由 `_on_finished` 续下一个）。
        #   ⚠ 队列只有本页方案时，跑的与旧版**逐字相同**（`signal_names` = 本页那些项的判定变量）。
        # ★1.77 续：记下"这次扫描前"的淘汰计数 ⇒ 回包时如实说清有没有淘汰过别的方案
        p._evicted_seen = int(getattr(p._store, 'evicted', 0))
        p._scan_queue = self.scan_plan_queue(p)
        p._scan_index = 0
        self._scan_force = bool(force)
        self._scan_incremental = bool(incremental)
        self._scan_params = params
        # ★ 过滤掉的"过期统计项"必须**当面说清**（它们是用户上一步留下的，否则他会以为扫描坏了）
        _skip = list((p._scan_queue[0] or {}).get('skipped') or []) if p._scan_queue else []
        p._scan_skipped = _skip
        _note = (f'　（已跳过不属于当前条件的统计项：{"、".join(_skip)} —— 它们来自上一份条件；'
                 '想继续看请切回那份条件，或用「＋ 从其他方案添加…」从那个方案借过来）'
                 if _skip else '')
        return self._run_queued_plan(busy_text + _note)

    def on_run_clicked(self) -> None:
        self._start_worker(busy_text='扫描中…（读盘 → 粗筛 → 逐标的求值）')

    # ==========================================
    # ★v1.46：历史页「重跑」—— 等名单解析完再自动开扫
    # ==========================================
    def request_run(self) -> None:
        """外部（运行历史页「▶ 重跑」）请求"复用参数后立刻扫一次"。

        ⚠ 旧版 `apply_config()` + `start_scan()` 连招对「指数成分」范围必然失败 ——
        成分股是**异步**解析的，`p._symbols` 此刻还是空 ⇒ `_start_worker` 早退
        （回执"范围是空的"），用户点了重跑什么都没发生。
        """
        p = self.page
        self._pending_run = True
        p.lbl_receipt.setText('已复用参数 —— 正在解析统计范围，就绪后自动开始扫描…')
        self._maybe_run_pending()

    def _maybe_run_pending(self) -> None:
        if not self._pending_run:
            return
        p = self.page
        if not p._symbols:
            return                              # 成分股还在异步解析
        self._pending_run = False
        self.on_run_clicked()

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
        # ★1.76 期 4：多方案队列 —— 结果存进**它那个方案**的槽位；本页方案同时写老字段
        #   `p._outcome`（所有老调用与断言零变化）。
        _step = self._queue_step(p)
        p._outcomes = dict(getattr(p, '_outcomes', None) or {})
        p._outcomes[str(_step.get('digest') or 'page')] = outcome
        if str(_step.get('digest') or 'page') == 'page':
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
        # ★ 幸存者偏差提示（v6.42，与 M2 同款）：区间起点早于成分快照 ⇒ 名单不是那时的
        meta = getattr(p, '_cons_meta', None)
        if (meta and p.cb_scope.currentIndex() == 1 and meta.get('snapshot_date')
                and outcome.result.dates is not None and len(outcome.result.dates)
                and pd.Timestamp(outcome.result.dates[0])
                < pd.Timestamp(meta['snapshot_date'])):
            text += (f' · ⚠ 成分是 {meta["snapshot_date"]} 的当前名单，'
                     f'区间更早 ⇒ 幸存者偏差（非时点名单）')
        # ★1.77 续：**缓存淘汰必须出声**（纪律："不许悄悄淘汰正在用的那套"）——
        #   多方案同屏超过上限（默认 4 套）时，旧方案的结果会被挤掉；用户切回去会"莫名其妙要重扫"。
        _ev_now = int(getattr(p._store, 'evicted', 0))
        if _ev_now > int(getattr(p, '_evicted_seen', _ev_now)):
            text += (f' · ⚠ 会话缓存已满：淘汰了 {_ev_now - int(p._evicted_seen)} 套旧方案结果'
                     '（再切回那些方案需要重扫）—— 想同时留更多方案请看设置里的缓存上限')
            p._evicted_seen = _ev_now
        p.lbl_receipt.setText(text)
        p.lbl_receipt.setToolTip(
            ('\n'.join(filter(None, [outcome.note or '',
                                     *('⚠ ' + w for w in warns)]))))
        self._refresh_chips()
        self.refresh()
        self._auto_archive(outcome)         # ★P4：非缓存的新扫描落一份 kind=M3 快照
        # ★1.76 期 4：队列里还有借来的方案 ⇒ **接着补扫**（回执明说"第几个/共几个"，
        #   **不许静默等待** —— 用户点一次扫描，三个方案都要算完，且看得见进度）
        if self._has_more_plans(p):
            p._scan_index = int(getattr(p, '_scan_index', 0)) + 1
            if self._run_queued_plan():
                _n = len(getattr(p, '_scan_queue', None) or [])
                p.lbl_receipt.setText(
                    f'{text} · 正在补第 {int(p._scan_index) + 1}/{_n} 个方案的扫描'
                    f'（{self._queue_step(p).get("label")}）…')

    def _auto_archive(self, outcome) -> None:
        """扫描完成落一份 `kind=M3` 不可变快照（§7-B12 P4 · v1.46 重做）。

        受「每次回测 / 扫描自动存档」开关控制；缓存命中不重落；成功后补一行**可见回执**
        （旧版纯静默）；存档失败绝不拖挂扫描回执。
        """
        p = self.page
        if outcome is None or outcome.cached:
            return
        if not bool((preferences.get('backtest_archive') or {}).get('auto', True)):
            return
        try:
            dates = outcome.result.dates
            asof = dates[-1] if dates is not None and len(dates) else outcome.asof
            counts = outcome.counts_on(asof) if asof is not None else {}
            label, code = scope_snapshot(p, counts.get('total', 0))   # ★带指数名（旧版会丢）
            range_label = (str(pd.Timestamp(dates[0]).date())
                           if dates is not None and len(dates) else '')
            rid = BacktestArchive().save(build_scan_record(
                p.current_config(), kind=KIND_M3, scope_label=label, scope_code=code,
                counts=counts, asof=asof, range_label=range_label, source=SOURCE_AUTO))
            if rid:
                p._last_archive_id = rid
                mark_archived(p, label)
        except Exception as e:  # noqa: BLE001 —— 存档失败绝不拖挂扫描回执
            logger.warning('广度统计：自动存档失败（忽略）: %s', e)

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
        """用缓存矩阵重画当前区间（**零成本**：不进线程、不读盘，D3）。

        ★1.73 / §7-B16 期 1：**逐统计项**取广度帧（每项一行）；区间切片对每一项各做一次
        （切片是纯内存操作，多做几次仍是"零成本"级）。
        """
        p = self.page
        self._sync_gate_bar(p)          # ★1.74 期 2：闸条跟"上屏项 + 当前区间"走（纯函数，零成本）
        self._refresh_views(p)          # ★1.75 期 3：当前视图跟着数据走（事件/卡视图才做重活）
        outcome = p._outcome
        if outcome is None:
            return
        items = self.active_items(p)
        if not items:
            p._result.set_empty('还没有统计项 —— 打开「📋 统计项」加一个判定变量，'
                                '或直接用公式的最后一条（默认）。')
            return
        frames: dict[str, pd.DataFrame] = {}
        for it in items:
            full = self.item_frame(p, it, sliced=False)   # ★1.76 期 4：**按项取它自己那个方案**
            if full is None or full.empty:
                continue
            # ⚠ **不许写 `self.item_frame(...) or full`** —— DataFrame 的布尔求值会抛
            #   "truth value of a DataFrame is ambiguous"（第三次踩：这个坑在 `refresh` /
            #   `_render` / `hit_day_stats` 各有一条注释，仍然又写了 `or`）。
            _sliced = self.item_frame(p, it)
            # ★1.76 修：帧表按**项身份**（`uid`）索引 —— 四个方案同名 `COND` 时按变量名会互相覆盖
            frames[self.item_uid(p, it)] = _sliced if _sliced is not None else full
        if not frames:
            # ★v1.41 / §11.5-80：文案说"先补数据再扫"，按钮就该是**补数据** ——
            #   旧版这里给的是「重新扫描」，与文案所指的动作根本不是一件事
            #   （数据没变，重扫一遍还是没产出），按钮名与实际行为必须一致。
            _miss = '、'.join(str(it.get('label') or '') for it in items)
            p._result.set_empty(
                f'这次扫描没有产出广度数据（涉及：{_miss}）—— 范围内标的本地没有日线文件是首要原因'
                f'（看上方回执的 ⚠ 提示），先「{SYNC_ACTION_LABEL}」把数据补上再扫；'
                '若只是**新加的统计项没算过**，点「▶ 开始扫描」把它一起算进来即可。',
                SYNC_ACTION_LABEL, lambda: p._readiness.update_latest())
            return
        # 交给图的 items 带上 `uid`（图按它取帧 —— 同名不同源不许互相覆盖）
        self._render([{**dict(it), 'uid': self.item_uid(p, it)} for it in items], frames)
        if p._display_pane.chk_overlay.isChecked():
            self._ensure_index()

    def _render(self, items, frames) -> None:
        p = self.page
        pane = p._display_pane
        overlay_wanted = pane.chk_overlay.isChecked()
        overlay_code = str(pane.cb_overlay_code.currentData() or '')
        index_df = p._index_df if (overlay_wanted and p._index_code == overlay_code) else None
        index_label = str(pane.cb_overlay_code.currentText()).split(' ')[0]
        painted = p.chart.render(
            items, frames, index_df,
            bar_mode=(BAR_MODE_RATIO if pane.chk_ratio.isChecked() else BAR_MODE_HITS),
            # ★1.74 期 2：均线窗口由用户定（0 = 只画柱）；「叠加均线」关掉 ⇒ 一律不画线
            #   （两个控件不打架：关掉时窗口输入框禁用，见 `BreadthDisplayPane`）
            ma_window=(pane.spin_ma.value() if pane.chk_smooth.isChecked() else 0),
            chart_type=str(pane.cb_chart.currentData() or DEFAULT_CHART_TYPE),
            index_style=str(pane.cb_index_style.currentData() or DEFAULT_INDEX_STYLE),
            with_index=overlay_wanted,
            focus=self.focus_key(p),
            index_label=index_label,
            # ★1.73 收尾：副图高度**可调**（用户拍板"必须有调整入口"）—— 改了立即重画、不重扫
            index_height=p._display_pane.spin_index_h.value(),
            # ★1.75 期 3：命中色带（副图叠加选项；开关在「📈 展示」卡）
            show_bands=p._display_pane.chk_bands.isChecked())
        if painted:
            p._result._show_chart(p, True)      # ★1.73：图 + 行区滚动容器**成对显隐**
            p.empty_box.hide()
            # 行区最小高 = 行数×行高下限 + 副图高 ⇒ 行多了由**行区自己滚动**（硬规则②），
            # 副图保持固定高度不被压扁、整页也不跟着滚。
            try:
                p.chart.setMinimumHeight(p.chart.min_content_height())
            except Exception:                    # noqa: BLE001 —— 布局高度是装饰性约束，绝不阻断渲染
                pass
            # —— L0 头部与页脚的三处状态行（口径 / 缓存标记 / 近 5 日）——
            #   ⚠ 它们原先挂在**旧 `_render` 的尾部**；接线时我把旧函数换掉、漏抄了这四行，
            #     结果它们被"甩"到 `on_item_focus` 末尾（既写错对象、又永不执行）。
            #     这正是那几条断言红的原因：**状态行没人写** ⇒ 现在归位到唯一的渲染出口。
            p.btn_incr.setEnabled(True)
            p.lbl_cached.setText('缓存命中（未重算）' if p._outcome.cached else '')
            # ⚠ 不能写 `frames.get(k) or next(...)` —— DataFrame 的布尔求值会抛
            #   "truth value of a DataFrame is ambiguous"（与 `relation_stats.hit_day_stats`
            #   里那条注释同一个坑；我在这里又踩了一次）。
            # ★1.75 修：**第一项可能还没算过**（扫描后新加）⇒ 这时改用**实际有的那一项**，
            #   并且**把它的名字写进读数**（否则底部会静默显示另一项的数字）。
            _primary_key = str((items[0] or {}).get('uid')
                               or (items[0] or {}).get('key') or '')
            _primary = frames.get(_primary_key)
            if _primary is None:
                _primary_key = next(iter(frames))
                _primary = frames[_primary_key]
            # ⚠ 匹配要用 **uid**（`_primary_key` 现在是 uid）—— 漏改这里的话，底部会写 `page|SLOW`
            #   这种内部键（实测被冒烟逮住）。
            _primary_label = next((str(it.get('label') or it.get('key')) for it in items
                                   if str(it.get('uid') or it.get('key')) == _primary_key),
                                  _primary_key)
            self._render_caption(_primary)
            self._render_mini(_primary, _primary_label)
        else:
            p._result._show_chart(p, False)
            p.empty_box.show()

    # ==========================================
    # 收尾（★1.73 / §7-B16 期 1）：引导条 + 常驻说明
    #   【为什么必须有】用户 2026-10-12 原话："这种功能没有引导根本不知道这个阈值到底是啥"
    #   ⇒ ① 首次进入弹一条**可关闭**的引导；② 关上之后**常驻 ⓘ 入口**还能再看
    #     （说明不许只存在首次弹窗里）；③ 关闭状态进偏好，不反复打扰。
    # ==========================================
    def on_hint_dismissed(self) -> None:
        """收起首次引导条（记住已读 ⇒ 下次不再弹；随时可点 ⓘ 再看）。

        ⚠ 这里是 `_hint_done` 的**唯一写入点**（★1.73 修：旧版按可见性反推 ⇒ 页签没切到就被
          误记成"已读"）。写标志 → 再保存，顺序不能反。
        """
        p = self.page
        p._hint_done = True
        bar = getattr(p, 'hint_bar', None)
        if bar is not None:
            bar.hide()
        p.save_breadth_ui()
        p.lbl_receipt.setText('引导已收起（随时点标题行的 ⓘ 再看；阈值在「📈 展示」卡里就地可调）')

    def show_gates_help(self) -> None:
        """弹「三道闸是什么」说明（内容 = 设计稿 E 页浓缩版，**同一份常量**）。"""
        from ui.widgets.breadth_layout import GATES_HELP_TEXT

        box = QMessageBox(self.page)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle('三道闸：什么样的条件配什么样的图')
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(GATES_HELP_TEXT)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()


    # ==========================================
    # 统计项（★1.73 / §7-B16 期 1）—— 真源 = `p._items`，**本模块是唯一写入点**（§9-D）
    # ==========================================
    @staticmethod
    def formula_signals(p) -> list[str]:
        """这段公式里可当**判定变量**的名字（`core.cross_section.signal_names`，与引擎同源）。"""
        from core.cross_section import signal_names as _names
        try:
            return list(_names(p._formula_pane.txt_formula.toPlainText()))
        except Exception:                     # noqa: BLE001 —— 公式还没写完 ⇒ 给空（面板如实说）
            return []

    def active_items(self, p=None) -> list[dict]:
        """上屏项（`visible != False`）；**空则退化成"公式最后一条"单项**（= 老行为）。

        ⚠ 退化是**有意的**：老用户的偏好里没有 `items` 字段，升级后打开本页必须仍是他熟悉的
          单条曲线（零迁移成本），而不是空白图。
        """
        p = p or self.page
        items = [it for it in (getattr(p, '_items', None) or [])
                 if bool(it.get('visible', True))]
        if items:
            return items
        signals = self.formula_signals(p)
        if not signals:
            return []
        return [{'key': signals[-1], 'label': signals[-1], 'color': ROW_COLORS[0],
                 'visible': True, 'focus': False}]

    def focus_key(self, p=None) -> str:
        """当前焦点项（空 = 全部等分）。焦点行会被置顶并加高（控件负责）。"""
        p = p or self.page
        for it in (getattr(p, '_items', None) or []):
            if it.get('focus') and bool(it.get('visible', True)):
                return str(it.get('key') or '')
        return ''

    def sync_items_panel(self, p=None) -> None:
        """回灌面板（可选变量 + 列表 + **三道闸徽标**）—— 面板只渲染，真源永远在 `p._items`。"""
        p = p or self.page
        panel = p._items_pane.panel
        panel.set_available(self.formula_signals(p))
        verdicts = self.gate_verdicts(p)
        # ★1.76 期 4：行内"来源"**从这里派生**（不给它单独存一份 —— 同一事实只存一处 §11.5-112）
        panel.set_items([{**dict(it), 'verdict': verdicts.get(self.item_uid(p, it)),
                          'source_label': (f'来自方案：{self.plan_for_item(p, it).get("name")}'
                                           if self.plan_for_item(p, it) else '')}
                         for it in (p._items or [])])
        self._sync_gate_bar(p, verdicts)

    # ==========================================
    # ★1.74 / §7-B16 期 2：三道闸（判据在 `core.relation_stats`，本件只负责"摆给人看"）
    # ==========================================
    def gate_verdicts(self, p=None) -> dict:
        """每个**上屏统计项**的三道闸结论：`{key: {mode,event_ok,ratio_pct,reason,suggest,…}}`。

        · 判据一律调 `gate_decision`（纯函数，唯一真源）—— 本件**不自己判边界**；
        · 阈值经 `thresholds_from_prefs()`（界面取阈值的唯一入口 ⇒ 与设置页/展示卡同源）；
        · 还没扫描 / 该项没帧 ⇒ `unknown`（**如实说"未扫描"**，不猜档位）。
        """
        p = p or self.page
        th = thresholds_from_prefs()
        out: dict[str, dict] = {}
        for it in self.active_items(p):
            key = str(it.get('key') or '')
            frame = self.item_frame(p, it, sliced=False)      # ★1.76 期 4：按项取它自己那个方案
            if frame is None or getattr(frame, 'empty', True) or 'hits' not in getattr(
                    frame, 'columns', []):
                dec = asdict(gate_decision(None, th['sparse_max'], th['freq_min']))
            else:
                st = hit_day_stats(frame['hits'])
                dec = asdict(gate_decision(st['ratio_pct'], th['sparse_max'], th['freq_min']))
                dec.update(hit_days=st['hit_days'], days=st['days'])
            out[self.item_uid(p, it)] = dec      # ★1.76 修：按**项身份**索引（同名不同源不许覆盖）
        return out

    def _sync_gate_bar(self, p, verdicts: dict = None) -> None:
        """闸条：**只在有项被拦下时**出现（原因/替代/动作三要素由 `GateHintBar` 保证）。"""
        bar = getattr(p, 'gate_bar', None)
        if bar is None:
            return
        verdicts = self.gate_verdicts(p) if verdicts is None else verdicts
        labels = {self.item_uid(p, it): str(it.get('label') or it.get('key') or '')
                  for it in self.active_items(p)}       # ★1.76 修：按项身份（同名不同源不许覆盖）
        blocked = [(labels.get(k, k), v) for k, v in verdicts.items()
                   if v and not v.get('event_ok', False)
                   and str(v.get('mode')) != MODE_UNKNOWN]
        # ★1.81：**同一批被拦项只提示一次** —— 用户收起后不反复冒；被拦项变了才再出现
        if not blocked:
            # 问题消失（全都不被拦了）⇒ **忘掉**收起状态：将来再被拦下要重新提示，
            # 否则"永久静音"会把新问题也一起压掉（诚实优先）
            p._gate_dismissed_sig = ''
        sig = '|'.join(sorted(lab for lab, _v in blocked))
        p._gate_blocked_sig = sig
        if blocked and sig and sig == str(getattr(p, '_gate_dismissed_sig', '')):
            bar.set_blocked([])
            return
        bar.set_blocked(blocked)

    def on_gate_dismissed(self) -> None:
        """收起闸条（★1.81）—— 记下"这一批被拦项"，并写进 `breadth_ui`。

        ⚠ **不丢信息**：常驻 ⓘ 有同一份三道闸文案；每行统计项的徽标仍标"不适用"。
        """
        p = self.page
        p._gate_dismissed_sig = str(getattr(p, '_gate_blocked_sig', ''))
        bar = getattr(p, 'gate_bar', None)
        if bar is not None:
            bar.set_blocked([])
        try:
            p._save_ui()
        except Exception:                   # noqa: BLE001 —— 记住与否都不该拖垮交互
            pass
        p.lbl_receipt.setText('已收起这条提醒 —— 右上 ⓘ 里有同一份「三道闸」说明；'
                              '被拦下的项有变化时它会再出现。')

    def on_thresholds_changed(self, values: dict) -> None:
        """展示卡**就地**改阈值 ⇒ 写进同一份偏好（经设置注册表）⇒ 重算徽标与闸条。

        ⚠ 只重算判据（纯函数）+ 重画，**绝不重扫** —— 否则用户"试着调阈值"要等几十秒。
        """
        p = self.page
        fixed = clamp_thresholds(values.get('sparse_max'), values.get('freq_min'),
                                 values.get('indep_gap'))
        for suffix, val in (('sparse_max', fixed['sparse_max']),
                            ('freq_min', fixed['freq_min']),
                            ('indep_gap', fixed['indep_gap'])):
            item = settings_registry.find(f'{PREF_KEY}.{suffix}')
            if item is not None:
                settings_registry.set_value(item, val)
        p._display_pane.gate_row.set_values(fixed, silent=True)   # 显示**实际生效值**
        notes = '；'.join(fixed.get('notes') or [])
        p.lbl_receipt.setText(
            '三道闸阈值已更新（与「设置 → 回测与扫描默认」是同一份，两边同步）'
            + (f' · 修正：{notes}' if notes else '')
            + ' —— 徽标与闸条已按新阈值重算，**没有重扫**。')
        self.sync_items_panel(p)
        p.save_breadth_ui()

    def on_gate_fix_clicked(self) -> None:
        """闸条上的「调整阈值」⇒ 打开「📈 展示」卡（阈值就在那）—— 真入口，不是假按钮。"""
        p = self.page
        p.lbl_receipt.setText('在「📈 展示」卡里改「三道闸阈值」—— 与设置页同一份，改完立即生效。')
        p.open_pane('display')

    def _after_items_changed(self, msg: str) -> None:
        """统计项改动后：回灌面板 → 重画（**不重扫**）→ 回执说清"哪些需要重扫才生效"。"""
        p = self.page
        self.sync_items_panel(p)
        self._refresh_chips()        # ⚠ 统计项胶囊是在 `_refresh_chips` 里写的（不是 sync_chip_states）
        # ★1.76 期 4：**"算过没有"必须按方案判断** —— 借来的项要去**它那个方案**的结果里看
        #   变量名在不在；拿本页结果去判会**谎报"已算过"**（明明没画出来，回执却说"已按缓存重画"）。
        #   同族纪律：§11.5-134（数字必须能追到它属于谁）。
        missing = sorted({str(it.get('key') or '') for it in self.active_items(p)
                          if not self._item_computed(p, it)})
        if missing:
            p.lbl_receipt.setText(
                f'{msg} —— 但「{"、".join(missing)}」还没算过：点「▶ 开始扫描」把它一起算进来'
                '（同一段公式的多个判定变量**一次扫描全部拿到**，不用为它单跑一遍）')
        else:
            p.lbl_receipt.setText(f'{msg}（已按缓存重画，**没有重扫**）')
        self.refresh()
        p.save_breadth_ui()

    def on_item_add(self, key: str) -> None:
        p = self.page
        # ⚠ **先固化"默认那一条"**：`p._items` 为空时页面上显示的是"公式最后一条"（隐式默认），
        #   若直接把新项写进空列表，用户会看到**原来那一行凭空消失**（用户实测口径：这是 bug）。
        items = [dict(it) for it in ((p._items or []) or self.active_items(p))]
        if any(str(it.get('key')) == str(key) for it in items):
            return
        items.append({'key': str(key), 'label': str(key),
                      'color': ROW_COLORS[len(items) % len(ROW_COLORS)],
                      'visible': True, 'focus': False})
        p._items = items
        self._after_items_changed(f'已添加统计项「{key}」')

    def on_item_remove(self, key: str) -> None:
        p = self.page
        p._items = [dict(it) for it in (p._items or [])
                    if str(it.get('key')) != str(key)]
        self._after_items_changed(f'已移除统计项「{key}」')

    def on_item_toggle_visible(self, key: str) -> None:
        p = self.page
        items = [dict(it) for it in (p._items or [])]
        for it in items:
            if str(it.get('key')) == str(key):
                it['visible'] = not bool(it.get('visible', True))
        p._items = items
        self._after_items_changed(f'已{"隐藏" if not self._is_visible(p, key) else "显示"}'
                                  f'统计项「{key}」')

    @staticmethod
    def _is_visible(p, key: str) -> bool:
        for it in (p._items or []):
            if str(it.get('key')) == str(key):
                return bool(it.get('visible', True))
        return False

    def on_item_focus(self, key: str) -> None:
        """设/取消焦点（再点一次 = 取消，与抽屉"再点收起"同款交互）。"""
        p = self.page
        items = [dict(it) for it in (p._items or [])]
        already = any(str(it.get('key')) == str(key) and it.get('focus') for it in items)
        for it in items:
            it['focus'] = (str(it.get('key')) == str(key)) and not already
        p._items = items
        self._after_items_changed(f'已{"取消焦点" if already else "设为焦点"}「{key}」')

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

    def _render_mini(self, frame: pd.DataFrame, label: str = '') -> None:
        """近 5 日迷你读数（原型 foot）：`MM-DD · N 只 / x%`。

        ⚠ **必须写明是哪一项**（`label`）：家数/占比是**逐项不同**的，而这里只显示一项的读数 ——
          不写名字的话，"第一项还没算过"时会静默把**另一项**的数字摆出来
          （与 2026-10-16 那个"新加项照抄主变量"是同一族毛病：**数字必须能追到它属于谁**）。
        """
        p = self.page
        tail = frame.tail(5).iloc[::-1]
        cells = []
        for day, row in tail.iterrows():
            valid = int(row.get('valid', 0))
            hits = int(row.get('hits', 0))
            ratio = (hits / valid * 100) if valid > 0 else 0.0
            cells.append(f'{pd.Timestamp(day).strftime("%m-%d")} · {hits} 只 / {ratio:.1f}%')
        name = f'（{label}）' if str(label or '').strip() else ''
        p.lbl_mini.setText((f'近5日{name}：' + ' ｜ '.join(cells)) if cells else '')
        if cells:
            p.lbl_mini.setToolTip(f'上面这些家数/占比属于统计项「{label}」'
                                  '（每项各算各的；要看别的项请把鼠标停到对应那一行上）')

    # ==========================================
    # 指数副图数据链（读湖 → 缺数据 或 落后于主图 ⇒ 自动补拉到最新；失败不连累主图）
    # ==========================================
    def _axis_latest(self):
        """主图广度轴的最后一个交易日（副图要对齐到这天）；无结果 ⇒ None（不判落后）。"""
        p = self.page
        result = p._outcome.result if p._outcome is not None else None
        dates = getattr(result, 'dates', None) if result is not None else None
        if dates is None or len(dates) == 0:
            return None
        return pd.Timestamp(dates[-1]).normalize()

    @staticmethod
    def _index_is_stale(df, want) -> bool:
        """指数日线末日是否**落后于目标日 want**（有数据但停在更早的日子）。

        `want is None`（还没扫描出广度轴）⇒ 不判落后（维持旧行为，绝不误发车）。
        """
        if want is None or df is None or df.empty or 'date' not in df.columns:
            return False
        try:
            last = pd.Timestamp(pd.to_datetime(df['date']).max()).normalize()
        except Exception:                                # noqa: BLE001 —— 解析不了当不落后，保守不动
            return False
        return last < want

    def _ensure_index(self) -> None:
        p = self.page
        code = str(p._display_pane.cb_overlay_code.currentData() or DEFAULT_INDEX_CODE)
        want = self._axis_latest()                       # 副图要对齐到的目标日（主图最右端）
        have = (p._index_code == code and p._index_df is not None
                and not p._index_df.empty)
        if have:
            # 已缓存该指数：不落后就直接用（旧行为，端到端测试靠这条不碰真实湖）
            if not self._index_is_stale(p._index_df, want):
                return
        else:
            df = p._lake.load_data(ZONE_INDEX, code)
            if df is not None and not df.empty:
                p._index_df = df
                p._index_code = code
                have = True
                if not self._index_is_stale(df, want):
                    self.refresh()                       # 读到且够新 ⇒ 带上副图重画
                    return
        # 走到这里：缺数据 或 落后于主图 ⇒ 后台补拉到最新（失败不连累主图）
        if p._index_fetching == code:
            return                                        # 已经在拉了，别重复发车
        if self._index_synced_to == (code, want):
            return                                        # 这一目标日已补拉过仍不够新 ⇒ 不再空转
        name = str(p._display_pane.cb_overlay_code.currentText()).split(' ')[0]
        if self._index_gate.blocked_by(code, ZONE_INDEX):
            # ★v1.43 / §7-B11：该指数已在后台队列里 ⇒ 不重复抓（同一个文件不能两个写者）；
            #   副图缺数据不影响主图广度，所以这里只出声、不阻断。
            p.lbl_receipt.setText(f'副图 {name} 日线待更新 —— 该指数正在后台下载队列里，'
                                  '等它跑完再重画（不影响主图广度）')
            return
        # have=True ⇒ 有数据但落后；have=False ⇒ 完全缺失（文案分别说清，不静默）
        p.lbl_receipt.setText(
            f'副图 {name} 日线{"落后于主图，后台更新中" if have else "缺失，后台拉取中"}'
            '…（失败不影响主图广度）')
        p._index_fetching = code
        self._index_synced_to = (code, want)
        job = p._index_guard.next()
        p._index_worker = SingleSyncWorker(code, zone=ZONE_INDEX, parent=p)
        p._index_worker.finished.connect(
            lambda _result, token=job, c=code: self._on_index_fetched(c, token))
        self._index_gate.hold(code, ZONE_INDEX)
        p._index_worker.start()

    def _on_index_fetched(self, code: str, token: int) -> None:
        """拉取回包：过守卫 + 重读湖。拿到了就重画；拿不到就出声（绝不静默）。"""
        p = self.page
        self._index_gate.release()                # 先释放占位，再判守卫（防泄漏）
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

    # ==========================================
    # ★P3 配置打包 / 还原（与 M2 同形，供共享的筛选方案库读写）
    # ==========================================
    def current_config(self) -> dict:
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
        """把一份方案快照还原进 M3（只动筛选配置，不碰展示偏好 range/chart/overlay）。"""
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
