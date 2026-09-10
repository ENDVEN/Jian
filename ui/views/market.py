# ui/views/market.py
import logging

import numpy as np
import pandas as pd
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLabel, QFrame, QLineEdit, QMessageBox, QCheckBox,
                             QSplitter, QDialog)
from PyQt6.QtCore import Qt
import pyqtgraph as pg

from core.formula.program import (FormulaProgramError, execute_programs_with_draws_grouped,
                                  parse_program)
from core.indicators import TAEngine
from core.utils import parse_params_text
from data.market_db import DataLakeManager
from data.sync_service import ZONE_KLINE, friendly_fetch_message
from ui.dialogs.formula_overlay import FormulaOverlayDialog
# v6.6/P4：内置指标与用户公式**都产出 DrawData**，交给唯一渲染器 OverlayPainter；
# v6.7：换算与"该放主图还是副图"的判断搬到 ui/widgets/chart_layers.py；
# v6.8：**窗格编排交给 ChartHost**（§10-12），本页不再自己 addPlot 拼窗格，
#       并支持**多张公式副图**（每段可选 副图 1/2/3）。
from ui.widgets.chart_host import AXIS_NO_VALUES, ChartHost
from ui.widgets.chart_layers import (builtin_indicator_layers, layer_value_range,
                                     scale_mismatch_hint)
from ui.widgets.chart_pane import ChartPane
from ui.widgets.chart_style import apply_pokorny_style
from ui.widgets.custom_widgets import CandlestickItem
from ui.widgets.draw_overlay import OverlayPainter
from ui.widgets.indicator_panes import fill_macd_pane, fill_volume_pane
from ui.workers import SingleSyncWorker

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

        # v6.6 / §7-B3 P4：主图"统一图层"（内置指标 + 用户公式 → 同一个渲染器）
        self._layer_builtin: list = []
        self._layer_formula: dict = {}       # 目标窗格 -> [DrawData]
        self._layer_bars = 0
        self._layer_items: list = []
        self._formula_segments: list = []    # [(函数文本, 目标窗格)]
        self._formula_params_text = ""
        self._formula_programs: list = []
        self._formula_error = ""
        self.formula_plots: dict = {}        # 目标窗格 -> PlotItem（副图按需创建）

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

        # ── 自定义公式（v6.6 · §7-B3 P4）──────────────────────────────
        # 与「均线 / 布林带」并列成一个开关：勾上就在主图显示，而且长得一样 ——
        # 因为它们**本来就是同一条图层管线**（都产出 DrawData → OverlayPainter）。
        control_layout.addSpacing(25)
        lbl_formula = QLabel("🧮 自定义公式")
        lbl_formula.setStyleSheet("font-weight:bold; color:#757575;")
        control_layout.addWidget(lbl_formula)

        self.cb_formula = QCheckBox("显示公式叠加")
        self.cb_formula.setChecked(True)
        self.cb_formula.setStyleSheet(
            "QCheckBox { font-size: 13px; color: #424242; margin-top: 5px; }")
        self.cb_formula.setToolTip("显示/隐藏函数画出的线、状态柱、图标（与均线/布林带同一套开关行为）")
        self.cb_formula.stateChanged.connect(self.render_charts)
        control_layout.addWidget(self.cb_formula)

        self.btn_edit_formula = QPushButton("✏️ 编辑公式…")
        self.btn_edit_formula.setStyleSheet(
            "QPushButton { background-color: #F5F5F5; border: 1px solid #E0E0E0; "
            "border-radius: 4px; padding: 6px; font-weight:bold; color: #424242;}")
        self.btn_edit_formula.setToolTip("粘贴通达信式函数，叠加到当前标的的主图上")
        self.btn_edit_formula.clicked.connect(self.edit_formula)
        control_layout.addWidget(self.btn_edit_formula)

        self.lbl_formula_status = QLabel("未设置")
        self.lbl_formula_status.setWordWrap(True)
        self.lbl_formula_status.setStyleSheet(
            "font-size: 11px; color: #8A94A6; margin-top: 4px;")
        control_layout.addWidget(self.lbl_formula_status)

        self.chart_container = QFrame()
        self.chart_container.setStyleSheet("QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }")
        chart_layout = QVBoxLayout(self.chart_container)
        chart_layout.setContentsMargins(5, 5, 5, 5)

        # v6.8：窗格编排交给 ChartHost（§10-12）—— 本页不再自己 addPlot 拼窗格。
        # bottom_axis_mode=no_values 沿用旧观感：非最下窗格保留轴线、只隐藏刻度值。
        self.host = ChartHost(bottom_axis_mode=AXIS_NO_VALUES)
        self.host.setBackground('w')
        chart_layout.addWidget(self.host)

        # 主图窗格**常驻**（不再每次重渲染都重建），K 线等内容每次重画
        self.main_plot = self.host.main_pane.plot_item
        self._apply_pokorny_axis(self.main_plot)

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
        self.host.clear_sub_panes()
        self.formula_plots = {}
        self.drawn_lines.clear()
        self._layer_builtin = []
        self._layer_formula = {}
        self._layer_items = []
        self.host.clear_pane_content('main')   # 保留窗格与十字光标，只清内容

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
        
        self.main_plot.setTitle(title)
        k_data = [(i, row['open'], row['close'], row['low'], row['high']) for i, row in df.iterrows()]
        self.main_plot.addItem(CandlestickItem(k_data))
        
        # ---- 统一图层：先算数据（§7-B3 D4），窗格全部建完后再一次性绘制（见本函数尾部）----
        # 内置指标（MA/BOLL）与用户公式**都翻成 DrawData**，交给同一个 OverlayPainter；
        # 换算在 ui/widgets/chart_layers.py（页面只留开关与窗格编排）。
        self._layer_builtin = builtin_indicator_layers(
            df, ma=self.cb_ma.isChecked(), boll=self.cb_boll.isChecked())
        self._layer_formula = self._formula_layers(df)
        self._layer_bars = len(df)
        self._report_formula_status(df)
        

        # ---- 副图（编排交给 ChartHost §10-12；内容构建在 ui/widgets/indicator_panes.py）----
        if self.cb_vol.isChecked():
            vol_plot = self.host.add_pane('vol', fixed_height=SUB_PLOT_HEIGHT)
            self._apply_pokorny_axis(vol_plot.plot_item)
            fill_volume_pane(vol_plot.plot_item, df, x_data)

        if self.cb_macd.isChecked():
            macd_plot = self.host.add_pane('macd', fixed_height=SUB_PLOT_HEIGHT)
            self._apply_pokorny_axis(macd_plot.plot_item)
            fill_macd_pane(macd_plot.plot_item, df, x_data)

        # ==========================================
        # 窗口 N：公式副图（v6.8 · **多副图**，每段可选 副图 1/2/3）
        # ==========================================
        # 副图量级的函数（MACD/RSI/成交量）叠在主图会把 K 线压扁 —— 给它**独立坐标轴**的一格。
        # 渲染仍是同一个 OverlayPainter，只是换了 pane（§10-11）。
        if self.cb_formula.isChecked():
            for target in sorted(self._layer_formula):
                if target == 'main' or not self._layer_formula[target]:
                    continue
                pane = self.host.add_pane(target, fixed_height=SUB_PLOT_HEIGHT)
                self._apply_pokorny_axis(pane.plot_item)
                span = layer_value_range(self._layer_formula[target])
                if span and span[0] <= 0 <= span[1]:
                    # 穿越 0 的振荡型指标给一条零轴参考线（不穿越就不画，免得误导）
                    pane.plot_item.addLine(
                        y=0, pen=pg.mkPen(color='#BDBDBD', style=Qt.PenStyle.DashLine))
                self.formula_plots[target] = pane.plot_item

        # ==========================================
        # 格式化日期刻度 (仅最底部的图表显示时间轴)
        # ==========================================
        bottom_plot = self.host.panes[-1].plot_item
        axis = bottom_plot.getAxis('bottom')
        ticks = []
        step = max(1, len(df) // 10)
        for i in range(0, len(df), step):
            ticks.append((i, df['date'].iloc[i].strftime('%Y-%m')))
        axis.setTicks([ticks])

        # 非最下窗格的"隐藏刻度值"由 ChartHost 统一处理（bottom_axis_mode=no_values）

        # 窗格全部就位后才落笔（唯一渲染器，§10-11）
        self._paint_layers()

        if len(df) > DEFAULT_VISIBLE_BARS:
            self.main_plot.getViewBox().setXRange(len(df) - DEFAULT_VISIBLE_BARS, len(df))

    # ==========================================
    # 统一图层（v6.6 · §7-B3 P4）
    # ==========================================
    def edit_formula(self):
        """打开公式编辑器；应用后立刻在当前标的上重新求值并叠加。"""
        dlg = FormulaOverlayDialog(self, segments=self._formula_segments,
                                   params_text=self._formula_params_text)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._formula_segments = dlg.result_segments()
        self._formula_params_text = dlg.params_text()
        self._compile_formula()
        self.render_charts()

    def _compile_formula(self):
        """把 (函数文本, 目标窗格) 编译成 programs（顺序与 `_formula_segments` 一一对应）。"""
        self._formula_programs = []
        self._formula_error = ""
        if not self._formula_segments:
            self._set_formula_status(True, "未设置")
            return
        for idx, (text, _target) in enumerate(self._formula_segments, start=1):
            try:
                self._formula_programs.append(parse_program(text))
            except FormulaProgramError as e:
                self._formula_error = f"函数段 {idx}: {e}"
                return

    def _formula_layers(self, df) -> dict:
        """按目标窗格分组求值。**失败不打断整页渲染**，只把原因写进面板状态。

        ⚠ 各段仍共用**同一个变量池**（后段引用前段变量，这是多段共享池的核心契约）——
        所以引擎**只求值一次**，再按段归位（`execute_programs_with_draws_grouped`）。
        """
        targets: dict = {}
        if not self._formula_programs:
            if self._formula_error:
                self._set_formula_status(False, f"❌ {self._formula_error}")
            return targets
        params = parse_params_text(self._formula_params_text)
        try:
            _variables, groups = execute_programs_with_draws_grouped(
                self._formula_programs, df, params)
        except FormulaProgramError as e:
            self._set_formula_status(False, f"❌ 执行失败: {e}")
            return targets
        for (_text, target), draws in zip(self._formula_segments, groups):
            targets.setdefault(target, []).extend(draws)
        return targets

    def _paint_layers(self):
        """把「内置指标 + 用户公式」画到各自窗格 —— 全 app 唯一渲染器（§10-11）。

        内置指标固定进主图；用户公式按**每段选的目标窗格**落位（主图或某张副图）。
        两者在渲染层**没有任何区别**（都是 DrawData → OverlayPainter），这正是 §7-B3 D4 的效果。
        """
        x = np.arange(self._layer_bars)
        items: list = []

        main_pane = self.host.main_pane
        main_pane.clear_overlays()
        OverlayPainter(main_pane, x).render(self._layer_builtin)
        if self.cb_formula.isChecked():
            OverlayPainter(main_pane, x).render(self._layer_formula.get('main', []))
        items += main_pane.overlay_items

        if self.cb_formula.isChecked():
            for target, plot_item in self.formula_plots.items():
                pane = ChartPane.wrap(plot_item, name=target, role='sub')
                pane.clear_overlays()
                OverlayPainter(pane, x).render(self._layer_formula.get(target, []))
                items += pane.overlay_items

        self._layer_items = items

    def _report_formula_status(self, df):
        """写面板状态：图层数 + 落点分布，必要时补一句"该放副图"的引导。

        引导判据是纯函数 `ui/widgets/chart_layers.scale_mismatch_hint`（可单测）。
        """
        if not self._formula_programs:
            return
        if not any(self._layer_formula.values()):
            return          # 已由 _formula_layers 写过 ❌，不覆盖
        main_count = len(self._layer_formula.get('main', []))
        sub_targets = sorted(t for t in self._layer_formula
                             if t != 'main' and self._layer_formula[t])
        message = (f"✓ {sum(len(v) for v in self._layer_formula.values())} 个图层 · "
                   f"主图 {main_count} · 副图 {len(sub_targets)} 格")
        hint = None
        if main_count and not df.empty:
            hint = scale_mismatch_hint(self._layer_formula.get('main', []),
                                       float(df['low'].min()), float(df['high'].max()))
        if hint:
            # 面板只有 200px 宽：标签上留一句短的，完整解释进 tooltip（§10-10）
            self._set_formula_status(
                True, message + "\n⚠ 主图部分与股价量级相差很大 · 建议改用副图", warn=True)
            self.lbl_formula_status.setToolTip(hint)
        else:
            self._set_formula_status(True, message)

    def _set_formula_status(self, ok: bool, message: str, *, warn: bool = False):
        self.lbl_formula_status.setText(message)
        self.lbl_formula_status.setToolTip(message)   # 窄面板会截断，完整内容进 tooltip
        color = '#E65100' if warn else ('#4CAF50' if ok else '#F44336')
        self.lbl_formula_status.setStyleSheet(
            f"font-size: 11px; color: {color}; margin-top: 4px;")

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