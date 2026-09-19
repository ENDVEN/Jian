# ui/views/review.py
"""🧭 复盘工作台（ReviewView）—— §9-U 版式收口 + §9-L 拆分（1.25）。

【本文件现在是什么】**状态 + 接线**：
  · 页面是全部**状态的唯一所有者**：当前复盘日期 / 月·年模态、当前视图 df、
    当前编辑行号、交易日历缓存、界面偏好 `review_ui`……
  · **行为**分居 `ui/widgets/review_*.py`，本文件只保留**同名薄壳**（一个名字都没改）——
    这是本轮拆分的成功判据：同一套断言（`smoke_chart` + `smoke_pages_overlay`）零改动。
  · 分工（§10-12：新能力一律落 `ui/widgets/*`）：
      · 版式装配（两行操作轴 / 宏观·微观竖向分栏 / 编辑卡） → `ui/widgets/review_layout.py`
      · 图表渲染（日历热力图 / 月度图表 / 持仓时长）          → `ui/widgets/review_charts.py`
      · 交易回放（K 线双锚点 / 单点降级 / 数据缺口提示）      → `ui/widgets/review_playback.py`
      · 清单与编辑（当日清单 / 详情头 / 复盘保存 / 孤儿单缝合） → `ui/widgets/review_editor.py`
      · 筛选与导航（月年切换 / 五个筛选 / 时间跳转 / 视图刷新） → `ui/widgets/review_flow.py`

【§9-U 收口（1.25）】常驻行 ≤3（标题行 + 筛选行 + 分栏主体吃满剩余高度），
  符合 §10-14「使用频率 × 视线停留时长」：低频配置不再与结果抢纵向空间。
  宏观(日历|图表) 与 微观(清单|编辑) 之间改为**可拖的竖向分栏**并**记住上次**
  （偏好键 `review_ui.v_sizes`）—— 短屏上不再被写死的 5:4 比例挤死（见 review_layout）。

【兼容性 re-export（§11.7）】
  下面从 `ui/widgets/review_charts.py` 再导出的常量，是"拆分前从这里 import 的既有用法"的
  兼容层，测试与外部模块的 import 语句零改动。
"""
from datetime import datetime

import pandas as pd
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QWidget

from core.preferences import preferences
from data.market_db import DataLakeManager
from ui.widgets.chart_style import apply_pokorny_style
from ui.widgets.review_charts import ReviewCharts
from ui.widgets.review_editor import ReviewEditor
from ui.widgets.review_flow import ReviewFlow
from ui.widgets.review_layout import ReviewLayout
from ui.widgets.review_playback import (MAX_ANCHOR_GAP_DAYS,  # noqa: F401
                                        PLAYBACK_CONTEXT_DAYS, ReviewPlayback)

# 偏好键：复盘页界面状态（与 `backtest_ui` / `desk_ui` 同源做法：记住上次）
REVIEW_UI_KEY = "review_ui"
# 拖动分栏后的落盘防抖（毫秒）：拖动过程中 splitterMoved 会连发，直接落盘会一路写文件
_REVIEW_UI_SAVE_DEBOUNCE_MS = 300


class ReviewView(QWidget):
    """复盘工作台：月/年双模态 + 宏观(日历·图表) / 微观(清单·编辑) 可拖分栏。

    ⚠ 本类**只持状态 + 转发**：行为都在 `ui/widgets/review_*.py`；
      方法名 / 控件名 / 私有状态名三者都**与拆分前逐字相同**（§11.7 迁移红线）。
    """

    def __init__(self, main_win):
        super().__init__()
        self.main_win = main_win
        self.current_review_date = datetime.now()
        self.is_yearly_view = False
        self.current_view_df = pd.DataFrame()
        self.current_editing_idx = None

        # 实例化数据湖，随时准备抽取 K 线
        self.data_lake = DataLakeManager()
        # v1.3：交易日历缓存（只对"仅日期"的记录按需加载，避免无谓 IO）
        self._trading_cal: dict[str, list] = {}

        # 界面偏好（记住上次）：与 `backtest_ui` / `desk_ui` 同源；坏值一律回落默认。
        self._review_ui = self._load_review_ui()
        # 拖动分栏结束后（防抖）落偏好 —— 版式模块不落盘（它连 preferences 都不 import）
        self._review_save_timer = QTimer(self)
        self._review_save_timer.setSingleShot(True)
        self._review_save_timer.setInterval(_REVIEW_UI_SAVE_DEBOUNCE_MS)
        self._review_save_timer.timeout.connect(self._persist_review_ui)

        # 行为模块（1.25 · §9-U 收口 + §9-L 拆分）：页面持状态，行为分居各模块
        self._layout = ReviewLayout(self)
        self._charts = ReviewCharts(self)
        self._playback = ReviewPlayback(self)
        self._editor = ReviewEditor(self)
        self._flow = ReviewFlow(self)

        self._setup_ui()

    # ==========================================
    # 图表轴样式（§9-O7 唯一来源的委托壳）
    # ==========================================
    def _apply_pokorny_style(self, chart, title: str = ""):
        """委托给 ui/widgets/chart_style.py —— 全 app 图表轴样式唯一来源 (v5.12 · §9-O7)"""
        return apply_pokorny_style(chart, title)

    # ==========================================
    # 界面偏好（记住上次）
    # ==========================================
    @staticmethod
    def _load_review_ui() -> dict:
        """复盘页界面偏好（与 `backtest_ui` / `desk_ui` 同源做法）；坏值一律回落默认。"""
        raw = preferences.get(REVIEW_UI_KEY)
        data = dict(raw) if isinstance(raw, dict) else {}
        sizes = data.get("v_sizes")
        if (isinstance(sizes, (list, tuple)) and len(sizes) == 2
                and all(isinstance(v, (int, float)) and v > 0 for v in sizes)):
            return {"v_sizes": [int(sizes[0]), int(sizes[1])]}
        return {}

    def _on_review_splitter_moved(self, *args):
        """宏观/微观分栏被拖动 —— 300ms 防抖后落偏好（拖动中连发，直接写文件太重）"""
        self._review_save_timer.start()

    def _persist_review_ui(self):
        """把当前分栏高度写进偏好（**唯一落点**）"""
        splitter = getattr(self, "macro_micro_splitter", None)
        if splitter is None:
            return
        sizes = list(splitter.sizes())
        if len(sizes) == 2 and all(s > 0 for s in sizes):
            self._review_ui["v_sizes"] = sizes
            preferences.set(REVIEW_UI_KEY, dict(self._review_ui))

    # ==========================================
    # 界面装配（→ review_layout.ReviewLayout）
    # ==========================================
    def _setup_ui(self):
        return self._layout.build()

    def _build_monthly_mode(self):
        return self._layout._build_monthly_mode()

    def _build_orphan_bar(self):
        return self._layout._build_orphan_bar()

    # ==========================================
    # 筛选与导航（→ review_flow.ReviewFlow）
    # ==========================================
    def toggle_review_mode(self):
        return self._flow.toggle_review_mode()

    def refresh_review_filters(self):
        return self._flow.refresh_review_filters()

    def _populate_review_filter_options(self):
        return self._flow._populate_review_filter_options()

    def refresh_time_picker(self, is_year=False):
        return self._flow.refresh_time_picker(is_year)

    def quick_jump_time(self):
        return self._flow.quick_jump_time()

    def change_review_time(self, delta):
        return self._flow.change_review_time(delta)

    def jump_to_latest(self):
        return self._flow.jump_to_latest()

    def update_review_view(self):
        return self._flow.update_review_view()

    # ==========================================
    # 图表渲染（→ review_charts.ReviewCharts）
    # ==========================================
    def _render_calendar(self):
        return self._charts._render_calendar()

    def _render_monthly_charts(self):
        return self._charts._render_monthly_charts()

    def _trading_dates_for(self, symbol: str) -> list:
        return self._charts._trading_dates_for(symbol)

    def _render_duration_analysis(self):
        return self._charts._render_duration_analysis()

    @staticmethod
    def _nearest_bar_index(df_slice, anchor_ts) -> int:
        return ReviewPlayback._nearest_bar_index(df_slice, anchor_ts)

    def _render_trade_playback(self, record):
        return self._playback._render_trade_playback(record)

    # ==========================================
    # 清单与编辑（→ review_editor.ReviewEditor）
    # ==========================================
    def on_calendar_day_clicked(self, row, col):
        return self._editor.on_calendar_day_clicked(row, col)

    def on_review_trade_selected(self, current, previous):
        return self._editor.on_review_trade_selected(current, previous)

    def _update_detail_header(self, record, is_orphan: bool, pnl: float):
        return self._editor._update_detail_header(record, is_orphan, pnl)

    @staticmethod
    def _display_time(record) -> str:
        return ReviewEditor._display_time(record)

    @staticmethod
    def _format_leg_time(value) -> str:
        return ReviewEditor._format_leg_time(value)

    def save_review_text(self):
        return self._editor.save_review_text()

    def _save_image_paths_to_df(self):
        return self._editor._save_image_paths_to_df()

    def delete_current_trade(self):
        return self._editor.delete_current_trade()

    def silent_update_strategy(self, *args):
        return self._editor.silent_update_strategy(*args)

    @staticmethod
    def _guess_orphan_entry_price(record):
        return ReviewEditor._guess_orphan_entry_price(record)

    def guess_orphan_entry_price(self):
        return self._editor.guess_orphan_entry_price()

    def stitch_current_orphan(self):
        return self._editor.stitch_current_orphan()
