# ui/widgets/scan_layout.py
"""🌐 M2「全市场筛选」—— 版式装配（§7-B1/B2 主案 E 节 · 样板 A）

【版式分层（§10-14）】页签（沿用 `backtest_module` 壳）→ **L1 操作轴**（统计范围 · 基准日 · 复权，1 行）
→ **L2 摘要条**（配置 chips + 回执 + 主按钮 + 进度条，1 行）→ **L0 结果区**（吃满）
→ **L3 配置抽屉**（覆盖层，不动主区高度）—— **常驻 ≤3 行**。

【职责边界】只造控件、只排布局；**不存状态、不做取数**（状态全在页面，行为在
`scan_flow` / `scan_result`）。widgets 模块构造只收 `page`，方法内一律 `p = self.page`。

【复用与诚实注记】`EditPane` / `EditDrawer` / `ClickCatcher` 定义在 `ui/widgets/backtest_panes.py`
（1.22 定稿的样板 A 构件）—— 本文件直接 import，**择机上收 `custom_widgets`**
（本轮不动已验证文件，§7-G 纪律）。
"""
from __future__ import annotations

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFrame,
                             QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
                             QProgressBar, QSizePolicy, QTableWidget, QTableWidgetItem,
                             QTextEdit, QVBoxLayout, QWidget)

from data.akshare_feed import INDEX_PRESETS
from ui.widgets.backtest_panes import (CARD_QSS, ClickCatcher, EditDrawer, EditPane,
                                       FLAT_QSS, number_spin)
from ui.widgets.custom_widgets import (CHIP_QSS_OFF, CHIP_QSS_ON, COMBO_QSS,
                                       SYNC_ACTION_LABEL, NoWheelComboBox,
                                       NoWheelDateEdit, TAB_QSS_OFF, TAB_QSS_ON,
                                       date_edit_qss, hint_icon, mini_label)
from ui.widgets.scan_result import STATUS_BG, STATUS_FG

__all__ = ['ScanLayout', 'ScanFormulaPane', 'ScanFilterPane',
           'KPI_KEYS', 'TABLE_COLUMNS', 'DAY_HINT']

# 抽屉几何（与 backtest.py 同款口径，§11.5-26）
DRAWER_MIN_WIDTH = 420
DRAWER_MAX_WIDTH = 560

# 结果表列（顺序即列序；"说明"列放"为什么没进样本 / 为什么数据不足"）
TABLE_COLUMNS = ('代码', '名称', '收盘', '成交额(万)', '换手率%', '状态', '说明')

# KPI 顺序（E 节：三态 + 有效样本 + 用时；**数据不足必须显式**，绝不并进"未命中"）
KPI_KEYS = ('hit', 'miss', 'insufficient', 'filtered', 'valid', 'elapsed')

DAY_HINT = '◀ ▷ 在扫描结果的交易日轴上移动；切日期**零成本**（读的是缓存矩阵，不重算）'

# 基准日可选的硬下限（再早的日期本地也没有日线，给了也扫不出东西；
# 上限由就绪度体检回传的「本地最新交易日」动态收紧，见 readiness_flow）
ASOF_MIN_YEAR = 2010


def _chip(text: str, tooltip: str = '') -> QPushButton:
    """摘要条胶囊（样式唯一来源 = custom_widgets 的 CHIP_QSS_*，§10-9 控件契约）"""
    btn = QPushButton(text)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(CHIP_QSS_ON)
    if tooltip:
        btn.setToolTip(tooltip)
    return btn


# ==========================================
# ① ƒ 函数（多段公式；**最后一条变量语句**就是判定变量 —— core.cross_section.scan 的约定）
# ==========================================
class ScanFormulaPane(EditPane):
    def __init__(self, parent=None):
        super().__init__('fn', 'ƒ 筛选条件（可多段 · 共享变量池）', '#1976D2', 'ƒ 筛选条件', parent)
        self.txt_formula = QTextEdit()
        self.txt_formula.setPlaceholderText(
            "例：\nDIFF := EMA(C,12) - EMA(C,26);\nDEA  := EMA(DIFF,9);\n"
            "COND := CROSS(DIFF, DEA) AND C > MA(C,20);")
        self.txt_formula.setMinimumHeight(150)
        self.txt_formula.setStyleSheet(
            "QTextEdit { font-family: Consolas, monospace; font-size: 12.5px; }")
        self.txt_formula.setToolTip(
            "可写多段 `变量 := 表达式;`；**最后一条变量**就是判定变量（也可在下方指定）。\n"
            "函数与 M1 单股回测 / 行情页叠加同一套引擎 —— 口径一致。")
        self.body_lay.addWidget(self.txt_formula)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(mini_label('参数'))
        self.txt_params = QLineEdit()
        self.txt_params.setPlaceholderText('N=20;M=60（可空）')
        self.txt_params.setStyleSheet(
            "QLineEdit { border:1px solid #E0E0E0; border-radius:8px; padding:5px 8px; }")
        row.addWidget(self.txt_params, 1)
        self.lbl_signal = QLabel('')
        self.lbl_signal.setStyleSheet('font-size: 11.5px; color: #8A94A6;')
        row.addWidget(self.lbl_signal)
        self.body_lay.addLayout(row)


# ==========================================
# ② 🎚 粗筛漏斗（D5：内置默认 + 全部可调 + 「↺ 恢复默认」；单位走用户量纲 §10-10）
# ==========================================
class ScanFilterPane(EditPane):
    """粗筛阈值 ↔ 控件的**唯一换算处**（界面用 亿元 / %，内核用 元 / 小数）。"""

    def __init__(self, parent=None):
        super().__init__('filter', '🎚 粗筛漏斗（先便宜筛，再精算）', '#E65100', '🎚 粗筛', parent)

        def _row(label: str, tip: str, spin: QDoubleSpinBox, suffix: str = ''):
            lay = QHBoxLayout()
            lay.setSpacing(6)
            lay.addWidget(mini_label(label))
            lay.addWidget(spin)
            if suffix:
                lay.addWidget(QLabel(suffix))
            lay.addStretch()
            hint = hint_icon(tip)
            lay.addWidget(hint)
            self.body_lay.addLayout(lay)
            return spin

        self.spin_amount = number_spin('成交额下限（元）。0 = 关掉这一项', 0.0, 0.0, 1e6, 2)
        self.spin_price = number_spin('收盘价下限（元）。0 = 关掉这一项', 0.0, 0.0, 1e5, 2)
        self.spin_bars = number_spin('有效数据至少多少个交易日（新上市股记「数据不足」）。0 = 关掉', 0.0,
                                     0.0, 5000, 0)
        self.spin_turnover = number_spin('换手率下限（%）。0 = 关掉这一项', 0.0, 0.0, 100.0, 2)
        self.spin_mktcap = number_spin('流通市值下限（亿元）。0 = 关掉这一项', 0.0, 0.0, 1e5, 1)

        _row('成交额 ≥', '当日成交额下限（元）。设 0 = 不启用', self.spin_amount, '亿元')
        _row('价格 ≥', '收盘价下限（元）。设 0 = 不启用', self.spin_price, '元')
        _row('上市 ≥', '有效数据 ≥ 多少个交易日（不足记「数据不足」，不是"未命中"）',
             self.spin_bars, '个交易日')
        _row('换手率 ≥', '当日换手率下限（%）。⚠ 东财兜底源没有该列 ⇒ 那些股记「数据不足」，绝不当 0',
             self.spin_turnover, '%')
        _row('流通市值 ≥', '收盘 × 流通股本。⚠ 同上，缺列记「数据不足」', self.spin_mktcap, '亿元')

        check_row = QHBoxLayout()
        check_row.setSpacing(10)
        self.chk_suspended = QCheckBox('剔除停牌（量 = 0）')
        self.chk_st = QCheckBox('剔除 ST / 退市（按当前名称）')
        self.chk_limit = QCheckBox('剔除一字板（高 = 低）')
        for chk, tip in ((self.chk_suspended, '停牌日该股没有可判定数据 ⇒ 记「数据不足」'),
                         (self.chk_st, '只能按**当前**名称过滤，历史 ST 不可追溯（界面如实标注）'),
                         (self.chk_limit, '一字板当天无法成交，剔除')):
            chk.setToolTip(tip)
            check_row.addWidget(chk)
        check_row.addStretch()
        self.body_lay.addLayout(check_row)

        foot = QHBoxLayout()
        foot.addStretch()
        self.btn_reset = QPushButton('↺ 恢复默认')
        self.btn_reset.setStyleSheet(FLAT_QSS)
        self.btn_reset.setToolTip('恢复主案 D5 的内置默认（成交额 5000 万 / 价格 2 元 / 上市 250 日 / '
                                  '非停牌 / 剔 ST / 剔一字板；换手率与市值默认关闭）')
        foot.addWidget(self.btn_reset)
        self.body_lay.addLayout(foot)

    # ---------- 阈值 ⇄ 控件（唯一换算处） ----------
    def from_thresholds(self, th) -> None:
        """内核小数口径 → 界面用户量纲（亿元 / %）。"""
        self.spin_amount.setValue((th.min_amount or 0.0) / 1e8)
        self.spin_price.setValue(float(th.min_price or 0.0))
        self.spin_bars.setValue(float(th.min_bars or 0))
        self.spin_turnover.setValue((th.min_turnover or 0.0) * 100.0)
        self.spin_mktcap.setValue((th.min_float_mktcap or 0.0) / 1e8)
        self.chk_suspended.setChecked(bool(th.exclude_suspended))
        self.chk_st.setChecked(bool(th.exclude_st))
        self.chk_limit.setChecked(bool(th.exclude_limit))

    def to_thresholds(self):
        """界面用户量纲 → 内核小数口径。**0 = 关掉这一项**（D5：关掉即不参与漏斗）。"""
        from core.cross_section import ScanThresholds
        return ScanThresholds(
            min_amount=(self.spin_amount.value() * 1e8) or None,
            min_price=self.spin_price.value() or None,
            min_bars=int(self.spin_bars.value()) or None,
            exclude_suspended=self.chk_suspended.isChecked(),
            exclude_st=self.chk_st.isChecked(),
            exclude_limit=self.chk_limit.isChecked(),
            min_turnover=(self.spin_turnover.value() / 100.0) or None,
            min_float_mktcap=(self.spin_mktcap.value() * 1e8) or None,
        )


# ==========================================
# 装配器
# ==========================================
class ScanLayout:
    """M2 页的版式装配（只造控件 / 排布局；行为在 `scan_flow`，渲染在 `scan_result`）。"""

    def __init__(self, page):
        self.page = page

    # ---------- L1 操作轴 ----------
    def build_top_bar(self) -> QHBoxLayout:
        p = self.page
        lay = QHBoxLayout()
        lay.setSpacing(8)

        lay.addWidget(mini_label('统计范围'))
        p.cb_scope = NoWheelComboBox()
        p.cb_scope.addItems(['我的自选', '指数成分…', '全 A 花名册'])
        p.cb_scope.setStyleSheet(COMBO_QSS)
        p.cb_scope.setToolTip('自选 / 指数成分 / 全 A。⚠ 先小范围跑通，再放开全 A（主案 G-STEP 4）')
        lay.addWidget(p.cb_scope)

        p.cb_index = NoWheelComboBox()
        for code, name in INDEX_PRESETS.items():
            p.cb_index.addItem(f'{name} {code}', code)
        p.cb_index.setStyleSheet(COMBO_QSS)
        p.cb_index.hide()
        p.cb_index.setToolTip('选一个指数，抓它的成分股（走 MarketSyncService，§9-H）')
        lay.addWidget(p.cb_index)

        p.lbl_scope = QLabel('')
        p.lbl_scope.setStyleSheet('font-size: 11.5px; color: #8A94A6;')
        lay.addWidget(p.lbl_scope)
        lay.addStretch()

        lay.addWidget(mini_label('基准日'))
        # —— 先选后扫（用户 2026-09-21 拍板）：日期必须**扫描前就能自由选**
        #   （日历弹窗 + 直接键入），不能只靠 ◀▶ 在结果轴上挪；默认落在本地最新
        #   交易日（就绪度体检回包后自动校准，见 readiness_flow）。
        p.date_asof = NoWheelDateEdit()
        p.date_asof.setCalendarPopup(True)
        p.date_asof.setDisplayFormat('yyyy-MM-dd')
        p.date_asof.setMinimumDate(QDate(ASOF_MIN_YEAR, 1, 1))
        p.date_asof.setMaximumDate(QDate.currentDate())
        p.date_asof.setDate(QDate.currentDate())
        p.date_asof.setStyleSheet(date_edit_qss())
        p.date_asof.setToolTip('先选日期再点「▶ 开始扫描」——扫描就按这一天取截面；\n'
                               '选到周末/节假日会**就近落到最近的交易日**（回执会说明）。\n'
                               '扫完后也可以改：切日期读的是缓存矩阵，零成本不重算。')
        lay.addWidget(p.date_asof)

        # 基准日诚实化（§7-B10 STEP 4）：上限=本地最新（防选了扫不出），要更近先“更新到最新”
        p.lbl_asof_hint = QLabel('')
        p.lbl_asof_hint.setStyleSheet('font-size: 11px; color: #8A94A6;')
        p.lbl_asof_hint.setToolTip('基准日只能选到本地已有数据的最新交易日；若需更近的日子，'
                                   '先点空态的「⬆ 更新到最新交易日」把数据拉齐，上限会自动抬升。')
        lay.addWidget(p.lbl_asof_hint)

        p.btn_prev_day = QPushButton('◀')
        p.btn_next_day = QPushButton('▶')
        p.btn_latest_day = QPushButton('最新')
        for btn in (p.btn_prev_day, p.btn_next_day, p.btn_latest_day):
            btn.setStyleSheet(FLAT_QSS)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        p.btn_prev_day.setToolTip(DAY_HINT)
        p.btn_next_day.setToolTip(DAY_HINT)
        p.btn_latest_day.setToolTip('跳到扫描结果里最新的交易日（同样零成本）')
        p.lbl_day = QLabel('—')
        p.lbl_day.setStyleSheet('font-size: 13px; font-weight: bold; color: #1F2430;')
        lay.addWidget(p.btn_prev_day)
        lay.addWidget(p.lbl_day)
        lay.addWidget(p.btn_next_day)
        lay.addWidget(p.btn_latest_day)

        p.lbl_adjust = QLabel('前复权')
        p.lbl_adjust.setStyleSheet(
            'font-size: 11.5px; color: #1976D2; border:1px solid #BBDEFB;'
            'border-radius:8px; padding:3px 8px;')
        p.lbl_adjust.setToolTip('本轮只用前复权一种口径（与 M1 单股回测同口径）。\n'
                                '不复权分区尚未备齐 —— 备齐前不在界面上假装支持（主案 D8）。')
        lay.addWidget(p.lbl_adjust)

        p.btn_config = QPushButton('⚙ 配置')
        p.btn_config.setStyleSheet(FLAT_QSS)
        p.btn_config.setCursor(Qt.CursorShape.PointingHandCursor)
        lay.addWidget(p.btn_config)
        return lay

    # ---------- L2 摘要条 ----------
    def build_summary_bar(self) -> QHBoxLayout:
        p = self.page
        lay = QHBoxLayout()
        lay.setSpacing(6)

        p.chip_formula = _chip('ƒ 条件 —', '当前筛选条件（点开抽屉编辑）')
        p.chip_filter = _chip('🎚 粗筛 —', '粗筛阈值（点开抽屉编辑）')
        p.chip_scope = _chip('🌐 范围 —', '统计范围（标的域与只数）')
        for chip in (p.chip_formula, p.chip_filter, p.chip_scope):
            lay.addWidget(chip)
        lay.addStretch()

        p.lbl_receipt = QLabel('还没有扫描过 —— 选好范围与条件后点「▶ 开始扫描」')
        p.lbl_receipt.setStyleSheet('font-size: 11.5px; color: #8A94A6;')
        # 窄屏不撑窗：水平方向 Ignored ⇒ 长文本不会抬高窗口最小宽度（详情走 tooltip / 结果区）
        p.lbl_receipt.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(p.lbl_receipt, 1)

        p.bar_progress = QProgressBar()
        p.bar_progress.setRange(0, 1)
        p.bar_progress.setValue(0)
        p.bar_progress.setTextVisible(False)
        p.bar_progress.setFixedWidth(120)
        p.bar_progress.hide()
        lay.addWidget(p.bar_progress)

        # ★v1.41 / §11.5-80：**常驻**「更新到最新」入口。
        # 【为什么必须常驻】旧版唯一的"补数据"入口是结果区的空态按钮，而它只在
        #   `_outcome is None`（还没有扫描结果）时出现 ⇒ **一旦扫过一次，整页就再也
        #   找不到"更新/补齐数据"的地方**（用户实测：范围切到中证500、体检说未下载 456，
        #   页面上没有任何入口）。入口不该依赖结果区的显示状态。
        #   文字与空态按钮、以及各处**指称它的文案**同源（`SYNC_ACTION_LABEL`）。
        p.btn_sync = QPushButton(SYNC_ACTION_LABEL)
        p.btn_sync.setStyleSheet(FLAT_QSS)
        p.btn_sync.setCursor(Qt.CursorShape.PointingHandCursor)
        p.btn_sync.setToolTip(
            '把当前范围的数据补齐/更新到**最近一个已收盘定稿的交易日**\n'
            '（当日日线 15:05 后才定稿；此前不拉，避免半截数据入库）。\n'
            '已是最新的标的会**自动跳过、不发请求** —— 周末 / 节假日 / 盘中几乎瞬时完成。\n'
            '只补未下载的少数几只时，点它也够了（与旧版的"补齐"入口是同一个动作）。')
        lay.addWidget(p.btn_sync)

        p.btn_run = QPushButton('▶ 开始扫描')
        p.btn_run.setCursor(Qt.CursorShape.PointingHandCursor)
        p.btn_run.setStyleSheet(
            "QPushButton { background:#1976D2; color:white; font-weight:bold;"
            " padding:6px 16px; border-radius:8px; border:none; }"
            "QPushButton:hover { background:#1565C0; }"
            "QPushButton:disabled { background:#B0C4DE; }")
        lay.addWidget(p.btn_run)
        return lay

    # ---------- L0 结果区 ----------
    def build_result_area(self) -> QFrame:
        p = self.page
        card = QFrame()
        card.setStyleSheet(CARD_QSS)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(8)

        # —— 标题行：口径必须印在标题上（E 节）——
        head = QHBoxLayout()
        head.setSpacing(8)
        p.lbl_title = QLabel('某一天的全市场筛选')
        p.lbl_title.setStyleSheet('font-size: 14px; font-weight: bold; color: #1F2430;')
        head.addWidget(p.lbl_title)
        head.addStretch()
        p.lbl_cached = QLabel('')
        p.lbl_cached.setStyleSheet('font-size: 11px; color: #8A94A6;')
        head.addWidget(p.lbl_cached)
        lay.addLayout(head)

        # —— KPI 行（三态 + 有效样本 + 用时）——
        kpis = QHBoxLayout()
        kpis.setSpacing(8)
        p.kpi = {}
        for key in KPI_KEYS:
            pill = QLabel('—')
            pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pill.setStyleSheet(
                'font-size: 12px; font-weight: bold; color:#8A94A6;'
                'background:#F5F6F8; border-radius:8px; padding:5px 10px;')
            pill.setToolTip('还没有结果')
            p.kpi[key] = pill
            kpis.addWidget(pill)
        lay.addLayout(kpis)

        # —— 结果表（只读 + 单选；双击 → 行情工作台，E 节"不另做看图器"）——
        p.table = QTableWidget()
        p.table.setColumnCount(len(TABLE_COLUMNS))
        p.table.setHorizontalHeaderLabels(TABLE_COLUMNS)
        p.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        p.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        p.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        p.table.setAlternatingRowColors(True)
        p.table.verticalHeader().setVisible(False)
        header = p.table.horizontalHeader()
        # ⚠ 列宽模式用 Interactive（可手动拖）而**不是 ResizeToContents**：后者是动态测宽，
        #   每插一格都全表重测 —— 全 A 5000+ 行直接把 UI 线程冻死（v6.42 卡死根因）。
        #   宽度由 `scan_result._render_table` 填完数据后**一次性** resizeColumnsToContents 算出。
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col in range(2, len(TABLE_COLUMNS)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        p.table.setStyleSheet(
            "QTableWidget { gridline-color:#EEF1F5; font-size:12px; }"
            "QHeaderView::section { background:#F7F9FC; border:none;"
            " padding:4px 6px; font-weight:bold; color:#5A6474; }")
        lay.addWidget(p.table, 1)

        # —— 空态（三种空态都给下一步动作，E 节"禁止静默"）——
        empty = QWidget()
        empty_lay = QVBoxLayout(empty)
        empty_lay.setContentsMargins(8, 26, 8, 26)
        empty_lay.setSpacing(10)
        p.lbl_empty = QLabel('还没有可展示的结果')
        p.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        p.lbl_empty.setStyleSheet('font-size: 13px; color:#8A94A6;')
        p.lbl_empty.setWordWrap(True)
        empty_lay.addWidget(p.lbl_empty)
        p.row_empty_action = QHBoxLayout()
        p.row_empty_action.addStretch()
        p.btn_empty_action = QPushButton('')
        p.btn_empty_action.setStyleSheet(
            "QPushButton { background:#E8F1FF; color:#1976D2; font-weight:bold;"
            " padding:6px 14px; border-radius:8px; border:none; }"
            "QPushButton:hover { background:#D6E8FF; }")
        p.btn_empty_action.hide()
        p.row_empty_action.addWidget(p.btn_empty_action)
        p.row_empty_action.addStretch()
        empty_lay.addLayout(p.row_empty_action)
        p.empty_box = empty
        lay.addWidget(empty, 1)
        p.table.hide()

        # —— 口径脚注 ——
        p.lbl_foot = QLabel('口径：统计范围 · 前复权 · 粗筛后精算 · **数据不足不计入命中**'
                            ' · 双击任意一行 → 行情工作台打开该股')
        p.lbl_foot.setStyleSheet('font-size: 11px; color:#B4BECB;')
        lay.addWidget(p.lbl_foot)
        return card

    # ---------- L3 配置抽屉（覆盖层；必须**最后**创建 —— 堆叠顺序 = 创建顺序）----------
    def build_overlays(self) -> None:
        p = self.page
        p._panes = [ScanFormulaPane(), ScanFilterPane()]
        p._formula_pane = p._panes[0]
        p._filter_pane = p._panes[1]
        p._scrim = ClickCatcher(p)
        p._scrim.setStyleSheet('QFrame { background: rgba(15, 22, 34, 0.28); }')
        p._scrim.hide()
        p._drawer = EditDrawer(p._panes, p)
        p._drawer.hide()
