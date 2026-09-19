# ui/widgets/review_layout.py
"""复盘页的**版式装配**（1.25 自 `ui/views/review.py` 拆出 · §9-L 拆分 + §9-U 收口）。

【职责】只做"把控件摆到该去的地方"，不承载任何业务规则：
  · 第 1 行（L1 操作轴）：标题 + 月/年切换 + 时间导航（◀ ▶ 最新）；
  · 第 2 行（L1 操作轴）：账户 / 策略 / 品种主体 / 方向 / 结果 五个筛选下拉；
  · 主体 = **竖向 QSplitter**（宏观在上、微观在下）：
      - 宏观 = 日历热力图 ｜ 四页签图表（累计盈亏 / 交易回放 / 资金K线 / 持仓时长）；
      - 微观 = 当日清单 ｜ 编辑卡（详情头 / 进场逻辑 / 离场反思 / 孤儿补录 / 截图画廊）。

【★§9-U 收口（1.25）】旧版是"宏观 stretch=5 / 微观 stretch=4"两段**固定比例**平铺 ——
短屏上交易明细与回放图被挤死，用户也没法"把图表拉大、清单收矮"。现在：
  ① 宏观/微观之间是**可拖的竖向分栏**（`macro_micro_splitter`，子项不可折叠到 0）；
  ② 分栏高度**记住上次**（偏好键 `review_ui.v_sizes`，拖动后 300ms 防抖落盘）。
常驻行数仍 ≤3（标题行 + 筛选行 + 分栏主体吃满剩余高度），与 §10-14 一致。

【搬家不重建（§11.5 / 1.22 已验证）】控件对象与变量名一个都不动，只是 `addWidget`
到新的容器里 ⇒ 既有页面断言与 main_window 的访问口径零改动。
"""
from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QHeaderView, QLabel,
                             QLineEdit, QListWidget, QPushButton, QSplitter,
                             QStackedWidget, QTabWidget, QTableWidget,
                             QTextEdit, QVBoxLayout, QWidget)

import pyqtgraph as pg

from ui.widgets.adaptive_axis import attach_date_axis  # noqa: F401  (re-export 方便未来接线)
from ui.widgets.chart_style import apply_pokorny_style
from ui.widgets.custom_widgets import (COMBO_QSS_ACCENT, COMBO_QSS_EDIT,
                                       DATEEDIT_QSS_WARN, NoWheelComboBox,
                                       NoWheelDateEdit)
from ui.widgets.screenshot_gallery import ScreenshotGallery
from ui.widgets.yearly_review import YearlyReviewPanel
from config import settings

# 宏观/微观分栏的默认高度（用户拖过之后以偏好里的 v_sizes 为准）
_REVIEW_V_SIZES_DEFAULT = (560, 340)
# 拖动分栏后的落盘防抖（毫秒）：拖动过程中 splitterMoved 会连发，直接落盘会一路写文件
_REVIEW_UI_SAVE_DEBOUNCE_MS = 300


class ReviewLayout:
    """复盘页的版式装配（页面持状态，本类只摆控件）。"""

    def __init__(self, page):
        self.page = page

    # ==========================================
    # 整体骨架：两行常驻操作轴 + 主体栈（月视图 / 年视图）
    # ==========================================
    def build(self) -> None:
        p = self.page
        layout = QVBoxLayout(p)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        layout.addLayout(self._build_title_row())
        layout.addLayout(self._build_filter_row())

        p.review_stack = QStackedWidget()
        p.review_monthly_widget = self._build_monthly_mode()
        p.yearly_panel = YearlyReviewPanel(p)

        p.review_stack.addWidget(p.review_monthly_widget)
        p.review_stack.addWidget(p.yearly_panel)
        # 【§11.5-13】主体必须显式 stretch=1：否则顶部两行里的 QLabel 会把富余高度吞掉，
        # 分栏主体反而被压扁（这与行情工作台给 main_splitter 显式 stretch=1 同源）。
        layout.addWidget(p.review_stack, 1)

    # ==========================================
    # 第 1 行：标题 + 月/年切换 + 时间导航
    # ==========================================
    def _build_title_row(self) -> QHBoxLayout:
        p = self.page
        top_bar_1 = QHBoxLayout()
        title = QLabel("复盘工作台")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #212121;")
        top_bar_1.addWidget(title)
        top_bar_1.addStretch()

        p.btn_mode_toggle = QPushButton("切换年视图 📅")
        p.btn_mode_toggle.setStyleSheet("QPushButton { font-size: 14px; font-weight: bold; color: #FF9800; padding: 5px 15px; border: 1px solid #FFCC80; border-radius: 6px; background: #FFF3E0; margin-right: 15px;} QPushButton:hover { background: #FFE0B2; }")
        p.btn_mode_toggle.clicked.connect(p.toggle_review_mode)
        top_bar_1.addWidget(p.btn_mode_toggle)

        nav_layout = QHBoxLayout()
        p.btn_prev_time = QPushButton("◀")
        p.btn_next_time = QPushButton("▶")
        for btn in [p.btn_prev_time, p.btn_next_time]:
            btn.setStyleSheet("QPushButton { border: none; font-size: 18px; color: #9E9E9E;} QPushButton:hover { color: #1976D2; }")
        p.btn_prev_time.clicked.connect(lambda: p.change_review_time(-1))
        p.btn_next_time.clicked.connect(lambda: p.change_review_time(1))

        p.cb_time_picker = NoWheelComboBox()
        # v6.9：样式收敛到 custom_widgets 的完整契约（旧写法只给 ::drop-down 不给
        # ::down-arrow，Qt 会切到样式化绘制路径 ⇒ 箭头消失，§10-9）
        p.cb_time_picker.setStyleSheet(COMBO_QSS_ACCENT)
        p.cb_time_picker.activated.connect(p.quick_jump_time)

        p.btn_latest_time = QPushButton("⏭️ 最新")
        p.btn_latest_time.setStyleSheet("QPushButton { font-size: 14px; font-weight: bold; color: #4CAF50; padding: 5px 10px; border: 1px solid #A5D6A7; border-radius: 6px; background: #E8F5E9; margin-left: 5px;} QPushButton:hover { background: #C8E6C9; }")
        p.btn_latest_time.clicked.connect(p.jump_to_latest)

        nav_layout.addWidget(p.btn_prev_time)
        nav_layout.addWidget(p.cb_time_picker)
        nav_layout.addWidget(p.btn_next_time)
        nav_layout.addWidget(p.btn_latest_time)
        top_bar_1.addLayout(nav_layout)
        return top_bar_1

    # ==========================================
    # 第 2 行：五个筛选下拉（L1 操作轴 · 一行）
    # ==========================================
    def _build_filter_row(self) -> QHBoxLayout:
        p = self.page
        top_bar_2 = QHBoxLayout()
        top_bar_2.addWidget(QLabel("账户:"))
        p.cb_rev_account = NoWheelComboBox()
        p.cb_rev_account.currentIndexChanged.connect(p.update_review_view)
        top_bar_2.addWidget(p.cb_rev_account)

        top_bar_2.addSpacing(15)
        top_bar_2.addWidget(QLabel("策略:"))
        p.cb_rev_strategy = NoWheelComboBox()
        p.cb_rev_strategy.currentIndexChanged.connect(p.update_review_view)
        top_bar_2.addWidget(p.cb_rev_strategy)

        p.btn_manage_str = QPushButton("🏷️管理")
        p.btn_manage_str.setStyleSheet("QPushButton { border: none; color: #1976D2; font-weight:bold; font-size:13px;} QPushButton:hover { text-decoration: underline; }")
        p.btn_manage_str.clicked.connect(p.main_win.manage_strategies)
        top_bar_2.addWidget(p.btn_manage_str)

        top_bar_2.addSpacing(15)
        top_bar_2.addWidget(QLabel("品种主体:"))
        p.cb_rev_symbol = NoWheelComboBox()
        p.cb_rev_symbol.currentIndexChanged.connect(p.update_review_view)
        top_bar_2.addWidget(p.cb_rev_symbol)

        top_bar_2.addSpacing(15)
        top_bar_2.addWidget(QLabel("方向:"))
        p.cb_rev_direction = NoWheelComboBox()
        p.cb_rev_direction.addItems(["全部", "做多", "做空"])
        p.cb_rev_direction.currentIndexChanged.connect(p.update_review_view)
        top_bar_2.addWidget(p.cb_rev_direction)

        top_bar_2.addSpacing(15)
        top_bar_2.addWidget(QLabel("结果:"))
        p.cb_rev_result = NoWheelComboBox()
        p.cb_rev_result.addItems(["全部", "仅盈利", "仅亏损"])
        p.cb_rev_result.setToolTip("按「净额 = 平仓盈亏 − 手续费」判断（真实到手），"
                                   "与绩效统计口径一致")
        p.cb_rev_result.currentIndexChanged.connect(p.update_review_view)
        top_bar_2.addWidget(p.cb_rev_result)

        top_bar_2.addStretch()
        return top_bar_2

    # ==========================================
    # 月视图：宏观(日历|图表) + 微观(清单|编辑) 竖向分栏
    # ==========================================
    def _build_monthly_mode(self) -> QWidget:
        p = self.page
        widget = QWidget()
        layout = QVBoxLayout(widget); layout.setContentsMargins(0, 0, 0, 0)

        # ---- 宏观：日历热力图 ｜ 四页签图表 ----
        macro_splitter = QSplitter(Qt.Orientation.Horizontal)

        cal_card = QFrame()
        cal_card.setStyleSheet("QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }")
        cal_layout = QVBoxLayout(cal_card)
        cal_layout.setContentsMargins(10, 10, 10, 10)

        p.lbl_cal_month_title = QLabel("📅 正在加载...")
        p.lbl_cal_month_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #1976D2; margin-bottom: 5px;")
        p.lbl_cal_month_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cal_layout.addWidget(p.lbl_cal_month_title)

        p.review_calendar = QTableWidget(6, 7)
        p.review_calendar.setHorizontalHeaderLabels(["一", "二", "三", "四", "五", "六", "日"])
        p.review_calendar.verticalHeader().setVisible(False)
        p.review_calendar.setStyleSheet("QTableWidget { border: none; background: white; gridline-color: transparent; } QHeaderView::section { background: white; color: #9E9E9E; border: none; font-weight: bold; font-size: 13px; } QTableWidget::item { border-radius: 6px; margin: 2px; } QTableWidget::item:selected { border: 2px solid #1976D2; background: transparent; color: black; }")
        p.review_calendar.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        p.review_calendar.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        p.review_calendar.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        p.review_calendar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        p.review_calendar.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        p.review_calendar.cellClicked.connect(p.on_calendar_day_clicked)
        cal_layout.addWidget(p.review_calendar)

        chart_card = QFrame(); chart_card.setStyleSheet("QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }"); chart_layout = QVBoxLayout(chart_card); chart_layout.setContentsMargins(5, 5, 5, 5)
        p.review_chart_tabs = QTabWidget(); p.review_chart_tabs.setStyleSheet("QTabWidget::pane { border: none; } QTabBar::tab { background: transparent; color: #757575; padding: 8px 15px; font-weight: bold; font-size: 14px;} QTabBar::tab:selected { color: #1976D2; border-bottom: 3px solid #1976D2; }")

        p.review_pnl_chart = pg.PlotWidget()
        apply_pokorny_style(p.review_pnl_chart)

        p.review_kline_chart = pg.PlotWidget()
        apply_pokorny_style(p.review_kline_chart)

        # 【交易回放】v1.1 起为"单时间点锚定式"展示，见 review_playback.render_trade_playback
        p.playback_chart = pg.PlotWidget()
        apply_pokorny_style(p.playback_chart)

        # v1.3 持仓时长分布（v1.1 曾因无开仓时间而下线，现数据已补齐后重新引入）
        p.review_duration_chart = pg.PlotWidget()
        apply_pokorny_style(p.review_duration_chart)

        p.review_chart_tabs.addTab(p.review_pnl_chart, "📈 累计盈亏")
        p.review_chart_tabs.addTab(p.playback_chart, "🎯 交易回放")
        p.review_chart_tabs.addTab(p.review_kline_chart, "📊 资金 K线")
        p.review_chart_tabs.addTab(p.review_duration_chart, "⏱ 持仓时长")

        chart_layout.addWidget(p.review_chart_tabs)

        macro_splitter.addWidget(cal_card); macro_splitter.addWidget(chart_card); macro_splitter.setSizes([450, 600])

        # ---- 微观：当日清单 ｜ 编辑卡 ----
        micro_splitter = QSplitter(Qt.Orientation.Horizontal)
        list_card = QFrame(); list_card.setStyleSheet("QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }"); list_layout = QVBoxLayout(list_card); p.lbl_selected_date = QLabel("请在日历中选择日期..."); p.lbl_selected_date.setStyleSheet("font-weight: bold; color: #757575; font-size: 14px;")
        p.day_trades_list = QListWidget(); p.day_trades_list.setStyleSheet("QListWidget { border: none; font-size: 13px; } QListWidget::item { padding: 12px; border-bottom: 1px solid #F5F5F5; } QListWidget::item:selected { background: #E3F2FD; color: #1976D2; border-radius: 4px; }")
        p.day_trades_list.currentItemChanged.connect(p.on_review_trade_selected)
        list_layout.addWidget(p.lbl_selected_date); list_layout.addWidget(p.day_trades_list)

        editor_card = QFrame()
        editor_card.setStyleSheet("QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }")
        editor_layout = QVBoxLayout(editor_card)

        p.editor_header_card = QFrame()
        # v1.2: 详情头展示动作链 + 价格 + 点数，需要更高一点的空间
        p.editor_header_card.setFixedHeight(96)
        p.editor_header_card.setStyleSheet("QFrame { background: #FAFAFA; border-radius: 6px; border: 1px solid #EEEEEE; }")
        header_layout = QHBoxLayout(p.editor_header_card)
        header_layout.setContentsMargins(15, 10, 15, 10)

        p.lbl_trade_detail = QLabel("等待选择交易...")
        p.lbl_trade_detail.setStyleSheet("font-size: 14px; color: #9E9E9E; border: none;")
        p.lbl_trade_detail.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        header_layout.addWidget(p.lbl_trade_detail)

        header_layout.addStretch()

        strat_layout = QVBoxLayout()
        strat_layout.setContentsMargins(0, 0, 0, 0)
        lbl_cat = QLabel("归属策略:")
        lbl_cat.setStyleSheet("font-size: 11px; color: #757575; font-weight: bold; border: none;")
        strat_layout.addWidget(lbl_cat)

        p.cb_edit_strategy = NoWheelComboBox()
        p.cb_edit_strategy.setEditable(True)
        p.cb_edit_strategy.setFixedWidth(130)
        p.cb_edit_strategy.setStyleSheet(COMBO_QSS_EDIT)
        p.cb_edit_strategy.lineEdit().editingFinished.connect(p.silent_update_strategy)
        p.cb_edit_strategy.activated.connect(p.silent_update_strategy)
        strat_layout.addWidget(p.cb_edit_strategy)

        header_layout.addLayout(strat_layout)
        editor_layout.addWidget(p.editor_header_card)

        from PyQt6.QtWidgets import QTextEdit
        text_layout = QHBoxLayout(); v1, v2 = QVBoxLayout(), QVBoxLayout()
        v1.addWidget(QLabel("💡 进场逻辑:")); p.txt_reason = QTextEdit(); p.txt_reason.setStyleSheet("QTextEdit { border: 1px solid #EEEEEE; border-radius: 4px; background: #FAFAFA; padding: 5px;}"); v1.addWidget(p.txt_reason)
        v2.addWidget(QLabel("🔍 离场反思:")); p.txt_reflection = QTextEdit(); p.txt_reflection.setStyleSheet("QTextEdit { border: 1px solid #EEEEEE; border-radius: 4px; background: #FAFAFA; padding: 5px;}"); v2.addWidget(p.txt_reflection)
        text_layout.addLayout(v1); text_layout.addLayout(v2); editor_layout.addLayout(text_layout)

        p.orphan_bar = self._build_orphan_bar()
        editor_layout.addWidget(p.orphan_bar)

        # 【SRP 拆分】截图画廊的全部职能已下沉为独立组件，此处只负责挂载与信号桥接
        p.gallery = ScreenshotGallery(p)
        p.gallery.paths_changed.connect(p._save_image_paths_to_df)
        editor_layout.addWidget(p.gallery)

        action_layout = QHBoxLayout(); p.btn_del_trade = QPushButton("🗑️ 删除此单"); p.btn_del_trade.setStyleSheet(f"QPushButton {{ background-color: white; color: {settings.COLOR_LOSS}; border: 1px solid {settings.COLOR_LOSS}; border-radius: 6px; padding: 10px; font-weight: bold; }} QPushButton:hover {{ background-color: #FFEBEE; }}"); p.btn_del_trade.clicked.connect(p.delete_current_trade)

        p.btn_save_review = QPushButton("💾 保存复盘文字与截图")
        p.btn_save_review.setStyleSheet("QPushButton { background-color: #1976D2; color: white; border: none; border-radius: 6px; padding: 10px; font-weight: bold; } QPushButton:hover { background-color: #1565C0; }")
        p.btn_save_review.clicked.connect(p.save_review_text)

        action_layout.addWidget(p.btn_del_trade); action_layout.addStretch(); action_layout.addWidget(p.btn_save_review); editor_layout.addLayout(action_layout)

        micro_splitter.addWidget(list_card); micro_splitter.addWidget(editor_card); micro_splitter.setSizes([350, 700])

        # ---- ★§9-U 收口：宏观/微观之间竖向可拖分栏 + 记住上次 ----
        #   旧版 `addWidget(macro, 5) / addWidget(micro, 4)` 是写死的比例平铺：
        #   短屏上回放图被挤、且用户无法"拉大图表收矮清单"。
        p.macro_micro_splitter = QSplitter(Qt.Orientation.Vertical)
        p.macro_micro_splitter.addWidget(macro_splitter)
        p.macro_micro_splitter.addWidget(micro_splitter)
        # 不允许拖到 0（整块塌掉后用户会以为控件丢了）
        p.macro_micro_splitter.setChildrenCollapsible(False)
        p.macro_micro_splitter.setSizes(list(self._restored_v_sizes()))
        # 拖动结束后（防抖）由页面落偏好 —— 版式模块不落盘（它连 preferences 都不 import）
        p.macro_micro_splitter.splitterMoved.connect(p._on_review_splitter_moved)
        layout.addWidget(p.macro_micro_splitter, 1)
        return widget

    def _restored_v_sizes(self):
        """上次的分栏高度（页面状态里的偏好）；没有就用默认 560/340。"""
        saved = (self.page._review_ui or {}).get("v_sizes")
        if isinstance(saved, (list, tuple)) and len(saved) == 2 and all(
                isinstance(v, (int, float)) and v > 0 for v in saved):
            return [int(v) for v in saved]
        return list(_REVIEW_V_SIZES_DEFAULT)

    # ==========================================
    # 孤儿单补录条（仅选中孤儿单时可见）
    # ==========================================
    def _build_orphan_bar(self) -> QFrame:
        p = self.page
        # v1.2: 孤儿单（待缝合平仓）手工补录条 —— 仅当选中孤儿单时显示。
        # 【绝不阻断】补录是可选项；不补录也不影响任何统计，只是开仓价显示为待补录。
        orphan_bar = QFrame()
        orphan_bar.setStyleSheet(
            "QFrame { background: #FFF8E1; border: 1px solid #FFE082; border-radius: 6px; }")
        ob = QVBoxLayout(orphan_bar)
        ob.setContentsMargins(12, 8, 12, 8)
        ob.setSpacing(5)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        p.lbl_orphan_tip = QLabel("⚠️ 待缝合平仓：未找到开仓记录")
        p.lbl_orphan_tip.setStyleSheet("color: #E65100; font-size: 12px; border: none;")
        row1.addWidget(p.lbl_orphan_tip)
        row1.addStretch()

        p.inp_orphan_date = NoWheelDateEdit(QDate.currentDate())
        p.inp_orphan_date.setCalendarPopup(True)
        p.inp_orphan_date.setDisplayFormat("yyyy-MM-dd")
        p.inp_orphan_date.setFixedWidth(120)
        p.inp_orphan_date.setStyleSheet(DATEEDIT_QSS_WARN)

        p.inp_orphan_price = QLineEdit()
        p.inp_orphan_price.setPlaceholderText("开仓价")
        p.inp_orphan_price.setFixedWidth(100)
        p.inp_orphan_price.setStyleSheet(
            "QLineEdit { border: 1px solid #FFCC80; border-radius: 4px; "
            "padding: 3px; background: white; }")

        p.btn_guess_price = QPushButton("↩ 按盈亏推算")
        p.btn_guess_price.setToolTip(
            "用这笔平仓的盈亏 / 手数 / 合约乘数反推一个理论开仓价，填入输入框。\n"
            "仅供参考，请与真实交割单核对后再缝合。")
        p.btn_guess_price.setStyleSheet(
            "QPushButton { background: white; color: #E65100; "
            "border: 1px solid #FFB74D; "
            "border-radius: 4px; padding: 5px 10px; font-size: 12px; }"
            "QPushButton:hover { background: #FFE0B2; }")
        p.btn_guess_price.clicked.connect(p.guess_orphan_entry_price)

        p.btn_orphan_stitch = QPushButton("✂️ 补录并缝合")
        p.btn_orphan_stitch.setStyleSheet(
            "QPushButton { background: #FB8C00; color: white; border: none; border-radius: 4px; "
            "padding: 5px 12px; font-weight: bold; font-size: 12px; }"
            "QPushButton:hover { background: #F57C00; }")
        p.btn_orphan_stitch.clicked.connect(p.stitch_current_orphan)

        row1.addWidget(p.inp_orphan_date)
        row1.addWidget(p.inp_orphan_price)
        row1.addWidget(p.btn_guess_price)
        row1.addWidget(p.btn_orphan_stitch)
        ob.addLayout(row1)

        # 引导语：告诉用户操作路径与"表格不支持直接编辑"这一约束
        p.lbl_orphan_guide = QLabel(
            "填写上方的开仓日期与开仓价，点「补录并缝合」即永久保存。"
            "找不到真实开仓价时，可点「↩ 按盈亏推算」获得一个参考值，再与交割单核对。"
            "（交易流水表格仅供查看，直接敲单元格不会被保存。）")
        p.lbl_orphan_guide.setWordWrap(True)
        p.lbl_orphan_guide.setStyleSheet(
            "color: #A1887F; font-size: 11px; border: none;")
        ob.addWidget(p.lbl_orphan_guide)

        orphan_bar.setVisible(False)
        return orphan_bar
