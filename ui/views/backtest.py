# ui/views/backtest.py
"""
📐 市场回测 视图 —— 策略工作台（UI 1.22 = 「样板 A」：摘要条 + 右侧遮罩抽屉 + 结果吃满）。

布局（自上而下 5 行，前 4 行是"薄壳"，其余全给结果）：
  ┌ 模块页签（在 backtest_module.py：单股回测 / 全市场筛选 / 广度统计）
  ├ ① 工具栏行  : 标的 + 策略库（选用 / 保存当前 / 移除）          ← L1 高频·短停留
  ├ ② 配置摘要条: ƒ函数 ⇄条件 📉大盘门控 🛡风控 🎯成交 + 回执 + ▶运行 ← L2 一行 chips
  ├ ③ 运行轴行  : 回测区间（快捷下拉 + 起止日期）                  ← L1 高频·短停留
  ├ ④ 配置抽屉  : 五张卡片住在右侧**遮罩抽屉**里，点胶囊才浮出来（**覆盖层，不动布局**）← L3 低频
  └ ⑤ 结果区    : KPI 卡片 + K线控制 + 4 个结果页签（吃满剩余高度）      ← L0 主角
  └──────────────────────────────────────────────────────────┘

【为什么改成这样（用户 2026-09-16 拍板 · 渐进披露）】
用户实测反馈：函数段 / 条件段 / 大盘门控三块"粘好就基本不动"，却与"天天盯着的回测结果"
抢同一份纵向空间，且**每加一个新功能都只能继续往下挤**（实测结果区只剩 ~60px）。
按「使用频率 × 视线停留时长」分层：低频高占地的配置收进摘要条（常显状态、点击才展开），
把空间还给 L0 结果区（常态 ≈70% 高度）。分层规则与样板见 `design/1.22-backtest-ui/`。
  · 卡片实现 = `ui/widgets/backtest_panes.py`（纯视图）
  · 摘要条实现 = `ui/widgets/backtest_summary_bar.py`
  · 导出实现 = `ui/widgets/backtest_export.py`
  · 展开状态随 `preferences.json` 记忆（"打开页面用记住上次"）

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
import pandas as pd
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLabel, QLineEdit, QFrame, QSizePolicy,
                             QMessageBox, QDialog, QInputDialog, QMenu)

from core.formula.program import (parse_program, execute_programs_with_draws,
                                  probe_missing_parameters, FormulaProgramError)
# v5.15：离场原因标签/配色/风控文案从 core.backtest 统一导入（CSV 表头 / 明细着色 / PNG 报告同源）
# v6.17：成交时点模型的三档常量/文案/归一化与 T+1 说明同样只有一份来源（§7-B5）
from core.backtest import (EXIT_REASON_COLORS, EXIT_REASON_LABELS,
                           FILL_CLOSE, FILL_MODE_LABELS, FILL_NEXT_OPEN, FILL_TRIGGER,
                           T1_SUMMARY, fill_mode_oneliner, fill_summary, normalize_fill,
                           risk_summary, tick_to_yuan, yuan_to_tick)
from core.preferences import preferences
from core.utils import parse_params_text, synthetic_bars
from data.market_db import DataLakeManager
# P7：公式资产化（配方库）+ 与行情页互送
from data.formula_store import (SOURCE_BACKTEST, get_formula_store, make_formula,
                                segments_as_texts)
# 说明：is_index_symbol / is_stock_code 是纯校验函数（无副作用、不联网），因此允许被 UI
#      直接引用（INDEX_PRESETS 常量 1.22 起由 ui/widgets/backtest_panes.py 引用）；
#      但**任何联网抓取**都必须走 MarketSyncService（见下方 worker）。
from data.akshare_feed import is_index_symbol, is_stock_code
from data.strategy_store import StrategyStore
from ui.widgets.custom_widgets import LINE_COMBO_QSS, NoWheelComboBox, NoWheelDateEdit
from ui.widgets.formula_library import FormulaLibraryDialog
# 1.22 / §9-L：本页已把「编辑卡片 + 抽屉 / 摘要条 / 结果区 / 导出 / 运行流程」拆出独立模块，
#   自己只做装配与接线（视图层四件套的落点见各模块 docstring）。
from ui.widgets.backtest_panes import (CARD_QSS, FLAT_QSS, ClickCatcher, ConditionPane,
                                       EditDrawer, FillPane, FunctionPane, IndexPane,
                                       RiskPane, hint_icon, mini_label)
from ui.widgets.backtest_summary_bar import SummaryBar
from ui.widgets.backtest_result import BacktestResultArea
from ui.widgets.backtest_flow import BacktestFlow
from ui.widgets.backtest_strategy import StrategyBridge
from ui.widgets.backtest_export import (compose_result_csv, export_result_csv,
                                        export_result_png_file, risk_readable)
from ui.widgets.backtest_xlsx import export_result_xlsx_file
# v6.17：成交模型的用户教学弹窗（术语必须"看得见地"解释，不能只藏在 tooltip 里）
from ui.dialogs.fill_model_help import FillModelHelpDialog


# NOTE(v5.15)：EXIT_REASON_LABELS / EXIT_REASON_COLORS 已上收到 core/backtest.py，
# 本页与 PNG 报告图共用同一来源，禁止在此再定义副本。

# 快捷区间（数组顺序 = 下拉展示顺序，单一事实来源，不再另设无人使用的映射表）
# 下沿 2016 与 core/backtest.DEFAULT_START_DATE 保持一致（回测意义窗）
_PRESET_ORDER = ["近3个月", "近6个月", "近1年", "近3年", "近5年", "全部(2016起)"]

# 卡片外观唯一来源 = ui/widgets/backtest_panes.CARD_QSS（1.22 起本页不再自带副本）
_CARD_QSS = CARD_QSS

# 配置抽屉（覆盖层）的宽度区间：页面宽 × 42%，夹在 [360, 560] 之间
# （覆盖层不进布局 ⇒ 结果区高度不受影响，见 §11.5-26）
_DRAWER_MIN_WIDTH = 360
_DRAWER_MAX_WIDTH = 560


# ==========================================
# 数据/工具
# ==========================================
def _dummy_bars(n: int = 200) -> pd.DataFrame:
    """哑行情（仅供公式自检试跑）。

    v6.6：实现上收到 `core.utils.synthetic_bars` —— 行情页的「公式叠加」自检
    也要同一份，两处各存一份必然漂移（§11.5-12）。
    """
    return synthetic_bars(n)


# ==========================================
# 后台线程
# ==========================================
# 【架构纪律 v5.12 · §9-O2】回测计算线程已从本文件迁入 ui/workers.py。
# 页面与弹窗不再自造 QThread —— 全 app 的线程统一在 ui/workers.py 定义。


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
        # v6.45 / §7-B10：交易日历（后台一次性拉，供默认回测终点与滞后判定共用）
        self._calendar = None          # list[date] | None（None = 未就绪/离线）
        self._calendar_thread = None
        # v6.4 / §7-B3 P3：本次运行的公式叠层（引擎 IR，与 _last_df 行序一致）。
        # 注：`_kline_state` / `_kline_win_draws` / `_overlay_items` 已随结果区搬到
        #     `ui/widgets/backtest_result.py`（本页以 property 读口暴露，口径不变）。
        self._last_draws: list = []

        # 1.22（样板 A）：编辑卡片开合状态 —— 低频配置默认全收起，空间留给结果区。
        # 这两个字段随 preferences.json 落盘（用户拍板："打开页面用记住上次"）。
        self._open_key: str | None = None   # 当前展开的卡片 key（None = 全部收起）
        self._last_pane = "fn"              # 最近展开过的卡片（「⚙ 编辑配置」的落点）
        self._ui_restoring = False          # 恢复状态期间不回写磁盘（避免无谓写）
        self._pending_risk = {}
        self._pending_index = None     # 阶段C：{symbol, index_df} (数据就绪后)

        # 1.22：两块"行为"搬进独立模块，**状态仍全部留在本页**（见各自 docstring）：
        #   flow     = 选标的 / 数据就绪链 / 求值 / 后台计算 / 结果落地
        #   strategy = 策略快照的打包·还原·存删·归档·对比
        self.flow = BacktestFlow(self)
        self.strategy = StrategyBridge(self)

        self._setup_ui()
        self._sync_index_enabled(False)
        self._set_condition_enabled(False)
        self._reload_strategy_combo()
        self._sync_fill_controls()
        self._restore_ui_state()   # 打开页面即恢复上次展开的卡片
        self._refresh_summary()
        # 后台拉一次交易日历，就绪后把回测默认终点精修到「最近已定稿交易日」（§7-B10）
        self.flow.start_calendar_fetch()
        # Esc 关闭配置抽屉（与样板 A 一致；抽屉没开时是空操作）
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self,
                  activated=lambda: self._open_pane(None))

    # ==========================================
    # UI 构建
    # ==========================================
    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 6, 0)
        root.setSpacing(8)

        # ---------- ① 工具栏行 (L1 操作轴：等宽控件 + 去框化，降低密度) ----------
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        # 统一输入控件高度/圆角，避免“大大小小”的混乱感
        # v6.9：收敛到 custom_widgets.LINE_COMBO_QSS（含成对 ::drop-down/::down-arrow，§10-9）
        self._ctrl_qss = LINE_COMBO_QSS
        self._flat_qss = FLAT_QSS   # 唯一来源 ui/widgets/backtest_panes.FLAT_QSS
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
        self.cmb_strategy.currentIndexChanged.connect(self.strategy.on_strategy_selected)
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
            self._hint_icon("低频配置按使用频率收进下面那条「摘要」：点任意胶囊即展开对应设置；"
                            "平时全部收起，纵向空间都留给回测结果与图表。"))
        root.addLayout(toolbar)

        # ---------- ② 配置摘要条（L2：低频配置压成一行 chips · 样板 A 的核心）----------
        # 常显 = "我到底配了什么"（不必展开就能确认）；点击 = 展开对应编辑卡片。
        self.summary = SummaryBar()
        self.lbl_run_status = self.summary.lbl_status
        self.btn_run = self.summary.btn_run
        self.summary.sig_chip_clicked.connect(self._on_chip_clicked)
        self.summary.sig_edit_clicked.connect(self._on_edit_clicked)
        self.btn_run.clicked.connect(self.start_backtest)
        root.addWidget(self.summary)

        # ---------- ③ 运行轴行（L1：区间是高频微调项，保持常驻一行）----------
        range_bar = QFrame()
        range_bar.setStyleSheet(_CARD_QSS)
        run_lay = QHBoxLayout(range_bar)
        run_lay.setContentsMargins(14, 6, 14, 6)
        run_lay.setSpacing(8)
        run_lay.addWidget(mini_label("回测区间"))
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
        # 防选未来日（默认值随后由 CalendarWorker 精修为最近已定稿交易日）
        self.date_end.setMaximumDate(QDate.currentDate())
        run_lay.addWidget(self.date_end)
        # 一行回执：默认终点来源 / 离线回退 / 滞后补全后的实际终点（§7-B10）
        self.lbl_range_note = QLabel("")
        self.lbl_range_note.setStyleSheet(
            "color:#8A94A6; font-size:12px; border:none; background:transparent;")
        # 窄屏不撑窗：水平 Ignored ⇒ 回执长文本不抬高窗口最小宽度（详情走 tooltip）
        self.lbl_range_note.setSizePolicy(QSizePolicy.Policy.Ignored,
                                          QSizePolicy.Policy.Preferred)
        run_lay.addWidget(self.lbl_range_note)
        run_lay.addStretch()
        run_lay.addWidget(self._hint_icon(
            "回测数据最早可回溯到 2016-01-01（与引擎 DEFAULT_START_DATE 同源）。"
            "改完区间直接点摘要条右侧「▶ 开始回测」。"))
        root.addWidget(range_bar)

        # ---------- ④ 配置抽屉（L3：覆盖层 · 默认关闭）----------
        # 五张卡片全部住在抽屉里、**不进页面布局** ⇒ 结果区高度自始至终不变（样板 A 的观感）。
        # key 与摘要条 chip 一一对应（顺序 = 配置时的心智顺序）。
        self.pane_fn = FunctionPane()
        self.pane_cond = ConditionPane()
        self.pane_index = IndexPane()
        self.pane_risk = RiskPane()
        self.pane_fill = FillPane()
        self._panes = (self.pane_fn, self.pane_cond, self.pane_index,
                       self.pane_risk, self.pane_fill)


        # ---------- 控件别名：卡片交出控件，页面仍是唯一业务入口 ----------
        # 【为什么保留这些同名字段】页面全套业务逻辑（检测/存档/表达式/导出）与
        # 既有验收断言都按"页面属性"访问控件；别名让 1.22 的版式改造**不改变访问口径**。
        self.segments = self.pane_fn.segments
        self.lbl_detect = self.pane_fn.lbl_detect
        self.btn_detect = self.pane_fn.btn_detect
        self.btn_library = self.pane_fn.btn_library
        self.btn_save_formula = self.pane_fn.btn_save_formula
        self.btn_send_market = self.pane_fn.btn_send_market
        self.txt_params = self.pane_cond.txt_params
        self.gate_buy = self.pane_cond.gate_buy
        self.gate_sell = self.pane_cond.gate_sell
        self.chk_index_enable = self.pane_index.chk_index_enable
        self.cmb_index = self.pane_index.cmb_index
        self.lbl_index_status = self.pane_index.lbl_index_status
        self.gate_index_buy = self.pane_index.gate_index_buy
        self.gate_index_sell = self.pane_index.gate_index_sell
        self.spin_risk_bars = self.pane_risk.spin_risk_bars
        self.spin_risk_stop = self.pane_risk.spin_risk_stop
        self.spin_risk_take = self.pane_risk.spin_risk_take
        self.spin_risk_trail = self.pane_risk.spin_risk_trail
        self.cmb_fill_mode = self.pane_fill.cmb_fill_mode
        self.spin_fill_offset = self.pane_fill.spin_fill_offset
        self._fill_offset_box = self.pane_fill._fill_offset_box
        self.lbl_fill_desc = self.pane_fill.lbl_fill_desc
        self.lbl_fill_t1 = self.pane_fill.lbl_fill_t1
        self.btn_fill_help = self.pane_fill.btn_fill_help

        # ---------- 接线（原就地 connect 全部保留，只是控件来自卡片）----------
        self.btn_detect.clicked.connect(self.detect_function)
        self.btn_library.clicked.connect(self.open_formula_library)
        self.btn_save_formula.clicked.connect(self.save_formula_as)
        self.btn_send_market.clicked.connect(self.send_formula_to_market)
        self.chk_index_enable.toggled.connect(self._sync_index_enabled)
        self.cmb_fill_mode.currentIndexChanged.connect(self._sync_fill_controls)
        self.btn_fill_help.clicked.connect(self._show_fill_help)

        # ---------- 摘要条联动：配置一变，胶囊文案立刻跟上 ----------
        # 单一事实来源永远是控件本身，这里只做"汇总显示"，避免摘要与实际配置不符。
        self.segments.changed.connect(self._refresh_summary)
        self.gate_buy.changed.connect(self._refresh_summary)
        self.gate_sell.changed.connect(self._refresh_summary)
        self.gate_index_buy.changed.connect(self._refresh_summary)
        self.gate_index_sell.changed.connect(self._refresh_summary)
        self.chk_index_enable.toggled.connect(lambda *_: self._refresh_summary())
        self.cmb_fill_mode.currentIndexChanged.connect(lambda *_: self._refresh_summary())
        for spin in (self.spin_risk_bars, self.spin_risk_stop,
                     self.spin_risk_take, self.spin_risk_trail, self.spin_fill_offset):
            spin.valueChanged.connect(lambda *_: self._refresh_summary())
        self.txt_params.textChanged.connect(lambda *_: self._refresh_summary())

        # NOTE(1.22 / §9-L)：旧「① 函数 / ② 条件 / ③ 大盘门控」三张卡片的构建已搬到
        #   ui/widgets/backtest_panes.py（纯视图）；运行条已并入摘要条，区间行见上方 ③。
        #   本页只做装配与接线，故这里不再有任何卡片构建代码。

        # ========== 下区：结果区（L0 主角 —— 吃满剩余高度，永不折叠）==========
        bottom_area = QWidget()
        bottom_lay = QVBoxLayout(bottom_area)
        bottom_lay.setContentsMargins(0, 0, 0, 0)
        bottom_lay.setSpacing(8)

        # ⑤ 结果区（L0 主角 · 1.22 拆出独立模块 ui/widgets/backtest_result.py）
        #    只有这里吃剩余高度；「导出结果 ▾」由页面建好（菜单动作是页面职责）再传进去。
        self._build_export_button()
        self.result = BacktestResultArea(self.btn_export_result)
        # 结果区控件按旧名挂回页面：既有断言与其它模块仍按"页面属性"访问（口径不变）
        for _attr in ("tabs", "equity_chart", "kline_chart", "compare_tab", "compare_chart",
                      "compare_table", "trades_table", "card_total", "card_win", "card_cum",
                      "card_avg", "chk_follow", "chk_log", "chk_overlay",
                      "btn_fit_full", "btn_fit_last"):
            setattr(self, _attr, getattr(self.result, _attr))
        bottom_lay.addWidget(self.result, 1)

        # 结果区吃满剩余高度
        root.addWidget(bottom_area, 1)

        # ---------- ⑥ 覆盖层：遮罩 + 配置抽屉 ----------
        # ⚠【必须在 _setup_ui 的**最后**创建】：同级 widget 的堆叠顺序 = 创建顺序，
        #   遮罩若建在结果区之前，结果区（KPI 卡 / 成交明细表 / 图表）就会整体压在遮罩
        #   之上 —— 真实踩到："点开胶囊后遮罩盖不住表格，非常丑"（§11.5-27）。
        #   先建遮罩、后建抽屉 ⇒ 抽屉在遮罩之上；打开时再 raise 一次兜底。
        self._scrim = ClickCatcher(self)
        self._scrim.setStyleSheet("background: rgba(16, 24, 40, 64);")
        self._scrim.clicked.connect(lambda: self._open_pane(None))
        self._scrim.hide()
        self._drawer = EditDrawer(self._panes, self)
        self._drawer.sig_closed.connect(lambda: self._open_pane(None))
        self._drawer.hide()

    # ---------- 小构件（唯一来源 = ui/widgets/backtest_panes.py，此处只留别名）----------
    # 说明：卡片模块与本页都要用这几个构件，**实现只允许有一份**；这里用别名而非复制，
    # 避免"改一处漏一处"（§11.5-12 的老毛病）。数值输入框（原 `_risk_spin`）已随卡片
    # 一起搬进 panes 模块（`number_spin`），本页不再需要。
    _mini_label = staticmethod(mini_label)
    _hint_icon = staticmethod(hint_icon)

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
        self._refresh_summary()

    # ---------- 成交模型 (v6.17 · §7-B5) ----------
    def _fill_config(self) -> dict:
        """读取成交模型行 -> 引擎口径 dict。

        ⚠ 界面上用「元」跟用户说话，落库/签名仍存**整数跳**（跳 × 0.01 元）：
        避免浮点小数在比较与签名里漂移（`0.03` vs `0.030000000000000002`）。
        """
        return {
            "fill_mode": self.cmb_fill_mode.currentData() or FILL_NEXT_OPEN,
            "trigger_tick": yuan_to_tick(self.spin_fill_offset.value()),
        }

    def _apply_fill_config(self, cfg: dict):
        """从策略快照恢复成交模型。

        旧存档没有 fill 字段 -> `normalize_fill` 一律回落
        **次日开盘 + 0.01 元**（= 改动前的行为），保证老策略读出来跑的还是同一套口径。
        """
        conf = normalize_fill((cfg or {}).get("fill_mode"),
                              (cfg or {}).get("trigger_tick"))
        pos = self.cmb_fill_mode.findData(conf["fill_mode"])
        self.cmb_fill_mode.blockSignals(True)
        self.cmb_fill_mode.setCurrentIndex(pos if pos >= 0 else 0)
        self.cmb_fill_mode.blockSignals(False)
        self.spin_fill_offset.setValue(tick_to_yuan(conf["trigger_tick"]))
        self._sync_fill_controls()
        self._refresh_summary()

    def _sync_fill_controls(self):
        """「多等多少元」只在第三档下有含义；行内说明随选择实时更新（用户指引的主体）。"""
        is_trigger = self.cmb_fill_mode.currentData() == FILL_TRIGGER
        if hasattr(self, "_fill_offset_box"):
            self._fill_offset_box.setVisible(is_trigger)
        if hasattr(self, "lbl_fill_desc"):
            self.lbl_fill_desc.setText(fill_mode_oneliner(
                self.cmb_fill_mode.currentData(), self._fill_config()["trigger_tick"]))

    def _show_fill_help(self):
        """用户教学弹窗（只解释、不改配置）—— 术语必须有"看得见的"解释入口。"""
        FillModelHelpDialog(self, trigger_tick=self._fill_config()["trigger_tick"]).exec()

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
        self._refresh_summary()   # 摘要条「ƒ 函数」胶囊：段数 / 变量数 / 是否可运行

    # ==========================================
    # ② 条件 (Gate 桥接) + ③ 指数门控
    # ==========================================
    def _set_condition_enabled(self, enabled: bool):
        self.gate_buy.set_gate_enabled(enabled)
        self.gate_sell.set_gate_enabled(enabled)
        self._sync_index_enabled(self.chk_index_enable.isChecked() if enabled else False)
        self.btn_run.setEnabled(enabled)
        self._refresh_summary()

    def _sync_index_enabled(self, enabled: bool):
        """指数门控启用联动：勾选开启 + 函数已检测才可配条件"""
        on = bool(enabled) and bool(self._variables)
        self.gate_index_buy.set_gate_enabled(on)
        self.gate_index_sell.set_gate_enabled(on)
        self.cmb_index.setEnabled(bool(enabled) and bool(self._variables))
        if on and self._index_symbol():
            self._refresh_index_status()
        self._refresh_summary()

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
    # 策略库（1.22 起实现在 ui/widgets/backtest_strategy.py）
    #   同运行流程：**状态留在本页**（`store` / `_active_strategy_id` / 各配置控件），
    #   模块只做"打包 / 还原 / 存删 / 归档 / 对比"这些行为。下面几个是同名转发。
    # ==========================================
    def _strategy_payload(self) -> dict:
        """当前编辑器状态 → 可持久化策略快照（验收断言与归档同源）"""
        return self.strategy.payload()

    def _reload_strategy_combo(self, keep_active: str | None = None):
        self.strategy.reload_combo(keep_active)

    def _render_compare(self):
        self.strategy.render_compare()

    def save_strategy(self):
        self.strategy.save()

    def delete_strategy(self):
        self.strategy.delete()

    # 回测运行流程（1.22 起实现在 ui/widgets/backtest_flow.py）
    #   状态——标的 / `_pending_*` / `_last_*` / 三个线程句柄——**全部留在本页**，
    #   模块只承载"行为"，读写一律经 `self.page.*`（见该模块 docstring 的"设计约定"）。
    #   下面三个入口只是转发，供按钮接线与既有调用点保持同名。
    # ==========================================
    def select_symbol(self):
        self.flow.select_symbol()

    def _on_range_preset(self, preset: str):
        self.flow._on_range_preset(preset)

    def start_backtest(self):
        self.flow.start_backtest()


    # ==========================================
    # 结果导出 (v5.14 · §7-A2)
    # ==========================================
    def _build_export_button(self):
        """「导出结果 ▾」下拉按钮（菜单动作是页面职责，故在这里建好后交给结果区摆放）。

        v5.14/v5.15：仅导出，不删除/不存档（§7-A2）。
        下拉菜单承载多种格式：CSV 明细（专业溯源）/ PNG 报告图（一图看懂）；
        未来要加 XLSX 等格式只需在此新增一个 action。
        """
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
        act_xlsx = self._export_menu.addAction("📊 导出 Excel 图表…")
        act_xlsx.setToolTip(".xlsx 内嵌真正的净值曲线图 + 买卖点标记（打开即见图）；另含明细 sheet")
        act_xlsx.triggered.connect(self.export_result_xlsx)
        self.btn_export_result.setMenu(self._export_menu)

    # ==========================================
    # 导出（1.22 起实现在 ui/widgets/backtest_export.py，本页只留入口与同名转发）
    # ==========================================
    @staticmethod
    def _risk_readable(risk: dict) -> str:
        """风控人话文案 —— 唯一来源 core/backtest.risk_summary（与导出模块同源）"""
        return risk_readable(risk)

    @staticmethod
    def _compose_result_csv(result, meta: dict) -> str:
        """把一次回测结果渲染成规范 CSV 文本（实现已搬到 ui/widgets/backtest_export.py）。

        页面保留同名转发：① 既有验收断言按页面方法调用；② 调用点不必关心实现落点。
        """
        return compose_result_csv(result, meta)

    def _export_meta(self) -> tuple:
        """导出用的参数快照与命名 —— 必须来自 start_backtest 定格的那份 meta"""
        meta = self._last_meta or {}
        symbol = meta.get("symbol") or self.current_symbol or "标的"
        name = meta.get("name") or self.current_name or symbol
        return meta, symbol, name

    def export_result(self):
        """导出当前这份结果的 CSV 明细（仅导出，不落库、不删除 —— 见 §7-A2）"""
        if self._last_result is None:
            QMessageBox.information(self, "提示", "请先完成一次回测，再导出明细。")
            return
        meta, symbol, name = self._export_meta()
        export_result_csv(self, result=self._last_result, meta=meta,
                          symbol=symbol, name=name)

    def export_result_png(self):
        """导出当前这份结果的 PNG 报告图（v5.15；渲染在 ui/widgets/backtest_report.py）"""
        if self._last_result is None:
            QMessageBox.information(self, "提示", "请先完成一次回测，再导出结果图。")
            return
        meta, symbol, name = self._export_meta()
        export_result_png_file(self, result=self._last_result, meta=meta,
                               symbol=symbol, name=name)

    def export_result_xlsx(self):
        """导出 .xlsx（内嵌净值曲线图 + 买卖点；§7-A2，渲染在 ui/widgets/backtest_xlsx.py）"""
        if self._last_result is None:
            QMessageBox.information(self, "提示", "请先完成一次回测，再导出 Excel。")
            return
        meta, symbol, name = self._export_meta()
        export_result_xlsx_file(self, result=self._last_result, meta=meta,
                                symbol=symbol, name=name)


    # ==========================================
    # 编辑卡片开合 ⇄ 摘要条联动（样板 A 的 L2/L3：默认全收起，点开一张）
    # ==========================================
    def _on_chip_clicked(self, key: str):
        """点摘要条胶囊：展开对应编辑卡片（再点一次 = 收起）。"""
        self._open_pane(key)

    def _on_edit_clicked(self):
        """「⚙ 编辑配置」：展开最近用过的那张卡片（没有记录时默认函数）。"""
        self._open_pane(self._last_pane or "fn")

    def _open_pane(self, key):
        """打开/关闭配置抽屉；key=None = 关闭（结果区永远保持满高）。

        【为什么是覆盖层而不是"就地展开"】用户 2026-09-16 拍板：就地展开虽直观但不美观
        —— 抽屉浮在页面上方，**页面布局一动不动**，结果区高度自始至终不变（样板 A 的观感）。

        【打开页面用记住上次（用户拍板）】展开的卡片与最近使用随 preferences.json 落盘，
        下次打开照原样恢复；`_ui_restoring` 期间不回写，避免恢复动作把磁盘写脏。
        """
        if key == self._open_key:
            key = None                      # 再点同一个胶囊 = 关闭
        self._open_key = key
        if key:
            self._last_pane = key
            self._drawer.show_pane(key)
            self._drawer.scroll_area.verticalScrollBar().setValue(0)
        self._layout_overlay()
        self._drawer.setVisible(key is not None)
        self._scrim.setVisible(key is not None)
        if key is not None:
            self._drawer.raise_()
        self.summary.set_active(key)
        self._save_ui_state()

    def _layout_overlay(self):
        """覆盖层几何：遮罩铺满页面，抽屉贴右、整页高。

        覆盖层**不进布局**，尺寸只能自己算（`resizeEvent` 里重算）—— 见 §11.5-26；
        正因为它是覆盖层，结果区的高度**永远不会**因为打开配置而改变。
        """
        rect = self.rect()
        self._scrim.setGeometry(rect)
        width = min(_DRAWER_MAX_WIDTH, max(_DRAWER_MIN_WIDTH, int(rect.width() * 0.42)))
        self._drawer.setGeometry(rect.width() - width, 0, width, rect.height())

    def resizeEvent(self, event):  # noqa: N802 —— Qt 命名约定
        super().resizeEvent(event)
        self._layout_overlay()

    def _refresh_summary(self):
        """把各控件的当前状态汇总到摘要条（**控件本身才是唯一事实来源**）。

        触发点 = "配置变了"的每一个时刻：函数检测完 / 条件增删 / 门控开关 /
        风控与成交参数变化 / 载入策略 / 恢复存档（见 _setup_ui 末尾的 connect 群）。
        """
        texts = [t for t in self.segments.texts() if t.strip()]
        if not self._programs:
            self.summary.set_value("fn", "尚未检测", "off")
        else:
            self.summary.set_value(
                "fn", f"{len(texts)} 段 · {len(self._variables)} 变量 ✓", "ok")

        n_buy = len(self.gate_buy.config().get("conditions") or [])
        n_sell = len(self.gate_sell.config().get("conditions") or [])
        self.summary.set_value("cond", f"买 {n_buy} · 卖 {n_sell}",
                               "on" if (n_buy or n_sell) else "off")

        if self.chk_index_enable.isChecked() and self._variables:
            self.summary.set_value(
                "index", f"{self._index_symbol() or '未选指数'} · 已启用", "on")
        else:
            self.summary.set_value("index", "未启用", "off")

        risk = self._risk_config()
        parts = []
        if risk["max_bars"]:
            parts.append(f"最长 {risk['max_bars']} 根")
        if risk["stop_loss_pct"]:
            parts.append(f"止损 {risk['stop_loss_pct']:g}%")
        if risk["take_profit_pct"]:
            parts.append(f"止盈 {risk['take_profit_pct']:g}%")
        if risk["trailing_pct"]:
            parts.append(f"回撤 {risk['trailing_pct']:g}%")
        self.summary.set_value("risk", " · ".join(parts) if parts else "全部关闭",
                               "on" if parts else "off")

        conf = self._fill_config()
        fill_txt = FILL_MODE_LABELS.get(conf["fill_mode"], str(conf["fill_mode"]))
        if conf["fill_mode"] == FILL_TRIGGER:
            fill_txt += f" · {tick_to_yuan(conf['trigger_tick']):.2f} 元"
        self.summary.set_value("fill", fill_txt, "on")

    # ---------- 状态记忆（打开页面用记住上次）----------
    def _save_ui_state(self):
        if self._ui_restoring:
            return
        preferences.set("backtest_ui", {"pane": self._open_key, "last": self._last_pane})

    def _restore_ui_state(self):
        """恢复上次的展开状态；没有记录时**全部收起**（一进来就是"结果最大"）。"""
        state = preferences.get("backtest_ui")
        if not isinstance(state, dict):
            state = {}
        self._last_pane = state.get("last") or "fn"
        keys = {p.key for p in self._panes}
        pane = state.get("pane")
        self._ui_restoring = True
        try:
            self._open_pane(pane if pane in keys else None)
        finally:
            self._ui_restoring = False


    # ==========================================
    # 结果区（1.22 起实现在 ui/widgets/backtest_result.py）
    #   本页只做两件事：① 把"本次运行的数据 + 引擎绘图 IR"喂进去；② 写运行回执。
    #   图表缩放、日期轴与量程自适应由结果区自己接线（见 BacktestResultArea._build_tabs）。
    # ==========================================
    def _render_result(self, result):
        """渲染一次回测结果（KPI + 净值曲线 + 成交明细 + K线买卖点）。

        画面全在结果区模块里；页面负责喂数据并写回运行回执
        （回执文字带 current_name/current_symbol 的语境，属页面职责）。
        """
        summary = self.result.render_result(
            result, self.current_name, self.current_symbol,
            df=self._last_df, draws=self._last_draws)
        cum = summary["cumulative_return"]
        self.lbl_run_status.setText(
            f"{self.current_name} ({self.current_symbol}) | "
            f"{result.start_date} ~ {result.end_date} | "
            f"{result.total_trades} 笔闭环, 累计 {cum * 100:+.2f}%")

    def _render_kline(self, result):
        """（1.22 起实现在 backtest_result.py；保留同名转发供内部调用与验收断言）"""
        self.result.render_kline(result, df=self._last_df, draws=self._last_draws,
                                 name=self.current_name, symbol=self.current_symbol)

    # ---------- 结果区私有状态的读口 ----------
    # 这三份状态在每次渲染时会被**整体替换**，所以不能用"构造时别名"，
    # 必须用 property 每次取当前对象（既有断言读的就是它们）。
    @property
    def _kline_state(self):
        return self.result._kline_state

    @property
    def _kline_win_draws(self):
        return self.result._kline_win_draws

    @property
    def _overlay_items(self):
        return self.result._overlay_items
