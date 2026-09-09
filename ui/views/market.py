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
from ui.widgets.chart_style import apply_pokorny_style
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
        self.btn_sync.setToolTip(
            "本地有数据 → 只补下载缺失的最新几天（快）；\n"
            "本地没数据 → 直接整段抓取。\n\n"
            "需要「丢弃本地重新整段下载」时，请到「🗄 数据管理」页用「重新全量下载」\n"
            "（日常用不到，只在怀疑本地数据异常时才需要）。")
        self.btn_sync.clicked.connect(self.sync_cloud)
        top_bar.addWidget(self.btn_sync)

        # 同步结果回执（成功/已是最新/失败都要给用户一个明确交代，不能点了没反应）
        self.lbl_sync_status = QLabel("")
        self.lbl_sync_status.setStyleSheet("font-size: 12px; color: #8A94A6; margin-left: 8px;")
        top_bar.addWidget(self.lbl_sync_status)

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

        # 【v5.13 修复 · Qt 布局坑】必须给 main_splitter 显式 stretch=1：
        # 顶部栏里一旦出现 vertical=Preferred 的控件（如本页新增的 lbl_sync_status QLabel，
        # 或将来任何 QLabel 后缀），Qt 会把整段富余高度全部分给顶部栏（实测把 34px 的
        # 顶栏拉成 401px，标题占据大半页）。显式 stretch 让富余空间永远归主区，不再受
        # 子布局启发式分配影响。类似结构的新页面务必照抄这句。
        layout.addWidget(main_splitter, 1)

    @staticmethod
    def _apply_pokorny_axis(plot_item):
        """委托给 ui/widgets/chart_style.py —— 全 app 图表轴样式唯一来源 (v5.12 · §9-O7)

        注意：本页的图表来自 `GraphicsLayoutWidget.addPlot()`，拿到的是 PlotItem
        而非 PlotWidget，chart_style 内部已兼容这两种类型。
        """
        return apply_pokorny_style(plot_item, background=None, margins=0)

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

        # 本地没数据（或文件为空）→ 直接抓取；sync_cloud 内部会自动走"全量"分支
        self.sync_cloud()

    def sync_cloud(self):
        """
        把当前标的同步到最新。

        NOTE(v5.12)：方法名由 `force_sync_cloud` 改为 `sync_cloud` ——
        它已不再是"强制全量"，名字必须如实反映行为（§10-10 面向用户说人话，
        同样适用于面向未来的我的命名）。

        【v5.12 修正 · §9-O4】语义改为与用户直觉一致：
          · 本地有数据 → 增量：只补下载缺失的最新几天（秒级完成）
          · 本地没数据 → 全量：整段抓取（force_full 与否结果相同，因为本地是空的）
        旧代码恒传 force_full=True，导致对已缓存标的点一次就从 2010 整段重下，
        又慢又浪费请求额度。真正需要"丢弃本地重下"的场景，
        统一去「🗄 数据管理」页用「重新全量下载」（§10-10 危险/耗时动作隔离）。
        """
        if not self.current_symbol:
            QMessageBox.information(self, "提示", "请先搜索并选中一个标的，再进行云端同步。")
            return
        self.btn_sync.setEnabled(False)
        self.lbl_sync_status.setText("正在同步…")
        # 【架构纪律】UI 不发网络请求：统一走 SingleSyncWorker → MarketSyncService。
        self.fetch_thread = SingleSyncWorker(self.current_symbol, zone=ZONE_KLINE,
                                             force_full=False, parent=self)
        self.fetch_thread.finished.connect(self._on_sync_finished)
        self.fetch_thread.start()

    def _on_sync_finished(self, result: dict):
        self.btn_sync.setEnabled(True)
        symbol = str(result.get("symbol", self.current_symbol) or self.current_symbol)

        # 【竞态防护】拉取期间用户可能已切换到其他标的，过期结果必须丢弃
        if symbol != self.current_symbol:
            self.lbl_sync_status.setText("")
            return

        if not result.get("ok"):
            self.lbl_sync_status.setText("同步失败")
            # 用"人话"说明失败原因：网络？还是代码有误 / 该股已退市？(v5.10)
            QMessageBox.warning(self, "行情同步失败", friendly_fetch_message(symbol, result))
            return

        # 同步成功：把"到底发生了什么"明确回执给用户，避免"点了没反应"的错觉
        if result.get("skipped"):
            self.lbl_sync_status.setText("已是最新，无需更新")
        else:
            added = int(result.get("added", 0) or 0)
            self.lbl_sync_status.setText(
                f"已更新，新增 {added} 行" if added > 0 else "已更新")

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