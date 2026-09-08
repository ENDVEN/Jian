# ui/views/market.py
import logging
import pandas as pd
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QFrame, QLineEdit, QMessageBox, QCheckBox,
                             QSplitter)
from PyQt6.QtCore import Qt
import pyqtgraph as pg
from pyqtgraph import QtGui

from config import settings
from data.market_db import DataLakeManager
from data.sync_service import ZONE_KLINE, friendly_fetch_message
from ui.widgets.custom_widgets import CandlestickItem
from ui.workers import SingleSyncWorker
from core.indicators import TAEngine

# 主图均线序列：(列名, 配色)。需与 TAEngine.add_ma 的默认窗口 (5/20/60) 保持一致
MA_SERIES = (
    ('MA_5',  '#2196F3'),
    ('MA_20', '#FF9800'),
    ('MA_60', '#9C27B0'),
)

# 附图 (成交量 / MACD) 统一高度
SUB_PLOT_HEIGHT = 150

# 默认可视 K 线根数，超出后只展示最近一段
DEFAULT_VISIBLE_BARS = 150

# 趋势线默认横向跨度 (起点比例, 终点比例)
TRENDLINE_SPAN = (0.2, 0.8)


class MarketView(QWidget):
    def __init__(self, main_win):
        super().__init__()
        self.main_win = main_win
        self.data_lake = DataLakeManager()
        self.current_symbol = None
        self.current_name = ""
        self.current_df = pd.DataFrame()
        
        self.main_plot = None
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
        
        res_df = self.main_win.engine.search_symbol(keyword)   # 经 DataEngine 门面，UI 不碰 DAO
        if res_df.empty:
            QMessageBox.warning(self, "未找到", "未找到该标的，请确认花名册已更新。")
            return
            
        self.current_symbol = str(res_df.iloc[0]['symbol'])
        self.current_name = str(res_df.iloc[0]['name'])
        
        # 【性能要点】先用轻量探针命中本地缓存，避免每次都把整个 Parquet 读进内存
        if self.data_lake.exists("kline_daily", self.current_symbol):
            self.current_df = self.data_lake.load_data("kline_daily", self.current_symbol)
            if not self.current_df.empty:
                self.render_charts()
                return
            
        self.force_sync_cloud()

    def force_sync_cloud(self):
        if not self.current_symbol:
            QMessageBox.information(self, "提示", "请先搜索并选中一个标的，再进行云端同步。")
            return
        self.btn_sync.setEnabled(False)
        # 【架构纪律】UI 不发网络请求：统一走 SingleSyncWorker → MarketSyncService。
        # force_full=True 对应"☁️ 云端同步"的语义（用户就是想重拉一遍）。
        self.fetch_thread = SingleSyncWorker(self.current_symbol, zone=ZONE_KLINE,
                                             force_full=True, parent=self)
        self.fetch_thread.finished.connect(self._on_sync_finished)
        self.fetch_thread.start()

    def _on_sync_finished(self, result: dict):
        self.btn_sync.setEnabled(True)
        symbol = str(result.get("symbol", self.current_symbol) or self.current_symbol)

        # 【竞态防护】拉取期间用户可能已切换到其他标的，过期结果必须丢弃
        if symbol != self.current_symbol:
            return

        if not result.get("ok"):
            # 用"人话"说明失败原因：网络？还是代码有误 / 该股已退市？(v5.10)
            QMessageBox.warning(self, "行情同步失败", friendly_fetch_message(symbol, result))
            return

        df = self.data_lake.load_data(ZONE_KLINE, symbol)
        if df.empty:
            QMessageBox.critical(self, "错误", f"{symbol} 行情拉取失败（未取得数据）。")
            return

        self.current_df = df
        self.render_charts()

    def render_charts(self):
        """按当前指标开关重建整个图表矩阵 (幂等设计，可安全重复调用)"""
        self.graphics_layout.clear()
        self.drawn_lines.clear()
        self.main_plot = None
        
        if self.current_df.empty: return
        
        # 使用 copy 保护原始数据
        df = self.current_df.copy().sort_values(by='date').reset_index(drop=True)
        
        # 【数据防御】日期为 NaT 的行会让 strftime 崩溃，先剔除
        df = df.dropna(subset=['date'])
        if df.empty:
            logging.warning("行情数据缺少有效日期列，已中止渲染。")
            return
            
        x_data = list(range(len(df)))
        
        # --- 通过 TAEngine 注册表声明式计算指标 ---
        selected = [
            key for key, checkbox in
            (('ma', self.cb_ma), ('boll', self.cb_boll), ('macd', self.cb_macd))
            if checkbox.isChecked()
        ]
        df = TAEngine.apply(df, selected)
            
        # ==========================================
        # 窗口 1：主图
        # ==========================================
        end_date = df['date'].iloc[-1].strftime('%Y-%m-%d')
        display_name = self.current_name or self.current_symbol
        title = (f"<span style='color:#212121; font-size:16px; font-weight:bold;'>"
                 f"{display_name} ({self.current_symbol})</span> "
                 f"<span style='color:#757575; font-size:12px;'> 日线 | {end_date}</span>")
        
        self.main_plot = self.graphics_layout.addPlot(row=0, col=0, title=title)
        self._apply_pokorny_axis(self.main_plot)
        
        k_data = [(i, row['open'], row['close'], row['low'], row['high']) for i, row in df.iterrows()]
        self.main_plot.addItem(CandlestickItem(k_data))
        
        if self.cb_ma.isChecked():
            for column, color in MA_SERIES:
                if column in df.columns:
                    self.main_plot.plot(x_data, df[column], pen=pg.mkPen(color=color, width=1.5))
        
        if self.cb_boll.isChecked():
            boll_pen = pg.mkPen(color='#90CAF9', width=1, style=Qt.PenStyle.DashLine)
            self.main_plot.plot(x_data, df['BOLL_UP'], pen=boll_pen)
            self.main_plot.plot(x_data, df['BOLL_DOWN'], pen=boll_pen)

        # 附图按添加顺序入列，最后一个负责显示时间轴
        sub_plots = []
        row_idx = 1
        
        # ==========================================
        # 窗口 2：成交量
        # ==========================================
        if self.cb_vol.isChecked():
            vol_plot = self.graphics_layout.addPlot(row=row_idx, col=0)
            self._apply_pokorny_axis(vol_plot)
            vol_plot.setMaximumHeight(SUB_PLOT_HEIGHT) 
            vol_plot.setXLink(self.main_plot)
            
            colors = [settings.COLOR_PROFIT if close >= open else settings.COLOR_LOSS for open, close in zip(df['open'], df['close'])]
            brushes = [pg.mkBrush(c) for c in colors]
            pens = [pg.mkPen(c) for c in colors]
            
            vol_item = pg.BarGraphItem(x=x_data, height=df['volume'], width=0.6, brushes=brushes, pens=pens)
            vol_plot.addItem(vol_item)
            sub_plots.append(vol_plot)
            row_idx += 1

        # ==========================================
        # 窗口 3：MACD
        # ==========================================
        if self.cb_macd.isChecked():
            macd_plot = self.graphics_layout.addPlot(row=row_idx, col=0)
            self._apply_pokorny_axis(macd_plot)
            macd_plot.setMaximumHeight(SUB_PLOT_HEIGHT)
            macd_plot.setXLink(self.main_plot) 
            macd_plot.addLine(y=0, pen=pg.mkPen(color='#BDBDBD', style=Qt.PenStyle.DashLine))
            
            macd_plot.plot(x_data, df['MACD_line'], pen=pg.mkPen(color='#212121', width=1.5))
            macd_plot.plot(x_data, df['MACD_signal'], pen=pg.mkPen(color='#FF9800', width=1.5))
            
            hist = df['MACD_hist']
            hist_colors = [settings.COLOR_PROFIT if v > 0 else settings.COLOR_LOSS for v in hist]
            hist_brushes = [pg.mkBrush(QtGui.QColor(c).lighter(120)) for c in hist_colors]
            hist_pens = [pg.mkPen(c) for c in hist_colors]
            macd_hist_item = pg.BarGraphItem(x=x_data, height=hist, width=0.5, brushes=hist_brushes, pens=hist_pens)
            macd_plot.addItem(macd_hist_item)
            sub_plots.append(macd_plot)
            
        # ==========================================
        # 格式化日期刻度 (仅最底部的图表显示时间轴)
        # ==========================================
        bottom_plot = sub_plots[-1] if sub_plots else self.main_plot
        axis = bottom_plot.getAxis('bottom')
        ticks = []
        step = max(1, len(df) // 10)
        for i in range(0, len(df), step):
            ticks.append((i, df['date'].iloc[i].strftime('%Y-%m')))
        axis.setTicks([ticks])
        
        # 除最底部图表外，其余图表的横轴刻度值全部隐藏，保持画面干净
        for plot in [self.main_plot] + sub_plots[:-1]:
            plot.getAxis('bottom').setStyle(showValues=False)

        if len(df) > DEFAULT_VISIBLE_BARS:
            self.main_plot.getViewBox().setXRange(len(df) - DEFAULT_VISIBLE_BARS, len(df))

    def add_trendline(self):
        if self.main_plot is None: return
        
        view_range = self.main_plot.getViewBox().viewRange()
        x_min, x_max = view_range[0]
        y_min, y_max = view_range[1]
        
        start_x = x_min + (x_max - x_min) * TRENDLINE_SPAN[0]
        end_x = x_min + (x_max - x_min) * TRENDLINE_SPAN[1]
        y_mid = (y_max + y_min) / 2
        
        line = pg.LineSegmentROI([[start_x, y_mid], [end_x, y_mid]], pen=pg.mkPen(color='#1976D2', width=2))
        self.main_plot.addItem(line)
        self.drawn_lines.append(line)

    def clear_trendlines(self):
        if self.main_plot is None: return
        for line in self.drawn_lines:
            self.main_plot.removeItem(line)
        self.drawn_lines.clear()