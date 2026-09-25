# ui/widgets/breadth_layout.py
"""📊 M3「广度统计」—— 版式装配（§7-B1/B2 主案 E 节 · 样板 A，与 M2 `scan_layout` 同款）

【版式分层（§10-14）】页签（沿用 `backtest_module` 壳）→ **L1 操作轴**（统计范围 · 区间 ·
复权，1 行）→ **L2 摘要条**（配置 chips + 回执 + ⚡增量 / ⟳全量重算 / ▶主按钮，1 行）
→ **L0 结果区**（双窗格折线，吃满）→ **L3 配置抽屉**（覆盖层，不动主区高度）—— **常驻 ≤3 行**。

【职责边界】只造控件、只排布局；**不存状态、不做取数**（状态全在页面，行为在
`breadth_flow`，图表在 `breadth_chart`）。widgets 模块构造只收 `page`，方法内一律 `p = self.page`。

【复用】ƒ 函数卡与 🎚 粗筛卡**直接 import `scan_layout` 的同款 EditPane** —— M2/M3 共用同一份
编辑器（原型："与单股回测 / 全市场筛选共用同一份函数段与配方库"），阈值⇄控件的换算
也只有 `ScanFilterPane` 那一处；危险动作（⟳ 全量重算）在 L2 上**低调呈现**（§10-10）。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel,
                             QPushButton, QProgressBar, QSizePolicy, QVBoxLayout, QWidget)

from data.akshare_feed import INDEX_PRESETS
from ui.widgets.backtest_panes import CARD_QSS, ClickCatcher, EditDrawer, EditPane, FLAT_QSS
from ui.widgets.breadth_chart import (CHART_TYPES, DEFAULT_CHART_TYPE,
                                      DEFAULT_INDEX_STYLE, INDEX_STYLES,
                                      BreadthChart)
from ui.widgets.custom_widgets import (CHIP_QSS_ON, COMBO_QSS,
                                       SYNC_ACTION_LABEL, NoWheelComboBox,
                                       hint_icon, mini_label)
from ui.widgets.scan_layout import ScanFilterPane, ScanFormulaPane

__all__ = ['BreadthLayout', 'BreadthDisplayPane', 'RANGE_PRESETS', 'DEFAULT_INDEX_CODE']

# 区间快捷档（顺序即下拉顺序；语义与回测页区间档一致）
RANGE_PRESETS = (('3m', '近3个月'), ('6m', '近6个月'), ('1y', '近1年'),
                 ('3y', '近3年'), ('5y', '近5年'), ('all', '全部历史'))
DEFAULT_RANGE = '1y'
DEFAULT_INDEX_CODE = 'sh000001'          # 副图默认上证指数（INDEX_PRESETS 首项）

# 抽屉几何（与 scan_layout / backtest.py 同款口径，§11.5-26）
DRAWER_MIN_WIDTH = 420
DRAWER_MAX_WIDTH = 560


def _chip(text: str, tooltip: str = '') -> QPushButton:
    btn = QPushButton(text)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(CHIP_QSS_ON)
    if tooltip:
        btn.setToolTip(tooltip)
    return btn


def _flat_btn(text: str, tooltip: str = '') -> QPushButton:
    btn = QPushButton(text)
    btn.setStyleSheet(FLAT_QSS)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if tooltip:
        btn.setToolTip(tooltip)
    return btn


# ==========================================
# ③ 📈 平滑与展示（原型「平滑与展示」卡）
# ==========================================
class BreadthDisplayPane(EditPane):
    """这条线**怎么画**：MA5 平滑 / 占比口径 / 指数副图。只管控件，不碰数据。"""

    def __init__(self, parent=None):
        super().__init__('display', '📈 平滑与展示（这条线怎么画）', '#2E7D32', '📈 展示', parent)

        # —— 视觉方案（用户 2026-09-21 拍板：柱状/折线都要有，默认柱状+趋势线）——
        style_row = QHBoxLayout()
        style_row.setSpacing(6)
        style_row.addWidget(mini_label('图形'))
        self.cb_chart = NoWheelComboBox()
        for key, label in CHART_TYPES:
            self.cb_chart.addItem(label, key)
        idx = [k for k, _ in CHART_TYPES].index(DEFAULT_CHART_TYPE)
        self.cb_chart.setCurrentIndex(idx)
        self.cb_chart.setStyleSheet(COMBO_QSS)
        self.cb_chart.setToolTip('柱状 = 每日家数一根柱（整数计数天然该用柱子读），叠 MA5 实线看趋势；\n'
                                 '折线 = 原始折线 + 浅面积填充，MA5 橙色虚线。\n'
                                 '只换画法，数据一个字节都不动。')
        style_row.addWidget(self.cb_chart, 1)
        style_row.addStretch()
        self.body_lay.addLayout(style_row)

        self.chk_smooth = QCheckBox('叠加 MA5 平滑（柱状态为主线 / 折线态为橙虚线）')
        self.chk_smooth.setToolTip('对广度序列做 5 日滚动平均，看趋势不看单日抖动')
        self.chk_ratio = QCheckBox('改用「占比 %」（家数 ÷ 有效样本）')
        self.chk_ratio.setToolTip('占比的分母 = **有效样本**（命中 + 未命中），不是全市场只数'
                                  ' —— 新上市 / 数据不足的票不进分母（三态铁律，E 节）')
        self.chk_overlay = QCheckBox('叠加指数（下方副图，同 x 轴联动）')
        self.chk_overlay.setToolTip('副图画指数收盘线，与广度共用同一根日期轴 —— 对照着看'
                                    '"条件命中变多/变少"与大盘的关系')
        self.body_lay.addWidget(self.chk_smooth)
        self.body_lay.addWidget(self.chk_ratio)
        self.body_lay.addWidget(self.chk_overlay)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(mini_label('指数'))
        self.cb_overlay_code = NoWheelComboBox()
        for code, name in INDEX_PRESETS.items():
            self.cb_overlay_code.addItem(f'{name} {code}', code)
        self.cb_overlay_code.setStyleSheet(COMBO_QSS)
        self.cb_overlay_code.setToolTip('选哪个指数画在副图；本地没有它的日线时会在后台拉一次'
                                        '（走 MarketSyncService，失败不影响主图）')
        row.addWidget(self.cb_overlay_code, 1)
        row.addStretch()
        row.addWidget(hint_icon('指数日线来自数据湖 index_daily 分区；缺数据会自动补拉一次，'
                                '失败时副图留空并出声，主图广度不受影响。'))
        self.body_lay.addLayout(row)

        # —— 指数图形（用户 2026-09-21 拍板：不止折线，K线/美国线都要有）——
        istyle_row = QHBoxLayout()
        istyle_row.setSpacing(6)
        istyle_row.addWidget(mini_label('指数图形'))
        self.cb_index_style = NoWheelComboBox()
        for key, label in INDEX_STYLES:
            self.cb_index_style.addItem(label, key)
        self.cb_index_style.setCurrentIndex(
            [k for k, _ in INDEX_STYLES].index(DEFAULT_INDEX_STYLE))
        self.cb_index_style.setStyleSheet(COMBO_QSS)
        self.cb_index_style.setToolTip('只换副图的画法，数据不动。\n'
                                       'K 线 / 美国线需要本地指数有开高低列；缺列自动退回折线（不画假四价）。\n'
                                       '想看大一点的指数图：按住两图之间的分界线往下拖，双击分界线恢复默认。')
        istyle_row.addWidget(self.cb_index_style, 1)
        istyle_row.addStretch()
        self.body_lay.addLayout(istyle_row)


# ==========================================
# 装配器
# ==========================================
class BreadthLayout:
    """M3 页的版式装配（只造控件 / 排布局；行为在 `breadth_flow`，图表在 `breadth_chart`）。"""

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
        p.cb_scope.setToolTip('广度统计的是这个范围内的标的（与 M2 全市场筛选同一套范围语义）')
        lay.addWidget(p.cb_scope)

        p.cb_index = NoWheelComboBox()
        for code, name in INDEX_PRESETS.items():
            p.cb_index.addItem(f'{name} {code}', code)
        p.cb_index.setStyleSheet(COMBO_QSS)
        p.cb_index.hide()
        p.cb_index.setToolTip('选一个指数，统计它的成分股（走 MarketSyncService，§9-H）')
        lay.addWidget(p.cb_index)

        p.lbl_scope = QLabel('')
        p.lbl_scope.setStyleSheet('font-size: 11.5px; color: #8A94A6;')
        lay.addWidget(p.lbl_scope)
        lay.addStretch()

        lay.addWidget(mini_label('区间'))
        p.cb_range = NoWheelComboBox()
        for _key, label in RANGE_PRESETS:
            p.cb_range.addItem(label)
        p.cb_range.setStyleSheet(COMBO_QSS)
        p.cb_range.setToolTip('只改**看多长**：广度矩阵本来就是全日期的，切区间是纯切片、'
                              '零成本不重算（D3）')
        lay.addWidget(p.cb_range)

        p.lbl_adjust = QLabel('前复权')
        p.lbl_adjust.setStyleSheet(
            'font-size: 11.5px; color: #1976D2; border:1px solid #BBDEFB;'
            'border-radius:8px; padding:3px 8px;')
        p.lbl_adjust.setToolTip('本轮只用前复权一种口径（与 M1 单股回测 / M2 筛选同口径，D8）。\n'
                                '不复权分区尚未备齐 —— 备齐前不在界面上假装支持。')
        lay.addWidget(p.lbl_adjust)

        p.btn_config = _flat_btn('⚙ 配置')
        lay.addWidget(p.btn_config)
        return lay

    # ---------- L2 摘要条 ----------
    def build_summary_bar(self) -> QHBoxLayout:
        p = self.page
        lay = QHBoxLayout()
        lay.setSpacing(6)

        p.chip_formula = _chip('ƒ 条件 —', '筛选条件（点开抽屉编辑；与 M2/M1 同一套引擎）')
        p.chip_filter = _chip('🎚 粗筛 —', '粗筛阈值（点开抽屉编辑）')
        p.chip_scope = _chip('🌐 范围 —', '统计范围（标的域与只数）')
        p.chip_display = _chip('📈 展示 —', '平滑 / 占比 / 指数副图（点开抽屉编辑）')
        for chip in (p.chip_formula, p.chip_filter, p.chip_scope, p.chip_display):
            lay.addWidget(chip)

        # ★v1.46 / §7-B12 P3：筛选方案「载入 / 存为 / 管理」（与 M2 共享一份方案池）。
        p.btn_load = _flat_btn('📚 载入', '载入已保存的筛选方案（函数/参数/粗筛/范围）；M2 与 M3 共用一份方案库')
        p.btn_save = _flat_btn('💾 存为', '把当前筛选配置存成命名方案（同名覆盖），下次一键载入')
        p.btn_manage = _flat_btn('管理', '管理（删除）已保存的筛选方案')
        for _b in (p.btn_load, p.btn_save, p.btn_manage):
            lay.addWidget(_b)
        lay.addStretch()

        p.lbl_receipt = QLabel('还没有扫描过 —— 选好范围与条件后点「▶ 开始扫描」')
        p.lbl_receipt.setStyleSheet('font-size: 11.5px; color: #8A94A6;')
        # 窄屏不撑窗：水平 Ignored ⇒ 长文本不抬高窗口最小宽度（详情走 tooltip / 结果区）
        p.lbl_receipt.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(p.lbl_receipt, 1)

        p.bar_progress = QProgressBar()
        p.bar_progress.setRange(0, 1)
        p.bar_progress.setValue(0)
        p.bar_progress.setTextVisible(False)
        p.bar_progress.setFixedWidth(120)
        p.bar_progress.hide()
        lay.addWidget(p.bar_progress)

        # ★v1.41 / §11.5-80：**常驻**「更新到最新」入口（与 M2 同款、同文案）。
        #   ⚠ 与下面「⚡ 只补新交易日」**职责不同**：这个**下载数据**，那个**用已有数据续算广度**。
        #   旧版 M3 也没有任何常驻的下载入口（唯一入口同样是空态按钮）⇒ 一并补齐。
        p.btn_sync = _flat_btn(SYNC_ACTION_LABEL,
                               '把当前范围的数据补齐/更新到最近一个已收盘定稿的交易日。\n'
                               '已是最新的标的会**自动跳过、不发请求**。\n'
                               '⚠ 它只**下载数据**；下载完还要点「⚡ 只补新交易日」把广度续算上去。\n'
                               '⚠ 口径固定 = **前复权**日线（`kline_daily`），'
                               '与行情页当前选的口径无关；不复权那份在「🗄 数据管理」单独维护。')
        lay.addWidget(p.btn_sync)

        p.btn_incr = _flat_btn('⚡ 只补新交易日', '已经有结果、只是新下了几天数据时用：'
                               '过去每一天都不重算、逐位不变，只把新增的交易日接到曲线末尾（D7）。'
                               '数据没变时点了也只是确认一下"已是最新"。\n'
                               '（要整段历史重算请用「▶ 开始扫描」；怀疑历史被修订用「⟳ 全量重算」。）')
        p.btn_incr.setEnabled(False)
        lay.addWidget(p.btn_incr)

        p.btn_full = QPushButton('⟳ 全量重算')
        p.btn_full.setStyleSheet(
            "QPushButton { color:#8A94A6; background:transparent; border:none;"
            " padding:5px 8px; font-size:12px; }"
            "QPushButton:hover { color:#C62828; }")
        p.btn_full.setCursor(Qt.CursorShape.PointingHandCursor)
        p.btn_full.setToolTip('**危险动作**（隔离 + 二次确认）：只有"数据被修订"或"换了复权口径"'
                              '时才需要 —— 日常用「⚡ 只补新交易日」即可，它只算新交易日（D7）。')
        lay.addWidget(p.btn_full)

        p.btn_run = QPushButton('▶ 开始扫描')
        p.btn_run.setToolTip('按当前公式/阈值/范围，把**整段历史从头算一遍**（首次运行、'
                             '或改了条件时用）。数据与条件都没变 ⇒ 直接命中缓存秒回。')
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
        lay.setSpacing(6)

        # —— 标题行：口径必须印在标题上（E 节）——
        head = QHBoxLayout()
        head.setSpacing(8)
        p.lbl_title = QLabel('📊 广度：每天有多少只满足条件')
        p.lbl_title.setStyleSheet('font-size: 14px; font-weight: bold; color: #1F2430;')
        head.addWidget(p.lbl_title)
        head.addStretch()
        p.lbl_cal = QLabel('')
        p.lbl_cal.setStyleSheet('font-size: 11.5px; color: #5A6474;')
        head.addWidget(p.lbl_cal)
        p.lbl_cached = QLabel('')
        p.lbl_cached.setStyleSheet('font-size: 11px; color: #8A94A6;')
        head.addWidget(p.lbl_cached)
        lay.addLayout(head)

        # —— L0 主角：双窗格折线（吃满剩余高度）——
        p.chart = BreadthChart()
        lay.addWidget(p.chart, 1)

        # —— 近 5 日迷你读数（原型 foot）——
        p.lbl_mini = QLabel('')
        p.lbl_mini.setStyleSheet('font-size: 11.5px; color: #8A94A6;')
        lay.addWidget(p.lbl_mini)

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
        p.chart.hide()

        # —— 口径脚注 ——
        p.lbl_foot = QLabel('口径：前复权 · 粗筛后精算 · 数据不足不计入命中 · '
                            '广度占比的分母 = 有效样本（命中 + 未命中），不是全市场只数')
        p.lbl_foot.setStyleSheet('font-size: 11px; color:#B4BECB;')
        lay.addWidget(p.lbl_foot)
        return card

    # ---------- L3 配置抽屉（覆盖层；必须**最后**创建 —— 堆叠顺序 = 创建顺序）----------
    def build_overlays(self) -> None:
        p = self.page
        p._panes = [ScanFormulaPane(), ScanFilterPane(), BreadthDisplayPane()]
        p._formula_pane = p._panes[0]
        p._filter_pane = p._panes[1]
        p._display_pane = p._panes[2]
        p._scrim = ClickCatcher(p)
        p._scrim.setStyleSheet('QFrame { background: rgba(15, 22, 34, 0.28); }')
        p._scrim.hide()
        p._drawer = EditDrawer(p._panes, p)
        p._drawer.hide()
