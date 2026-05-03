# ui/views/review.py
import os
import shutil
import calendar
import pandas as pd
from datetime import datetime
import re

import pyqtgraph as pg
from pyqtgraph import QtGui
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QFrame, QStackedWidget, QTableWidget, 
                             QTableWidgetItem, QHeaderView, QGridLayout, 
                             QTabWidget, QDialog, QFileDialog, QComboBox, 
                             QMessageBox, QListWidget, QListWidgetItem, 
                             QTextEdit, QSplitter, QApplication)
from PyQt6.QtCore import Qt, QDate, QTimer
from PyQt6.QtGui import QColor, QFont, QKeySequence

from ui.widgets.custom_widgets import HoverDeleteListWidget, CandlestickItem
from config import settings

# 【新增】引入数据湖管家和原生指标引擎，准备缝合！
from data.market_db import DataLakeManager
from core.indicators import TAEngine

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
        self.review_yearly_widget = self._build_yearly_mode()
        
        self.review_stack.addWidget(self.review_monthly_widget) 
        self.review_stack.addWidget(self.review_yearly_widget)  
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
        
        self.review_duration_chart = pg.PlotWidget()
        self._apply_pokorny_style(self.review_duration_chart)
        self.review_duration_chart.setLabel('left', '单笔盈亏', color='#9E9E9E')
        self.review_duration_chart.setLabel('bottom', '时长(H)', color='#9E9E9E')

        # 【核心新增】：🎯 交易回放视图
        self.playback_chart = pg.PlotWidget()
        self._apply_pokorny_style(self.playback_chart)

        self.review_chart_tabs.addTab(self.review_pnl_chart, "📈 累计盈亏")
        self.review_chart_tabs.addTab(self.playback_chart, "🎯 交易回放") # 放到第二位，最高优先级体验
        self.review_chart_tabs.addTab(self.review_kline_chart, "📊 资金 K线")
        self.review_chart_tabs.addTab(self.review_duration_chart, "⏳ 时长分析")
        
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
        
        img_layout = QVBoxLayout(); img_header = QHBoxLayout(); lbl_img = QLabel("📸 画廊:"); lbl_img.setStyleSheet("font-weight: bold; color: #424242;"); img_header.addWidget(lbl_img); img_header.addStretch()
        self.btn_paste_img = QPushButton("📋 粘贴"); self.btn_import_img = QPushButton("📁 导入")
        for btn in [self.btn_paste_img, self.btn_import_img]: btn.setStyleSheet("QPushButton { background-color: #F5F5F5; color: #424242; border: 1px solid #E0E0E0; border-radius: 4px; padding: 4px 10px; font-weight: bold; } QPushButton:hover { background-color: #EEEEEE; }")
        self.btn_paste_img.clicked.connect(self.paste_image); self.btn_import_img.clicked.connect(self.import_image); img_header.addWidget(self.btn_paste_img); img_header.addWidget(self.btn_import_img); img_layout.addLayout(img_header)
        self.list_screenshots = HoverDeleteListWidget(self.delete_image, self); self.list_screenshots.itemDoubleClicked.connect(self.view_full_image); shortcut = QtGui.QShortcut(QKeySequence("Ctrl+V"), self.list_screenshots); shortcut.activated.connect(self.paste_image); img_layout.addWidget(self.list_screenshots); editor_layout.addLayout(img_layout)
        
        action_layout = QHBoxLayout(); self.btn_del_trade = QPushButton("🗑️ 删除此单"); self.btn_del_trade.setStyleSheet(f"QPushButton {{ background-color: white; color: {settings.COLOR_LOSS}; border: 1px solid {settings.COLOR_LOSS}; border-radius: 6px; padding: 10px; font-weight: bold; }} QPushButton:hover {{ background-color: #FFEBEE; }}"); self.btn_del_trade.clicked.connect(self.delete_current_trade)
        
        self.btn_save_review = QPushButton("💾 保存复盘文字与截图")
        self.btn_save_review.setStyleSheet("QPushButton { background-color: #1976D2; color: white; border: none; border-radius: 6px; padding: 10px; font-weight: bold; } QPushButton:hover { background-color: #1565C0; }")
        self.btn_save_review.clicked.connect(self.save_review_text)
        
        action_layout.addWidget(self.btn_del_trade); action_layout.addStretch(); action_layout.addWidget(self.btn_save_review); editor_layout.addLayout(action_layout)
        
        micro_splitter.addWidget(list_card); micro_splitter.addWidget(editor_card); micro_splitter.setSizes([350, 700])
        layout.addWidget(micro_splitter, 4)
        return widget

    def _build_yearly_mode(self):
        widget = QWidget()
        layout = QVBoxLayout(widget); layout.setContentsMargins(0, 0, 0, 0)
        
        cal_card = QFrame()
        cal_card.setStyleSheet("QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }")
        cal_layout = QVBoxLayout(cal_card)
        cal_title = QLabel("📅 年度各月盈亏概览")
        cal_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #424242; margin-bottom: 5px;")
        cal_layout.addWidget(cal_title)
        
        self.yearly_grid = QGridLayout()
        self.yearly_grid.setSpacing(10)
        self.month_cards = []
        
        for i in range(12):
            card = QLabel(f"{i+1}月\n无数据")
            card.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card.setStyleSheet("background: #F5F5F5; border-radius: 6px; font-size: 14px; font-weight:bold; color: #9E9E9E;")
            card.setMinimumSize(80, 80)
            self.month_cards.append(card)
            self.yearly_grid.addWidget(card, i // 6, i % 6)
            
        cal_layout.addLayout(self.yearly_grid)
        layout.addWidget(cal_card, 2)
        
        radar_splitter = QSplitter(Qt.Orientation.Horizontal)
        bar_card = QFrame()
        bar_card.setStyleSheet("QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }")
        bar_layout = QVBoxLayout(bar_card)
        
        self.yearly_bar_chart = pg.PlotWidget()
        self._apply_pokorny_style(self.yearly_bar_chart, title="🏆 年度策略利润贡献度")
        self.yearly_bar_chart.showGrid(x=False, y=False)
        bar_layout.addWidget(self.yearly_bar_chart)
        radar_splitter.addWidget(bar_card)
        
        curve_card = QFrame()
        curve_card.setStyleSheet("QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }")
        curve_layout = QVBoxLayout(curve_card)
        
        self.yearly_curve_chart = pg.PlotWidget()
        self._apply_pokorny_style(self.yearly_curve_chart, title="📈 年度资金净值曲线")
        curve_layout.addWidget(self.yearly_curve_chart)
        radar_splitter.addWidget(curve_card)
        
        radar_splitter.setSizes([500, 500])
        layout.addWidget(radar_splitter, 5)
        return widget

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
        if self.main_win.engine.df.empty: return
        
        self.cb_rev_account.blockSignals(True)
        self.cb_rev_strategy.blockSignals(True)
        self.cb_rev_symbol.blockSignals(True)
        self.cb_edit_strategy.blockSignals(True)
        
        self.cb_rev_account.clear(); self.cb_rev_account.addItem("全账户", "ALL")
        for acc in self.main_win.engine.df['account'].dropna().unique(): 
            self.cb_rev_account.addItem(str(acc), str(acc))
            
        self.cb_rev_strategy.clear(); self.cb_rev_strategy.addItem("全策略", "ALL")
        all_st = list(set(self.main_win.engine.strategies + self.main_win.engine.df['strategy_tag'].dropna().unique().tolist()))
        self.cb_edit_strategy.clear()
        for st in all_st: 
            self.cb_rev_strategy.addItem(str(st), str(st))
            self.cb_edit_strategy.addItem(str(st))
            
        self.cb_rev_symbol.clear()
        self.cb_rev_symbol.addItem("全品种", "ALL")
        roots = set()
        for sym in self.main_win.engine.df['symbol'].dropna().unique():
            match = re.match(r'^[A-Za-z]+', str(sym))
            if match:
                roots.add(match.group().upper())
            else:
                roots.add(str(sym).upper()) 
        
        for r in sorted(roots):
            self.cb_rev_symbol.addItem(r, r)
            
        self.cb_rev_account.blockSignals(False)
        self.cb_rev_strategy.blockSignals(False)
        self.cb_rev_symbol.blockSignals(False)
        self.cb_edit_strategy.blockSignals(False)

    def refresh_time_picker(self, is_year=False):
        self.cb_time_picker.blockSignals(True)
        self.cb_time_picker.clear()
        if self.main_win.engine.df.empty: 
            self.cb_time_picker.blockSignals(False)
            return
        
        dates = pd.to_datetime(self.main_win.engine.df['exit_time'])
        
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
        latest_date = pd.to_datetime(self.main_win.engine.df['exit_time']).dropna().max()
        if pd.notna(latest_date):
            self.current_review_date = latest_date.to_pydatetime()
            self.update_review_view()

    def update_review_view(self):
        self.lbl_selected_date.setText("当前视图已改变，请在日历重新选择日期...")
        self.day_trades_list.clear()
        self.txt_reason.clear()
        self.txt_reflection.clear()
        self.list_screenshots.clear()
        
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
            df['root_sym'] = df['symbol'].apply(lambda x: re.match(r'^[A-Za-z]+', str(x)).group().upper() if re.match(r'^[A-Za-z]+', str(x)) else str(x).upper())
            df = df[df['root_sym'] == sym_sel]
            
        dir_sel = self.cb_rev_direction.currentText()
        if dir_sel == "做多": df = df[df['direction'] == 'LONG']
        elif dir_sel == "做空": df = df[df['direction'] == 'SHORT']
            
        res_sel = self.cb_rev_result.currentText()
        if res_sel == "仅盈利": df = df[df['net_profit'] > 0]
        elif res_sel == "仅亏损": df = df[df['net_profit'] <= 0]
            
        df['exit_time'] = pd.to_datetime(df['exit_time']); df['entry_time'] = pd.to_datetime(df['entry_time'])
        
        y = self.current_review_date.year
        if self.is_yearly_view:
            self.current_view_df = df[df['exit_time'].dt.year == y].copy()
            self._render_yearly_view()
        else:
            m = self.current_review_date.month
            self.current_view_df = df[(df['exit_time'].dt.year == y) & (df['exit_time'].dt.month == m)].copy()
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
            df['day'] = df['exit_time'].dt.day
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
        self.review_pnl_chart.clear(); self.review_kline_chart.clear(); self.review_duration_chart.clear()
        df = self.current_view_df.copy()
        if df.empty: return
        df_sorted = df.sort_values(by='exit_time')
        equity_curve = [0.0] + df_sorted['net_profit'].cumsum().tolist(); x_data = list(range(len(equity_curve)))
        is_prof = equity_curve[-1] >= 0
        
        col = settings.RGB_PROFIT if is_prof else settings.RGB_LOSS
        fill = settings.RGB_PROFIT_FILL if is_prof else settings.RGB_LOSS_FILL
        self.review_pnl_chart.plot(x_data, equity_curve, pen=pg.mkPen(color=col, width=2), fillLevel=0, fillBrush=fill)
        
        df_sorted['day'] = df_sorted['exit_time'].dt.day; k_data = []; current_equity = 0.0
        for i, (day, group) in enumerate(df_sorted.groupby('day')):
            open_eq = current_equity; high_eq = current_equity; low_eq = current_equity
            for pnl in group['net_profit']:
                current_equity += pnl; high_eq = max(high_eq, current_equity); low_eq = min(low_eq, current_equity)
            k_data.append((i, open_eq, current_equity, low_eq, high_eq))
        if k_data:
            self.review_kline_chart.addItem(CandlestickItem(k_data)); axis = self.review_kline_chart.getAxis('bottom'); axis.setTicks([[(i, f"{day}日") for i, day in enumerate(df_sorted['day'].unique())]])
            
        durations = (df['exit_time'] - df['entry_time']).dt.total_seconds() / 3600.0; profits = df['net_profit'].values; spots = []
        
        for h, p in zip(durations, profits):
            h = max(h, 0)
            color = settings.RGB_PROFIT if p > 0 else settings.RGB_LOSS
            brush = pg.mkBrush(color=(color[0], color[1], color[2], 180)) 
            pen = pg.mkPen(color=(color[0], color[1], color[2], 255), width=1) 
            spots.append({'pos': (h, p), 'brush': brush, 'pen': pen, 'size': 10})
            
        self.review_duration_chart.addItem(pg.ScatterPlotItem(spots=spots))
        self.review_duration_chart.addLine(y=0, pen=pg.mkPen(color='#9E9E9E', style=Qt.PenStyle.DashLine))

    def on_calendar_day_clicked(self, row, col):
        item = self.review_calendar.item(row, col)
        if not item or not item.data(Qt.ItemDataRole.UserRole): return
        qdate = item.data(Qt.ItemDataRole.UserRole)
        self.lbl_selected_date.setText(f"👇 选定日期: {qdate.toString('yyyy年MM月dd日')}")
        self.lbl_selected_date.setStyleSheet("font-weight: bold; color: #1976D2; font-size: 14px;")
        
        self.day_trades_list.clear(); self.txt_reason.clear(); self.txt_reflection.clear(); self.list_screenshots.clear()
        
        self.lbl_trade_detail.setText("请在下方列表选择一笔特定交易...")
        self.lbl_trade_detail.setStyleSheet("font-size: 14px; color: #9E9E9E; border: none;")
        
        self.current_editing_idx = None
        day_df = self.current_view_df[self.current_view_df['exit_time'].dt.day == qdate.day()]
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
        
        pnl = record['net_profit']; duration = (record['exit_time'] - record['entry_time']).total_seconds() / 3600
        col_hex = settings.COLOR_PROFIT_TEXT if pnl > 0 else settings.COLOR_LOSS_TEXT
        
        self.lbl_trade_detail.setText(
            f"""<span style="font-size:16px; font-weight:bold; color:#212121;">{record['symbol']}</span> 
            <span style="color:#757575; font-size:12px;">&nbsp;|&nbsp; 进: {pd.to_datetime(record['entry_time']).strftime('%m-%d %H:%M')} 
            &nbsp;|&nbsp; 出: {pd.to_datetime(record['exit_time']).strftime('%m-%d %H:%M')} (持仓 {duration:.1f} h)</span><br>
            <span style="font-size:13px; color:#757575;">结果: </span>
            <b style="color:{col_hex}; font-size:16px;">￥{pnl:,.2f}</b>"""
        )
        
        self.txt_reason.setPlainText(str(record.get('entry_reason', ''))); self.txt_reflection.setPlainText(str(record.get('reflection', '')))
        
        self.cb_edit_strategy.blockSignals(True)
        self.cb_edit_strategy.setCurrentText(str(record.get('strategy_tag', settings.DEFAULT_STRATEGY)))
        self.cb_edit_strategy.blockSignals(False)
        
        self.list_screenshots.clear()
        paths_str = str(record.get('screenshot_paths', ''))
        if paths_str and paths_str != 'nan':
            for p in paths_str.split(';'):
                if os.path.exists(p): self.add_thumbnail(p)
                
        # ==========================================
        # 【终极杀器】触发 K 线回放渲染引擎！
        # ==========================================
        self._render_trade_playback(record)

    def _render_trade_playback(self, record):
        """核心缝合逻辑：将交易点位死死钉在历史 K 线上"""
        self.playback_chart.clear()
        symbol = str(record['symbol'])
        
        # 提取真实标的主体去数据湖寻址
        match = re.match(r'^[A-Za-z]+', symbol)
        root_sym = match.group().upper() if match else symbol.upper()
        
        df_k = self.data_lake.load_data("kline_daily", root_sym)
        if df_k.empty:
            df_k = self.data_lake.load_data("kline_daily", symbol) # 备用寻址
            
        if df_k.empty:
            self.playback_chart.setTitle(f"⚠️ 缺乏 {symbol} 的本地数据，请先前往 [市场行情] 页面进行云端同步！", color="#FF9800", size="11pt")
            # 自动跳回累积盈亏，防止用户盯着空图看
            self.review_chart_tabs.setCurrentIndex(0)
            return

        # 转换并切片数据 (提取进场前60天，出场后20天)
        df_k['date'] = pd.to_datetime(df_k['date'])
        entry_time = pd.to_datetime(record['entry_time'])
        exit_time = pd.to_datetime(record['exit_time'])
        
        start_cut = entry_time - pd.Timedelta(days=60)
        end_cut = exit_time + pd.Timedelta(days=20)
        
        df_slice = df_k[(df_k['date'] >= start_cut) & (df_k['date'] <= end_cut)].copy()
        if df_slice.empty: return
        
        df_slice.reset_index(drop=True, inplace=True)
        
        # 加上原生的 20 日均线，辅助看趋势
        df_slice = TAEngine.add_ma(df_slice, windows=(20,))
        x_data = list(range(len(df_slice)))
        
        # 找准进出场的绝对坐标 (X轴索引，Y轴价格)
        try:
            entry_idx = df_slice[df_slice['date'] <= entry_time].index[-1]
        except: entry_idx = 0
        try:
            exit_idx = df_slice[df_slice['date'] <= exit_time].index[-1]
        except: exit_idx = len(df_slice) - 1
        
        # 做多和做空的标识画法完全相反
        is_long = record['direction'] == 'LONG'
        entry_y = df_slice.loc[entry_idx, 'low'] * 0.98 if is_long else df_slice.loc[entry_idx, 'high'] * 1.02
        exit_y = df_slice.loc[exit_idx, 'high'] * 1.02 if is_long else df_slice.loc[exit_idx, 'low'] * 0.98
        
        # 画图：背景与基础 K 线
        self.playback_chart.setTitle(f"🎯 {symbol} | 交易回放", color="#1976D2", size="12pt", bold=True)
        k_data = [(i, row['open'], row['close'], row['low'], row['high']) for i, row in df_slice.iterrows()]
        self.playback_chart.addItem(CandlestickItem(k_data))
        self.playback_chart.plot(x_data, df_slice['MA_20'], pen=pg.mkPen(color='#FF9800', width=1.5, style=Qt.PenStyle.DashLine))

        # 画图：进出场连线 (亏损用红虚线，盈利用绿虚线)
        is_profit = record['net_profit'] > 0
        line_color = settings.COLOR_PROFIT if is_profit else settings.COLOR_LOSS
        self.playback_chart.plot([entry_idx, exit_idx], [entry_y, exit_y], pen=pg.mkPen(color=line_color, width=2, style=Qt.PenStyle.DotLine))
        
        # 画图：进出场箭头 (使用 ScatterPlot 里的三角形)
        entry_brush = pg.mkBrush(settings.COLOR_PROFIT) if is_long else pg.mkBrush(settings.COLOR_LOSS)
        exit_brush = pg.mkBrush(settings.COLOR_LOSS) if is_long else pg.mkBrush(settings.COLOR_PROFIT)
        
        # t = triangle up (买入), d = triangle down (卖出)
        entry_symbol = 't' if is_long else 'd'
        exit_symbol = 'd' if is_long else 't'
        
        entry_marker = pg.ScatterPlotItem(x=[entry_idx], y=[entry_y], symbol=entry_symbol, size=18, brush=entry_brush, pen='w')
        exit_marker = pg.ScatterPlotItem(x=[exit_idx], y=[exit_y], symbol=exit_symbol, size=18, brush=exit_brush, pen='w')
        
        self.playback_chart.addItem(entry_marker)
        self.playback_chart.addItem(exit_marker)
        
        # 格式化底部时间
        axis = self.playback_chart.getAxis('bottom')
        ticks = [[(i, df_slice['date'].iloc[i].strftime('%m-%d')) for i in range(0, len(df_slice), max(1, len(df_slice)//8))]]
        axis.setTicks(ticks)

        # 【极其聪明的交互体验】一旦点击交易单，图表区立刻自动切到“回放模式”！
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

    def _render_yearly_view(self):
        df = self.current_view_df
        monthly_stats = {}
        if not df.empty:
            df['month'] = df['exit_time'].dt.month
            for m, group in df.groupby('month'):
                monthly_stats[m] = group['net_profit'].sum()

        for i in range(12):
            m = i + 1
            card = self.month_cards[i]
            if m in monthly_stats:
                net = monthly_stats[m]
                if net > 0:
                    card.setStyleSheet(f"background: #E8F5E9; border-radius: 6px; font-size: 16px; font-weight:bold; color: {settings.COLOR_PROFIT_TEXT};")
                    card.setText(f"{m}月\n+{net:,.0f}")
                else:
                    card.setStyleSheet(f"background: #FFEBEE; border-radius: 6px; font-size: 16px; font-weight:bold; color: {settings.COLOR_LOSS_TEXT};")
                    card.setText(f"{m}月\n{net:,.0f}")
            else:
                card.setStyleSheet("background: #F5F5F5; border-radius: 6px; font-size: 14px; font-weight:bold; color: #9E9E9E;")
                card.setText(f"{m}月\n无交易")

        self.yearly_bar_chart.clear(); self.yearly_curve_chart.clear()
        if df.empty: return
        
        df_sorted = df.sort_values(by='exit_time')
        equity_curve = [0.0] + df_sorted['net_profit'].cumsum().tolist(); x_data = list(range(len(equity_curve)))
        is_prof = equity_curve[-1] >= 0
        
        col = settings.RGB_PROFIT if is_prof else settings.RGB_LOSS
        fill = settings.RGB_PROFIT_FILL if is_prof else settings.RGB_LOSS_FILL
        self.yearly_curve_chart.plot(x_data, equity_curve, pen=pg.mkPen(color=col, width=3), fillLevel=0, fillBrush=fill)
        
        strategy_pnl = df.groupby('strategy_tag')['net_profit'].sum().sort_values()
        y_pos = list(range(len(strategy_pnl)))
        x_vals = strategy_pnl.values.tolist()
        
        brushes = [pg.mkBrush(settings.COLOR_PROFIT) if x > 0 else pg.mkBrush(settings.COLOR_LOSS) for x in x_vals]
        pens = [pg.mkPen(settings.COLOR_PROFIT) if x > 0 else pg.mkPen(settings.COLOR_LOSS) for x in x_vals]
        bar_item = pg.BarGraphItem(x0=0, y=y_pos, width=x_vals, height=0.5, brushes=brushes, pens=pens)
        self.yearly_bar_chart.addItem(bar_item)
        
        ax = self.yearly_bar_chart.getAxis('left')
        ticks = [list(zip(y_pos, strategy_pnl.index.tolist()))]
        ax.setTicks(ticks)
        self.yearly_bar_chart.addLine(x=0, pen=pg.mkPen(color='#9E9E9E'))

    def paste_image(self):
        if getattr(self, 'current_editing_idx', None) is None: QMessageBox.warning(self, "提示", "请先选择交易！"); return
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()
        if mime_data.hasImage():
            image = clipboard.image()
            internal_id = str(self.main_win.engine.df.at[self.current_editing_idx, 'internal_id'])
            timestamp = int(datetime.now().timestamp() * 1000)
            filename = os.path.join(settings.SCREENSHOT_DIR, f"{internal_id}_{timestamp}.png")
            image.save(filename)
            self.add_thumbnail(filename)
            self._save_image_paths_to_df() 
        else: QMessageBox.warning(self, "提示", "剪贴板无图片！")

    def import_image(self):
        if getattr(self, 'current_editing_idx', None) is None: return
        file_paths, _ = QFileDialog.getOpenFileNames(self, "选择截图", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        internal_id = str(self.main_win.engine.df.at[self.current_editing_idx, 'internal_id'])
        for path in file_paths:
            timestamp = int(datetime.now().timestamp() * 1000); ext = path.split('.')[-1]
            filename = os.path.join(settings.SCREENSHOT_DIR, f"{internal_id}_{timestamp}.{ext}")
            shutil.copy(path, filename)
            self.add_thumbnail(filename)
        self._save_image_paths_to_df()

    def add_thumbnail(self, filepath):
        icon = QtGui.QIcon(filepath)
        item = QListWidgetItem(icon, "")
        item.setData(Qt.ItemDataRole.UserRole, filepath)
        self.list_screenshots.addItem(item)

    def delete_image(self, item, filepath):
        reply = QMessageBox.question(self, "删除截图", "确定要永久删除截图吗？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                if os.path.exists(filepath): os.remove(filepath)
            except Exception as e: QMessageBox.warning(self, "错误", str(e))
            row = self.list_screenshots.row(item)
            self.list_screenshots.takeItem(row)
            self._save_image_paths_to_df()

    def _save_image_paths_to_df(self):
        if getattr(self, 'current_editing_idx', None) is None: return
        paths = [self.list_screenshots.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list_screenshots.count())]
        self.main_win.engine.df.at[self.current_editing_idx, 'screenshot_paths'] = ";".join(paths)

    def view_full_image(self, item):
        filepath = item.data(Qt.ItemDataRole.UserRole) 
        if not os.path.exists(filepath): return
        dialog = QDialog(self)
        dialog.setWindowTitle("查看截图")
        dialog.setStyleSheet("QDialog { background-color: #212121; }")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel()
        pixmap = QtGui.QPixmap(filepath)
        screen = QApplication.primaryScreen().geometry()
        if pixmap.width() > screen.width() * 0.8 or pixmap.height() > screen.height() * 0.8:
            pixmap = pixmap.scaled(int(screen.width() * 0.8), int(screen.height() * 0.8), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        label.setPixmap(pixmap)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        dialog.exec()

    def delete_current_trade(self):
        if getattr(self, 'current_editing_idx', None) is None: return
        if QMessageBox.question(self, "危险操作", "永久删除此交易记录？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            if self.main_win.engine.delete_trade(self.current_editing_idx):
                self.current_editing_idx = None
                self.main_win.render_all_data()