# ui/views/market.py
import pandas as pd
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QFrame, QLineEdit, QMessageBox, QCheckBox,
                             QScrollArea, QSplitter)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
import pyqtgraph as pg
from pyqtgraph import QtGui, QtCore

from config import settings
from data.akshare_feed import AkShareFeed
from data.market_db import DataLakeManager
from ui.widgets.custom_widgets import CandlestickItem
from core.indicators import TAEngine  # 【新增】引入我们自己的原生引擎

class FetchDataThread(QThread):
    finished_signal = pyqtSignal(bool, str, pd.DataFrame, str)
    def __init__(self, symbol: str, name: str):
        super().__init__()
        self.symbol = symbol; self.name = name
    def run(self):
        try:
            # 【核心修复：智能路由】
            # 如果代码是纯数字(如 600519)，走股票接口；如果含字母(如 RB)，走期货主力接口
            if self.symbol.isdigit():
                df = AkShareFeed.fetch_a_share_daily(self.symbol)
            else:
                df = AkShareFeed.fetch_futures_daily(self.symbol)
                
            if not df.empty:
                DataLakeManager().save_data("kline_daily", self.symbol, df)
                self.finished_signal.emit(True, self.symbol, df, self.name)
            else: 
                self.finished_signal.emit(False, self.symbol, pd.DataFrame(), self.name)
        except Exception as e:
            print(f"线程崩溃: {e}")
            self.finished_signal.emit(False, self.symbol, pd.DataFrame(), self.name)

class MarketView(QWidget):
    def __init__(self, main_win):
        super().__init__()
        self.main_win = main_win
        self.data_lake = DataLakeManager()
        self.current_symbol = None
        self.current_name = None
        self.current_df = pd.DataFrame()
        
        self.drawn_lines = [] 
        
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)
        
        # ==========================================
        # 1. 顶部搜索栏
        # ==========================================
        top_bar = QHBoxLayout()
        title = QLabel("行情数据中心")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #212121;")
        top_bar.addWidget(title)
        top_bar.addStretch()
        
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("输入代码或中文名 (如: 600519或茅台)")
        self.txt_search.setFixedWidth(250)
        self.txt_search.setStyleSheet("QLineEdit { font-size: 14px; padding: 8px 15px; border: 1px solid #E0E0E0; border-radius: 6px; background: white; }")
        self.txt_search.returnPressed.connect(self.search_and_load)
        top_bar.addWidget(self.txt_search)
        
        self.btn_search = QPushButton("🔍 查阅")
        self.btn_search.setStyleSheet("QPushButton { font-size: 14px; font-weight: bold; color: white; background: #1976D2; padding: 8px 15px; border: none; border-radius: 6px; } QPushButton:hover { background: #1565C0; }")
        self.btn_search.clicked.connect(self.search_and_load)
        top_bar.addWidget(self.btn_search)
        
        self.btn_sync = QPushButton("☁️ 云端同步")
        self.btn_sync.setStyleSheet("QPushButton { font-size: 14px; font-weight: bold; color: #1976D2; background: #E3F2FD; padding: 8px 15px; border: 1px solid #BBDEFB; border-radius: 6px; margin-left: 10px; }")
        self.btn_sync.clicked.connect(self.force_sync_cloud)
        top_bar.addWidget(self.btn_sync)
        
        layout.addLayout(top_bar)
        
        # ==========================================
        # 2. 核心区：左侧指标台 + 右侧动态矩阵画布
        # ==========================================
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        control_panel = QFrame()
        control_panel.setStyleSheet("QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }")
        control_layout = QVBoxLayout(control_panel)
        control_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        lbl_ind = QLabel("🎛️ 主图叠加")
        lbl_ind.setStyleSheet("font-weight:bold; color:#757575;")
        control_layout.addWidget(lbl_ind)
        
        self.cb_ma = QCheckBox("均线 (MA 5/20/60)")
        self.cb_boll = QCheckBox("布林带 (BOLL)")
        for cb in [self.cb_ma, self.cb_boll]:
            cb.setStyleSheet("QCheckBox { font-size: 13px; color: #424242; margin-top: 5px; }")
            cb.stateChanged.connect(self.render_charts)
            control_layout.addWidget(cb)
            
        control_layout.addSpacing(15)
        lbl_sub = QLabel("📊 附图窗口")
        lbl_sub.setStyleSheet("font-weight:bold; color:#757575;")
        control_layout.addWidget(lbl_sub)
        
        self.cb_vol = QCheckBox("成交量 (Volume)")
        self.cb_macd = QCheckBox("MACD 指标")
        self.cb_vol.setChecked(True) 
        for cb in [self.cb_vol, self.cb_macd]:
            cb.setStyleSheet("QCheckBox { font-size: 13px; color: #424242; margin-top: 5px; }")
            cb.stateChanged.connect(self.render_charts)
            control_layout.addWidget(cb)
            
        control_layout.addSpacing(25)
        lbl_tools = QLabel("🛠️ 画图工具")
        lbl_tools.setStyleSheet("font-weight:bold; color:#757575;")
        control_layout.addWidget(lbl_tools)
        
        self.btn_draw_line = QPushButton("✏️ 添加趋势线")
        self.btn_draw_line.setStyleSheet("QPushButton { background-color: #F5F5F5; border: 1px solid #E0E0E0; border-radius: 4px; padding: 6px; font-weight:bold; color: #424242;}")
        self.btn_draw_line.clicked.connect(self.add_trendline)
        self.btn_clear_lines = QPushButton("🗑️ 清除所有画线")
        self.btn_clear_lines.setStyleSheet("QPushButton { background-color: #FFEBEE; border: 1px solid #FFCDD2; border-radius: 4px; padding: 6px; font-weight:bold; color: #D32F2F; margin-top:5px;}")
        self.btn_clear_lines.clicked.connect(self.clear_trendlines)
        control_layout.addWidget(self.btn_draw_line)
        control_layout.addWidget(self.btn_clear_lines)

        self.chart_container = QFrame()
        self.chart_container.setStyleSheet("QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }")
        chart_layout = QVBoxLayout(self.chart_container)
        chart_layout.setContentsMargins(5, 5, 5, 5)
        
        self.graphics_layout = pg.GraphicsLayoutWidget()
        self.graphics_layout.setBackground('w')
        chart_layout.addWidget(self.graphics_layout)
        
        main_splitter.addWidget(control_panel)
        main_splitter.addWidget(self.chart_container)
        main_splitter.setSizes([200, 1000]) 
        
        layout.addWidget(main_splitter)

    def _apply_pokorny_axis(self, plot_item):
        plot_item.hideAxis('top'); plot_item.hideAxis('right')
        plot_item.showGrid(x=True, y=True, alpha=0.15)
        pen = pg.mkPen(color='#E0E0E0', width=1); text_pen = pg.mkPen(color='#9E9E9E')
        for axis_name in ['left', 'bottom']:
            axis = plot_item.getAxis(axis_name)
            axis.setPen(pen); axis.setTextPen(text_pen)

    def search_and_load(self):
        keyword = self.txt_search.text().strip()
        if not keyword: return
        
        res_df = self.main_win.engine.db.search_symbol(keyword)
        if res_df.empty:
            QMessageBox.warning(self, "未找到", "未找到该标的，请确认花名册已更新。")
            return
            
        self.current_symbol = str(res_df.iloc[0]['symbol'])
        self.current_name = str(res_df.iloc[0]['name'])
        
        df = self.data_lake.load_data("kline_daily", self.current_symbol)
        
        if df.empty:
            self.force_sync_cloud()
        else:
            self.current_df = df
            self.render_charts()

    def force_sync_cloud(self):
        if not self.current_symbol: return
        self.btn_sync.setEnabled(False)
        self.fetch_thread = FetchDataThread(self.current_symbol, self.current_name)
        self.fetch_thread.finished_signal.connect(self._on_sync_finished)
        self.fetch_thread.start()

    def _on_sync_finished(self, success, symbol, df, name):
        self.btn_sync.setEnabled(True)
        if success and not df.empty:
            self.current_df = df
            self.render_charts()
        else:
            QMessageBox.critical(self, "错误", "拉取失败。")

    def render_charts(self):
        self.graphics_layout.clear()
        self.drawn_lines.clear()
        
        if self.current_df.empty: return
        
        # 使用 copy 保护原始数据
        df = self.current_df.copy().sort_values(by='date').reset_index(drop=True)
        x_data = list(range(len(df)))
        
        # --- 接入原生 TAEngine ---
        if self.cb_ma.isChecked():
            df = TAEngine.add_ma(df, windows=(5, 20, 60))
        if self.cb_boll.isChecked():
            df = TAEngine.add_boll(df, window=20, num_std=2)
        if self.cb_macd.isChecked():
            df = TAEngine.add_macd(df, fast=12, slow=26, signal=9)
            
        # ==========================================
        # 窗口 1：主图
        # ==========================================
        start_date = df['date'].iloc[0].strftime('%Y-%m-%d'); end_date = df['date'].iloc[-1].strftime('%Y-%m-%d')
        title = f"<span style='color:#212121; font-size:16px; font-weight:bold;'>{self.current_name} ({self.current_symbol})</span> <span style='color:#757575; font-size:12px;'> 日线 | {end_date}</span>"
        
        self.main_plot = self.graphics_layout.addPlot(row=0, col=0, title=title)
        self._apply_pokorny_axis(self.main_plot)
        
        k_data = [(i, row['open'], row['close'], row['low'], row['high']) for i, row in df.iterrows()]
        self.main_plot.addItem(CandlestickItem(k_data))
        
        if self.cb_ma.isChecked():
            self.main_plot.plot(x_data, df['MA_5'], pen=pg.mkPen(color='#2196F3', width=1.5))
            self.main_plot.plot(x_data, df['MA_20'], pen=pg.mkPen(color='#FF9800', width=1.5))
            self.main_plot.plot(x_data, df['MA_60'], pen=pg.mkPen(color='#9C27B0', width=1.5))
        
        if self.cb_boll.isChecked():
            self.main_plot.plot(x_data, df['BOLL_UP'], pen=pg.mkPen(color='#90CAF9', width=1, style=Qt.PenStyle.DashLine))
            self.main_plot.plot(x_data, df['BOLL_DOWN'], pen=pg.mkPen(color='#90CAF9', width=1, style=Qt.PenStyle.DashLine))

        row_idx = 1
        
        # ==========================================
        # 窗口 2：成交量
        # ==========================================
        if self.cb_vol.isChecked():
            self.vol_plot = self.graphics_layout.addPlot(row=row_idx, col=0)
            self._apply_pokorny_axis(self.vol_plot)
            self.vol_plot.setMaximumHeight(150) 
            self.vol_plot.setXLink(self.main_plot)
            
            colors = [settings.COLOR_PROFIT if close >= open else settings.COLOR_LOSS for open, close in zip(df['open'], df['close'])]
            brushes = [pg.mkBrush(c) for c in colors]
            pens = [pg.mkPen(c) for c in colors]
            
            vol_item = pg.BarGraphItem(x=x_data, height=df['volume'], width=0.6, brushes=brushes, pens=pens)
            self.vol_plot.addItem(vol_item)
            row_idx += 1

        # ==========================================
        # 窗口 3：MACD
        # ==========================================
        if self.cb_macd.isChecked():
            self.macd_plot = self.graphics_layout.addPlot(row=row_idx, col=0)
            self._apply_pokorny_axis(self.macd_plot)
            self.macd_plot.setMaximumHeight(150)
            self.macd_plot.setXLink(self.main_plot) 
            self.macd_plot.addLine(y=0, pen=pg.mkPen(color='#BDBDBD', style=Qt.PenStyle.DashLine))
            
            self.macd_plot.plot(x_data, df['MACD_line'], pen=pg.mkPen(color='#212121', width=1.5))
            self.macd_plot.plot(x_data, df['MACD_signal'], pen=pg.mkPen(color='#FF9800', width=1.5))
            
            hist = df['MACD_hist']
            hist_colors = [settings.COLOR_PROFIT if v > 0 else settings.COLOR_LOSS for v in hist]
            hist_brushes = [pg.mkBrush(QtGui.QColor(c).lighter(120)) for c in hist_colors]
            hist_pens = [pg.mkPen(c) for c in hist_colors]
            macd_hist_item = pg.BarGraphItem(x=x_data, height=hist, width=0.5, brushes=hist_brushes, pens=hist_pens)
            self.macd_plot.addItem(macd_hist_item)
            
        # ==========================================
        # 格式化日期刻度
        # ==========================================
        bottom_plot = self.macd_plot if self.cb_macd.isChecked() else (self.vol_plot if self.cb_vol.isChecked() else self.main_plot)
        axis = bottom_plot.getAxis('bottom')
        ticks = []
        step = max(1, len(df) // 10)
        for i in range(0, len(df), step):
            ticks.append((i, df['date'].iloc[i].strftime('%Y-%m')))
        axis.setTicks([ticks])
        
        if bottom_plot != self.main_plot:
            self.main_plot.getAxis('bottom').setStyle(showValues=False)
        if self.cb_vol.isChecked() and bottom_plot != self.vol_plot:
            self.vol_plot.getAxis('bottom').setStyle(showValues=False)

        if len(df) > 150:
            self.main_plot.getViewBox().setXRange(len(df) - 150, len(df))

    def add_trendline(self):
        if not hasattr(self, 'main_plot') or self.current_df.empty: return
        
        view_range = self.main_plot.getViewBox().viewRange()
        x_min, x_max = view_range[0]
        y_min, y_max = view_range[1]
        
        start_x = x_min + (x_max - x_min) * 0.2
        end_x = x_min + (x_max - x_min) * 0.8
        y_mid = (y_max + y_min) / 2
        
        line = pg.LineSegmentROI([[start_x, y_mid], [end_x, y_mid]], pen=pg.mkPen(color='#1976D2', width=2))
        self.main_plot.addItem(line)
        self.drawn_lines.append(line)

    def clear_trendlines(self):
        if not hasattr(self, 'main_plot'): return
        for line in self.drawn_lines:
            self.main_plot.removeItem(line)
        self.drawn_lines.clear()