# ui/views/review.py
import os
import shutil
import calendar
import pandas as pd
from datetime import datetime
import pyqtgraph as pg
from pyqtgraph import QtGui
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QFrame, QStackedWidget, QTableWidget, 
                             QTableWidgetItem, QHeaderView, QGridLayout, 
                             QTabWidget, QDialog, QFileDialog, QComboBox, 
                             QMessageBox, QListWidget, QListWidgetItem, 
                             QTextEdit, QSplitter, QApplication)
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QColor, QFont, QKeySequence

from ui.widgets.custom_widgets import HoverDeleteListWidget, CandlestickItem
from config import settings

class ReviewView(QWidget):
    def __init__(self, main_win):
        super().__init__()
        self.main_win = main_win  
        self.current_review_date = datetime.now()
        self.is_yearly_view = False
        self.current_view_df = pd.DataFrame()
        self.current_editing_idx = None
        
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)
        
        top_bar = QHBoxLayout()
        title = QLabel("复盘工作台")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #212121;")
        top_bar.addWidget(title)
        top_bar.addSpacing(30)

        top_bar.addWidget(QLabel("账户:"))
        self.cb_rev_account = QComboBox()
        self.cb_rev_account.currentIndexChanged.connect(self.update_review_view)
        top_bar.addWidget(self.cb_rev_account)
        top_bar.addSpacing(15)
        
        top_bar.addWidget(QLabel("策略:"))
        self.cb_rev_strategy = QComboBox()
        self.cb_rev_strategy.currentIndexChanged.connect(self.update_review_view)
        top_bar.addWidget(self.cb_rev_strategy)
        
        self.btn_manage_str = QPushButton("🏷️ 管理策略")
        self.btn_manage_str.setStyleSheet("QPushButton { border: none; color: #1976D2; font-weight:bold; font-size:14px; margin-left: 5px;} QPushButton:hover { text-decoration: underline; }")
        self.btn_manage_str.clicked.connect(self.main_win.manage_strategies)
        top_bar.addWidget(self.btn_manage_str)
        top_bar.addStretch()

        self.btn_mode_toggle = QPushButton("切换年视图 📅")
        self.btn_mode_toggle.setStyleSheet("QPushButton { font-size: 14px; font-weight: bold; color: #FF9800; padding: 5px 15px; border: 1px solid #FFCC80; border-radius: 6px; background: #FFF3E0; margin-right: 15px;} QPushButton:hover { background: #FFE0B2; }")
        self.btn_mode_toggle.clicked.connect(self.toggle_review_mode)
        top_bar.addWidget(self.btn_mode_toggle)

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

        nav_layout.addWidget(self.btn_prev_time)
        nav_layout.addWidget(self.cb_time_picker)
        nav_layout.addWidget(self.btn_next_time)
        top_bar.addLayout(nav_layout)
        layout.addLayout(top_bar)

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
        cal_card = QFrame(); cal_card.setStyleSheet("QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }"); cal_layout = QVBoxLayout(cal_card); cal_layout.setContentsMargins(10, 10, 10, 10)
        self.review_calendar = QTableWidget(6, 7); self.review_calendar.setHorizontalHeaderLabels(["一", "二", "三", "四", "五", "六", "日"]); self.review_calendar.verticalHeader().setVisible(False)
        self.review_calendar.setStyleSheet("QTableWidget { border: none; background: white; gridline-color: transparent; } QHeaderView::section { background: white; color: #9E9E9E; border: none; font-weight: bold; font-size: 13px; } QTableWidget::item { border-radius: 6px; margin: 2px; } QTableWidget::item:selected { border: 2px solid #1976D2; background: transparent; color: black;}")
        self.review_calendar.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); self.review_calendar.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); self.review_calendar.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.review_calendar.setFocusPolicy(Qt.FocusPolicy.NoFocus); self.review_calendar.setSelectionMode(QTableWidget.SelectionMode.SingleSelection); self.review_calendar.cellClicked.connect(self.on_calendar_day_clicked)
        cal_layout.addWidget(self.review_calendar)
        
        chart_card = QFrame(); chart_card.setStyleSheet("QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }"); chart_layout = QVBoxLayout(chart_card); chart_layout.setContentsMargins(5, 5, 5, 5)
        self.review_chart_tabs = QTabWidget(); self.review_chart_tabs.setStyleSheet("QTabWidget::pane { border: none; } QTabBar::tab { background: transparent; color: #757575; padding: 8px 15px; font-weight: bold; font-size: 14px;} QTabBar::tab:selected { color: #1976D2; border-bottom: 3px solid #1976D2; }")
        self.review_pnl_chart = pg.PlotWidget(); self.review_pnl_chart.setBackground('w'); self.review_pnl_chart.showGrid(x=True, y=True, alpha=0.2)
        self.review_kline_chart = pg.PlotWidget(); self.review_kline_chart.setBackground('w'); self.review_kline_chart.showGrid(x=True, y=True, alpha=0.2) 
        self.review_duration_chart = pg.PlotWidget(); self.review_duration_chart.setBackground('w'); self.review_duration_chart.showGrid(x=True, y=True, alpha=0.3); self.review_duration_chart.setLabel('left', '单笔盈亏'); self.review_duration_chart.setLabel('bottom', '时长(H)')
        self.review_chart_tabs.addTab(self.review_pnl_chart, "📈 累计盈亏"); self.review_chart_tabs.addTab(self.review_kline_chart, "📊 资金 K线"); self.review_chart_tabs.addTab(self.review_duration_chart, "⏳ 时长分析")
        chart_layout.addWidget(self.review_chart_tabs)
        macro_splitter.addWidget(cal_card); macro_splitter.addWidget(chart_card); macro_splitter.setSizes([450, 600])
        layout.addWidget(macro_splitter, 5)

        micro_splitter = QSplitter(Qt.Orientation.Horizontal)
        list_card = QFrame(); list_card.setStyleSheet("QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }"); list_layout = QVBoxLayout(list_card); self.lbl_selected_date = QLabel("选定日期: 无"); self.lbl_selected_date.setStyleSheet("font-weight: bold; color: #757575; font-size: 14px;")
        self.day_trades_list = QListWidget(); self.day_trades_list.setStyleSheet("QListWidget { border: none; font-size: 13px; } QListWidget::item { padding: 12px; border-bottom: 1px solid #F5F5F5; } QListWidget::item:selected { background: #E3F2FD; color: #1976D2; border-radius: 4px;}")
        self.day_trades_list.currentItemChanged.connect(self.on_review_trade_selected)
        list_layout.addWidget(self.lbl_selected_date); list_layout.addWidget(self.day_trades_list)
        
        editor_card = QFrame(); editor_card.setStyleSheet("QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }"); editor_layout = QVBoxLayout(editor_card)
        header_layout = QHBoxLayout(); self.lbl_trade_detail = QLabel("请选择交易..."); self.lbl_trade_detail.setStyleSheet("font-size: 14px; font-weight: bold; color: #424242;"); header_layout.addWidget(self.lbl_trade_detail); header_layout.addStretch()
        header_layout.addWidget(QLabel("分类至: ")); self.cb_edit_strategy = QComboBox(); self.cb_edit_strategy.setEditable(True); self.cb_edit_strategy.setMinimumWidth(150); self.cb_edit_strategy.setStyleSheet("QComboBox { border: 1px solid #1976D2; border-radius: 4px; background: #F3E5F5; }"); self.cb_edit_strategy.lineEdit().editingFinished.connect(self.silent_update_strategy); self.cb_edit_strategy.activated.connect(self.silent_update_strategy); header_layout.addWidget(self.cb_edit_strategy)
        editor_layout.addLayout(header_layout)

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
        self.btn_save_review = QPushButton("💾 保存复盘文字与截图"); self.btn_save_review.setStyleSheet("QPushButton { background-color: #1976D2; color: white; border: none; border-radius: 6px; padding: 10px; font-weight: bold; } QPushButton:hover { background-color: #1565C0; }"); self.btn_save_review.clicked.connect(self.save_review_text)
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
        self.yearly_bar_chart = pg.PlotWidget(title="🏆 年度策略利润贡献度")
        self.yearly_bar_chart.setBackground('w'); self.yearly_bar_chart.showGrid(x=False, y=True, alpha=0.2)
        bar_layout.addWidget(self.yearly_bar_chart)
        radar_splitter.addWidget(bar_card)
        
        curve_card = QFrame()
        curve_card.setStyleSheet("QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }")
        curve_layout = QVBoxLayout(curve_card)
        self.yearly_curve_chart = pg.PlotWidget(title="📈 年度资金净值曲线")
        self.yearly_curve_chart.setBackground('w'); self.yearly_curve_chart.showGrid(x=True, y=True, alpha=0.2)
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
            self.refresh_time_picker(is_year=True)
        else:
            self.btn_mode_toggle.setText("切换年视图 📅")
            self.btn_mode_toggle.setStyleSheet("QPushButton { font-size: 14px; font-weight: bold; color: #FF9800; padding: 5px 15px; border: 1px solid #FFCC80; border-radius: 6px; background: #FFF3E0; margin-right: 15px;} QPushButton:hover { background: #FFE0B2; }")
            self.review_stack.setCurrentIndex(0) 
            self.refresh_time_picker(is_year=False)
            
        self.update_review_view()

    def refresh_review_filters(self):
        if self.main_win.engine.df.empty: return
        self.cb_rev_account.blockSignals(True); self.cb_rev_strategy.blockSignals(True); self.cb_edit_strategy.blockSignals(True)
        
        self.cb_rev_account.clear(); self.cb_rev_account.addItem("全账户汇总", "ALL")
        for acc in self.main_win.engine.df['account'].dropna().unique(): 
            self.cb_rev_account.addItem(str(acc), str(acc))
            
        self.cb_rev_strategy.clear(); self.cb_rev_strategy.addItem("全策略分类", "ALL")
        all_st = list(set(self.main_win.engine.strategies + self.main_win.engine.df['strategy_tag'].dropna().unique().tolist()))
        self.cb_edit_strategy.clear()
        for st in all_st: 
            self.cb_rev_strategy.addItem(str(st), str(st))
            self.cb_edit_strategy.addItem(str(st))
            
        self.refresh_time_picker(self.is_yearly_view)
        
        self.cb_rev_account.blockSignals(False); self.cb_rev_strategy.blockSignals(False); self.cb_edit_strategy.blockSignals(False)

    def refresh_time_picker(self, is_year=False):
        self.cb_time_picker.blockSignals(True)
        self.cb_time_picker.clear()
        if self.main_win.engine.df.empty: return
        
        dates = pd.to_datetime(self.main_win.engine.df['exit_time'])
        if is_year:
            years = sorted(dates.dt.year.unique().tolist(), reverse=True)
            for y in years:
                self.cb_time_picker.addItem(f"{y}年", datetime(y, 1, 1))
        else:
            months = sorted([d.to_timestamp() for d in dates.dt.to_period('M').unique()], reverse=True)
            for dt in months:
                self.cb_time_picker.addItem(dt.strftime("%Y年 %m月"), dt)
                
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

    def update_review_view(self):
        if self.main_win.engine.df.empty: return
        
        display_text = f"{self.current_review_date.year}年" if self.is_yearly_view else self.current_review_date.strftime("%Y年 %m月")
        idx = self.cb_time_picker.findText(display_text)
        if idx >= 0: self.cb_time_picker.setCurrentIndex(idx)
        
        df = self.main_win.engine.df.copy()
        acc_sel = self.cb_rev_account.currentData()
        if acc_sel != "ALL" and acc_sel is not None: df = df[df['account'] == acc_sel]
        str_sel = self.cb_rev_strategy.currentData()
        if str_sel != "ALL" and str_sel is not None: df = df[df['strategy_tag'] == str_sel]
            
        df['exit_time'] = pd.to_datetime(df['exit_time']); df['entry_time'] = pd.to_datetime(df['entry_time'])
        
        y = self.current_review_date.year
        if self.is_yearly_view:
            self.current_view_df = df[df['exit_time'].dt.year == y]
            self._render_yearly_view()
        else:
            m = self.current_review_date.month
            self.current_view_df = df[(df['exit_time'].dt.year == y) & (df['exit_time'].dt.month == m)]
            self.day_trades_list.clear(); self.txt_reason.clear(); self.txt_reflection.clear(); self.list_screenshots.clear()
            self.lbl_trade_detail.setText("请在左侧列表选择一笔特定交易...")
            self.current_editing_idx = None
            self._render_calendar(); self._render_monthly_charts() 

    def _render_calendar(self):
        self.review_calendar.clearContents()
        y, m = self.current_review_date.year, self.current_review_date.month
        cal = calendar.monthcalendar(y, m); df = self.current_view_df; daily_stats = {}
        if not df.empty:
            df['day'] = df['exit_time'].dt.day
            for day, group in df.groupby('day'):
                daily_stats[day] = {'net': group['net_profit'].sum(), 'reviewed': any((pd.notna(group['reflection']) & (group['reflection'].str.strip() != '')))}
        for row, week in enumerate(cal):
            for col, day in enumerate(week):
                if day == 0: continue 
                item = QTableWidgetItem(str(day))
                if day in daily_stats:
                    net = daily_stats[day]['net']
                    if net > 0: 
                        item.setBackground(QColor("#E8F5E9"))
                        item.setForeground(QColor(settings.COLOR_PROFIT_TEXT))
                        item.setText(f"{day}\n+{net:,.0f}")
                    elif net < 0: 
                        item.setBackground(QColor("#FFEBEE"))
                        item.setForeground(QColor(settings.COLOR_LOSS_TEXT))
                        item.setText(f"{day}\n{net:,.0f}")
                    if daily_stats[day]['reviewed']: item.setText(item.text() + "\n📝")
                else: item.setForeground(QColor("#BDBDBD"))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter); font = QFont(); font.setBold(day in daily_stats); item.setFont(font); item.setData(Qt.ItemDataRole.UserRole, QDate(y, m, day))
                self.review_calendar.setItem(row, col, item)

    def _render_monthly_charts(self):
        self.review_pnl_chart.clear(); self.review_kline_chart.clear(); self.review_duration_chart.clear()
        df = self.current_view_df.copy()
        if df.empty: return
        df_sorted = df.sort_values(by='exit_time')
        equity_curve = [0.0] + df_sorted['net_profit'].cumsum().tolist(); x_data = list(range(len(equity_curve)))
        is_prof = equity_curve[-1] >= 0
        
        # 【进化】使用配置中心的 RGB 颜色
        col = settings.RGB_PROFIT if is_prof else settings.RGB_LOSS
        fill = settings.RGB_PROFIT_FILL if is_prof else settings.RGB_LOSS_FILL
        self.review_pnl_chart.plot(x_data, equity_curve, pen=pg.mkPen(color=col, width=3), fillLevel=0, fillBrush=fill)
        
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
            brush = pg.mkBrush(color=(settings.RGB_PROFIT[0], settings.RGB_PROFIT[1], settings.RGB_PROFIT[2], 150)) if p > 0 else pg.mkBrush(color=(settings.RGB_LOSS[0], settings.RGB_LOSS[1], settings.RGB_LOSS[2], 150))
            spots.append({'pos': (h, p), 'brush': brush, 'pen': None, 'size': 12})
        self.review_duration_chart.addItem(pg.ScatterPlotItem(spots=spots)); self.review_duration_chart.addLine(y=0, pen=pg.mkPen(color='#9E9E9E', style=Qt.PenStyle.DashLine))

    def on_calendar_day_clicked(self, row, col):
        item = self.review_calendar.item(row, col)
        if not item or not item.data(Qt.ItemDataRole.UserRole): return
        qdate = item.data(Qt.ItemDataRole.UserRole); self.lbl_selected_date.setText(f"选定日期: {qdate.toString('yyyy-MM-dd')}")
        self.day_trades_list.clear(); self.txt_reason.clear(); self.txt_reflection.clear(); self.list_screenshots.clear(); self.lbl_trade_detail.setText("请在左侧列表选择一笔特定交易...")
        self.current_editing_idx = None
        day_df = self.current_view_df[self.current_view_df['exit_time'].dt.day == qdate.day()]
        for idx, record in day_df.iterrows():
            pnl, sym = record['net_profit'], record['symbol']
            txt = f"{sym} | ￥{'+' if pnl>0 else ''}{pnl:,.2f}" + (" 📝" if pd.notna(record.get('reflection')) and str(record.get('reflection')).strip()!="" else "")
            list_item = QListWidgetItem(txt)
            list_item.setData(Qt.ItemDataRole.UserRole, idx)
            # 【进化】使用深色文本确保对比度
            list_item.setForeground(QColor(settings.COLOR_PROFIT_TEXT) if pnl > 0 else QColor(settings.COLOR_LOSS_TEXT))
            self.day_trades_list.addItem(list_item)

    def on_review_trade_selected(self, current, previous):
        if not current: return
        df_idx = current.data(Qt.ItemDataRole.UserRole)
        record = self.main_win.engine.df.loc[df_idx]
        self.current_editing_idx = df_idx
        
        pnl = record['net_profit']; duration = (record['exit_time'] - record['entry_time']).total_seconds() / 3600
        col_hex = settings.COLOR_PROFIT_TEXT if pnl > 0 else settings.COLOR_LOSS_TEXT
        
        self.lbl_trade_detail.setText(f"""<span style="font-size:16px;">{record['symbol']}</span><br><span style="color:#757575;">进场: {pd.to_datetime(record['entry_time']).strftime('%m-%d %H:%M')} <br>出场: {pd.to_datetime(record['exit_time']).strftime('%m-%d %H:%M')} (持仓 {duration:.1f} h)</span><br>结果: <b style="color:{col_hex}; font-size:16px;">￥{pnl:,.2f}</b>""")
        self.txt_reason.setPlainText(str(record.get('entry_reason', ''))); self.txt_reflection.setPlainText(str(record.get('reflection', '')))
        
        self.cb_edit_strategy.blockSignals(True)
        # 【进化】如果策略为空，使用配置文件的默认策略
        self.cb_edit_strategy.setCurrentText(str(record.get('strategy_tag', settings.DEFAULT_STRATEGY)))
        self.cb_edit_strategy.blockSignals(False)
        
        self.list_screenshots.clear()
        paths_str = str(record.get('screenshot_paths', ''))
        if paths_str and paths_str != 'nan':
            for p in paths_str.split(';'):
                if os.path.exists(p): self.add_thumbnail(p)

    def silent_update_strategy(self, *args):
        if getattr(self, 'current_editing_idx', None) is None: return
        new_st = self.cb_edit_strategy.currentText().strip()
        new_st = settings.DEFAULT_STRATEGY if new_st == "" else new_st
        old_st = str(self.main_win.engine.df.at[self.current_editing_idx, 'strategy_tag']).strip()
        
        if new_st == old_st: return
        self.main_win.engine.update_trade_strategy(self.current_editing_idx, new_st)
        self.main_win.render_all_data()

    def save_review_text(self):
        if getattr(self, 'current_editing_idx', None) is None: QMessageBox.warning(self, "提示", "请先选择一笔交易！"); return
        
        reason = self.txt_reason.toPlainText()
        reflection = self.txt_reflection.toPlainText()
        self._save_image_paths_to_df()
        
        paths = self.main_win.engine.df.at[self.current_editing_idx, 'screenshot_paths']
        self.main_win.engine.update_trade_review(self.current_editing_idx, reason, reflection, paths)
        
        self.update_review_view()
        QMessageBox.information(self, "保存成功", "复盘文字及截图状态已保存。")

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
        
        bar_item = pg.BarGraphItem(x0=0, y=y_pos, width=x_vals, height=0.6, brushes=brushes)
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
            trade_id = str(self.main_win.engine.df.at[self.current_editing_idx, 'trade_id']).replace(" ", "_")
            timestamp = int(datetime.now().timestamp() * 1000)
            filename = os.path.join(settings.SCREENSHOT_DIR, f"{trade_id}_{timestamp}.png")
            image.save(filename)
            self.add_thumbnail(filename)
            self._save_image_paths_to_df() 
        else: QMessageBox.warning(self, "提示", "剪贴板无图片！")

    def import_image(self):
        if getattr(self, 'current_editing_idx', None) is None: return
        file_paths, _ = QFileDialog.getOpenFileNames(self, "选择截图", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        trade_id = str(self.main_win.engine.df.at[self.current_editing_idx, 'trade_id']).replace(" ", "_")
        for path in file_paths:
            timestamp = int(datetime.now().timestamp() * 1000); ext = path.split('.')[-1]
            filename = os.path.join(settings.SCREENSHOT_DIR, f"{trade_id}_{timestamp}.{ext}")
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