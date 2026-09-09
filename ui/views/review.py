# ui/views/review.py
import math
import calendar
import numpy as np
import pandas as pd
from datetime import datetime

import pyqtgraph as pg
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QFrame, QStackedWidget, QTableWidget, 
                             QTableWidgetItem, QHeaderView,
                             QTabWidget, QMessageBox, QListWidget, 
                             QListWidgetItem, QTextEdit, QSplitter, QLineEdit,
                             QDateEdit)
from PyQt6.QtCore import Qt, QDate, QTimer
from PyQt6.QtGui import QColor, QFont

from ui.widgets.custom_widgets import CandlestickItem, NoWheelComboBox
from ui.widgets.chart_style import apply_pokorny_style, plot_equity_curve
from ui.widgets.screenshot_gallery import ScreenshotGallery
from ui.widgets.yearly_review import YearlyReviewPanel
from config import settings
from core.preferences import preferences
from core.utils import (extract_root_symbol, format_duration, format_fill_time,
                        format_points, format_price, format_trade_time,
                        record_entry_has_clock, record_holding_seconds,
                        row_points, trading_day_count)
from data.market_db import DataLakeManager
from core.indicators import TAEngine

# 交易回放上下文窗口 (交易时间前后各多少天) 与可容忍的锚点误差
PLAYBACK_CONTEXT_DAYS = 45
MAX_ANCHOR_GAP_DAYS = 7


class ReviewView(QWidget):
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

        self._setup_ui()

    def _apply_pokorny_style(self, chart: pg.PlotWidget, title: str = ""):
        """委托给 ui/widgets/chart_style.py —— 全 app 图表轴样式唯一来源 (v5.12 · §9-O7)"""
        return apply_pokorny_style(chart, title)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)
        
        top_bar_1 = QHBoxLayout()
        title = QLabel("复盘工作台")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #212121;")
        top_bar_1.addWidget(title)
        top_bar_1.addStretch()

        self.btn_mode_toggle = QPushButton("切换年视图 📅")
        self.btn_mode_toggle.setStyleSheet("QPushButton { font-size: 14px; font-weight: bold; color: #FF9800; padding: 5px 15px; border: 1px solid #FFCC80; border-radius: 6px; background: #FFF3E0; margin-right: 15px;} QPushButton:hover { background: #FFE0B2; }")
        self.btn_mode_toggle.clicked.connect(self.toggle_review_mode)
        top_bar_1.addWidget(self.btn_mode_toggle)

        nav_layout = QHBoxLayout()
        self.btn_prev_time = QPushButton("◀")
        self.btn_next_time = QPushButton("▶")
        for btn in [self.btn_prev_time, self.btn_next_time]: 
            btn.setStyleSheet("QPushButton { border: none; font-size: 18px; color: #9E9E9E;} QPushButton:hover { color: #1976D2; }")
        self.btn_prev_time.clicked.connect(lambda: self.change_review_time(-1))
        self.btn_next_time.clicked.connect(lambda: self.change_review_time(1))
        
        self.cb_time_picker = NoWheelComboBox()
        self.cb_time_picker.setStyleSheet("QComboBox { font-size: 16px; font-weight: bold; color: #1976D2; padding: 5px 15px; border: 1px solid #E0E0E0; border-radius: 6px; background: white;} QComboBox::drop-down { border: none; width: 20px;} QComboBox:hover { background: #F5F5F5; }")
        self.cb_time_picker.activated.connect(self.quick_jump_time)

        self.btn_latest_time = QPushButton("⏭️ 最新")
        self.btn_latest_time.setStyleSheet("QPushButton { font-size: 14px; font-weight: bold; color: #4CAF50; padding: 5px 10px; border: 1px solid #A5D6A7; border-radius: 6px; background: #E8F5E9; margin-left: 5px;} QPushButton:hover { background: #C8E6C9; }")
        self.btn_latest_time.clicked.connect(self.jump_to_latest)

        nav_layout.addWidget(self.btn_prev_time)
        nav_layout.addWidget(self.cb_time_picker)
        nav_layout.addWidget(self.btn_next_time)
        nav_layout.addWidget(self.btn_latest_time)
        top_bar_1.addLayout(nav_layout)
        
        top_bar_2 = QHBoxLayout()
        top_bar_2.addWidget(QLabel("账户:"))
        self.cb_rev_account = NoWheelComboBox()
        self.cb_rev_account.currentIndexChanged.connect(self.update_review_view)
        top_bar_2.addWidget(self.cb_rev_account)
        
        top_bar_2.addSpacing(15)
        top_bar_2.addWidget(QLabel("策略:"))
        self.cb_rev_strategy = NoWheelComboBox()
        self.cb_rev_strategy.currentIndexChanged.connect(self.update_review_view)
        top_bar_2.addWidget(self.cb_rev_strategy)
        
        self.btn_manage_str = QPushButton("🏷️管理")
        self.btn_manage_str.setStyleSheet("QPushButton { border: none; color: #1976D2; font-weight:bold; font-size:13px;} QPushButton:hover { text-decoration: underline; }")
        self.btn_manage_str.clicked.connect(self.main_win.manage_strategies)
        top_bar_2.addWidget(self.btn_manage_str)

        top_bar_2.addSpacing(15)
        top_bar_2.addWidget(QLabel("品种主体:"))
        self.cb_rev_symbol = NoWheelComboBox()
        self.cb_rev_symbol.currentIndexChanged.connect(self.update_review_view)
        top_bar_2.addWidget(self.cb_rev_symbol)

        top_bar_2.addSpacing(15)
        top_bar_2.addWidget(QLabel("方向:"))
        self.cb_rev_direction = NoWheelComboBox()
        self.cb_rev_direction.addItems(["全部", "做多", "做空"])
        self.cb_rev_direction.currentIndexChanged.connect(self.update_review_view)
        top_bar_2.addWidget(self.cb_rev_direction)

        top_bar_2.addSpacing(15)
        top_bar_2.addWidget(QLabel("结果:"))
        self.cb_rev_result = NoWheelComboBox()
        self.cb_rev_result.addItems(["全部", "仅盈利", "仅亏损"])
        self.cb_rev_result.setToolTip("按「净额 = 平仓盈亏 − 手续费」判断（真实到手），"
                                      "与绩效统计口径一致")
        self.cb_rev_result.currentIndexChanged.connect(self.update_review_view)
        top_bar_2.addWidget(self.cb_rev_result)

        top_bar_2.addStretch()

        layout.addLayout(top_bar_1)
        layout.addLayout(top_bar_2)

        self.review_stack = QStackedWidget()
        self.review_monthly_widget = self._build_monthly_mode()
        self.yearly_panel = YearlyReviewPanel(self)
        
        self.review_stack.addWidget(self.review_monthly_widget) 
        self.review_stack.addWidget(self.yearly_panel)  
        layout.addWidget(self.review_stack)

    def _build_monthly_mode(self):
        widget = QWidget()
        layout = QVBoxLayout(widget); layout.setContentsMargins(0, 0, 0, 0)
        
        macro_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        cal_card = QFrame()
        cal_card.setStyleSheet("QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }")
        cal_layout = QVBoxLayout(cal_card)
        cal_layout.setContentsMargins(10, 10, 10, 10)
        
        self.lbl_cal_month_title = QLabel("📅 正在加载...")
        self.lbl_cal_month_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #1976D2; margin-bottom: 5px;")
        self.lbl_cal_month_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cal_layout.addWidget(self.lbl_cal_month_title)

        self.review_calendar = QTableWidget(6, 7)
        self.review_calendar.setHorizontalHeaderLabels(["一", "二", "三", "四", "五", "六", "日"])
        self.review_calendar.verticalHeader().setVisible(False)
        self.review_calendar.setStyleSheet("QTableWidget { border: none; background: white; gridline-color: transparent; } QHeaderView::section { background: white; color: #9E9E9E; border: none; font-weight: bold; font-size: 13px; } QTableWidget::item { border-radius: 6px; margin: 2px; } QTableWidget::item:selected { border: 2px solid #1976D2; background: transparent; color: black;}")
        self.review_calendar.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.review_calendar.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.review_calendar.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.review_calendar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.review_calendar.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.review_calendar.cellClicked.connect(self.on_calendar_day_clicked)
        cal_layout.addWidget(self.review_calendar)
        
        chart_card = QFrame(); chart_card.setStyleSheet("QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }"); chart_layout = QVBoxLayout(chart_card); chart_layout.setContentsMargins(5, 5, 5, 5)
        self.review_chart_tabs = QTabWidget(); self.review_chart_tabs.setStyleSheet("QTabWidget::pane { border: none; } QTabBar::tab { background: transparent; color: #757575; padding: 8px 15px; font-weight: bold; font-size: 14px;} QTabBar::tab:selected { color: #1976D2; border-bottom: 3px solid #1976D2; }")
        
        self.review_pnl_chart = pg.PlotWidget()
        self._apply_pokorny_style(self.review_pnl_chart)
        
        self.review_kline_chart = pg.PlotWidget()
        self._apply_pokorny_style(self.review_kline_chart)

        # 【交易回放】v1.1 起为"单时间点锚定式"展示，见 _render_trade_playback
        self.playback_chart = pg.PlotWidget()
        self._apply_pokorny_style(self.playback_chart)

        # v1.3 持仓时长分布（v1.1 曾因无开仓时间而下线，现数据已补齐后重新引入）
        self.review_duration_chart = pg.PlotWidget()
        self._apply_pokorny_style(self.review_duration_chart)

        self.review_chart_tabs.addTab(self.review_pnl_chart, "📈 累计盈亏")
        self.review_chart_tabs.addTab(self.playback_chart, "🎯 交易回放")
        self.review_chart_tabs.addTab(self.review_kline_chart, "📊 资金 K线")
        self.review_chart_tabs.addTab(self.review_duration_chart, "⏱ 持仓时长")
        
        chart_layout.addWidget(self.review_chart_tabs)
        
        macro_splitter.addWidget(cal_card); macro_splitter.addWidget(chart_card); macro_splitter.setSizes([450, 600])
        layout.addWidget(macro_splitter, 5)

        micro_splitter = QSplitter(Qt.Orientation.Horizontal)
        list_card = QFrame(); list_card.setStyleSheet("QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }"); list_layout = QVBoxLayout(list_card); self.lbl_selected_date = QLabel("请在日历中选择日期..."); self.lbl_selected_date.setStyleSheet("font-weight: bold; color: #757575; font-size: 14px;")
        self.day_trades_list = QListWidget(); self.day_trades_list.setStyleSheet("QListWidget { border: none; font-size: 13px; } QListWidget::item { padding: 12px; border-bottom: 1px solid #F5F5F5; } QListWidget::item:selected { background: #E3F2FD; color: #1976D2; border-radius: 4px;}")
        self.day_trades_list.currentItemChanged.connect(self.on_review_trade_selected)
        list_layout.addWidget(self.lbl_selected_date); list_layout.addWidget(self.day_trades_list)
        
        editor_card = QFrame()
        editor_card.setStyleSheet("QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }")
        editor_layout = QVBoxLayout(editor_card)
        
        self.editor_header_card = QFrame()
        # v1.2: 详情头展示动作链 + 价格 + 点数，需要更高一点的空间
        self.editor_header_card.setFixedHeight(96)
        self.editor_header_card.setStyleSheet("QFrame { background: #FAFAFA; border-radius: 6px; border: 1px solid #EEEEEE; }")
        header_layout = QHBoxLayout(self.editor_header_card)
        header_layout.setContentsMargins(15, 10, 15, 10)
        
        self.lbl_trade_detail = QLabel("等待选择交易...")
        self.lbl_trade_detail.setStyleSheet("font-size: 14px; color: #9E9E9E; border: none;")
        self.lbl_trade_detail.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        header_layout.addWidget(self.lbl_trade_detail)
        
        header_layout.addStretch()
        
        strat_layout = QVBoxLayout()
        strat_layout.setContentsMargins(0, 0, 0, 0)
        lbl_cat = QLabel("归属策略:")
        lbl_cat.setStyleSheet("font-size: 11px; color: #757575; font-weight: bold; border: none;")
        strat_layout.addWidget(lbl_cat)
        
        self.cb_edit_strategy = NoWheelComboBox()
        self.cb_edit_strategy.setEditable(True)
        self.cb_edit_strategy.setFixedWidth(130)  
        self.cb_edit_strategy.setStyleSheet("QComboBox { border: 1px solid #D1D9E6; border-radius: 4px; background: white; color: #212121; padding: 4px; }")
        self.cb_edit_strategy.lineEdit().editingFinished.connect(self.silent_update_strategy)
        self.cb_edit_strategy.activated.connect(self.silent_update_strategy)
        strat_layout.addWidget(self.cb_edit_strategy)
        
        header_layout.addLayout(strat_layout)
        editor_layout.addWidget(self.editor_header_card)

        text_layout = QHBoxLayout(); v1, v2 = QVBoxLayout(), QVBoxLayout()
        v1.addWidget(QLabel("💡 进场逻辑:")); self.txt_reason = QTextEdit(); self.txt_reason.setStyleSheet("QTextEdit { border: 1px solid #EEEEEE; border-radius: 4px; background: #FAFAFA; padding: 5px;}"); v1.addWidget(self.txt_reason)
        v2.addWidget(QLabel("🔍 离场反思:")); self.txt_reflection = QTextEdit(); self.txt_reflection.setStyleSheet("QTextEdit { border: 1px solid #EEEEEE; border-radius: 4px; background: #FAFAFA; padding: 5px;}"); v2.addWidget(self.txt_reflection)
        text_layout.addLayout(v1); text_layout.addLayout(v2); editor_layout.addLayout(text_layout)
        
        # v1.2: 孤儿单（待缝合平仓）手工补录条 —— 仅当选中孤儿单时显示。
        # 【绝不阻断】补录是可选项；不补录也不影响任何统计，只是开仓价显示为待补录。
        self.orphan_bar = QFrame()
        self.orphan_bar.setStyleSheet(
            "QFrame { background: #FFF8E1; border: 1px solid #FFE082; border-radius: 6px; }")
        ob = QVBoxLayout(self.orphan_bar)
        ob.setContentsMargins(12, 8, 12, 8)
        ob.setSpacing(5)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self.lbl_orphan_tip = QLabel("⚠️ 待缝合平仓：未找到开仓记录")
        self.lbl_orphan_tip.setStyleSheet("color: #E65100; font-size: 12px; border: none;")
        row1.addWidget(self.lbl_orphan_tip)
        row1.addStretch()

        self.inp_orphan_date = QDateEdit(QDate.currentDate())
        self.inp_orphan_date.setCalendarPopup(True)
        self.inp_orphan_date.setDisplayFormat("yyyy-MM-dd")
        self.inp_orphan_date.setFixedWidth(120)
        self.inp_orphan_date.setStyleSheet(
            "QDateEdit { border: 1px solid #FFCC80; border-radius: 4px; "
            "padding: 3px; background: white; }")

        self.inp_orphan_price = QLineEdit()
        self.inp_orphan_price.setPlaceholderText("开仓价")
        self.inp_orphan_price.setFixedWidth(100)
        self.inp_orphan_price.setStyleSheet(
            "QLineEdit { border: 1px solid #FFCC80; border-radius: 4px; "
            "padding: 3px; background: white; }")

        self.btn_guess_price = QPushButton("↩ 按盈亏推算")
        self.btn_guess_price.setToolTip(
            "用这笔平仓的盈亏 / 手数 / 合约乘数反推一个理论开仓价，填入输入框。\n"
            "仅供参考，请与真实交割单核对后再缝合。")
        self.btn_guess_price.setStyleSheet(
            "QPushButton { border: 1px solid #FFB74D; color: #E65100; background: white; "
            "border-radius: 4px; padding: 5px 10px; font-size: 12px; }"
            "QPushButton:hover { background: #FFE0B2; }")
        self.btn_guess_price.clicked.connect(self.guess_orphan_entry_price)

        self.btn_orphan_stitch = QPushButton("✂️ 补录并缝合")
        self.btn_orphan_stitch.setStyleSheet(
            "QPushButton { background: #FB8C00; color: white; border: none; border-radius: 4px; "
            "padding: 5px 12px; font-weight: bold; font-size: 12px; }"
            "QPushButton:hover { background: #F57C00; }")
        self.btn_orphan_stitch.clicked.connect(self.stitch_current_orphan)

        row1.addWidget(self.inp_orphan_date)
        row1.addWidget(self.inp_orphan_price)
        row1.addWidget(self.btn_guess_price)
        row1.addWidget(self.btn_orphan_stitch)
        ob.addLayout(row1)

        # 引导语：告诉用户操作路径与"表格不支持直接编辑"这一约束
        self.lbl_orphan_guide = QLabel(
            "填写上方的开仓日期与开仓价，点「补录并缝合」即永久保存。"
            "找不到真实开仓价时，可点「↩ 按盈亏推算」获得一个参考值，再与交割单核对。"
            "（交易流水表格仅供查看，直接敲单元格不会被保存。）")
        self.lbl_orphan_guide.setWordWrap(True)
        self.lbl_orphan_guide.setStyleSheet(
            "color: #A1887F; font-size: 11px; border: none;")
        ob.addWidget(self.lbl_orphan_guide)

        self.orphan_bar.setVisible(False)
        editor_layout.addWidget(self.orphan_bar)
        
        # 【SRP 拆分】截图画廊的全部职能已下沉为独立组件，此处只负责挂载与信号桥接
        self.gallery = ScreenshotGallery(self)
        self.gallery.paths_changed.connect(self._save_image_paths_to_df)
        editor_layout.addWidget(self.gallery)
        
        action_layout = QHBoxLayout(); self.btn_del_trade = QPushButton("🗑️ 删除此单"); self.btn_del_trade.setStyleSheet(f"QPushButton {{ background-color: white; color: {settings.COLOR_LOSS}; border: 1px solid {settings.COLOR_LOSS}; border-radius: 6px; padding: 10px; font-weight: bold; }} QPushButton:hover {{ background-color: #FFEBEE; }}"); self.btn_del_trade.clicked.connect(self.delete_current_trade)
        
        self.btn_save_review = QPushButton("💾 保存复盘文字与截图")
        self.btn_save_review.setStyleSheet("QPushButton { background-color: #1976D2; color: white; border: none; border-radius: 6px; padding: 10px; font-weight: bold; } QPushButton:hover { background-color: #1565C0; }")
        self.btn_save_review.clicked.connect(self.save_review_text)
        
        action_layout.addWidget(self.btn_del_trade); action_layout.addStretch(); action_layout.addWidget(self.btn_save_review); editor_layout.addLayout(action_layout)
        
        micro_splitter.addWidget(list_card); micro_splitter.addWidget(editor_card); micro_splitter.setSizes([350, 700])
        layout.addWidget(micro_splitter, 4)
        return widget

    # NOTE: 年度视图的 UI 构建与渲染已整体下沉至 ui/widgets/yearly_review.py (YearlyReviewPanel)
    def toggle_review_mode(self):
        self.is_yearly_view = not self.is_yearly_view
        if self.is_yearly_view:
            self.btn_mode_toggle.setText("切换月视图 🔍")
            self.btn_mode_toggle.setStyleSheet(f"QPushButton {{ font-size: 14px; font-weight: bold; color: {settings.COLOR_PROFIT_TEXT}; padding: 5px 15px; border: 1px solid #A5D6A7; border-radius: 6px; background: #E8F5E9; margin-right: 15px;}} QPushButton:hover {{ background: #C8E6C9; }}")
            self.review_stack.setCurrentIndex(1)
            # 【v5.12 修正 · §9-O8】年视图不存在"交易回放"，切过去必须清空画布，
            # 否则下次切回月视图会残留上一次的 K 线回放（看起来像"数据没刷新"）。
            self.playback_chart.clear()
        else:
            self.btn_mode_toggle.setText("切换年视图 📅")
            self.btn_mode_toggle.setStyleSheet("QPushButton { font-size: 14px; font-weight: bold; color: #FF9800; padding: 5px 15px; border: 1px solid #FFCC80; border-radius: 6px; background: #FFF3E0; margin-right: 15px;} QPushButton:hover { background: #FFE0B2; }")
            self.review_stack.setCurrentIndex(0) 
            
        self.update_review_view()

    def refresh_review_filters(self):
        """数据变动后重建筛选下拉框。数据为空时重置为默认项，绝不残留旧选项。"""
        combos = [self.cb_rev_account, self.cb_rev_strategy, self.cb_rev_symbol, self.cb_edit_strategy]
        for cb in combos:
            cb.blockSignals(True)
        try:
            self._populate_review_filter_options()
        finally:
            # 【健壮性】即使中途抛异常也必须恢复信号，否则控件会“假死”
            for cb in combos:
                cb.blockSignals(False)

    def _populate_review_filter_options(self):
        df = self.main_win.engine.df

        self.cb_rev_account.clear()
        self.cb_rev_account.addItem("全账户", "ALL")
        if not df.empty:
            for acc in df['account'].dropna().unique():
                self.cb_rev_account.addItem(str(acc), str(acc))

        # engine.strategies 已汇总默认策略与历史出现过的策略，数据为空时自动退化为默认项
        self.cb_rev_strategy.clear()
        self.cb_rev_strategy.addItem("全策略", "ALL")
        self.cb_edit_strategy.clear()
        for st in self.main_win.engine.strategies:
            self.cb_rev_strategy.addItem(str(st), str(st))
            self.cb_edit_strategy.addItem(str(st))

        self.cb_rev_symbol.clear()
        self.cb_rev_symbol.addItem("全品种", "ALL")
        if not df.empty:
            roots = {extract_root_symbol(sym) for sym in df['symbol'].dropna().unique()}
            for r in sorted(roots):
                self.cb_rev_symbol.addItem(r, r)

    def refresh_time_picker(self, is_year=False):
        self.cb_time_picker.blockSignals(True)
        self.cb_time_picker.clear()
        if self.main_win.engine.df.empty: 
            self.cb_time_picker.blockSignals(False)
            return
        
        dates = pd.to_datetime(self.main_win.engine.df['trade_time'])
        
        if is_year:
            data_years = set(dates.dt.year.dropna().unique())
            all_years = sorted(list(data_years | {self.current_review_date.year}), reverse=True)
            for y in all_years:
                txt = f"{y}年" if y in data_years else f"{y}年 (无记录)"
                self.cb_time_picker.addItem(txt, datetime(y, 1, 1))
        else:
            data_months = set([d.to_timestamp() for d in dates.dt.to_period('M').dropna().unique()])
            current_m = pd.Timestamp(self.current_review_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0))
            all_months = sorted(list(data_months | {current_m}), reverse=True)
            for dt in all_months:
                txt = dt.strftime("%Y年 %m月") if dt in data_months else dt.strftime("%Y年 %m月 (无记录)")
                self.cb_time_picker.addItem(txt, dt.to_pydatetime())
                
        self.cb_time_picker.blockSignals(False)

    def quick_jump_time(self):
        selected_dt = self.cb_time_picker.currentData()
        if selected_dt:
            self.current_review_date = selected_dt
            self.update_review_view()

    def change_review_time(self, delta):
        if self.is_yearly_view:
            y = self.current_review_date.year + delta
            self.current_review_date = self.current_review_date.replace(year=y, month=1, day=1)
        else:
            m = self.current_review_date.month - 1 + delta; y = self.current_review_date.year + m // 12; m = m % 12 + 1
            self.current_review_date = self.current_review_date.replace(year=y, month=m, day=1)
        self.update_review_view()

    def jump_to_latest(self):
        if self.main_win.engine.df.empty: return
        latest_date = pd.to_datetime(self.main_win.engine.df['trade_time']).dropna().max()
        if pd.notna(latest_date):
            self.current_review_date = latest_date.to_pydatetime()
            self.update_review_view()

    def update_review_view(self):
        self.lbl_selected_date.setText("当前视图已改变，请在日历重新选择日期...")
        self.day_trades_list.clear()
        self.txt_reason.clear()
        self.txt_reflection.clear()
        self.gallery.clear()
        
        self.lbl_trade_detail.setText("等待选择交易...")
        self.lbl_trade_detail.setStyleSheet("font-size: 14px; color: #9E9E9E; border: none;")
        self.orphan_bar.setVisible(False)

        self.current_editing_idx = None

        # 【v5.12 修正 · §9-O8】数据为空时也必须刷新时间选择器：
        # 旧代码在这里直接 return，导至清空账户/删完最后一条后，
        # 下拉框仍残留着已经不存在的月份项（陈旧 UI）。
        if self.main_win.engine.df.empty:
            self.refresh_time_picker(self.is_yearly_view)
            return

        self.refresh_time_picker(self.is_yearly_view)
        
        self.cb_time_picker.blockSignals(True)
        for i in range(self.cb_time_picker.count()):
            item_data = self.cb_time_picker.itemData(i)
            dt = item_data.toPyDateTime() if hasattr(item_data, 'toPyDateTime') else item_data
            
            if self.is_yearly_view:
                if dt.year == self.current_review_date.year:
                    self.cb_time_picker.setCurrentIndex(i)
                    break
            else:
                if dt.year == self.current_review_date.year and dt.month == self.current_review_date.month:
                    self.cb_time_picker.setCurrentIndex(i)
                    break
        self.cb_time_picker.blockSignals(False)
        
        df = self.main_win.engine.df.copy()

        # 【v5.12 · §9-O1 净额口径统一】"仅盈利 / 仅亏损"按真实到手判断，
        # 与流水页、Dashboard、core/analyzer 保持同一口径（§5.3-B）。
        if {'net_profit', 'commission'}.issubset(df.columns):
            df['net_amount'] = df['net_profit'] - df['commission'].fillna(0)
        else:
            df['net_amount'] = df['net_profit']

        acc_sel = self.cb_rev_account.currentData()
        if acc_sel != "ALL" and acc_sel is not None: df = df[df['account'] == acc_sel]
        
        str_sel = self.cb_rev_strategy.currentData()
        if str_sel != "ALL" and str_sel is not None: df = df[df['strategy_tag'] == str_sel]
            
        sym_sel = self.cb_rev_symbol.currentData()
        if sym_sel != "ALL" and sym_sel is not None: 
            df['root_sym'] = df['symbol'].apply(extract_root_symbol)
            df = df[df['root_sym'] == sym_sel]
            
        dir_sel = self.cb_rev_direction.currentText()
        if dir_sel == "做多": df = df[df['direction'] == 'LONG']
        elif dir_sel == "做空": df = df[df['direction'] == 'SHORT']
            
        res_sel = self.cb_rev_result.currentText()
        if res_sel == "仅盈利": df = df[df['net_amount'] > 0]
        elif res_sel == "仅亏损": df = df[df['net_amount'] <= 0]
            
        df['trade_time'] = pd.to_datetime(df['trade_time'])
        
        y = self.current_review_date.year
        if self.is_yearly_view:
            self.current_view_df = df[df['trade_time'].dt.year == y].copy()
            self.yearly_panel.render(self.current_view_df)
        else:
            m = self.current_review_date.month
            self.current_view_df = df[(df['trade_time'].dt.year == y) & (df['trade_time'].dt.month == m)].copy()
            self.lbl_cal_month_title.setText(f"📅 {y}年 {m}月 复盘热力图")
            self._render_calendar()
            self._render_monthly_charts()
            self._render_duration_analysis()

    def _render_calendar(self):
        self.review_calendar.clearContents()
        y, m = self.current_review_date.year, self.current_review_date.month
        cal = calendar.monthcalendar(y, m)
        df = self.current_view_df.copy()
        daily_stats = {}
        max_abs_net = 0.0
        
        if not df.empty:
            # v1.2 净额口径：当日真实到手 = 平仓盈亏 − 手续费
            df['net_amount'] = df['net_profit'] - df['commission'].fillna(0)
            df['day'] = df['trade_time'].dt.day
            daily_sums = df.groupby('day')['net_amount'].sum()
            if not daily_sums.empty:
                max_abs_net = daily_sums.abs().max()
                if max_abs_net == 0: max_abs_net = 1.0  
            
            for day, group in df.groupby('day'):
                daily_stats[day] = {
                    'net': group['net_amount'].sum(), 
                    'reviewed': any((pd.notna(group['reflection']) & (group['reflection'].str.strip() != '')))
                }
                
        for row, week in enumerate(cal):
            for col, day in enumerate(week):
                if day == 0: continue 
                item = QTableWidgetItem(str(day))
                
                if day in daily_stats:
                    net = daily_stats[day]['net']
                    intensity = 40 + int((abs(net) / max_abs_net) * 215)
                    
                    if net > 0: 
                        r, g, b = settings.RGB_PROFIT
                        bg_color = QColor(r, g, b, intensity)
                        text_color = QColor(settings.COLOR_PROFIT_TEXT) 
                    elif net < 0: 
                        r, g, b = settings.RGB_LOSS
                        bg_color = QColor(r, g, b, intensity)
                        text_color = QColor(settings.COLOR_LOSS_TEXT)
                    else:
                        bg_color = QColor("#F5F5F5")
                        text_color = QColor("#757575")

                    item.setBackground(bg_color)
                    item.setForeground(text_color)
                    item.setText(f"{day}\n{'+' if net>0 else ''}{net:,.0f}")
                    
                    if daily_stats[day]['reviewed']: item.setText(item.text() + "\n📝")
                else: 
                    item.setForeground(QColor("#BDBDBD"))
                    
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                font = QFont(); font.setBold(day in daily_stats); item.setFont(font)
                item.setData(Qt.ItemDataRole.UserRole, QDate(y, m, day))
                self.review_calendar.setItem(row, col, item)

    def _render_monthly_charts(self):
        """月度复盘图表：累计盈亏净值曲线 + 按日聚合成K线的资金曲线。

        NOTE(v1.1): 原"时长分析"散点图依赖开/平仓双时间，交割单不再提供，已删除。
        """
        self.review_pnl_chart.clear()
        self.review_kline_chart.clear()
        df = self.current_view_df.copy()
        if df.empty: return

        # v1.2 净额口径：净值曲线 / 资金 K线 均基于真实到手盈亏（扣手续费后）
        df_sorted = df.sort_values(by='trade_time').copy()
        df_sorted['net_amount'] = df_sorted['net_profit'] - df_sorted['commission'].fillna(0)
        equity_curve = [0.0] + df_sorted['net_amount'].cumsum().tolist()
        # 累计盈亏曲线：统一走 chart_style（v5.12 · §9-O7），基准线 0
        plot_equity_curve(self.review_pnl_chart, equity_curve, fill_base=0.0, width=2)

        # 资金 K 线：把同一天的多笔交易聚合成一根蜡烛 (当日权益的开高低收)
        df_sorted['day'] = df_sorted['trade_time'].dt.day
        k_data, day_labels = [], []
        current_equity = 0.0
        for i, (day, group) in enumerate(df_sorted.groupby('day')):
            open_eq = current_equity
            high_eq = current_equity
            low_eq = current_equity
            for pnl in group['net_amount']:
                current_equity += pnl
                high_eq = max(high_eq, current_equity)
                low_eq = min(low_eq, current_equity)
            k_data.append((i, open_eq, current_equity, low_eq, high_eq))
            day_labels.append(f"{day}日")

        if k_data:
            self.review_kline_chart.addItem(CandlestickItem(k_data))
            axis = self.review_kline_chart.getAxis('bottom')
            axis.setTicks([list(enumerate(day_labels))])

    def _trading_dates_for(self, symbol: str) -> list:
        """按需读取某品种主体的本地交易日历（带缓存），无本地数据返回空列表"""
        root = extract_root_symbol(symbol)
        if root in self._trading_cal:
            return self._trading_cal[root]
        dates: list = []
        try:
            if self.data_lake.exists("kline_daily", root):
                df_k = self.data_lake.load_data("kline_daily", root)
                if not df_k.empty and 'date' in df_k.columns:
                    dates = list(pd.to_datetime(df_k['date']).dropna().unique())
        except Exception:
            dates = []
        self._trading_cal[root] = dates
        return dates

    def _render_duration_analysis(self):
        """
        v1.3 持仓时长分析（v1.1 曾因无开仓时间而下线，数据补齐后重新引入）：
          - 开仓带时分的记录 → 精确计时，按"分钟(对数)"绘制分布直方图；
          - 开仓仅日期的记录 → 用本地交易日历按「交易日」计数（周末/节假日不虚增），
            本地无行情时回退自然日并如实标注；
          - 完全缺开仓时间 → 不参与统计，覆盖率始终明示。
        """
        chart = self.review_duration_chart
        chart.clear()
        df = self.current_view_df.copy()
        if df.empty:
            chart.setTitle("⏱ 当前区间暂无数据", color="#9E9E9E", size="11pt")
            return

        exact_minutes: list[float] = []
        day_days: list[int] = []
        day_natural_fallback = 0
        unknown = 0
        total = len(df)

        for _, rec in df.iterrows():
            entry_raw = rec.get('entry_time')
            if entry_raw is None or pd.isna(entry_raw):
                unknown += 1
                continue
            if record_entry_has_clock(rec):
                secs = record_holding_seconds(rec)
                if secs is not None and secs >= 0:
                    exact_minutes.append(secs / 60.0)
            else:
                # 仅日期：交易日计数优先，日历不足回退自然日
                cal = self._trading_dates_for(str(rec.get('symbol', '')))
                days = trading_day_count(entry_raw, rec.get('trade_time'), cal) if cal else None
                if days is None:
                    try:
                        a = pd.to_datetime(entry_raw).date()
                        b = pd.to_datetime(rec.get('trade_time')).date()
                        days = max(0, (b - a).days + 1)
                        day_natural_fallback += 1
                    except Exception:
                        # 【v5.12 修正 · §9-O8】旧代码在此把 0 天计入均值，
                        # 与"算不出来就不参与统计"的设计自相矛盾（会系统性拉低均值）。
                        # 算不出来就如实跳过，绝不拿 0 冒充。
                        continue
                day_days.append(days)

        covered = len(exact_minutes)
        if not exact_minutes and not day_days:
            chart.setTitle(f"⏱ 无可计时持仓（{total} 笔均缺开仓时间）",
                           color="#FF9800", size="11pt")
            return

        # 概要（覆盖率 / 中位 / 仅日期交易日口径）
        summary = []
        if exact_minutes:
            median_min = float(np.median(exact_minutes))
            summary.append(f"精确 {covered} 笔 · 中位 {format_duration(median_min * 60)}")
        if day_days:
            mean_day = float(np.mean(day_days))
            label = f"仅日期 {len(day_days)} 笔 · 平均跨 {mean_day:.1f} 个交易日"
            if day_natural_fallback:
                label += "（其中部分因本地无行情按自然日计）"
            summary.append(label)
        if unknown:
            summary.append(f"无开仓时间 {unknown} 笔")
        chart.setTitle("⏱ " + " | ".join(summary), color="#1976D2", size="11pt")

        if exact_minutes:
            log_mins = [math.log10(max(m, 0.2)) for m in exact_minutes]
            hi = max(math.log10(max(exact_minutes) * 1.05), math.log10(0.2))
            bins = np.linspace(math.log10(0.2), hi, 16)
            hist, edges = np.histogram(log_mins, bins=bins)
            x_vals, y_vals = [], []
            for i in range(len(edges) - 1):
                x_vals += [edges[i], edges[i + 1]]
                y_vals += [hist[i], hist[i]]
            chart.plot(x_vals, y_vals, pen=pg.mkPen(color='#1976D2', width=2),
                       fillLevel=0, fillBrush=pg.mkBrush((25, 118, 210, 90)))
            chart.getAxis('left').setLabel('笔数')
            chart.getAxis('bottom').setLabel('持仓时长（对数分钟）')

            # 平均线参考
            avg_min = float(np.mean(exact_minutes))
            chart.addLine(x=math.log10(max(avg_min, 0.2)),
                          pen=pg.mkPen(color='#FB8C00', width=1.5,
                                       style=Qt.PenStyle.DashLine))

            # 可读时间刻度
            refs = [(0.5, "30秒"), (1, "1分"), (5, "5分"), (15, "15分"),
                    (60, "1小时"), (240, "4小时"), (1440, "1天"), (10080, "7天")]
            ticks = [[(math.log10(v), label) for v, label in refs
                      if math.log10(v) <= hi]]
            chart.getAxis('bottom').setTicks(ticks)

    def on_calendar_day_clicked(self, row, col):
        item = self.review_calendar.item(row, col)
        if not item or not item.data(Qt.ItemDataRole.UserRole): return
        qdate = item.data(Qt.ItemDataRole.UserRole)
        self.lbl_selected_date.setText(f"👇 选定日期: {qdate.toString('yyyy年MM月dd日')}")
        self.lbl_selected_date.setStyleSheet("font-weight: bold; color: #1976D2; font-size: 14px;")
        
        self.day_trades_list.clear(); self.txt_reason.clear(); self.txt_reflection.clear(); self.gallery.clear()
        
        self.lbl_trade_detail.setText("请在下方列表选择一笔特定交易...")
        self.lbl_trade_detail.setStyleSheet("font-size: 14px; color: #9E9E9E; border: none;")
        self.orphan_bar.setVisible(False)

        self.current_editing_idx = None
        day_df = self.current_view_df[self.current_view_df['trade_time'].dt.day == qdate.day()]
        for idx, record in day_df.iterrows():
            pnl, sym = record['net_profit'], record['symbol']
            is_orphan = int(record.get('is_orphan', 0) or 0) == 1
            action = "买开" if record.get('direction') == 'LONG' else "卖开"
            entry_txt = format_price(record.get('entry_price')) if not is_orphan else "?"
            exit_txt = format_price(record.get('exit_price'))
            pts = row_points(record)
            pts_txt = format_points(pts) if pts is not None else "—点"
            arrow = "→" if not is_orphan else "?"
            time_tag = ""
            if preferences.use_fill_time():
                fill = format_fill_time(record.get('exit_fill_time'))
                if fill:
                    time_tag = f"@{fill}"

            txt = (f"{sym} | {action}{time_tag} {entry_txt}{arrow}{exit_txt} "
                   f"{pts_txt} ￥{'+' if pnl > 0 else ''}{pnl:,.0f}")
            if pd.notna(record.get('reflection')) and str(record.get('reflection')).strip() != "":
                txt += " 📝"

            list_item = QListWidgetItem(txt)
            list_item.setData(Qt.ItemDataRole.UserRole, idx)
            list_item.setForeground(QColor(settings.COLOR_PROFIT_TEXT) if pnl > 0 else QColor(settings.COLOR_LOSS_TEXT))
            if is_orphan:
                list_item.setToolTip("待缝合：未找到开仓记录。可补导更早月份交割单，或在选中后手工补录开仓价。")
            self.day_trades_list.addItem(list_item)

    @staticmethod
    def _display_time(record) -> str:
        """
        渲染主时间列（平仓锚点）。按用户的时间精度偏好附加真实时分。
        trade_time 主锚点永远是纯日期，时分来自独立的 exit_fill_time 字段。
        """
        base = format_trade_time(record.get('trade_time'))
        if preferences.use_fill_time():
            fill = format_fill_time(record.get('exit_fill_time'))
            if fill:
                return f"{base} {fill}"
        return base

    @staticmethod
    def _format_leg_time(value) -> str:
        """渲染某一腿的真实成交时刻；信息缺失时返回空串"""
        if value is None:
            return ""
        try:
            parsed = pd.to_datetime(value)
            return "" if pd.isna(parsed) else format_trade_time(parsed)
        except Exception:
            return ""

    def _update_detail_header(self, record, is_orphan: bool, pnl: float):
        """详情头：品种 + 动作链 + 开/平价格 + 点数 + 盈亏（孤儿单如实标注待补录）"""
        col_hex = settings.COLOR_PROFIT_TEXT if pnl > 0 else settings.COLOR_LOSS_TEXT
        is_long = record.get('direction') == 'LONG'
        action = "买入开仓" if is_long else "卖出开仓"
        close = "卖出平仓" if is_long else "买入平仓"
        entry_time_txt = self._format_leg_time(record.get('entry_time'))
        entry_price = format_price(record.get('entry_price'))
        exit_price = format_price(record.get('exit_price'))
        pts = row_points(record)

        html = (
            f'<span style="font-size:16px; font-weight:bold; color:#212121;">{record["symbol"]}</span>'
            f'<span style="color:#757575; font-size:12px;">&nbsp;|&nbsp; {action} → {close}</span><br/>'
            f'<span style="font-size:12px; color:#616161;">'
            f'平仓 {self._display_time(record)}'
            + (f'　·　开仓 {entry_time_txt}' if entry_time_txt else '')
            + '</span>'
        )
        if is_orphan:
            html += (
                '<br/><span style="font-size:13px; color:#757575;">开仓价: </span>'
                '<span style="font-size:13px; color:#F57C00; font-style:italic;">待补录（缝合前点数不可算）</span>'
                f'　→　平仓价 <b style="color:#212121;">{exit_price}</b>'
                '<span style="color:#757575;">　|　结果: </span>'
                f'<b style="color:{col_hex}; font-size:16px;">￥{pnl:,.2f}</b>'
            )
        else:
            pts_txt = format_points(pts) if pts is not None else "—"
            html += (
                '<br/><span style="font-size:13px; color:#757575;">开仓价 </span>'
                f'<b style="color:#212121;">{entry_price}</b>'
                '<span style="color:#616161;"> → </span>'
                f'<b style="color:#212121;">{exit_price}</b>'
                '<span style="color:#757575;">　|　盈亏 </span>'
                f'<b style="color:{col_hex};">{pts_txt} 点</b>'
                '<span style="color:#757575;">　|　结果: </span>'
                f'<b style="color:{col_hex}; font-size:16px;">￥{pnl:,.2f}</b>'
            )
        self.lbl_trade_detail.setText(html)

    def on_review_trade_selected(self, current, previous):
        if not current: return
        df_idx = current.data(Qt.ItemDataRole.UserRole)
        if df_idx not in self.main_win.engine.df.index: return
        
        record = self.main_win.engine.df.loc[df_idx]
        self.current_editing_idx = df_idx

        is_orphan = int(record.get('is_orphan', 0) or 0) == 1
        self._update_detail_header(record, is_orphan, record['net_profit'])

        self.txt_reason.setPlainText(str(record.get('entry_reason', '')))
        self.txt_reflection.setPlainText(str(record.get('reflection', '')))
        
        self.cb_edit_strategy.blockSignals(True)
        self.cb_edit_strategy.setCurrentText(str(record.get('strategy_tag', settings.DEFAULT_STRATEGY)))
        self.cb_edit_strategy.blockSignals(False)

        # 孤儿补录条：仅孤儿单显示，开仓日期默认给到平仓日前一天（用户自行核对）
        self.orphan_bar.setVisible(is_orphan)
        if is_orphan:
            close_dt = pd.to_datetime(record['trade_time']) - pd.Timedelta(days=1)
            self.inp_orphan_date.setDate(QDate(close_dt.year, close_dt.month, close_dt.day))
            self.inp_orphan_price.clear()
            self.inp_orphan_price.setFocus()
        
        # 绑定归属交易后重建画廊，后续粘贴/导入的截图都会挂到这笔交易名下
        self.gallery.set_owner(record.get('internal_id'))
        self.gallery.set_paths(record.get('screenshot_paths', ''))
                
        # ==========================================
        # 【终极杀器】触发 K 线回放渲染引擎！
        # ==========================================
        self._render_trade_playback(record)

    @staticmethod
    def _guess_orphan_entry_price(record):
        """
        按盈亏反推理论开仓价（快速指引的可行性实现）。

        方向公式：
          LONG : 盈亏 = (平仓价 − 开仓价) × 乘数 × 手数  ⇒  开仓价 = 平仓价 − 盈亏/(乘数×手数)
          SHORT: 盈亏 = (开仓价 − 平仓价) × 乘数 × 手数  ⇒  开仓价 = 平仓价 + 盈亏/(乘数×手数)

        【诚实边界】仅在开仓价未知且整笔平仓可归因时足够准确；
        若一笔平仓混有多个开仓（含匹配片），反推值是加权近似，
        必须提示用户与真实交割单核对后使用。
        """
        try:
            exit_price = float(record.get('exit_price'))
            pnl = float(record.get('net_profit', 0.0))
            lots = int(record.get('lots', 0) or 0)
            multiplier = float(record.get('multiplier', 0.0) or 0.0)
        except (TypeError, ValueError):
            return None
        if exit_price <= 0 or lots <= 0 or multiplier <= 0:
            return None
        per_lot = pnl / (multiplier * lots)
        if record.get('direction') == 'LONG':
            return exit_price - per_lot
        return exit_price + per_lot

    def guess_orphan_entry_price(self):
        """点击「↩ 按盈亏推算」：把反推出的开仓价填入输入框供用户核对"""
        idx = getattr(self, 'current_editing_idx', None)
        if idx is None or idx not in self.main_win.engine.df.index:
            return
        record = self.main_win.engine.df.loc[idx]
        if int(record.get('is_orphan', 0) or 0) != 1:
            return

        guess = self._guess_orphan_entry_price(record)
        if guess is None:
            QMessageBox.information(
                self, "无法推算",
                "这笔交易缺少足够的平仓价 / 手数 / 合约乘数，无法按盈亏反推开仓价。\n"
                "请对照交割单手动填写真实开仓价。")
            return

        self.inp_orphan_price.setText(format_price(guess))
        self.inp_orphan_price.setFocus()
        self.lbl_orphan_guide.setText(
            f"已按盈亏反推：开仓价约 {format_price(guess)}（依据盈亏 {record['net_profit']:,.2f} ÷ "
            f"乘数 {record.get('multiplier', 0):.0f} ÷ 手数 {int(record.get('lots', 0) or 0)}）。\n"
            "该值仅供快速参考 —— 若此平仓同时对应多个开仓价位，结果会是加权近似值，"
            "请务必与交割单核对后再点「补录并缝合」。")

    def stitch_current_orphan(self):
        """孤儿单手工补录：开仓日期 + 开仓价 → 缝合为完整闭环"""
        idx = getattr(self, 'current_editing_idx', None)
        if idx is None or idx not in self.main_win.engine.df.index:
            return
        record = self.main_win.engine.df.loc[idx]
        if int(record.get('is_orphan', 0) or 0) != 1:
            return

        price_text = self.inp_orphan_price.text().strip().replace(',', '')
        try:
            price = float(price_text)
        except (TypeError, ValueError):
            price = 0.0
        if price <= 0:
            QMessageBox.warning(self, "请输入有效开仓价",
                                "请填写该笔平仓对应的开仓成交价（例如 6010.6）。")
            self.inp_orphan_price.setFocus()
            return

        qdate = self.inp_orphan_date.date()
        entry_dt = datetime(qdate.year(), qdate.month(), qdate.day())
        internal_id = record.get('internal_id')

        ok = self.main_win.engine.stitch_orphan_trade(internal_id, price, entry_time=entry_dt)
        if not ok:
            QMessageBox.critical(self, "缝合失败", "数据库更新失败，请重试。")
            return

        QMessageBox.information(
            self, "缝合成功",
            "已补录开仓信息，该笔交易已缝合为完整闭环。\n"
            "现在可显示开仓价与点数，并支持双点锚定回放。")
        self.orphan_bar.setVisible(False)
        self.current_editing_idx = None
        self.main_win.render_all_data()

    @staticmethod
    def _nearest_bar_index(df_slice: pd.DataFrame, anchor_ts) -> int:
        """返回切片内距离目标时间最近的一根 K 线位置索引"""
        return int((df_slice['date'] - anchor_ts).abs().idxmin())

    def _render_trade_playback(self, record):
        """
        v1.2 交易回放：双点区间锚定（完整闭环）/ 单点锚定降级。

        【完整闭环】(entry_time + entry_price + exit_price 齐全)：
          以开仓日与平仓日两根 K 线为双锚点，渲染：
            1. 开/平两条垂直虚线（蓝 / 橙）
            2. 开/平两条价格水平点线（蓝 / 橙）
            3. 两锚点之间半透明高亮带（绿 = 盈利、红 = 亏损）
            4. 平仓锚点叠加「多空箭头 + 点数 + 盈亏」标注

        【降级】(孤儿单 / v1.1 老数据缺少开仓信息)：
          诚实退回单点锚定，标题橙色标注"开仓信息缺失"，
          若存在平仓价则仍画一条平仓价水平线作为参考。

        数据缺口过大时明确给出提示，绝不硬凑坐标。
        """
        self.playback_chart.clear()
        symbol = str(record['symbol'])
        trade_time = pd.to_datetime(record['trade_time'])

        # 【数据防御】无有效交易时间则无法锚定，给出提示而不是渲染空图
        if pd.isna(trade_time):
            self.playback_chart.setTitle("⚠️ 该记录缺少交易时间，无法回放。", color="#FF9800", size="11pt")
            self.review_chart_tabs.setCurrentIndex(0)
            return

        is_orphan = int(record.get('is_orphan', 0) or 0) == 1
        entry_raw = record.get('entry_time')
        entry_time = pd.to_datetime(entry_raw) if (entry_raw is not None and pd.notna(entry_raw)) else None
        entry_price = record.get('entry_price')
        exit_price = record.get('exit_price')

        # 双点模式判定：非孤儿 + 真实开仓时刻 + 开/平仓价均有效
        def _valid_price(p):
            return p is not None and not pd.isna(p) and float(p) > 0

        dual = (not is_orphan and entry_time is not None and not pd.isna(entry_time)
                and _valid_price(entry_price) and _valid_price(exit_price))

        # ---- 数据窗口：包住开/平两个时间点并各自外扩上下文 ----
        ts_min, ts_max = trade_time, trade_time
        if dual:
            ts_min = min(entry_time, trade_time)
            ts_max = max(entry_time, trade_time)

        # 提取真实标的主体去数据湖寻址 (品种主体 RB -> 完整合约 RB2410)
        root_sym = extract_root_symbol(symbol)
        df_k = pd.DataFrame()
        for candidate in dict.fromkeys((root_sym, symbol)):
            if not candidate:
                continue
            # 【性能要点】先用轻量探针判断，避免为不存在的文件读取整个 Parquet
            if self.data_lake.exists("kline_daily", candidate):
                df_k = self.data_lake.load_data("kline_daily", candidate)
            if not df_k.empty:
                break

        if df_k.empty:
            self.playback_chart.setTitle(
                f"⚠️ 缺乏 {symbol} 的本地行情，请先前往 [市场行情] 页面进行云端同步！",
                color="#FF9800", size="11pt")
            # 自动跳回累积盈亏，防止用户盯着空图看
            self.review_chart_tabs.setCurrentIndex(0)
            return

        df_k['date'] = pd.to_datetime(df_k['date'])
        start_cut = ts_min - pd.Timedelta(days=PLAYBACK_CONTEXT_DAYS)
        end_cut = ts_max + pd.Timedelta(days=PLAYBACK_CONTEXT_DAYS)
        df_slice = df_k[(df_k['date'] >= start_cut) & (df_k['date'] <= end_cut)].copy()

        if df_slice.empty:
            self.playback_chart.setTitle(
                f"⚠️ {symbol} 缺少 {format_trade_time(ts_min)} 附近 {PLAYBACK_CONTEXT_DAYS} 天的K线数据，请先同步。",
                color="#FF9800", size="11pt")
            self.review_chart_tabs.setCurrentIndex(0)
            return

        df_slice = df_slice.reset_index(drop=True)

        # ---- 锚点定位（开仓日 / 平仓日最近 K 线）----
        exit_idx = self._nearest_bar_index(df_slice, trade_time)
        entry_idx = self._nearest_bar_index(df_slice, entry_time) if dual else None

        def _gap(ts, idx):
            return abs((df_slice['date'].iloc[idx] - ts).days)

        worst_gap = _gap(trade_time, exit_idx)
        if dual:
            worst_gap = max(worst_gap, _gap(entry_time, entry_idx))

        # 【诚实原则】任一时间点与最近 K 线距离过远 (节假日/停牌/数据断层) 时不硬凑坐标
        if worst_gap > MAX_ANCHOR_GAP_DAYS:
            self.playback_chart.setTitle(
                f"⚠️ {symbol} 本地数据距该交易日已达 {worst_gap} 天，无法可靠回放。\n"
                f"请核对交易日期或先前往 [市场行情] 补充同步。",
                color="#FF9800", size="11pt")
            self.review_chart_tabs.setCurrentIndex(0)
            return

        # ---- 基础图层：K 线 + MA20 ----
        df_slice = TAEngine.add_ma(df_slice, windows=(20,))
        x_data = list(range(len(df_slice)))
        k_data = [(i, row['open'], row['close'], row['low'], row['high'])
                  for i, row in df_slice.iterrows()]
        self.playback_chart.addItem(CandlestickItem(k_data))
        self.playback_chart.plot(x_data, df_slice['MA_20'],
                                 pen=pg.mkPen(color='#FF9800', width=1.5,
                                              style=Qt.PenStyle.DashLine))

        is_long = record['direction'] == 'LONG'
        pnl = float(record['net_profit'])
        marker_color = settings.COLOR_PROFIT if pnl >= 0 else settings.COLOR_LOSS

        if dual:
            # ================= 双点区间锚定 =================
            lo_x, hi_x = min(entry_idx, exit_idx), max(entry_idx, exit_idx)
            e_p = float(entry_price)
            x_p = float(exit_price)
            lo_y, hi_y = min(e_p, x_p), max(e_p, x_p)

            # 开~平区间高亮带（盈绿 / 亏红）
            brush_rgb = settings.RGB_PROFIT if pnl >= 0 else settings.RGB_LOSS
            region = pg.LinearRegionItem(
                values=[lo_x, hi_x], orientation='vertical',
                brush=pg.mkBrush(*brush_rgb, 30), pen=None, movable=False)
            region.setZValue(-100)
            self.playback_chart.addItem(region)

            # 垂直虚线：开仓(蓝) / 平仓(橙)
            self.playback_chart.addLine(x=entry_idx,
                                        pen=pg.mkPen(color='#1E88E5', width=1.4,
                                                     style=Qt.PenStyle.DashLine))
            self.playback_chart.addLine(x=exit_idx,
                                        pen=pg.mkPen(color='#FB8C00', width=1.4,
                                                     style=Qt.PenStyle.DashLine))
            # 水平价格线：开仓价(蓝) / 平仓价(橙)
            self.playback_chart.addLine(y=e_p,
                                        pen=pg.mkPen(color='#1E88E5', width=1,
                                                     style=Qt.PenStyle.DotLine))
            self.playback_chart.addLine(y=x_p,
                                        pen=pg.mkPen(color='#FB8C00', width=1,
                                                     style=Qt.PenStyle.DotLine))

            # 价格图例（右缘顶部）
            price_legend = pg.TextItem(
                f"开 {format_price(entry_price)}   平 {format_price(exit_price)}",
                color='#455A64', anchor=(1, 0))
            price_legend.setPos(len(df_slice) - 1, hi_y)
            self.playback_chart.addItem(price_legend)

            self.playback_chart.setTitle(
                f"🎯 {symbol} | 开仓 {self._format_leg_time(entry_time)} → 平仓 {self._display_time(record)}",
                color="#1976D2", size="12pt", bold=True)

            # 平仓锚点：方向箭头 + 点数 + 盈亏
            bar = df_slice.loc[exit_idx]
            anchor_y = bar['low'] * 0.97 if is_long else bar['high'] * 1.03
            marker = pg.ScatterPlotItem(
                x=[exit_idx], y=[anchor_y],
                symbol='t' if is_long else 'd', size=18,
                brush=pg.mkBrush(marker_color), pen='w')
            self.playback_chart.addItem(marker)

            pts = row_points(record)
            pts_txt = format_points(pts) if pts is not None else "—"
            annotation = pg.TextItem(
                f"{'做多' if is_long else '做空'}   {pts_txt} 点   ￥{pnl:+,.0f}",
                color=marker_color, anchor=(0.5, 1.2))
            annotation.setPos(exit_idx, anchor_y)
            self.playback_chart.addItem(annotation)

            # 自动聚焦开平区间，跨度不足时保留可读上下文
            span = hi_x - lo_x
            pad = max(10, span + 15)
            x_lo = max(0, lo_x - pad)
            x_hi = min(len(df_slice) - 1, hi_x + pad)
            self.playback_chart.setXRange(x_lo, x_hi, padding=0.05)
        else:
            # ================= 单点锚定（降级） =================
            self.playback_chart.addLine(x=exit_idx,
                                        pen=pg.mkPen(color='#90A4AE', width=1,
                                                     style=Qt.PenStyle.DashLine))
            title_txt = (f"🎯 {symbol} | 交易 {self._display_time(record)} "
                         f"(就近K线 {format_trade_time(df_slice['date'].iloc[exit_idx])})")
            degraded = is_orphan or not _valid_price(entry_price)
            self.playback_chart.setTitle(
                title_txt + ("　⚠️ 开仓信息缺失，单点回放" if degraded else ""),
                color="#F57C00" if degraded else "#1976D2", size="12pt", bold=True)

            bar = df_slice.loc[exit_idx]
            anchor_y = bar['low'] * 0.97 if is_long else bar['high'] * 1.03

            # 平仓价水平线参考（若有）
            if _valid_price(exit_price):
                self.playback_chart.addLine(
                    y=float(exit_price), pen=pg.mkPen(color='#FB8C00', width=1,
                                                      style=Qt.PenStyle.DotLine))

            marker = pg.ScatterPlotItem(
                x=[exit_idx], y=[anchor_y],
                symbol='t' if is_long else 'd', size=18,
                brush=pg.mkBrush(marker_color), pen='w')
            self.playback_chart.addItem(marker)

            note = "  ￥{:+,.0f}".format(pnl)
            if is_orphan:
                note = "  (待缝合) ￥{:+,.0f}".format(pnl)
            annotation = pg.TextItem(
                f"{'做多' if is_long else '做空'}{note}",
                color=marker_color, anchor=(0.5, 1.2))
            annotation.setPos(exit_idx, anchor_y)
            self.playback_chart.addItem(annotation)

            # 自动聚焦锚点附近窗口
            half = min(30, len(df_slice) // 2)
            lo = max(0, exit_idx - half)
            hi = min(len(df_slice) - 1, exit_idx + half)
            self.playback_chart.setXRange(lo, hi, padding=0.05)

        # ---- Y 范围：把价格参考线纳入可视区域，避免画在图外 ----
        y_lo = float(df_slice['low'].min())
        y_hi = float(df_slice['high'].max())
        for price_ref in (entry_price, exit_price):
            if _valid_price(price_ref):
                p = float(price_ref)
                y_lo, y_hi = min(y_lo, p), max(y_hi, p)
        span = (y_hi - y_lo) or 1.0
        self.playback_chart.setYRange(y_lo - span * 0.05, y_hi + span * 0.05)

        # 底部时间轴
        axis = self.playback_chart.getAxis('bottom')
        step = max(1, len(df_slice) // 8)
        ticks = [[(i, df_slice['date'].iloc[i].strftime('%m-%d'))
                  for i in range(0, len(df_slice), step)]]
        axis.setTicks(ticks)

        # 【交互体验】点击交易单即自动切到回放页
        self.review_chart_tabs.setCurrentWidget(self.playback_chart)

    def silent_update_strategy(self, *args):
        if getattr(self, 'current_editing_idx', None) is None: return
        new_st = self.cb_edit_strategy.currentText().strip()
        new_st = settings.DEFAULT_STRATEGY if new_st == "" else new_st
        
        if self.current_editing_idx not in self.main_win.engine.df.index: return
        old_st = str(self.main_win.engine.df.at[self.current_editing_idx, 'strategy_tag']).strip()
        
        if new_st == old_st: return
        self.main_win.engine.update_trade_strategy(self.current_editing_idx, new_st)
        
        if self.current_editing_idx in self.current_view_df.index:
            self.current_view_df.at[self.current_editing_idx, 'strategy_tag'] = new_st
            
        self.refresh_review_filters()
        
        original_style = "QComboBox { border: 1px solid #D1D9E6; border-radius: 4px; background: white; color: #212121; padding: 4px; }"
        self.cb_edit_strategy.setStyleSheet("QComboBox { border: 2px solid #4CAF50; border-radius: 4px; background: #E8F5E9; color: #2E7D32; padding: 4px; font-weight: bold; }")
        QTimer.singleShot(1000, lambda: self.cb_edit_strategy.setStyleSheet(original_style))

    def save_review_text(self):
        if getattr(self, 'current_editing_idx', None) is None: QMessageBox.warning(self, "提示", "请先选择一笔交易！"); return
        
        reason = self.txt_reason.toPlainText()
        reflection = self.txt_reflection.toPlainText()
        self._save_image_paths_to_df()
        
        paths = self.main_win.engine.df.at[self.current_editing_idx, 'screenshot_paths']
        self.main_win.engine.update_trade_review(self.current_editing_idx, reason, reflection, paths)
        
        if self.current_editing_idx in self.current_view_df.index:
            self.current_view_df.at[self.current_editing_idx, 'entry_reason'] = reason
            self.current_view_df.at[self.current_editing_idx, 'reflection'] = reflection
            self.current_view_df.at[self.current_editing_idx, 'screenshot_paths'] = paths
            
        self._render_calendar() 
        
        original_style = self.btn_save_review.styleSheet()
        self.btn_save_review.setText("✅ 保存成功")
        self.btn_save_review.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; border: none; border-radius: 6px; padding: 10px; font-weight: bold; }")
        
        def reset_btn():
            self.btn_save_review.setText("💾 保存复盘文字与截图")
            self.btn_save_review.setStyleSheet(original_style)
            
        QTimer.singleShot(1500, reset_btn)

    def _save_image_paths_to_df(self):
        """将画廊当前内容同步进内存 DataFrame (真正的落库时机由“保存复盘”按钮决定)"""
        if getattr(self, 'current_editing_idx', None) is None: return
        self.main_win.engine.df.at[self.current_editing_idx, 'screenshot_paths'] = self.gallery.get_paths()

    def delete_current_trade(self):
        if getattr(self, 'current_editing_idx', None) is None: return
        if QMessageBox.question(self, "危险操作", "永久删除此交易记录？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            if self.main_win.engine.delete_trade(self.current_editing_idx):
                self.current_editing_idx = None
                self.main_win.render_all_data()