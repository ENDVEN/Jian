# ui/views/breadth_view.py
"""📊 M3「广度统计」—— 页面本体（§7-B1/B2 主案 STEP 5）。

逐日统计"有多少只满足条件"：广度折线（家数 / 占比%）+ 指数副图同 x 轴联动，
**一个引擎，两种视图**：M2 = 某日纵向取列（全市场筛选）/ M3 = 跨标的按日求和（本页）。

【约定（1.22 / 1.23 / 1.26 / 1.28 同款）】**状态全在页面，行为搬模块 + 同名薄壳**：
  · 状态字段都在这里（`_thresholds` / `_symbols` / `_names` / `_outcome` / `_guard` /
    `_worker` / `_store` / `_range_key` / `_index_df` …）；
  · 版式装配 → `ui/widgets/breadth_layout.py`，运行流程 → `breadth_flow.py`，
    状态空态 → `breadth_result.py`，双窗格图表 → `breadth_chart.py`；
  · widgets 模块只读写 `p.X`，**不自己存副本**；
  · 成功判据 = 同一套断言零改动（迁移护栏会钉住本页的公共面）。
"""
from __future__ import annotations

from PyQt6.QtWidgets import QVBoxLayout, QWidget

from core.cross_section import ScanThresholds
from core.preferences import preferences
from data.market_db import DataLakeManager
from data.scan_store import get_scan_store
from ui.workers import JobGuard
from ui.widgets.breadth_flow import BREADTH_UI_KEY, BreadthFlow
from ui.widgets.breadth_layout import (DRAWER_MAX_WIDTH, DRAWER_MIN_WIDTH,
                                       BreadthLayout)
from ui.widgets.breadth_result import BreadthResult
from ui.widgets.readiness_flow import ReadinessFlow

# 出厂示例：与主案 B2/P3 用的同一句（用户一进来就有可跑的东西，而不是一个空框）
DEFAULT_FORMULA = ("DIFF := EMA(C,12) - EMA(C,26);\n"
                   "DEA  := EMA(DIFF,9);\n"
                   "COND := CROSS(DIFF, DEA) AND C > MA(C,20);")


class BreadthView(QWidget):
    """📊 广度统计（M3）。挂载在 `backtest_module.tabs` 的第 3 个页签。"""

    hub_origin = "breadth"   # v1.43：提交到后台下载队列时的发起方标识（回执只回给本页）

    def __init__(self, main_win):
        super().__init__()
        self.main_win = main_win

        # ---------------- 状态（全部在页面；widgets 模块只读写 p.X） ----------------
        self._thresholds = ScanThresholds()          # 粗筛阈值（唯一真源 = 抽屉里的控件）
        self._symbols: list = []
        self._names: dict = {}
        self._cons_meta = None                         # 成分股快照元信息（非成分范围 = None）
        self._outcome = None                         # ScanOutcome（含缓存矩阵）
        self._guard = JobGuard()                     # 竞态守卫（§9-O5）
        self._index_guard = JobGuard()               # 指数补拉自己的守卫（不与扫描互踢）
        self._worker = None                          # CrossSectionWorker
        self._cons_worker = None                     # 指数成分解析（异步）
        self._index_worker = None                    # 指数日线补拉（异步）
        self._index_fetching = ''                    # 正在补拉的指数代码（防重复发车）
        self._store = get_scan_store()               # 会话内存缓存（D3，单例；M2/M3 共用）
        self._lake = DataLakeManager()               # 只读 index_daily 分区（§9-H：读湖不联网）
        self._range_key = '1y'                       # 当前区间（切区间 = 纯切片，零成本）
        self._index_df = None                        # 副图指数日线（缓存一 只）
        self._index_code = ''                        # _index_df 属于哪只指数
        self._open_key = None                        # 当前展开的抽屉卡片
        self._last_pane = 'fn'                       # 「⚙ 配置」的落点
        self._ui_restoring = False                   # 恢复偏好期间不回写

        # ---------------- 装配 ----------------
        self._layout = BreadthLayout(self)
        self._setup_ui()
        self._result = BreadthResult(self)
        self._flow = BreadthFlow(self)
        self._readiness = ReadinessFlow(self)        # 就绪度体检 + 更新到最新/滞后（D6/§7-B10，两页共用）
        self._load_breadth_ui()
        self._result.set_empty('还没有扫描结果 —— 选好统计范围与条件，点「▶ 开始扫描」。')
        self._readiness.start_calendar_fetch()       # 后台拉一次交易日历，喂滞后提示（§7-B10 STEP 3）

    # ==========================================
    # 装配（同名薄壳：实现都在 breadth_layout）
    # ==========================================
    def _setup_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(6)
        lay.addLayout(self.build_top_bar())          # L1 操作轴（1 行）
        lay.addLayout(self.build_summary_bar())      # L2 摘要条（1 行）
        lay.addWidget(self.build_result_area(), 1)   # L0 结果区（吃满）
        self.build_overlays()                        # L3 抽屉（覆盖层，**必须最后建**）

    def build_top_bar(self):
        return self._layout.build_top_bar()

    def build_summary_bar(self):
        return self._layout.build_summary_bar()

    def build_result_area(self):
        return self._layout.build_result_area()

    def build_overlays(self):
        self._layout.build_overlays()
        self._drawer.sig_closed.connect(self.close_pane)
        self._scrim.clicked.connect(self.close_pane)
        self._drawer.sig_pane_changed.connect(self._on_pane_changed)

    # ==========================================
    # 抽屉（覆盖层；几何必须自己算，§11.5-26）
    # ==========================================
    def open_pane(self, key=None):
        """打开某张卡片；再点同一个 = 关闭（backtest 页同款交互）。"""
        if key is not None and self._open_key == key:
            key = None
        self._open_key = key
        if key is not None:
            self._last_pane = key
            self._drawer.show_pane(key)
            self._drawer.scroll_area.verticalScrollBar().setValue(0)
        self._layout_overlay()
        self._scrim.setVisible(key is not None)
        self._drawer.setVisible(key is not None)
        if key is not None:
            self._scrim.raise_()
            self._drawer.raise_()

    def close_pane(self):
        self.open_pane(None)

    def _on_pane_changed(self, key: str):
        self._last_pane = str(key)

    def _layout_overlay(self):
        rect = self.rect()
        width = min(DRAWER_MAX_WIDTH, max(DRAWER_MIN_WIDTH, int(rect.width() * 0.42)))
        self._drawer.setGeometry(rect.width() - width, 0, width, rect.height())
        self._scrim.setGeometry(0, 0, rect.width(), rect.height())

    def resizeEvent(self, event):  # noqa: N802 —— Qt 命名
        super().resizeEvent(event)
        self._layout_overlay()

    # ==========================================
    # 行为薄壳（实现都在 breadth_flow；页面留同名入口供测试与互送）
    # ==========================================
    def start_scan(self):
        self._flow.on_run_clicked()

    def incremental_scan(self):
        self._flow.on_incremental_clicked()

    def full_recompute(self):
        self._flow.on_full_clicked()

    def cancel_scan(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()

    def resolve_scope(self):
        self._flow.resolve_scope()

    def refresh(self):
        """用缓存矩阵重画当前区间（**零成本**，D3）。"""
        self._flow.refresh()

    def set_range(self, key: str):
        self._flow.set_range(key)

    def reset_thresholds(self):
        self._flow.reset_thresholds()

    def current_breadth(self):
        """当前区间的广度帧（冒烟 / 上层用；口径与 scan 同源）。"""
        if self._outcome is None:
            return None
        return self._outcome.breadth_frame()

    # ==========================================
    # 偏好（记住上次；坏数据逐字段回落，§9-D）
    # ==========================================
    def _load_breadth_ui(self):
        raw = preferences.get(BREADTH_UI_KEY)
        data = dict(raw) if isinstance(raw, dict) else {}
        self._ui_restoring = True
        try:
            scope = data.get('scope', 0)
            try:
                index = int(scope or 0)
            except (TypeError, ValueError):
                index = 0
            self.cb_scope.setCurrentIndex(index if 0 <= index < self.cb_scope.count() else 0)
            code = str(data.get('index_code') or '')
            if code:
                idx = self.cb_index.findData(code)
                if idx >= 0:
                    self.cb_index.setCurrentIndex(idx)
            text = str(data.get('formula') or '').strip()
            self._formula_pane.txt_formula.setPlainText(text or DEFAULT_FORMULA)
            self._formula_pane.txt_params.setText(str(data.get('params') or ''))
            thresholds = ScanThresholds.from_dict(data.get('thresholds'))
            self._thresholds = thresholds
            self._filter_pane.from_thresholds(thresholds)
            from ui.widgets.breadth_layout import RANGE_PRESETS
            range_key = str(data.get('range') or '1y')
            range_keys = [k for k, _ in RANGE_PRESETS]
            if range_key not in range_keys:
                range_key = '1y'
            self._range_key = range_key
            self.cb_range.setCurrentIndex(range_keys.index(range_key))
            display = self._display_pane
            from ui.widgets.breadth_chart import (CHART_TYPES, DEFAULT_CHART_TYPE,
                                                  DEFAULT_INDEX_STYLE, INDEX_STYLES)
            chart_key = str(data.get('chart') or DEFAULT_CHART_TYPE)
            chart_keys = [k for k, _ in CHART_TYPES]
            display.cb_chart.setCurrentIndex(
                chart_keys.index(chart_key) if chart_key in chart_keys else 0)
            istyle_key = str(data.get('index_style') or DEFAULT_INDEX_STYLE)
            istyle_keys = [k for k, _ in INDEX_STYLES]
            display.cb_index_style.setCurrentIndex(
                istyle_keys.index(istyle_key) if istyle_key in istyle_keys else 0)
            display.chk_smooth.setChecked(bool(data.get('smooth', True)))
            display.chk_ratio.setChecked(bool(data.get('ratio', False)))
            display.chk_overlay.setChecked(bool(data.get('overlay', True)))
            overlay_code = str(data.get('overlay_code') or '')
            if overlay_code:
                idx = display.cb_overlay_code.findData(overlay_code)
                if idx >= 0:
                    display.cb_overlay_code.setCurrentIndex(idx)
        finally:
            self._ui_restoring = False
        self.resolve_scope()                          # 手动触发一次范围解析

    def save_breadth_ui(self, **_):
        """「记住上次」。⚠ 只存**轻量配置**，绝不存扫描结果（结果只进会话缓存，D3）。"""
        if getattr(self, '_ui_restoring', False):
            return
        display = self._display_pane
        preferences.set(BREADTH_UI_KEY, {
            'scope': self.cb_scope.currentIndex(),
            'index_code': str(self.cb_index.currentData() or ''),
            'formula': self._formula_pane.txt_formula.toPlainText(),
            'params': self._formula_pane.txt_params.text(),
            'thresholds': self._filter_pane.to_thresholds().to_dict(),
            'range': self._range_key,
            'chart': str(self._display_pane.cb_chart.currentData() or 'bars'),
            'index_style': str(self._display_pane.cb_index_style.currentData() or 'line'),
            'smooth': display.chk_smooth.isChecked(),
            'ratio': display.chk_ratio.isChecked(),
            'overlay': display.chk_overlay.isChecked(),
            'overlay_code': str(display.cb_overlay_code.currentData() or ''),
        })
