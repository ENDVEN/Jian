# ui/views/review.py
import calendar
import pandas as pd
from datetime import datetime

import pyqtgraph as pg
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QFrame, QStackedWidget, QTableWidget, 
                             QTableWidgetItem, QHeaderView,
                             QTabWidget, QComboBox, QMessageBox, QListWidget, 
                             QListWidgetItem, QTextEdit, QSplitter)
from PyQt6.QtCore import Qt, QDate, QTimer
from PyQt6.QtGui import QColor, QFont

from ui.widgets.custom_widgets import CandlestickItem
from ui.widgets.screenshot_gallery import ScreenshotGallery
from ui.widgets.yearly_review import YearlyReviewPanel
from config import settings
from core.utils import extract_root_symbol, format_trade_time
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
        
        self._setup_ui()

    def _apply_pokorny_style(self, chart: pg.PlotWidget, title: str = ""):
        chart.setBackground('w')
        if title:
            chart.setTitle(title, color="#424242", size="11pt", bold=True)
            
        plot_item = chart.getPlotItem()
        plot_item.hideAxis('top')
        plot_item.hideAxis('right')
        chart.showGrid(x=True, y=True, alpha=0.15)
        
        pen = pg.mkPen(color='#E0E0E0', width=1)
        text_pen = pg.mkPen(color='#9E9E9E')
        
        for axis_name in ['left', 'bottom']:
            axis = plot_item.getAxis(axis_name)
            axis.setPen(pen)
            axis.setTextPen(text_pen)
            
        plot_item.getViewBox().setContentsMargins(15, 15, 15, 15)

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
        
        self.cb_time_picker = QComboBox()
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
        self.cb_rev_account = QComboBox()
        self.cb_rev_account.currentIndexChanged.connect(self.update_review_view)
        top_bar_2.addWidget(self.cb_rev_account)
        
        top_bar_2.addSpacing(15)
        top_bar_2.addWidget(QLabel("策略:"))
        self.cb_rev_strategy = QComboBox()
        self.cb_rev_strategy.currentIndexChanged.connect(self.update_review_view)
        top_bar_2.addWidget(self.cb_rev_strategy)
        
        self.btn_manage_str = QPushButton("🏷️管理")
        self.btn_manage_str.setStyleSheet("QPushButton { border: none; color: #1976D2; font-weight:bold; font-size:13px;} QPushButton:hover { text-decoration: underline; }")
        self.btn_manage_str.clicked.connect(self.main_win.manage_strategies)
        top_bar_2.addWidget(self.btn_manage_str)

        top_bar_2.addSpacing(15)
        top_bar_2.addWidget(QLabel("品种主体:"))
        self.cb_rev_symbol = QComboBox()
        self.cb_rev_symbol.currentIndexChanged.connect(self.update_review_view)
        top_bar_2.addWidget(self.cb_rev_symbol)

        top_bar_2.addSpacing(15)
        top_bar_2.addWidget(QLabel("方向:"))
        self.cb_rev_direction = QComboBox()
        self.cb_rev_direction.addItems(["全部", "做多", "做空"])
        self.cb_rev_direction.currentIndexChanged.connect(self.update_review_view)
        top_bar_2.addWidget(self.cb_rev_direction)

        top_bar_2.addSpacing(15)
        top_bar_2.addWidget(QLabel("结果:"))
        self.cb_rev_result = QComboBox()
        self.cb_rev_result.addItems(["全部", "仅盈利", "仅亏损"])
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

        self.review_chart_tabs.addTab(self.review_pnl_chart, "📈 累计盈亏")
        self.review_chart_tabs.addTab(self.playback_chart, "🎯 交易回放")
        self.review_chart_tabs.addTab(self.review_kline_chart, "📊 资金 K线")
        # NOTE(v1.1): "时长分析"依赖开/平仓双时间，交割单不再提供该数据，已整体下线
        
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
        self.editor_header_card.setFixedHeight(75)
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
        
        self.cb_edit_strategy = QComboBox()
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
        
        self.current_editing_idx = None
        
        if self.main_win.engine.df.empty: return
        
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
        if res_sel == "仅盈利": df = df[df['net_profit'] > 0]
        elif res_sel == "仅亏损": df = df[df['net_profit'] <= 0]
            
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

    def _render_calendar(self):
        self.review_calendar.clearContents()
        y, m = self.current_review_date.year, self.current_review_date.month
        cal = calendar.monthcalendar(y, m)
        df = self.current_view_df
        daily_stats = {}
        max_abs_net = 0.0
        
        if not df.empty:
            df['day'] = df['trade_time'].dt.day
            daily_sums = df.groupby('day')['net_profit'].sum()
            if not daily_sums.empty:
                max_abs_net = daily_sums.abs().max()
                if max_abs_net == 0: max_abs_net = 1.0  
            
            for day, group in df.groupby('day'):
                daily_stats[day] = {
                    'net': group['net_profit'].sum(), 
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

        df_sorted = df.sort_values(by='trade_time')
        equity_curve = [0.0] + df_sorted['net_profit'].cumsum().tolist()
        x_data = list(range(len(equity_curve)))
        is_prof = equity_curve[-1] >= 0

        col = settings.RGB_PROFIT if is_prof else settings.RGB_LOSS
        fill = settings.RGB_PROFIT_FILL if is_prof else settings.RGB_LOSS_FILL
        self.review_pnl_chart.plot(x_data, equity_curve, pen=pg.mkPen(color=col, width=2),
                                   fillLevel=0, fillBrush=fill)

        # 资金 K 线：把同一天的多笔交易聚合成一根蜡烛 (当日权益的开高低收)
        df_sorted['day'] = df_sorted['trade_time'].dt.day
        k_data, day_labels = [], []
        current_equity = 0.0
        for i, (day, group) in enumerate(df_sorted.groupby('day')):
            open_eq = current_equity
            high_eq = current_equity
            low_eq = current_equity
            for pnl in group['net_profit']:
                current_equity += pnl
                high_eq = max(high_eq, current_equity)
                low_eq = min(low_eq, current_equity)
            k_data.append((i, open_eq, current_equity, low_eq, high_eq))
            day_labels.append(f"{day}日")

        if k_data:
            self.review_kline_chart.addItem(CandlestickItem(k_data))
            axis = self.review_kline_chart.getAxis('bottom')
            axis.setTicks([list(enumerate(day_labels))])

    def on_calendar_day_clicked(self, row, col):
        item = self.review_calendar.item(row, col)
        if not item or not item.data(Qt.ItemDataRole.UserRole): return
        qdate = item.data(Qt.ItemDataRole.UserRole)
        self.lbl_selected_date.setText(f"👇 选定日期: {qdate.toString('yyyy年MM月dd日')}")
        self.lbl_selected_date.setStyleSheet("font-weight: bold; color: #1976D2; font-size: 14px;")
        
        self.day_trades_list.clear(); self.txt_reason.clear(); self.txt_reflection.clear(); self.gallery.clear()
        
        self.lbl_trade_detail.setText("请在下方列表选择一笔特定交易...")
        self.lbl_trade_detail.setStyleSheet("font-size: 14px; color: #9E9E9E; border: none;")
        
        self.current_editing_idx = None
        day_df = self.current_view_df[self.current_view_df['trade_time'].dt.day == qdate.day()]
        for idx, record in day_df.iterrows():
            pnl, sym = record['net_profit'], record['symbol']
            txt = f"{sym} | ￥{'+' if pnl>0 else ''}{pnl:,.2f}" + (" 📝" if pd.notna(record.get('reflection')) and str(record.get('reflection')).strip()!="" else "")
            list_item = QListWidgetItem(txt)
            list_item.setData(Qt.ItemDataRole.UserRole, idx)
            list_item.setForeground(QColor(settings.COLOR_PROFIT_TEXT) if pnl > 0 else QColor(settings.COLOR_LOSS_TEXT))
            self.day_trades_list.addItem(list_item)

    def on_review_trade_selected(self, current, previous):
        if not current: return
        df_idx = current.data(Qt.ItemDataRole.UserRole)
        if df_idx not in self.main_win.engine.df.index: return
        
        record = self.main_win.engine.df.loc[df_idx]
        self.current_editing_idx = df_idx
        
        pnl = record['net_profit']
        col_hex = settings.COLOR_PROFIT_TEXT if pnl > 0 else settings.COLOR_LOSS_TEXT
        trade_time = format_trade_time(record.get('trade_time'))
        
        self.lbl_trade_detail.setText(
            f"""<span style="font-size:16px; font-weight:bold; color:#212121;">{record['symbol']}</span> 
            <span style="color:#757575; font-size:12px;">&nbsp;|&nbsp; 交易时间: {trade_time}</span><br>
            <span style="font-size:13px; color:#757575;">结果: </span>
            <b style="color:{col_hex}; font-size:16px;">￥{pnl:,.2f}</b>"""
        )
        
        self.txt_reason.setPlainText(str(record.get('entry_reason', ''))); self.txt_reflection.setPlainText(str(record.get('reflection', '')))
        
        self.cb_edit_strategy.blockSignals(True)
        self.cb_edit_strategy.setCurrentText(str(record.get('strategy_tag', settings.DEFAULT_STRATEGY)))
        self.cb_edit_strategy.blockSignals(False)
        
        # 绑定归属交易后重建画廊，后续粘贴/导入的截图都会挂到这笔交易名下
        self.gallery.set_owner(record.get('internal_id'))
        self.gallery.set_paths(record.get('screenshot_paths', ''))
                
        # ==========================================
        # 【终极杀器】触发 K 线回放渲染引擎！
        # ==========================================
        self._render_trade_playback(record)

    @staticmethod
    def _nearest_bar_index(df_slice: pd.DataFrame, anchor_ts) -> int:
        """返回切片内距离目标时间最近的一根 K 线位置索引"""
        return int((df_slice['date'] - anchor_ts).abs().idxmin())

    def _render_trade_playback(self, record):
        """
        v1.1 交易回放：单时间点锚定式展示。

        交割单只提供唯一的"交易时间"，现实中不存在可区分的开/平仓区间，
        因此回放不再虚构进场/离场两个坐标点，而是：
          1. 截取交易时间前后 PLAYBACK_CONTEXT_DAYS 天的本地 K 线
          2. 以时间上最近的 K 线为锚点画一条垂直虚线
          3. 在该 K 线上叠加「多/空箭头 + 盈亏」标记，颜色即代表盈/亏
          4. 数据缺口过大时明确给出提示，绝不硬凑错误坐标
        """
        self.playback_chart.clear()
        symbol = str(record['symbol'])
        trade_time = pd.to_datetime(record['trade_time'])

        # 【数据防御】无有效交易时间则无法锚定，给出提示而不是渲染空图
        if pd.isna(trade_time):
            self.playback_chart.setTitle("⚠️ 该记录缺少交易时间，无法回放。", color="#FF9800", size="11pt")
            self.review_chart_tabs.setCurrentIndex(0)
            return

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

        # 以交易时间为圆心截取上下文窗口
        df_k['date'] = pd.to_datetime(df_k['date'])
        start_cut = trade_time - pd.Timedelta(days=PLAYBACK_CONTEXT_DAYS)
        end_cut = trade_time + pd.Timedelta(days=PLAYBACK_CONTEXT_DAYS)
        df_slice = df_k[(df_k['date'] >= start_cut) & (df_k['date'] <= end_cut)].copy()

        if df_slice.empty:
            self.playback_chart.setTitle(
                f"⚠️ {symbol} 缺少 {format_trade_time(trade_time)} 附近 {PLAYBACK_CONTEXT_DAYS} 天的K线数据，请先同步。",
                color="#FF9800", size="11pt")
            self.review_chart_tabs.setCurrentIndex(0)
            return

        df_slice = df_slice.reset_index(drop=True)

        # 找到离交易时间最近的 K 线作为锚点
        anchor_idx = self._nearest_bar_index(df_slice, trade_time)
        nearest_date = df_slice['date'].iloc[anchor_idx]
        gap_days = abs((nearest_date - trade_time).days)

        # 【诚实原则】最近 K 线距离过远 (节假日/停牌/数据断层) 时不硬凑坐标，
        # 明确提示用户核对日期或补充同步。
        if gap_days > MAX_ANCHOR_GAP_DAYS:
            self.playback_chart.setTitle(
                f"⚠️ {symbol} 本地数据距该交易日已达 {gap_days} 天，无法可靠回放。\n"
                f"请核对交易日期或先前往 [市场行情] 补充同步。",
                color="#FF9800", size="11pt")
            self.review_chart_tabs.setCurrentIndex(0)
            return

        # 辅助趋势参考：20 日均线
        df_slice = TAEngine.add_ma(df_slice, windows=(20,))
        x_data = list(range(len(df_slice)))

        title = (f"🎯 {symbol} | 交易 {format_trade_time(trade_time)} "
                 f"(就近K线 {format_trade_time(nearest_date)})")
        self.playback_chart.setTitle(title, color="#1976D2", size="12pt", bold=True)

        k_data = [(i, row['open'], row['close'], row['low'], row['high']) for i, row in df_slice.iterrows()]
        self.playback_chart.addItem(CandlestickItem(k_data))
        self.playback_chart.plot(x_data, df_slice['MA_20'],
                                 pen=pg.mkPen(color='#FF9800', width=1.5, style=Qt.PenStyle.DashLine))

        # 锚点垂直虚线，标明该笔交易落在哪根 K 线上
        self.playback_chart.addLine(x=anchor_idx,
                                    pen=pg.mkPen(color='#90A4AE', width=1, style=Qt.PenStyle.DashLine))

        # 标记语义：箭头方向 = 多空；颜色 = 盈亏 (绿盈红亏)
        is_long = record['direction'] == 'LONG'
        is_profit = record['net_profit'] > 0
        marker_color = settings.COLOR_PROFIT if is_profit else settings.COLOR_LOSS

        bar = df_slice.loc[anchor_idx]
        anchor_y = bar['low'] * 0.98 if is_long else bar['high'] * 1.02

        marker = pg.ScatterPlotItem(
            x=[anchor_idx], y=[anchor_y],
            symbol='t' if is_long else 'd',  # t=向上箭头(做多), d=向下箭头(做空)
            size=18, brush=pg.mkBrush(marker_color), pen='w')
        self.playback_chart.addItem(marker)

        # 盈亏文字标注
        annotation = pg.TextItem(
            f"{'做多' if is_long else '做空'}  ￥{record['net_profit']:+,.0f}",
            color=marker_color, anchor=(0.5, 1.2))
        annotation.setPos(anchor_idx, anchor_y)
        self.playback_chart.addItem(annotation)

        # 底部时间轴
        axis = self.playback_chart.getAxis('bottom')
        step = max(1, len(df_slice) // 8)
        ticks = [[(i, df_slice['date'].iloc[i].strftime('%m-%d')) for i in range(0, len(df_slice), step)]]
        axis.setTicks(ticks)

        # 自动聚焦锚点附近窗口，避免用户在大尺度下找不到那根 K 线
        half = min(30, len(df_slice) // 2)
        lo = max(0, anchor_idx - half)
        hi = min(len(df_slice) - 1, anchor_idx + half)
        self.playback_chart.setXRange(lo, hi, padding=0.05)

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