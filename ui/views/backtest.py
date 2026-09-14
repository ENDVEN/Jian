# ui/views/backtest.py
"""
📐 市场回测 视图 —— 策略工作台版 (UI v3 / 阶段A)。

布局：
  ┌ 顶部标题带: 标题 + 标的 + 策略库(选用/另存/删除) ┐
  ├ QSplitter(垂直) ─────────────────────────────┤
  │ 上区(策略编辑) : ① 函数(可多段) + ② 买卖条件组 │
  │ 下区(回测工作台): 区间+运行 / KPI卡片 / 结果页签 │
  └─────────────────────────────────────────────┘

工作流 (产品决策 / 阶段A)：
  ① 粘贴函数(可多段：标准MACD/KDJ/自研各一段，共享变量池、后段可引用前段)
     -> 检测(语法/执行/缺参)
  -> ② 买卖各为一个「条件组 Gate」：多条件积木行 + 满足逻辑
     (全部满足 / 任一满足 / 至少 N 个满足，内部翻译成 COUNT_TRUE 表达式)
  -> 运行回测 -> 保存为策略 -> 下次“选用”一键快速回测
  -> 「策略对比」页签横向比较各策略在该股上的胜率/累计收益。

隐私与职责边界同前：不内置任何私有公式；解析在 core/formula，
回测在 core/backtest，行情抓取在 data/，持久化在 data/strategy_store。
"""
import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import QCompleter
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLabel, QLineEdit, QFrame, QScrollArea,
                             QMessageBox, QTabWidget, QTableWidget,
                             QTableWidgetItem, QHeaderView,
                             QComboBox, QCheckBox, QSplitter, QDialog,
                             QInputDialog, QApplication, QFileDialog, QMenu)

from config import settings
from core.formula import FormulaEngine
from core.formula.program import (parse_program, execute_programs,
                                  execute_programs_with_draws,
                                  probe_missing_parameters, FormulaProgramError)
# v5.15：离场原因标签/配色/风控文案从 core.backtest 统一导入（CSV 表头 / 明细着色 / PNG 报告同源）
from core.backtest import (EXIT_REASON_COLORS, EXIT_REASON_LABELS, risk_summary)
from core.utils import align_by_date, parse_params_text, synthetic_bars
from data.market_db import DataLakeManager
# P7：公式资产化（配方库）+ 与行情页互送
from data.formula_store import (SOURCE_BACKTEST, get_formula_store, make_formula,
                                segments_as_texts)
# 说明：INDEX_PRESETS / is_index_symbol 是纯常量与纯校验函数（无副作用、不联网），
#      因此允许被 UI 直接引用；但**任何联网抓取**都必须走 MarketSyncService（见下方 worker）。
from data.akshare_feed import INDEX_PRESETS, is_index_symbol, is_stock_code
from data.strategy_store import StrategyStore
from data.sync_service import (ZONE_KLINE, ZONE_INDEX, friendly_fetch_message)
from ui.widgets.custom_widgets import (COMBO_QSS, LINE_COMBO_QSS, CandlestickItem,
                                       NoWheelComboBox, NoWheelDateEdit,
                                       NoWheelDoubleSpinBox, SPINBOX_QSS)
from ui.widgets.formula_library import FormulaLibraryDialog
from ui.workers import BacktestRunWorker, SingleSyncWorker
from ui.widgets.chart_style import apply_pokorny_style, plot_equity_curve
# v6.4 / §7-B3 P3：公式叠层渲染全 app 唯一入口（引擎 DrawData → 图元），本页只负责切窗口
from ui.widgets.adaptive_axis import axis_px, compute_ticks, slice_span, visible_span
from ui.widgets.chart_pane import ChartPane
from ui.widgets.draw_overlay import OverlayPainter, overlay_extent, slice_draws
from ui.widgets.condition_gate import ConditionGate
from ui.widgets.function_segments import FunctionSegments
# v5.15：PNG 报告图渲染下沉到独立模块（SRP，回测页只负责入口与文件对话框）
from ui.widgets.backtest_report import render_result_png

PLACEHOLDER = "-"
MARKER_MARGIN = 0.03
RECENT_BARS = 150

# NOTE(v5.15)：EXIT_REASON_LABELS / EXIT_REASON_COLORS 已上收到 core/backtest.py，
# 本页与 PNG 报告图共用同一来源，禁止在此再定义副本。

# 快捷区间（数组顺序 = 下拉展示顺序，单一事实来源，不再另设无人使用的映射表）
# 下沿 2016 与 core/backtest.DEFAULT_START_DATE 保持一致（回测意义窗）
_PRESET_ORDER = ["近3个月", "近6个月", "近1年", "近3年", "近5年", "全部(2016起)"]

_CARD_QSS = ("QFrame { background: white; border: 1px solid #E7EAF0; border-radius: 12px; }")


# ==========================================
# 数据/工具
# ==========================================
def _dummy_bars(n: int = 200) -> pd.DataFrame:
    """哑行情（仅供公式自检试跑）。

    v6.6：实现上收到 `core.utils.synthetic_bars` —— 行情页的「公式叠加」自检
    也要同一份，两处各存一份必然漂移（§11.5-12）。
    """
    return synthetic_bars(n)


def _date_from_preset(preset: str) -> QDate:
    """快捷区间 -> 起始日期；未命中的一律回落到「回测意义窗」下沿 2016-01-01"""
    today = QDate.currentDate()
    if preset == "近3个月":
        return today.addMonths(-3)
    if preset == "近6个月":
        return today.addMonths(-6)
    if preset == "近1年":
        return today.addYears(-1)
    if preset == "近3年":
        return today.addYears(-3)
    if preset == "近5年":
        return today.addYears(-5)
    return QDate(2016, 1, 1)


# ==========================================
# 后台线程
# ==========================================
# 【架构纪律 v5.12 · §9-O2】回测计算线程已从本文件迁入 ui/workers.py。
# 页面与弹窗不再自造 QThread —— 全 app 的线程统一在 ui/workers.py 定义。


class _MetricCard(QFrame):
    """大号 KPI 卡片：上标题下数值，数值越大越醒目"""

    def __init__(self, title: str, accent: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet(_CARD_QSS)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(2)
        head = QLabel(title)
        head.setStyleSheet("font-size: 12px; color: #8A94A6; font-weight: bold;")
        lay.addWidget(head)
        self.value = QLabel(PLACEHOLDER)
        self.value.setStyleSheet(f"font-size: 24px; font-weight: bold; color: {accent};")
        lay.addWidget(self.value)


# ==========================================
# 单股回测视图 (M1) —— 将由 回测模块(三子页容器) 内嵌
# ==========================================
class SingleStockBacktestView(QWidget):
    def __init__(self, main_win):
        super().__init__()
        self.main_win = main_win
        self.data_lake = DataLakeManager()
        self.store = StrategyStore()
        # P7：与行情页**共用同一个配方库实例**（否则后保存的会覆盖先保存的）
        self.formula_store = get_formula_store()

        self.current_symbol = None
        self.current_name = ""
        self._programs: list = []     # 多段函数编译产物 (阶段A)
        self._variables = []
        self._active_strategy_id = None

        self._last_df = pd.DataFrame()
        self._last_result = None
        # 【v5.14 导出】本次运行的"参数快照"（在 start_backtest 时定格，随 _last_result 一起换）。
        # 导出的必须是你真正跑出来的那次配置，而不是导出瞬间编辑框里的内容。
        self._last_meta = None
        self._sync_thread = None
        self._index_thread = None      # 阶段C：指数同步线程
        self._run_thread = None
        self._kline_state = None
        # v6.4 / §7-B3 P3：本次运行的公式叠层（引擎 IR，与 _last_df 行序一致）
        self._last_draws: list = []
        self._kline_win_draws: list = []   # 按 K 线窗口切片后的叠层
        self._overlay_items: list = []     # 已渲染的叠层图元（供"显示公式叠层"开关切换）

        self._equity_state = None
        self._collapsed = {}   # id(body) -> bool：编辑区 ①/②/③ 折叠状态
        self._pending_risk = {}
        self._pending_index = None     # 阶段C：{symbol, index_df} (数据就绪后)

        self._setup_ui()
        self._connect_chart_zoom()
        self._sync_index_enabled(False)
        self._set_condition_enabled(False)
        self._reload_strategy_combo()

    # ==========================================
    # UI 构建
    # ==========================================
    # NOTE(v5.12 · §9-O7): 图表轴样式已统一下沉到 ui/widgets/chart_style.py。
    # 本页图表嵌在白色卡片里，故 background=None（不重刷背景）、margins=0（不设内边距）。
    @staticmethod
    def _style_chart(chart):
        return apply_pokorny_style(chart, background=None, margins=0)

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 6, 0)
        root.setSpacing(10)

        # ---------- 顶部工具栏 (等宽控件 + 去框化，降低密度) ----------
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        # 统一输入控件高度/圆角，避免“大大小小”的混乱感
        # v6.9：收敛到 custom_widgets.LINE_COMBO_QSS（含成对 ::drop-down/::down-arrow，§10-9）
        self._ctrl_qss = LINE_COMBO_QSS
        self._flat_qss = ("QPushButton { color: #1976D2; background: transparent; border: none; "
                          "padding: 0 8px; font-weight: bold; border-radius: 8px; }"
                          "QPushButton:hover { background: #EEF4FD; } QPushButton:disabled { color: #B4BECB; }")
        ctrl_height = 32

        # —— 标的组 ——
        self.txt_symbol = QLineEdit()
        self.txt_symbol.setPlaceholderText("搜索 A股代码 / 名称，回车选择")
        self.txt_symbol.setFixedWidth(230)
        self.txt_symbol.setFixedHeight(ctrl_height)
        self.txt_symbol.returnPressed.connect(self.select_symbol)
        toolbar.addWidget(self.txt_symbol)
        self.btn_select = QPushButton("选择")
        self.btn_select.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_select.setFixedHeight(ctrl_height)
        self.btn_select.setStyleSheet(self._flat_qss)
        self.btn_select.clicked.connect(self.select_symbol)
        toolbar.addWidget(self.btn_select)
        self.lbl_symbol = QLabel("未选择标的")
        self.lbl_symbol.setStyleSheet("font-size: 12px; color: #8A94A6; padding-right: 6px;")
        toolbar.addWidget(self.lbl_symbol)

        # 细分隔线
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.VLine)
        sep1.setStyleSheet("color: #E3E7EF;")
        sep1.setFixedHeight(20)
        toolbar.addWidget(sep1)

        # —— 策略组 ——
        self.cmb_strategy = NoWheelComboBox()
        self.cmb_strategy.setPlaceholderText("选用已保存策略")
        self.cmb_strategy.setMinimumWidth(170)
        self.cmb_strategy.setFixedHeight(ctrl_height)
        self.cmb_strategy.setStyleSheet(self._ctrl_qss)
        self.cmb_strategy.currentIndexChanged.connect(self._on_strategy_selected)
        toolbar.addWidget(self.cmb_strategy)
        self.btn_save_strategy = QPushButton("保存当前")
        self.btn_save_strategy.setFixedHeight(ctrl_height)
        self.btn_save_strategy.setStyleSheet(self._flat_qss)
        self.btn_save_strategy.clicked.connect(self.save_strategy)
        toolbar.addWidget(self.btn_save_strategy)
        self.btn_del_strategy = QPushButton("移除")
        self.btn_del_strategy.setFixedHeight(ctrl_height)
        self.btn_del_strategy.setStyleSheet(self._flat_qss)
        self.btn_del_strategy.setToolTip("删除当前选中的策略")
        self.btn_del_strategy.clicked.connect(self.delete_strategy)
        toolbar.addWidget(self.btn_del_strategy)

        toolbar.addStretch()
        toolbar.addWidget(
            self._hint_icon("需要更大空间看结果？点击 ①/②/③ 卡片右上角「收起 ▲」即可折叠编辑区；"
                            "内容超高时编辑区可上下滚动。"))
        root.addLayout(toolbar)

        # ---------- 垂直分割: 上区 策略编辑 / 下区 回测工作台 ----------
        self._splitter = QSplitter(Qt.Orientation.Vertical)
        self._splitter.setHandleWidth(4)
        self._splitter.setStyleSheet("QSplitter::handle { background: #E7EAF0; border-radius: 2px; }")

        # ========== 上区：① 函数 + ② 条件 + ③ 指数 (可各自收起，超高时可滚动) ==========
        self._config_scroll = QScrollArea()
        self._config_scroll.setWidgetResizable(True)
        self._config_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._config_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._config_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }")
        top_area = QWidget()
        top_lay = QVBoxLayout(top_area)
        top_lay.setContentsMargins(0, 0, 0, 0)
        top_lay.setSpacing(10)
        self._config_scroll.setWidget(top_area)

        # —— 卡片 ① 函数 ——
        self._func_card = QFrame()
        self._func_card.setStyleSheet(_CARD_QSS)
        func_lay = QVBoxLayout(self._func_card)
        func_lay.setContentsMargins(16, 6, 10, 12)
        func_lay.setSpacing(6)

        func_head = QHBoxLayout()
        step1 = QLabel("① 粘贴你的函数（可多段 · 共享变量池）")
        step1.setStyleSheet("font-size: 14px; font-weight: bold; color: #1976D2;")
        func_head.addWidget(step1)
        func_head.addStretch()

        # —— P7：公式资产化 + 与行情页互送（与「🩺 检测」同排，都属于"对这段函数的操作"）——
        _action_qss = ("QPushButton { background:#F5F5F5; border:1px solid #E0E0E0; "
                       "border-radius:8px; padding:4px 10px; font-weight:bold; color:#424242; }"
                       "QPushButton:hover { background:#EDEDED; }")
        self.btn_library = QPushButton("📚 配方库")
        self.btn_library.setStyleSheet(_action_qss)
        self.btn_library.setToolTip("载入已保存的公式配方（含行情页存下的那些）")
        self.btn_library.clicked.connect(self.open_formula_library)
        func_head.addWidget(self.btn_library)

        self.btn_save_formula = QPushButton("💾 存为配方")
        self.btn_save_formula.setStyleSheet(_action_qss)
        self.btn_save_formula.setToolTip("把下面的函数与参数存进配方库；同名即覆盖")
        self.btn_save_formula.clicked.connect(self.save_formula_as)
        func_head.addWidget(self.btn_save_formula)

        self.btn_send_market = QPushButton("📤 送到行情页")
        self.btn_send_market.setStyleSheet(
            "QPushButton { background:#E8F1FF; border:1px solid #BBDEFB; border-radius:8px; "
            "padding:4px 10px; font-weight:bold; color:#1976D2; }"
            "QPushButton:hover { background:#D6E8FF; }")
        self.btn_send_market.setToolTip("把函数与参数送到「📈 市场行情」的公式叠加区，"
                                        "在真实 K 线上看它长什么样（每段默认落主图）")
        self.btn_send_market.clicked.connect(self.send_formula_to_market)
        func_head.addWidget(self.btn_send_market)

        self.btn_detect = QPushButton("🩺 检测")
        self.btn_detect.setStyleSheet("QPushButton { background:#E8F1FF; color:#1976D2; font-weight:bold; padding:4px 14px; border-radius:8px; border:none;} QPushButton:hover{background:#D6E8FF;} QPushButton:disabled{background:#F0F3F8; color:#A7AEBE;}")
        self.btn_detect.clicked.connect(self.detect_function)
        func_head.addWidget(self.btn_detect)
        self.btn_collapse_func = QPushButton("收起 ▲")
        self.btn_collapse_func.setStyleSheet("QPushButton { color:#8A94A6; background:transparent; border:none; padding:4px 6px; font-weight:bold; } QPushButton:hover{color:#1976D2;}")
        self.btn_collapse_func.clicked.connect(lambda: self._toggle_collapse(self._func_body, self.btn_collapse_func))
        func_head.addWidget(self.btn_collapse_func)
        func_lay.addLayout(func_head)

        self._func_body = QWidget()
        body_lay = QVBoxLayout(self._func_body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(6)
        self.segments = FunctionSegments(
            "MA5 := MA(C, 5);\n"
            "UPTREND := C > MA5;\n"
            "GOLD: CROSS(MA(C,5), MA(C,20)), COLORRED;\n\n"
            "粘贴你编写的整段函数后点击「检测函数」(示例为通用公开写法)")
        body_lay.addWidget(self.segments)
        self.lbl_detect = QLabel("尚未检测")
        self.lbl_detect.setWordWrap(True)
        self.lbl_detect.setStyleSheet("font-size: 12px; color: #9AA3B2;")
        body_lay.addWidget(self.lbl_detect)
        func_lay.addWidget(self._func_body)
        top_lay.addWidget(self._func_card)

        # —— 卡片 ② 条件 ——
        self._cond_card = QFrame()
        self._cond_card.setStyleSheet(_CARD_QSS)
        cond_lay = QVBoxLayout(self._cond_card)
        cond_lay.setContentsMargins(16, 6, 10, 12)
        cond_lay.setSpacing(8)

        cond_head = QHBoxLayout()
        title_cond = QLabel("② 买卖条件组（每个条件一行 · 满足计数触发）")
        title_cond.setStyleSheet("font-size: 14px; font-weight: bold; color: #1976D2;")
        cond_head.addWidget(title_cond)
        cond_head.addStretch()
        cond_head.addWidget(
            self._hint_icon("组合逻辑=满足计数：全部满足(AND) / 任一满足(OR) / 至少 N 个满足；"
                            "底部预览为该组实时翻译出的表达式。每行规则：变量 + 算子 + 数值。"))
        self.btn_collapse_cond = QPushButton("收起 ▲")
        self.btn_collapse_cond.setStyleSheet("QPushButton { color:#8A94A6; background:transparent; border:none; padding:4px 6px; font-weight:bold; } QPushButton:hover{color:#1976D2;}")
        self.btn_collapse_cond.clicked.connect(lambda: self._toggle_collapse(self._cond_body, self.btn_collapse_cond))
        cond_head.addWidget(self.btn_collapse_cond)
        cond_lay.addLayout(cond_head)

        self._cond_body = QWidget()
        cond_body_lay = QVBoxLayout(self._cond_body)
        cond_body_lay.setContentsMargins(0, 0, 0, 0)
        cond_body_lay.setSpacing(8)

        param_row = QHBoxLayout()
        param_row.addWidget(self._mini_label("函数参数"))
        self.txt_params = QLineEdit()
        self.txt_params.setPlaceholderText("形如 N1=5 N2=20（对所有函数段统一生效）")
        self.txt_params.setFixedHeight(30)
        self.txt_params.setStyleSheet("QLineEdit { padding: 0 10px; border: 1px solid #E0E4EC; border-radius: 8px; background: white; font-size: 13px; }")
        param_row.addWidget(self.txt_params, 1)
        cond_body_lay.addLayout(param_row)

        grid_rows = QHBoxLayout()
        grid_rows.setSpacing(16)
        self.gate_buy = ConditionGate("买入条件", settings.COLOR_PROFIT_TEXT)
        self.gate_sell = ConditionGate("卖出条件", settings.COLOR_LOSS_TEXT)
        grid_rows.addWidget(self.gate_buy, 1)
        grid_rows.addWidget(self.gate_sell, 1)
        cond_body_lay.addLayout(grid_rows)
        cond_lay.addWidget(self._cond_body)
        top_lay.addWidget(self._cond_card)

        # —— 卡片 ③ 大盘/指数 regime 门控 (阶段C) ——
        self._index_card = QFrame()
        self._index_card.setStyleSheet(_CARD_QSS)
        index_lay = QVBoxLayout(self._index_card)
        index_lay.setContentsMargins(16, 6, 10, 12)
        index_lay.setSpacing(8)

        index_head = QHBoxLayout()
        title_idx = QLabel("③ 大盘/指数 regime 门控（可选）")
        title_idx.setStyleSheet("font-size: 14px; font-weight: bold; color: #6A1B9A;")
        index_head.addWidget(title_idx)
        index_head.addStretch()
        self.btn_collapse_index = QPushButton("收起 ▲")
        self.btn_collapse_index.setStyleSheet("QPushButton { color:#8A94A6; background:transparent; border:none; padding:4px 6px; font-weight:bold; } QPushButton:hover{color:#6A1B9A;}")
        self.btn_collapse_index.clicked.connect(
            lambda: self._toggle_collapse(self._index_body, self.btn_collapse_index))
        index_head.addWidget(self.btn_collapse_index)
        index_lay.addLayout(index_head)

        self._index_body = QWidget()
        idx_body_lay = QVBoxLayout(self._index_body)
        idx_body_lay.setContentsMargins(0, 0, 0, 0)
        idx_body_lay.setSpacing(8)

        # 顶行：启用 + 指数选择 + 缓存状态
        idx_row = QHBoxLayout()
        self.chk_index_enable = QCheckBox("启用大盘先决条件")
        self.chk_index_enable.toggled.connect(self._sync_index_enabled)
        idx_row.addWidget(self.chk_index_enable)
        idx_row.addWidget(self._mini_label("指数"))
        self.cmb_index = NoWheelComboBox()
        self.cmb_index.setEditable(True)
        self.cmb_index.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        # 关闭自动补全：手输代码不应被预设文本接管
        completer = self.cmb_index.completer()
        if completer is not None:
            completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.cmb_index.setStyleSheet(COMBO_QSS)
        for code, name in INDEX_PRESETS.items():
            self.cmb_index.addItem(f"{code}  {name}", code)
        self.cmb_index.setCurrentIndex(0)
        self.cmb_index.setFixedHeight(30)
        idx_row.addWidget(self.cmb_index, 1)
        self.lbl_index_status = QLabel("")
        self.lbl_index_status.setStyleSheet("font-size: 11px; color: #8A94A6;")
        idx_row.addWidget(self.lbl_index_status)
        idx_row.addWidget(
            self._hint_icon("指数 regime 门控：用与个股相同的函数段对所选指数再求值，"
                            "指数侧变量自动加 IDX_ 前缀。"
                            "买入：个股条件与「指数买入许可」同时成立才进场；"
                            "卖出：个股条件或「指数卖出破位」任一成立即离场。"
                            "首次回测若本地无指数数据将自动联网同步。"))
        idx_body_lay.addLayout(idx_row)

        idx_gates = QHBoxLayout()
        idx_gates.setSpacing(16)
        self.gate_index_buy = ConditionGate("指数买入许可", "#6A1B9A")
        self.gate_index_sell = ConditionGate("指数卖出破位", "#E65100")
        idx_gates.addWidget(self.gate_index_buy, 1)
        idx_gates.addWidget(self.gate_index_sell, 1)
        idx_body_lay.addLayout(idx_gates)
        index_lay.addWidget(self._index_body)
        top_lay.addWidget(self._index_card)
        top_lay.addStretch()

        # ========== 下区：回测工作台 ==========
        bottom_area = QWidget()
        bottom_lay = QVBoxLayout(bottom_area)
        bottom_lay.setContentsMargins(0, 0, 0, 0)
        bottom_lay.setSpacing(8)

        # 运行条
        run_bar = QFrame()
        run_bar.setStyleSheet(_CARD_QSS)
        run_lay = QHBoxLayout(run_bar)
        run_lay.setContentsMargins(14, 8, 14, 8)
        run_lay.addWidget(self._mini_label("回测区间"))
        self.cmb_range_preset = NoWheelComboBox()
        self.cmb_range_preset.addItems(_PRESET_ORDER)
        self.cmb_range_preset.currentTextChanged.connect(self._on_range_preset)
        run_lay.addWidget(self.cmb_range_preset)
        self.date_start = NoWheelDateEdit(QDate(2016, 1, 1))
        self.date_start.setCalendarPopup(True)
        self.date_start.setDisplayFormat("yyyy-MM-dd")
        # 最早可回溯到 2016-01-01：与 core/backtest.DEFAULT_START_DATE 同源，避免两处漂移
        self.date_start.setMinimumDate(QDate(2016, 1, 1))
        run_lay.addWidget(self.date_start)
        run_lay.addWidget(QLabel("至"))
        self.date_end = NoWheelDateEdit(QDate.currentDate())
        self.date_end.setCalendarPopup(True)
        self.date_end.setDisplayFormat("yyyy-MM-dd")
        run_lay.addWidget(self.date_end)
        run_lay.addStretch()
        self.lbl_run_status = QLabel("完成检测并配置买卖条件后即可运行")
        self.lbl_run_status.setStyleSheet("font-size: 12px; color: #1976D2;")
        run_lay.addWidget(self.lbl_run_status)
        self.btn_run = QPushButton("▶ 开始回测")
        self.btn_run.setStyleSheet("QPushButton { background:#1976D2; color:white; font-weight:bold; padding:8px 22px; border:none; border-radius:8px; font-size:14px;} QPushButton:hover { background:#1565C0; } QPushButton:disabled { background:#B8C6D8; }")
        self.btn_run.clicked.connect(self.start_backtest)
        run_lay.addWidget(self.btn_run)
        bottom_lay.addWidget(run_bar)

        # 风控离场行 (阶段B；0 = 关闭对应规则)
        risk_bar = QFrame()
        risk_bar.setStyleSheet(_CARD_QSS)
        risk_lay = QHBoxLayout(risk_bar)
        risk_lay.setContentsMargins(14, 6, 14, 6)
        risk_lay.setSpacing(8)
        shield = QLabel("🛡 风控离场")
        shield.setStyleSheet("font-size: 12px; font-weight: bold; color: #E65100;")
        risk_lay.addWidget(shield)
        risk_lay.addWidget(self._mini_label("最长持仓"))
        self.spin_risk_bars = self._risk_spin("若持有超过 N 根 K 线仍未卖出则当日收盘强平", 0, 0, 999, 0)
        risk_lay.addWidget(self.spin_risk_bars)
        risk_lay.addWidget(self._mini_label("根"))
        risk_lay.addWidget(self._mini_label("固定止损"))
        self.spin_risk_stop = self._risk_spin("收盘/盘中自开仓价回撤达到该百分比即离场 (0=关闭)", 0, 0, 100, 1)
        risk_lay.addWidget(self.spin_risk_stop)
        risk_lay.addWidget(self._mini_label("%"))
        risk_lay.addWidget(self._mini_label("固定止盈"))
        self.spin_risk_take = self._risk_spin("自开仓价上涨达到该百分比即止盈离场 (0=关闭)", 0, 0, 100, 1)
        risk_lay.addWidget(self.spin_risk_take)
        risk_lay.addWidget(self._mini_label("%"))
        risk_lay.addWidget(self._mini_label("移动止盈回撤"))
        self.spin_risk_trail = self._risk_spin("自持仓最高点回落该百分比即离场，保护浮盈 (0=关闭)", 0, 0, 100, 1)
        risk_lay.addWidget(self.spin_risk_trail)
        risk_lay.addWidget(self._mini_label("%"))
        risk_lay.addStretch()
        risk_lay.addWidget(
            self._hint_icon("硬性保护规则：盘中触发即离场，优先于卖出信号，谁先到谁执行。"
                            "任意一项设 0 即关闭；悬停各项输入框可看单独说明。"))
        bottom_lay.addWidget(risk_bar)

        # KPI 卡片行
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(10)
        self.card_total = _MetricCard("总成交", "#1F2430")
        self.card_win = _MetricCard("胜率", settings.COLOR_PROFIT_TEXT)
        self.card_cum = _MetricCard("累计收益", settings.COLOR_PROFIT_TEXT)
        self.card_avg = _MetricCard("平均单笔", settings.COLOR_TEXT_PRIMARY)
        for card in (self.card_total, self.card_win, self.card_cum, self.card_avg):
            card.setMinimumWidth(150)
            kpi_row.addWidget(card, 1)
        bottom_lay.addLayout(kpi_row)

        # K线显示控制
        kview = QHBoxLayout()
        kview.addWidget(self._mini_label("K线:"))
        self.chk_follow = QCheckBox("价格轴跟随可视区间")
        self.chk_follow.setChecked(True)
        self.chk_follow.toggled.connect(self._refresh_kline_view)
        kview.addWidget(self.chk_follow)
        self.chk_log = QCheckBox("对数价格")
        self.chk_log.toggled.connect(self._on_log_toggled)
        kview.addWidget(self.chk_log)
        # v6.4 / §7-B3 P3：公式叠层开关（默认开）。切换只改可见性，不重置缩放。
        self.chk_overlay = QCheckBox("显示公式叠层")
        self.chk_overlay.setChecked(True)
        self.chk_overlay.setToolTip("叠加函数里的公式线 / STICKLINE 状态柱 / DRAWICON 图标")
        self.chk_overlay.toggled.connect(self._on_overlay_toggled)
        kview.addWidget(self.chk_overlay)
        self.btn_fit_full = QPushButton("适应全量")
        self.btn_fit_full.clicked.connect(self._fit_kline_full)
        kview.addWidget(self.btn_fit_full)
        self.btn_fit_last = QPushButton("最近150日")
        self.btn_fit_last.clicked.connect(self._fit_kline_recent)
        kview.addWidget(self.btn_fit_last)
        kview.addStretch()

        # v5.14/v5.15：导出本次回测结果（仅导出，不删除/存档，见 §7-A2）。
        # 下拉菜单承载多种格式：CSV 明细（专业溯源）/ PNG 报告图（一图看懂）；
        # 未来要加 XLSX 等格式只需在此新增一个 action。
        self.btn_export_result = QPushButton("导出结果 ▾")
        self.btn_export_result.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_export_result.setStyleSheet(
            "QPushButton { color:#1976D2; background:transparent; border:1px solid #BBDEFB; "
            "border-radius:6px; padding:4px 12px; font-weight:bold; font-size:12px; }"
            "QPushButton:hover { background:#E3F2FD; }"
            "QPushButton::menu-indicator { image: none; padding-left: 4px; }")
        self.btn_export_result.setToolTip(
            "导出本次回测：CSV 明细供逐笔/参数溯源核查；PNG 报告图一图看懂结论。")
        self._export_menu = QMenu(self.btn_export_result)
        self._export_menu.setStyleSheet(
            "QMenu { background:white; border:1px solid #E0E0E0; border-radius:6px; padding:4px; }"
            "QMenu::item { padding:6px 18px; font-size:13px; color:#1F2430; border-radius:4px; }"
            "QMenu::item:selected { background:#E3F2FD; color:#1976D2; }")
        act_csv = self._export_menu.addAction("📄 导出 CSV 明细…")
        act_csv.setToolTip("逐笔成交 + 参数快照 + 风控 + 指数门控（无净值行，溯源用）")
        act_csv.triggered.connect(self.export_result)
        act_png = self._export_menu.addAction("🖼 导出结果图 PNG…")
        act_png.setToolTip("单页报告图：KPI + 净值曲线 + 离场原因饼图 + 参数简表，打开即懂")
        act_png.triggered.connect(self.export_result_png)
        self.btn_export_result.setMenu(self._export_menu)
        kview.addWidget(self.btn_export_result)

        bottom_lay.addLayout(kview)

        # 结果页签
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("QTabWidget::pane { border:1px solid #E7EAF0; border-radius:10px; background:white; top:-1px;} QTabBar::tab { background:transparent; color:#8A94A6; padding:8px 18px; font-weight:bold; } QTabBar::tab:selected { color:#1976D2; border-bottom:3px solid #1976D2; }")
        self.equity_chart = pg.PlotWidget()
        self._style_chart(self.equity_chart)
        self.tabs.addTab(self.equity_chart, "📈 净值曲线")
        self.kline_chart = pg.PlotWidget()
        self._style_chart(self.kline_chart)
        self.tabs.addTab(self.kline_chart, "🕯️ K线买卖点")
        self.compare_tab = QWidget()
        self._build_compare_tab()
        self.tabs.addTab(self.compare_tab, "🧭 策略对比")
        self.trades_table = QTableWidget()
        self.trades_table.setColumnCount(9)
        self.trades_table.setHorizontalHeaderLabels(["#", "买入日期", "买入价", "卖出日期", "卖出价", "持有天数", "盈亏", "收益率", "离场原因"])
        self.trades_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.trades_table.setAlternatingRowColors(True)
        self.trades_table.setStyleSheet("QTableWidget { background: white; alternate-background-color: #F7F9FC; border:none; gridline-color:#EEF1F6;} QHeaderView::section { background:#F4F6FA; color:#5B6472; font-weight:bold; border:none; padding:8px; }")
        self.tabs.addTab(self.trades_table, "🧾 成交明细")
        bottom_lay.addWidget(self.tabs, 1)

        self._splitter.addWidget(self._config_scroll)
        self._splitter.addWidget(bottom_area)
        self._splitter.setSizes([420, 520])
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        root.addWidget(self._splitter, 1)

    # ---------- 小构件 ----------
    @staticmethod
    def _mini_label(text):
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size: 12px; font-weight: bold; color: #5B6472;")
        return lbl

    @staticmethod
    def _hint_icon(tooltip: str) -> QLabel:
        """灰字说明弱化：用一个小 ? 角标承载 tooltip，代替占据版面的长灰字"""
        icon = QLabel("?")
        icon.setFixedSize(15, 15)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("QLabel { background:#E3E7EF; color:#7A8392; border-radius:7px;"
                           " font-size:10px; font-weight:bold; }")
        icon.setToolTip(tooltip)
        return icon

    @staticmethod
    def _risk_spin(tooltip: str, value: float, lo: float, hi: float, decimals: int) -> NoWheelDoubleSpinBox:
        spin = NoWheelDoubleSpinBox()
        spin.setRange(lo, hi)
        spin.setDecimals(decimals)
        spin.setValue(value)
        spin.setSingleStep(1 if decimals == 0 else 0.5)
        # 宽度留足：原生箭头 + 数值 + 边距，避免窄控件挤压箭头导致热区与图标不符
        spin.setMinimumWidth(72)
        spin.setToolTip(tooltip)
        # 【一致性】与买卖条件组的数值控件共用同一套样式（原生渲染）。
        # 切勿在此就地写 QDoubleSpinBox 半截 QSS —— 会破坏子控件度量，
        # 造成箭头图标不一致 + 上箭头只有部分区域可点（见 custom_widgets.SPINBOX_QSS）。
        spin.setStyleSheet(SPINBOX_QSS)
        return spin

    def _risk_config(self) -> dict:
        """读取风控参数行 -> 引擎 risk dict (0 = 关闭)"""
        return {
            "max_bars": int(self.spin_risk_bars.value()),
            "stop_loss_pct": float(self.spin_risk_stop.value()),
            "take_profit_pct": float(self.spin_risk_take.value()),
            "trailing_pct": float(self.spin_risk_trail.value()),
        }

    def _apply_risk_config(self, cfg: dict):
        """从策略快照恢复风控参数 (字段缺失/非法则回落 0)"""
        cfg = cfg or {}
        for spin, key in ((self.spin_risk_bars, "max_bars"),
                          (self.spin_risk_stop, "stop_loss_pct"),
                          (self.spin_risk_take, "take_profit_pct"),
                          (self.spin_risk_trail, "trailing_pct")):
            try:
                spin.setValue(float(cfg.get(key, 0) or 0))
            except (TypeError, ValueError):
                spin.setValue(0)

    def _build_compare_tab(self):
        lay = QVBoxLayout(self.compare_tab)
        lay.setContentsMargins(10, 10, 10, 10)
        title = QLabel("🧭 当前标的下，已保存策略的回测表现对比")
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #1F2430;")
        lay.addWidget(title)
        desc = QLabel("运行某个已选用策略并完成回测后，指标会自动归档。横向比较可快速判断该股票更适合哪套策略。")
        desc.setStyleSheet("font-size: 12px; color: #8A94A6;")
        desc.setWordWrap(True)
        lay.addWidget(desc)

        self.compare_chart = pg.PlotWidget()
        self._style_chart(self.compare_chart)
        self.compare_chart.getPlotItem().setLabel('left', '累计收益')
        lay.addWidget(self.compare_chart, 1)

        self.compare_table = QTableWidget()
        self.compare_table.setColumnCount(5)
        self.compare_table.setHorizontalHeaderLabels(["策略", "总成交", "胜率", "累计收益", "归档时间"])
        self.compare_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.compare_table.setAlternatingRowColors(True)
        self.compare_table.setStyleSheet("QTableWidget { background: white; alternate-background-color:#F7F9FC; border:1px solid #E7EAF0; border-radius:8px; } QHeaderView::section { background:#F4F6FA; color:#5B6472; font-weight:bold; padding:6px; border:none; }")
        lay.addWidget(self.compare_table, 1)

    # ==========================================
    # ① 函数检测 / 参数
    # ==========================================
    @staticmethod
    def _parse_params_text(text: str) -> dict:
        """（v6.6 起委托 core.utils.parse_params_text —— 行情页参数框共用同一份）"""
        return parse_params_text(text)

    # ==========================================
    # 公式资产化 + 互送（P7 · §7-B3 P7）
    # ==========================================
    # 【与行情页的分工】行情页保留每段的"主图/副图"目标；回测页**没有副图概念**，
    # 所以互送时只带函数文本 + 参数。要连窗格一起留档，就用「💾 存为配方」——
    # 配方里 `segments[i].target` 是存下来的（行情页载入时原样还原）。
    def load_formula_from_external(self, texts, params_text: str = "") -> int:
        """接收外来公式（行情页「📤 送去做回测」/ 配方库）：填进函数段 + 参数，并自动检测。

        :return: 实际载入的段数（0 = 内容为空，什么都没做）
        """
        clean = [str(text).strip() for text in (texts or []) if str(text or "").strip()]
        if not clean:
            return 0
        self.segments.set_texts(clean)
        self.txt_params.setText(str(params_text or ""))
        self.detect_function(quiet=True)      # 送来的函数立刻自检：语法/缺参当场可见
        return len(clean)

    def current_formula_segments(self) -> list[str]:
        return [text.strip() for text in self.segments.texts() if text.strip()]

    def save_formula_as(self):
        """把①里的函数 + 参数存成配方（同名即覆盖）。"""
        texts = self.current_formula_segments()
        if not texts:
            QMessageBox.information(self, "暂无函数", "先在①里粘贴函数，再保存为配方。")
            return
        name, ok = QInputDialog.getText(self, "保存为配方", "配方名称（同名即覆盖）：")
        if not ok:
            return
        try:
            formula = make_formula(name, texts, params_text=self.txt_params.text(),
                                   source=SOURCE_BACKTEST)
        except ValueError as e:
            QMessageBox.warning(self, "无法保存", str(e))
            return
        saved = self.formula_store.upsert(formula)
        self._set_detect(True, f"✓ 已存入配方库：{saved['name']}")

    def open_formula_library(self):
        """打开配方库并载入选中项（行情页存下的配方在这里同样能用）。"""
        dialog = FormulaLibraryDialog(self.formula_store, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        formula = dialog.selected_formula()
        if not formula:
            return
        count = self.load_formula_from_external(segments_as_texts(formula),
                                                formula.get("params_text", ""))
        self._set_detect(True, f"✓ 已从配方库载入「{formula['name']}」（{count} 段）")

    def send_formula_to_market(self) -> int:
        """回测页 → 行情页（由主窗口转交，两个页面互不 import）；返回送过去的段数。"""
        texts = self.current_formula_segments()
        if not texts:
            QMessageBox.information(self, "暂无函数", "先在①里粘贴函数，再送到行情页。")
            return 0
        count = self.main_win.send_formula_to_market(texts, self.txt_params.text())
        if count:
            self._set_detect(True, f"✓ 已把 {count} 段函数送到「📈 市场行情」")
        return count

    def detect_function(self, quiet: bool = False):
        """多段函数：逐段解析 + 共享 context 试运行 + 缺参自动探测 (阶段A)"""
        texts = [t.strip() for t in self.segments.texts() if t.strip()]
        if not texts:
            if not quiet:
                QMessageBox.information(self, "提示", "请先粘贴函数内容。")
            return

        # 逐段解析，错误精确报出在哪一段
        programs = []
        for idx, text in enumerate(texts, start=1):
            try:
                programs.append(parse_program(text))
            except FormulaProgramError as e:
                self._set_detect(False, f"❌ 函数段 {idx}: {e}")
                return

        # 合并变量名 (保留声明顺序、去重；同名由后段覆盖，语义与单段一致)
        variables = []
        for program in programs:
            for name in program.output_names:
                if name not in variables:
                    variables.append(name)

        params = self._parse_params_text(self.txt_params.text())
        dummy = _dummy_bars()
        try:
            # v6.4：检测阶段就走"变量 + 绘图"入口，函数段里写错的绘图语句**当场**报出。
            # v6.6：缺参探测上收到引擎层（probe_missing_parameters）—— 行情页共用同一份口径，
            #       免得同一函数"行情页能跑、回测页缺参"（§11.5-11 同类防护做全套）。
            missing, _ = probe_missing_parameters(programs, params, dummy)
        except FormulaProgramError as e:
            self._set_detect(False, f"❌ {e}")
            return
        if missing:
            self._set_detect(False,
                f"❌ 缺少参数: {'、'.join(missing)}。请在「函数参数」中填写后重新检测。")
            return
        try:
            execute_programs_with_draws(programs, dummy, params)
        except FormulaProgramError as e:
            self._set_detect(False, f"❌ {e}")
            return

        self._programs = programs
        self._variables = variables
        # v6.5（§9-Q）：已知但本期不渲染的绘图语句 —— **不阻断运行**，只汇总成提示，
        # 避免"存量已保存的函数因为一行暂时画不出的语句而彻底跑不起来"。
        unsupported, unsupported_count = [], 0
        for program in programs:
            unsupported_count += program.unsupported_count
            for name in program.unsupported:
                if name not in unsupported:
                    unsupported.append(name)
        message = (
            f"✓ 可运行。识别 {len(self._variables)} 个共享变量: {', '.join(self._variables[:10])}"
            f"{' …' if len(self._variables) > 10 else ''}")
        if unsupported:
            message += f"　⚠ 本期不渲染 {unsupported_count} 处: {'、'.join(unsupported)}"
        self._set_detect(True, message)
        self.gate_buy.set_variables(self._variables)
        self.gate_sell.set_variables(self._variables)
        # 指数门控的变量池：同一批函数段在大盘上求值，产出 IDX_ 前缀变量 (阶段C)
        idx_vars = [f"IDX_{v}" for v in self._variables]
        self.gate_index_buy.set_variables(idx_vars)
        self.gate_index_sell.set_variables(idx_vars)
        self._set_condition_enabled(True)

    def _set_detect(self, ok: bool, message: str):
        self.lbl_detect.setText(message)
        # 单行标签放不下会长提示会被省略号截断 —— 完整内容一律进 tooltip
        self.lbl_detect.setToolTip(message)
        self.lbl_detect.setStyleSheet(
            f"font-size: 12px; color: {'#4CAF50' if ok else '#F44336'}; font-weight: bold;")

    # ==========================================
    # ② 条件 (Gate 桥接) + ③ 指数门控
    # ==========================================
    def _set_condition_enabled(self, enabled: bool):
        self.gate_buy.set_gate_enabled(enabled)
        self.gate_sell.set_gate_enabled(enabled)
        self._sync_index_enabled(self.chk_index_enable.isChecked() if enabled else False)
        self.btn_run.setEnabled(enabled)

    def _sync_index_enabled(self, enabled: bool):
        """指数门控启用联动：勾选开启 + 函数已检测才可配条件"""
        on = bool(enabled) and bool(self._variables)
        self.gate_index_buy.set_gate_enabled(on)
        self.gate_index_sell.set_gate_enabled(on)
        self.cmb_index.setEnabled(bool(enabled) and bool(self._variables))
        if on and self._index_symbol():
            self._refresh_index_status()

    def _index_symbol(self) -> str:
        """读取当前指数代码 (下拉选中或手动输入，规范化为新浪格式)"""
        text = self.cmb_index.currentText().strip()
        if not text:
            return ""
        # 支持用户直接输入 000300 -> 自动补 sh 前缀兜底 (仅对常见6位，用户亦可显式 sh/sz)
        sym = text.split()[0] if text else ""
        if sym.isdigit() and len(sym) == 6:
            return f"sh{sym}"
        return sym.lower()

    def _refresh_index_status(self):
        """刷新指数本地缓存状态提示"""
        symbol = self._index_symbol()
        if not symbol or not is_index_symbol(symbol):
            self.lbl_index_status.setText("需形如 sh000001 / sz399001")
            return
        cached = self.data_lake.exists("index_daily", symbol)
        self.lbl_index_status.setText("✓ 本地已缓存" if cached else "首次回测将自动联网同步")

    # ==========================================
    # 策略库 (选用 / 保存 / 删除 / 对比)
    # ==========================================
    def _strategy_payload(self) -> dict:
        """把当前编辑器状态打包为可持久化的策略快照 (阶段A 多段结构)

        存储约定：
        - segments: [各段函数文本]，UI 还原时精确恢复多段；
        - function: 各段以分号连接的合并文本，保留给 strategy_store 的
          find_same 签名与旧版载入逻辑 (分号连接 = 同一 EvalContext 顺序执行，语义等价)。
        """
        texts = [t.strip() for t in self.segments.texts() if t.strip()]
        return {
            "name": "",
            "note": "",
            "segments": texts,
            "function": "; ".join(texts),
            "params_text": self.txt_params.text().strip(),
            "condition_buy": self.gate_buy.config(),
            "condition_sell": self.gate_sell.config(),
            "risk": self._risk_config(),
            "index": self._index_config(),
            "start_date": self.date_start.date().toString("yyyy-MM-dd"),
            "end_date": self.date_end.date().toString("yyyy-MM-dd"),
            "symbol": self.current_symbol,
        }

    def _reload_strategy_combo(self, keep_active: str | None = None):
        strategies = self.store.list_strategies()
        self.cmb_strategy.blockSignals(True)
        self.cmb_strategy.clear()
        for item in strategies:
            self.cmb_strategy.addItem(str(item.get("name", "未命名")), item.get("id"))
        idx = -1
        if keep_active:
            for i in range(self.cmb_strategy.count()):
                if self.cmb_strategy.itemData(i) == keep_active:
                    idx = i
                    break
        if idx >= 0:
            self.cmb_strategy.setCurrentIndex(idx)
        elif strategies:
            self.cmb_strategy.setCurrentIndex(0)
        self.cmb_strategy.blockSignals(False)
        if idx < 0 and strategies:
            self._on_strategy_selected(self.cmb_strategy.currentIndex())

    def _on_strategy_selected(self, index: int):
        if index < 0:
            self._active_strategy_id = None
            return
        strategy = self.store.get(self.cmb_strategy.itemData(index))
        if not strategy:
            return
        self._active_strategy_id = strategy.get("id")
        # 载入函数：新档用 segments 多段还原；旧档回落单段 function
        segments = strategy.get("segments") or [str(strategy.get("function", ""))]
        self.segments.set_texts([s for s in segments if s and s.strip()])
        self.txt_params.setText(str(strategy.get("params_text", "")))
        if strategy.get("start_date"):
            self.date_start.setDate(QDate.fromString(strategy["start_date"], "yyyy-MM-dd"))
        if strategy.get("end_date"):
            self.date_end.setDate(QDate.fromString(strategy["end_date"], "yyyy-MM-dd"))
        self.detect_function(quiet=True)
        # 还原买卖条件组 (新结构 {logic,n,conditions} 与旧平铺 dict 均兼容)
        self.gate_buy.load_config(strategy.get("condition_buy") or {})
        self.gate_sell.load_config(strategy.get("condition_sell") or {})
        # 还原风控参数 (旧策略无 risk 字段 -> 回落 0 全关闭)
        self._apply_risk_config(strategy.get("risk") or {})
        # 还原指数 regime 门控 (旧策略无 index 字段 -> 全关)
        self._apply_index_config(strategy.get("index") or {})
        self.lbl_run_status.setText(f"已载入策略「{strategy.get('name')}」，请选择股票后运行。")

    def _index_config(self) -> dict:
        """读取当前指数门控状态 (阶段C)"""
        return {
            "enabled": bool(self.chk_index_enable.isChecked()),
            "symbol": self._index_symbol(),
            "buy": self.gate_index_buy.config(),
            "sell": self.gate_index_sell.config(),
        }

    def _apply_index_config(self, cfg: dict):
        """从策略快照恢复指数门控；缺失/非法一律回落关闭"""
        cfg = cfg or {}
        self.chk_index_enable.setChecked(bool(cfg.get("enabled", False)))
        symbol = str(cfg.get("symbol", "") or "").strip()
        if symbol:
            # 下拉中查找；不存在则以文本方式置入 (可编辑下拉支持任意新浪代码)
            idx = self.cmb_index.findData(symbol)
            if idx >= 0:
                self.cmb_index.setCurrentIndex(idx)
            else:
                self.cmb_index.setEditText(symbol)
        self.gate_index_buy.load_config(cfg.get("buy") or {})
        self.gate_index_sell.load_config(cfg.get("sell") or {})
        self._sync_index_enabled(self.chk_index_enable.isChecked())

    def save_strategy(self):
        if not self._programs:
            QMessageBox.information(self, "提示", "请先完成函数检测后再保存。")
            return
        payload = self._strategy_payload()
        name, ok = QInputDialog.getText(self, "保存策略", "策略名称:")
        name = (name or "").strip()
        if not ok or not name:
            return
        payload["name"] = name
        strategy_id = self.store.upsert(payload)
        self._active_strategy_id = strategy_id
        self._reload_strategy_combo(keep_active=strategy_id)
        self.lbl_run_status.setText(f"✅ 已保存策略「{name}」，下次可直接选用。")

    def delete_strategy(self):
        if not self._active_strategy_id:
            return
        strategy = self.store.get(self._active_strategy_id)
        if not strategy:
            return
        reply = QMessageBox.question(self, "删除策略", f"确认删除「{strategy.get('name')}」？")
        if reply == QMessageBox.StandardButton.Yes:
            self.store.delete(self._active_strategy_id)
            self._active_strategy_id = None
            self._reload_strategy_combo()
            self._render_compare()

    def _archive_current_result(self, summary: dict):
        """回测完成后：关联到当前/同配置策略并归档指标，刷新对比"""
        strategy_id = self._active_strategy_id
        if not strategy_id:
            strategy_id = self.store.find_same(self._strategy_payload())
        if strategy_id:
            self.store.record_result(strategy_id, self.current_symbol or "", summary)
            self._active_strategy_id = strategy_id
            self._reload_strategy_combo(keep_active=strategy_id)
            self._render_compare()

    def _render_compare(self):
        symbol = self.current_symbol or ""
        snapshots = self.store.metrics_snapshot(symbol)
        self.compare_table.setRowCount(len(snapshots))
        for row, snap in enumerate(snapshots):
            strategy = snap["strategy"]
            metrics = snap["metrics"]
            name_item = QTableWidgetItem(str(strategy.get("name", "-")))
            cum = metrics.get("cumulative_return")
            win = metrics.get("win_rate")
            if cum is not None:
                name_item.setForeground(QColor(settings.COLOR_PROFIT_TEXT if cum > 0 else settings.COLOR_LOSS_TEXT))
            self.compare_table.setItem(row, 0, name_item)
            self.compare_table.setItem(row, 1, QTableWidgetItem(str(metrics.get("total_trades", "-"))))
            self.compare_table.setItem(row, 2, QTableWidgetItem(
                f"{win * 100:.1f}%" if win is not None else "-"))
            self.compare_table.setItem(row, 3, QTableWidgetItem(
                f"{cum * 100:+.1f}%" if cum is not None else "-"))
            self.compare_table.setItem(row, 4, QTableWidgetItem(str(metrics.get("recorded_at", "-"))))
        self._render_compare_chart(snapshots)

    def _render_compare_chart(self, snapshots):
        self.compare_chart.clear()
        if not snapshots:
            self.compare_chart.getPlotItem().setTitle(
                "暂无该标的的归档结果：选用策略并完成回测后会自动出现在这里",
                color="#9AA3B2", size="10pt")
            return
        names = [str(s["strategy"].get("name", "?"))[:12] for s in snapshots]
        cums = [float(s["metrics"].get("cumulative_return", 0.0)) for s in snapshots]
        x = list(range(len(cums)))
        brushes = [pg.mkBrush(settings.COLOR_PROFIT if c >= 0 else settings.COLOR_LOSS) for c in cums]
        pens = [pg.mkPen(settings.COLOR_PROFIT if c >= 0 else settings.COLOR_LOSS) for c in cums]
        self.compare_chart.addItem(pg.BarGraphItem(x=x, height=cums, width=0.6, brushes=brushes, pens=pens))
        self.compare_chart.addLine(y=0, pen=pg.mkPen(color='#C3CAD6', style=Qt.PenStyle.DashLine))
        axis = self.compare_chart.getAxis('bottom')
        axis.setTicks([[(i, name) for i, name in enumerate(names)]])

    # ==========================================
    # 股票 / 区间 / 运行
    # ==========================================
    def select_symbol(self):
        keyword = self.txt_symbol.text().strip()
        if not keyword:
            QMessageBox.information(self, "提示", "请输入股票代码或名称。")
            return
        res_df = self.main_win.engine.search_symbol(keyword)   # 经 DataEngine 门面，UI 不碰 DAO
        if res_df.empty:
            QMessageBox.warning(self, "未找到", f"花名册中没有 '{keyword}'。")
            return
        symbol = str(res_df.iloc[0]['symbol'])
        name = str(res_df.iloc[0]['name'])
        if not is_stock_code(symbol):
            QMessageBox.warning(self, "仅支持A股", f"'{name} ({symbol})' 不是A股标的。")
            return
        self.current_symbol = symbol
        self.current_name = name
        self.txt_symbol.setText(symbol)
        self.lbl_symbol.setText(f"{name} ({symbol})" + (" · 已缓存" if self.data_lake.exists("kline_daily", symbol) else ""))
        self._render_compare()

    def _on_range_preset(self, preset: str):
        self.date_start.setDate(_date_from_preset(preset))

    def start_backtest(self):
        if not self.current_symbol:
            QMessageBox.information(self, "提示", "请先选择一只A股标的。")
            return
        if not self._programs:
            QMessageBox.information(self, "提示", "请先完成函数检测。")
            return
        buy_expr = (self.gate_buy.expression() or "").strip()
        sell_expr = (self.gate_sell.expression() or "").strip()
        if not buy_expr or not sell_expr:
            QMessageBox.warning(self, "条件缺失", "买入/卖出至少各配置一个有效条件。")
            return
        self._pending_run = (buy_expr, sell_expr)
        self._pending_params = self._parse_params_text(self.txt_params.text())
        self._pending_risk = self._risk_config()

        # 指数 regime 门控配置 (阶段C)：仅当启用且至少一侧配了条件才需要指数数据
        index_cfg = None
        if self.chk_index_enable.isChecked():
            symbol = self._index_symbol()
            if not is_index_symbol(symbol):
                QMessageBox.warning(self, "指数代码", "请输入有效的新浪指数代码，形如 sh000001 / sz399001。")
                return
            idx_buy = (self.gate_index_buy.expression() or "").strip()
            idx_sell = (self.gate_index_sell.expression() or "").strip()
            if idx_buy or idx_sell:
                index_cfg = {"symbol": symbol, "expr_buy": idx_buy, "expr_sell": idx_sell}
        self._pending_index = index_cfg

        # 【v5.14 导出】在发起回测这一刻定格参数快照（此后编辑框怎么改都不影响导出内容）
        strategy_name = ""
        if self._active_strategy_id:
            saved = self.store.get(self._active_strategy_id)
            strategy_name = str(saved.get("name", "")) if saved else ""
        self._last_meta = {
            "symbol": self.current_symbol,
            "name": self.current_name,
            "strategy_name": strategy_name,
            "start_date": self.date_start.date().toString("yyyy-MM-dd"),
            "end_date": self.date_end.date().toString("yyyy-MM-dd"),
            "segments": [t.strip() for t in self.segments.texts() if t.strip()],
            "params_text": self.txt_params.text().strip(),
            "buy_expr": buy_expr,
            "sell_expr": sell_expr,
            "risk": self._risk_config(),
            "index": index_cfg,
        }

        self._prepare_index_then_stock()

    def _prepare_index_then_stock(self):
        """阶段C 数据就绪链：先指数(若启用) 后个股，均就绪后执行回测"""
        if not self._pending_index:
            self._prepare_stock_then_run()
            return
        symbol = self._pending_index["symbol"]
        idx_df = self.data_lake.load_data(ZONE_INDEX, symbol)
        if idx_df.empty:
            self._set_busy(True, f"本地无指数 {symbol} 数据，正在联网同步...")
            self._index_thread = SingleSyncWorker(symbol, zone=ZONE_INDEX, parent=self)
            self._index_thread.finished.connect(self._on_index_synced)
            self._index_thread.start()
        else:
            self._prepare_stock_then_run()

    def _on_index_synced(self, result: dict):
        # 【竞态防护】同步期间用户可能改了指数代码，过期结果必须丢弃 (v5.12 · §9-O5)
        pending = getattr(self, '_pending_index', None) or {}
        if str(result.get("symbol", "")) != str(pending.get("symbol", "")):
            return
        if not result.get("ok"):
            self._set_busy(False, "")
            symbol = str(result.get("symbol", ""))
            QMessageBox.warning(
                self, "指数同步失败",
                friendly_fetch_message(symbol, result)
                + "\n\n（指数代码须形如 sh000001 / sz399001）")
            return
        self._prepare_stock_then_run()

    def _prepare_stock_then_run(self):
        df = self.data_lake.load_data(ZONE_KLINE, self.current_symbol)
        if df.empty:
            self._set_busy(True, "本地无日线，正在联网同步...")
            self._sync_thread = SingleSyncWorker(self.current_symbol, zone=ZONE_KLINE,
                                                 parent=self)
            self._sync_thread.finished.connect(self._on_synced)
            self._sync_thread.start()
        else:
            self._on_data_ready(df)

    def _on_synced(self, result: dict):
        symbol = str(result.get("symbol", self.current_symbol) or self.current_symbol)
        # 【竞态防护】拉取期间用户可能已切到别的标的，过期结果必须丢弃 (v5.12 · §9-O5)。
        # 与 ui/views/market.py 的 _on_sync_finished 同一手法 —— 同类防护要做就做全套。
        if symbol != self.current_symbol:
            self._set_busy(False, "")
            return
        if not result.get("ok"):
            self._set_busy(False, "行情同步失败。")
            QMessageBox.warning(self, "同步失败", friendly_fetch_message(symbol, result))
            return
        df = self.data_lake.load_data(ZONE_KLINE, symbol)
        if df.empty:
            self._set_busy(False, "行情同步失败，请检查网络。")
            QMessageBox.critical(self, "同步失败", f"无法获取 {symbol} 日线数据。")
            return
        self._on_data_ready(df)

    def _on_data_ready(self, df):
        params = getattr(self, '_pending_params', {})
        try:
            # v6.4 / §7-B3 P3：同一次求值**同时**产出 变量 + 绘图 IR（不二次求值）
            results, draws = execute_programs_with_draws(self._programs, df, params)
        except FormulaProgramError as e:
            self._set_busy(False, "")
            QMessageBox.critical(self, "函数执行失败", f"在真实行情上执行函数失败：\n{e}")
            return
        self._last_draws = draws

        merged = df.copy()
        collisions = sorted(set(results) & set(merged.columns))
        if collisions:
            self._set_busy(False, "")
            QMessageBox.critical(self, "命名冲突",
                                 f"函数变量与行情列重名: {', '.join(collisions)}。请改名后重试。")
            return
        for name, series in results.items():
            merged[name] = series.values

        buy_expr, sell_expr = self._pending_run
        risk = getattr(self, '_pending_risk', {}) or {}

        # 阶段C：指数 regime 门控列拼接 (引擎零改动)
        index_cfg = getattr(self, '_pending_index', None)
        if index_cfg:
            try:
                gated = self._attach_index_gates(merged, index_cfg, params)
            except FormulaProgramError as e:
                self._set_busy(False, "")
                QMessageBox.critical(self, "指数求值失败",
                                     "指数 regime 门控求值失败。请确认函数段仅依赖 K线列"
                                     "(C/O/H/L/V)，若函数含个股专属逻辑请拆成单独段。\n\n" + str(e))
                return
            if gated is not None:
                merged, buy_expr, sell_expr = gated

        self._last_df = merged.copy()
        self._set_busy(True, "回测计算中...")
        self._run_thread = BacktestRunWorker(
            merged, self.current_symbol, buy_expr, sell_expr,
            self.date_start.date().toString("yyyy-MM-dd"),
            self.date_end.date().toString("yyyy-MM-dd"),
            risk=risk)
        self._run_thread.finished_signal.connect(self._on_result)
        self._run_thread.start()

    def _attach_index_gates(self, merged: pd.DataFrame, index_cfg: dict, params: dict):
        """在个股 df 上拼入指数门控列，并返回合成后的 (merged, buy_expr, sell_expr)。

        实现要点 (引擎零改动)：
        1) 对指数日线执行同一批函数段 -> 变量加 IDX_ 前缀，供指数 Gate 表达式引用；
        2) 指数 Gate 表达式在指数行情上求值 -> 布尔门控；
        3) 门控布尔序列用 align_by_date 对齐到个股交易日 (缺失日 ffill, 前导默认 0)；
        4) 门控列(IDX_GATE_BUY/SELL)拼入 merged，买卖表达式 AND/OR 引用该列。
        """
        symbol = index_cfg.get("symbol")
        idx_buy_expr = (index_cfg.get("expr_buy") or "").strip()
        idx_sell_expr = (index_cfg.get("expr_sell") or "").strip()
        if not idx_buy_expr and not idx_sell_expr:
            return merged, self._pending_run[0], self._pending_run[1]

        idx_df = self.data_lake.load_data("index_daily", symbol)
        if idx_df.empty:
            QMessageBox.critical(self, "指数数据缺失",
                                 f"本地没有指数 {symbol} 数据，请重试运行(将自动联网同步)。")
            return None

        # 1) 指数侧执行函数段 -> IDX_ 变量列
        idx_vars = execute_programs(self._programs, idx_df, params)
        idx_ext = idx_df.copy()
        for name, series in idx_vars.items():
            idx_ext[f"IDX_{name}"] = series.values

        def build_gate(expr: str) -> pd.Series | None:
            if not expr:
                return None
            try:
                gate = FormulaEngine.signal(expr, idx_ext, params)
            except Exception as e:
                raise FormulaProgramError(f"指数门控表达式 {expr} 求值失败: {e}") from None
            # 以指数日期为索引 -> 对齐到个股交易日
            dated = pd.Series(gate.to_numpy(), index=pd.to_datetime(idx_ext['date']))
            aligned = align_by_date({"G": dated}, pd.to_datetime(merged['date']))["G"]
            return pd.Series(aligned.to_numpy(), index=merged.index)

        gate_buy = build_gate(idx_buy_expr)
        gate_sell = build_gate(idx_sell_expr)
        merged = merged.copy()
        if gate_buy is not None:
            merged["IDX_GATE_BUY"] = gate_buy.to_numpy()
        if gate_sell is not None:
            merged["IDX_GATE_SELL"] = gate_sell.to_numpy()

        buy_expr, sell_expr = self._pending_run
        if gate_buy is not None:
            buy_expr = f"({buy_expr}) AND IDX_GATE_BUY"
        if gate_sell is not None:
            sell_expr = f"({sell_expr}) OR IDX_GATE_SELL"
        return merged, buy_expr, sell_expr

    def _on_result(self, result):
        self._set_busy(False, "")
        if result is None:
            QMessageBox.critical(self, "回测失败",
                                 "回测失败。请确认条件变量存在于函数输出中，并检查参数/公式。")
            return
        self._last_result = result
        self._render_result(result)
        summary = result.summary()
        self._archive_current_result(summary)

    def _set_busy(self, busy: bool, text: str = ""):
        self.btn_run.setEnabled(not busy)
        self.btn_select.setEnabled(not busy)
        self.btn_detect.setEnabled(not busy)
        if text:
            self.lbl_run_status.setText(text)

    # ==========================================
    # 结果导出 (v5.14 · §7-A2)
    # ==========================================
    @staticmethod
    def _risk_readable(risk: dict) -> str:
        """风控人话文案 —— v5.15 起统一走 core/backtest.risk_summary，避免两处漂移"""
        return risk_summary(risk)

    def _compose_result_csv(self, result, meta: dict) -> str:
        """把一次回测结果渲染成规范 CSV 文本（表头参数块 + 逐笔成交明细）。

        拆成纯函数便于断言：导出的东西必须等于"这次跑出来的结果"，不掺现编。
        v5.15 起**不再输出每日净值行**（用户拍板，见文件尾注释）。

        【v5.16 为什么连"注释头行"都走 csv.writer 转义】
        函数源码里很多行含**英文逗号**（`STICKLINE(A, B, C, 3, 0), COLORFF0000;`、
        `MA(C, 5)`）。若像 v5.15 那样"裸写"，Excel/WPS 打开时会把这类行
        按逗号拆成多列，"第三部分：图形绘制"看起来就是碎成一格格的乱码。
        正确做法：每个逻辑行作为一个**单格字段**交给 csv.writer —— 含逗号的
        行被规范加引号（任何表格软件都把它还原成"一格"），不含逗号的行原样单格；
        空行用 `writerow([])`（真·空行，不会产生 `""` 假空行）。
        """
        import csv
        import io

        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")

        def row(text: str):
            writer.writerow([text])   # 单格行：csv 自动决定是否加引号

        def blank():
            writer.writerow([])       # 真·空行，避免产生 `""`

        # ---- 表头：参数快照（来自 start_backtest 定格的那份）----
        row("# 交易品种: {name} ({symbol})".format(
            name=meta.get("name") or "-", symbol=meta.get("symbol") or "-"))
        row(f"# 回测区间: {meta.get('start_date')} ~ {meta.get('end_date')}")
        row(f"# 策略: {meta.get('strategy_name') or '（未保存）'}")
        if meta.get("segments"):
            row("# 函数段:（以下每行一段，多段在同一个变量池顺序执行）")
            for seg in meta["segments"]:
                for seg_line in str(seg).splitlines():
                    row("    " + seg_line)
        row(f"# 函数参数: {meta.get('params_text') or '（无）'}")
        row(f"# 买入表达式: {meta.get('buy_expr')}")
        row(f"# 卖出表达式: {meta.get('sell_expr')}")
        row(f"# 风控: {self._risk_readable(meta.get('risk') or {})}")
        index = meta.get("index")
        if index:
            row("# 指数门控: 已启用 {symbol}（买入许可: {b} / 卖出破位: {s}）".format(
                symbol=index.get("symbol"),
                b=index.get("expr_buy") or "—",
                s=index.get("expr_sell") or "—"))
        else:
            row("# 指数门控: 未启用")

        # ---- KPI ----
        summary = result.summary()
        row(f"# KPI: 总成交 {summary['total_trades']} 笔 | 胜率 {summary['win_rate'] * 100:.2f}% | "
            f"累计收益 {summary['cumulative_return'] * 100:+.2f}% | "
            f"平均单笔 {summary['avg_return_pct'] * 100:+.2f}%")
        blank()

        # ---- 逐笔成交明细（数值列保持裸数值，方便 Excel 二次计算）----
        writer.writerow(["买入日期", "买入价", "卖出日期", "卖出价", "持有天数",
                         "盈亏", "收益率", "离场原因"])
        for t in result.trades:
            entry = pd.Timestamp(t.entry_date).strftime("%Y-%m-%d")
            exit_ = pd.Timestamp(t.exit_date).strftime("%Y-%m-%d")
            writer.writerow([
                entry, f"{t.entry_price:.2f}", exit_, f"{t.exit_price:.2f}",
                str(t.days_held if t.days_held is not None else ""),
                f"{t.pnl:.2f}", f"{t.return_pct:.4f}",
                EXIT_REASON_LABELS.get(getattr(t, "exit_reason", "signal"), "卖出信号"),
            ])
        # NOTE(v5.15 · 用户拍板)：不再输出 200+ 行的「每日净值明细」——
        #   ① 它是 CSV 可读性低的主因；② 专业投资者要核查的确定性事实是 参数+逐笔，
        #   引擎可用相同参数复现净值序列；③ 净值曲线的可视化由「导出结果图 PNG」承担。
        return buf.getvalue()

    def export_result(self):
        """把"当前这份 _last_result"导出为 CSV（仅导出，不落库、不删除 —— 见 §7-A2）"""
        if self._last_result is None:
            QMessageBox.information(self, "提示", "请先完成一次回测，再导出明细。")
            return
        meta = self._last_meta or {}
        symbol = meta.get("symbol") or self.current_symbol or "标的"
        name = meta.get("name") or self.current_name or symbol
        default_name = f"回测_{name}_{symbol}_{meta.get('start_date') or ''}~{meta.get('end_date') or ''}.csv"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出回测明细", default_name, "CSV 数据表 (*.csv)")
        if not file_path:
            return
        try:
            text = self._compose_result_csv(self._last_result, meta)
            with open(file_path, "w", encoding="utf-8-sig", newline="") as f:
                f.write(text)
        except OSError as e:
            QMessageBox.critical(self, "导出失败", f"文件写入失败：\n{e}")
            return
        QMessageBox.information(
            self, "导出成功",
            f"本次回测明细已导出（共 {len(self._last_result.trades)} 笔成交）：\n\n{file_path}")

    def export_result_png(self):
        """把"当前这份 _last_result"渲染成单页 PNG 报告图（v5.15）。

        只做入口 + 文件对话框；真正的渲染在 ui/widgets/backtest_report.py（可被
        未来的「结果历史存档」复用）。
        """
        if self._last_result is None:
            QMessageBox.information(self, "提示", "请先完成一次回测，再导出结果图。")
            return
        meta = self._last_meta or {}
        symbol = meta.get("symbol") or self.current_symbol or "标的"
        name = meta.get("name") or self.current_name or symbol
        default_name = f"回测报告_{name}_{symbol}_{meta.get('start_date') or ''}~{meta.get('end_date') or ''}.png"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出结果图", default_name, "PNG 图片 (*.png)")
        if not file_path:
            return
        try:
            ok = render_result_png(meta, self._last_result, file_path)
        except Exception as e:  # noqa: BLE001 —— 渲染异常要给反馈，绝不静默
            QMessageBox.critical(self, "导出失败", f"生成报告图时发生错误：\n{e}")
            return
        if not ok:
            QMessageBox.critical(self, "导出失败", f"报告图保存失败：\n{file_path}")
            return
        QMessageBox.information(
            self, "导出成功",
            f"回测报告图已导出（共 {len(self._last_result.trades)} 笔成交）：\n\n{file_path}")

    # ==========================================
    # 编辑区折叠 (①函数 / ②条件 可最小化，专注回测结果)
    # ==========================================
    def _toggle_collapse(self, body_widget, btn):
        key = id(body_widget)
        collapsed = self._collapsed.get(key, False)
        collapsed = not collapsed
        self._collapsed[key] = collapsed
        body_widget.setVisible(not collapsed)
        btn.setText("展开 ▼" if collapsed else "收起 ▲")
        self._resync_config_split()

    def _resync_config_split(self):
        """按折叠状态调整上/下区比例，把最大空间让给回测结果。

        关键：折叠只隐藏 body 后，顶区布局与 QSplitter 仍缓存旧尺寸，
        必须先 invalidate+activate 让卡片 sizeHint 收缩，再按“真实所需高度”
        设置分割比例，否则卡片下方会出现一大片无意义的空白。
        """
        if not hasattr(self, "_splitter"):
            return
        scroll = self._splitter.widget(0)
        if scroll is None:
            return

        # 上区卡片现在位于 QScrollArea 内部的 content widget 中 (超高可滚动)。
        content = scroll.widget()
        layout = content.layout() if content is not None else None
        if layout is not None:
            layout.invalidate()
            layout.activate()
        if content is not None:
            content.updateGeometry()
        # 布局激活后需交付一轮事件循环，sizeHint 才会收缩到折叠后的真实高度
        QApplication.processEvents()

        func_h = self._func_card.sizeHint().height()
        cond_h = self._cond_card.sizeHint().height()
        index_h = (self._index_card.sizeHint().height()
                   if hasattr(self, "_index_card") else 0)
        spacing = layout.spacing() if layout is not None else 10
        desired = int(func_h + cond_h + index_h + spacing * 2)

        total = self._splitter.height()
        if total <= 0:  # 尚未布局完成(首帧)时按当前分割总和兜底
            total = sum(self._splitter.sizes()) or 900
        # 上区高度上限：即便三卡全展开、行数很多也禁止把结果区挤没，
        # 超出上限的内容交给 QScrollArea 内部滚动 (配合 NoWheel 控件族滚轮直达)。
        max_top = max(320, int(total * 0.55))
        desired = min(desired, max_top)
        bottom = max(200, int(total - desired))
        self._splitter.setSizes([int(desired), bottom])

    # ==========================================
    # 图表日期轴自适应 (K线 + 净值)
    # ==========================================
    def _connect_chart_zoom(self):
        self.kline_chart.getViewBox().sigXRangeChanged.connect(self._on_kline_zoom)
        self.equity_chart.getViewBox().sigXRangeChanged.connect(self._on_equity_zoom)

    def _on_equity_zoom(self, *_args):
        if self._equity_state is not None:
            self._refresh_equity_axis()

    def _refresh_equity_axis(self):
        state = self._equity_state
        if state is None:
            return
        # 刻度算法收敛到公共件（§7-B4）：本页不再自己写"按可视 bar 重算 + 自适应格式"，
        # 与行情页/复盘页共用同一份口径（这正是当年"改一处漏三处"的病根）。
        dates = state['dates']
        view_box = self.equity_chart.getViewBox()
        axis = self.equity_chart.getAxis('bottom')
        i0, i1 = visible_span(view_box, len(dates))
        ticks = compute_ticks(dates, i0, i1, width_px=axis_px(axis))
        axis.setTicks([ticks] if ticks else [])

    def _on_kline_zoom(self, *_args):
        if self._kline_state is not None:
            self._refresh_kline_view()

    def _fit_kline_full(self):
        if self._kline_state is None:
            return
        n = len(self._kline_state['dates'])
        self.kline_chart.setXRange(0, max(1, n - 1), padding=0.02)
        self._refresh_kline_view()

    def _fit_kline_recent(self):
        if self._kline_state is None:
            return
        n = len(self._kline_state['dates'])
        lo = max(0, n - RECENT_BARS)
        self.kline_chart.setXRange(lo, max(lo + 1, n - 1), padding=0.02)
        self._refresh_kline_view()

    def _on_log_toggled(self):
        self.kline_chart.setLogMode(x=False, y=self.chk_log.isChecked())
        self._refresh_kline_view()

    def _refresh_kline_view(self, *_args):
        state = self._kline_state
        if state is None:
            return
        dates = state['dates']
        view_box = self.kline_chart.getViewBox()
        n = len(dates)
        # 刻度算法收敛到公共件（§7-B4）：横轴密度/格式全 app 一份口径
        axis = self.kline_chart.getAxis('bottom')
        i0, i1 = visible_span(view_box, n)
        ticks = compute_ticks(dates, i0, i1, width_px=axis_px(axis))
        axis.setTicks([ticks] if ticks else [])

        if self.chk_follow.isChecked():
            # 「价格轴跟随可视区间」开关语义保留（用户可以关，§7-B4 边界）：
            # 极值只在**可视窗口内**取，并沿用 v6.4 的"叠层也纳入视口"（§7-B3 B③）。
            low = np.asarray(state['low'], dtype=float)
            high = np.asarray(state['high'], dtype=float)
            ov_lo = state.get('overlay_lo')
            ov_hi = state.get('overlay_hi')
            if ov_lo is not None and np.asarray(ov_lo).size == n:
                low = np.fmin(low, np.asarray(ov_lo, dtype=float))
            if ov_hi is not None and np.asarray(ov_hi).size == n:
                high = np.fmax(high, np.asarray(ov_hi, dtype=float))
            span = slice_span(low, high, i0, i1)
            if span is not None:
                lo_p, hi_p = span
                pad = (hi_p - lo_p) * 0.06 or (abs(hi_p) * 0.01 or 1.0)
                # padding=0：pyqtgraph 会在我们给的范围上再叠一层自己的 padding（§11.5-21），
                # 那会让"价格轴跟随可视区间"的实际留白变成不可预期的数值。
                view_box.setYRange(lo_p - pad, hi_p + pad, padding=0)

    # ==========================================
    # 结果渲染
    # ==========================================
    def _render_result(self, result):
        summary = result.summary()
        self.card_total.value.setText(str(summary["total_trades"]))
        win_rate = summary["win_rate"]
        cum = summary["cumulative_return"]
        self.card_win.value.setText(f"{win_rate * 100:.1f}%")
        self.card_cum.value.setText(f"{cum * 100:+.1f}%")
        color = settings.COLOR_PROFIT_TEXT if cum >= 0 else settings.COLOR_LOSS_TEXT
        self.card_cum.value.setStyleSheet(f"font-size: 24px; font-weight: bold; color: {color};")
        self.card_avg.value.setText(f"{summary['avg_return_pct'] * 100:+.2f}%")

        self.lbl_run_status.setText(
            f"{self.current_name} ({self.current_symbol}) | {result.start_date} ~ {result.end_date} | "
            f"{result.total_trades} 笔闭环, 累计 {cum * 100:+.2f}%")

        self.equity_chart.clear()
        self._equity_state = None
        if not result.equity.empty:
            eq = result.equity
            dates = pd.to_datetime(eq['date'])
            # 净值曲线基准线 = 1.0（归一化起点），绘制统一走 chart_style（v5.12 · §9-O7）
            plot_equity_curve(self.equity_chart, eq['equity'], fill_base=1.0, width=2)
            self.equity_chart.addLine(y=1.0, pen=pg.mkPen(color='#BDBDBD', style=Qt.PenStyle.DashLine))
            self._equity_state = {'dates': dates.tolist()}
            self._refresh_equity_axis()

        self.trades_table.setRowCount(len(result.trades))
        for row, t in enumerate(result.trades):
            entry = pd.Timestamp(t.entry_date)
            exit_ = pd.Timestamp(t.exit_date)
            reason = EXIT_REASON_LABELS.get(getattr(t, 'exit_reason', 'signal'), "卖出信号")
            values = [
                str(row + 1), entry.strftime('%Y-%m-%d'), f"{t.entry_price:.2f}",
                exit_.strftime('%Y-%m-%d'), f"{t.exit_price:.2f}",
                str(t.days_held if t.days_held is not None else "-"),
                f"￥{t.pnl:+,.2f}", f"{t.return_pct * 100:+.2f}%",
                reason,
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                if col in (6, 7):
                    item_color = settings.COLOR_PROFIT_TEXT if t.pnl > 0 else settings.COLOR_LOSS_TEXT
                    item.setForeground(QColor(item_color))
                    item.setFont(QFont("Arial", 10, QFont.Weight.Bold))
                if col == 8:
                    item_color = EXIT_REASON_COLORS.get(
                        getattr(t, 'exit_reason', 'signal'), "#212121")
                    item.setForeground(QColor(item_color))
                    item.setToolTip(f"离场来源：{reason}")
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                self.trades_table.setItem(row, col, item)
        self._render_kline(result)

    def _render_kline(self, result):
        self.kline_chart.clear()
        self._kline_state = None
        self._overlay_items = []
        self._kline_win_draws = []
        df = self._last_df
        if df.empty or not result.trades:
            self.kline_chart.getPlotItem().setTitle("请回测后查看买卖点标注", color="#9AA3B2", size="11pt")
            return
        data = df.copy()
        data['date'] = pd.to_datetime(data['date'])
        # 【v6.4 关键】叠层是在**整段 df 的原行序**上求值的，而这里为稳妥会按日期重排；
        # 因此必须记下"排序后位置 → 原始行号"的映射，否则公式线会整体错位
        # （就是 §7-B3 强调的"跨窗口漂移"）。restore 后仍与 _last_df 行序严格对应。
        order = np.argsort(data['date'].to_numpy(), kind='stable')
        data = data.iloc[order].reset_index(drop=True)

        first_entry = pd.Timestamp(result.trades[0].entry_date)
        last_exit = pd.Timestamp(result.trades[-1].exit_date)
        mask = ((data['date'] >= first_entry - pd.Timedelta(days=90))
                & (data['date'] <= last_exit + pd.Timedelta(days=30))).to_numpy()
        win_pos = np.nonzero(mask)[0]
        if win_pos.size == 0:
            return
        window = data.iloc[win_pos].reset_index(drop=True)
        src_rows = order[win_pos]
        date_index = {d: i for i, d in enumerate(window['date'])}

        title = (f"<span style='color:#1F2430; font-size:15px; font-weight:bold;'>{self.current_name} "
                 f"({self.current_symbol})</span> <span style='color:#8A94A6; font-size:12px;'>买卖点标注</span>")
        self.kline_chart.getPlotItem().setTitle(title)
        k_data = [(i, row['open'], row['close'], row['low'], row['high'])
                  for i, row in window.iterrows()]
        self.kline_chart.addItem(CandlestickItem(k_data))

        # ---- 公式叠层：K线之后、买卖点之前（§7-B3 P3 堆叠顺序）----
        self._paint_overlays(src_rows, len(window))

        buy_x, buy_y, sell_x, sell_y = [], [], [], []
        for t in result.trades:
            e_date, x_date = pd.Timestamp(t.entry_date), pd.Timestamp(t.exit_date)
            if e_date in date_index:
                idx = date_index[e_date]
                buy_x.append(idx)
                buy_y.append(window['low'].iloc[idx] * (1 - MARKER_MARGIN))
            if x_date in date_index:
                idx = date_index[x_date]
                sell_x.append(idx)
                sell_y.append(window['high'].iloc[idx] * (1 + MARKER_MARGIN))
        if buy_x:
            self.kline_chart.addItem(pg.ScatterPlotItem(
                x=buy_x, y=buy_y, symbol='t', size=15, brush=pg.mkBrush(settings.COLOR_PROFIT), pen='w'))
        if sell_x:
            self.kline_chart.addItem(pg.ScatterPlotItem(
                x=sell_x, y=sell_y, symbol='d', size=15, brush=pg.mkBrush(settings.COLOR_LOSS), pen='w'))

        ov_lo = ov_hi = None
        if self._kline_win_draws and self.chk_overlay.isChecked():
            ov_lo, ov_hi = overlay_extent(self._kline_win_draws, len(window))
        self._kline_state = {
            'dates': window['date'].tolist(),
            'high': window['high'].to_numpy(dtype=float),
            'low': window['low'].to_numpy(dtype=float),
            'overlay_lo': ov_lo,
            'overlay_hi': ov_hi,
        }
        lo = max(0, date_index.get(first_entry, 0) - 60)
        hi = min(len(window) - 1, date_index.get(last_exit, len(window) - 1) + 10)
        self.kline_chart.getPlotItem().setXRange(lo, hi, padding=0.02)
        self._on_log_toggled()
        self._refresh_kline_view()

    # ==========================================
    # 公式叠层（v6.4 · §7-B3 P3）
    # ==========================================
    def _paint_overlays(self, src_rows, bar_count: int):
        """把引擎绘图 IR（整段）按 K 线窗口切片后渲染到 K 线窗格上。

        宿主只做三件事（§7-B3 B③）：**切窗口 / 喂 x 数组 / 把 y 范围扩到盖住叠层**；
        "IR → 图元" 全部在 `ui/widgets/draw_overlay.py`（全 app 唯一渲染器），
        本页**不得**自己写任何绘图逻辑（§10-11）。
        """
        self._kline_win_draws = []
        if not self._last_draws or bar_count <= 0:
            return
        win_draws = slice_draws(self._last_draws, src_rows)
        self._kline_win_draws = win_draws
        if not self.chk_overlay.isChecked():
            return
        painter = OverlayPainter(
            ChartPane.wrap(self.kline_chart, name="kline", role="main"),
            np.arange(bar_count))
        self._overlay_items = painter.render(win_draws)

    def _on_overlay_toggled(self):
        """「显示公式叠层」开关：只切可见性 + 重算 y 范围，**不重置用户的缩放**。"""
        visible = self.chk_overlay.isChecked()
        for item in self._overlay_items:
            item.setVisible(visible)
        state = self._kline_state
        if state is None:
            return
        if visible and self._kline_win_draws:
            lo, hi = overlay_extent(self._kline_win_draws, len(state['dates']))
        else:
            lo = hi = None
        state['overlay_lo'], state['overlay_hi'] = lo, hi
        self._refresh_kline_view()
