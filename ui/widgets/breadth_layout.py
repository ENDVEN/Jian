# ui/widgets/breadth_layout.py
"""📊 M3「广度统计」—— 版式装配（§7-B1/B2 主案 E 节 · 样板 A，与 M2 `scan_layout` 同款）

【版式分层（§10-14）】页签（沿用 `backtest_module` 壳）→ **L1 操作轴**（统计范围 · 区间 ·
复权，1 行）→ **L2 摘要条**（配置 chips + 回执 + ⚡增量 / ⟳全量重算 / ▶主按钮，1 行）
→ **L0 结果区**（双窗格折线，吃满）→ **L3 配置抽屉**（覆盖层，不动主区高度）—— **常驻 ≤3 行**。

【职责边界】只造控件、只排布局；**不存状态、不做取数**（状态全在页面，行为在
`breadth_flow`，**多行小图**在 `breadth_rows`）。widgets 模块构造只收 `page`，方法内一律 `p = self.page`。

【复用】ƒ 函数卡与 🎚 粗筛卡**直接 import `scan_layout` 的同款 EditPane** —— M2/M3 共用同一份
编辑器（原型："与单股回测 / 全市场筛选共用同一份函数段与配方库"），阈值⇄控件的换算
也只有 `ScanFilterPane` 那一处；危险动作（⟳ 全量重算）在 L2 上**低调呈现**（§10-10）。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel,
                             QPushButton, QProgressBar, QScrollArea, QSizePolicy,
                             QStackedWidget, QVBoxLayout, QWidget)

from data.akshare_feed import INDEX_PRESETS
from ui.widgets.backtest_panes import CARD_QSS, ClickCatcher, EditDrawer, EditPane
from ui.widgets.breadth_chart import (CHART_TYPES, DEFAULT_CHART_TYPE,
                                      DEFAULT_INDEX_STYLE, INDEX_STYLES)
# ★1.73 / §7-B16 期 1：L0 换成**多行小图**（每项一行：柱 + 5 周均线；底部指数副图固定高度）
from ui.widgets.breadth_items import BreadthItemsPanel
from ui.widgets.breadth_rows import (INDEX_HEIGHT_RANGE, INDEX_PANE_HEIGHT,
                                     MA_WINDOW_DEFAULT, BreadthRowsChart)
from ui.widgets.gate_hint import GateHintBar, GateThresholdRow   # ★1.74 期 2：闸的"看得见"部件
from ui.widgets.relation_card import RelationCard                 # ★1.75 期 3：关系量化卡（含导出）
from ui.widgets.relation_chart import EventStudyChart             # ★1.75 期 3：事件对齐图
from ui.widgets.summary_chip import build_chip, chip_qss   # ★1.64：chip 的**三页唯一来源**
from ui.widgets.styles import SUMMARY_GHOST_QSS, SUMMARY_RUN_QSS   # ★1.64：三页同一张脸
from ui.widgets.custom_widgets import (COMBO_QSS, FLAT_QSS,
                                        SYNC_ACTION_LABEL, NoWheelComboBox,
                                        NoWheelSpinBox, SegmentedControl,
                                        hint_icon, mini_label)
from ui.widgets.scan_layout import (ScanFilterPane, ScanFormulaPane,  # noqa: F401
                                    ScanScopePane)

__all__ = ['BreadthLayout', 'BreadthDisplayPane', 'RANGE_PRESETS', 'DEFAULT_INDEX_CODE']

# 区间快捷档（顺序即下拉顺序；语义与回测页区间档一致）
RANGE_PRESETS = (('3m', '近3个月'), ('6m', '近6个月'), ('1y', '近1年'),
                 ('3y', '近3年'), ('5y', '近5年'), ('all', '全部历史'))
DEFAULT_RANGE = '1y'
DEFAULT_INDEX_CODE = 'sh000001'          # 副图默认上证指数（INDEX_PRESETS 首项）

# ★1.75 / §7-B16 期 3：**三视图**（用户 2026-10-15 确认：L1 分段控件切换，**不新开页面**）。
#   三视图**共用同一份扫描结果** ⇒ 切换 = 纯渲染（不进线程、不读盘、**不重扫**）。
#   key 进偏好（`breadth_ui.view`）；顺序即分段控件顺序。
VIEW_ROWS, VIEW_EVENT, VIEW_CARD = 'rows', 'event', 'card'
VIEWS = ((VIEW_ROWS, '📊 多行小图'), (VIEW_EVENT, '🧪 事件对齐'), (VIEW_CARD, '🧮 关系卡'))
VIEW_INDEX = {VIEW_ROWS: 0, VIEW_EVENT: 1, VIEW_CARD: 2}

# ★1.73 / §7-B16 期 1 收尾：**引导文案**（用户 2026-10-12 原话："这种功能没有引导根本不知道
#   这个阈值到底是啥"）—— 文案写成模块级常量：冒烟能直接断言"该说的都说了"，
#   且只有一份（首次引导条 + 常驻 ⓘ 入口共用，不会两处漂）。
HINT_TEXT = ('你可以这样看这张图：<b>柱</b> = 每天有多少只满足条件，<b>线</b> = 5 周均'
             '（把每天的噪声抹掉看趋势）· 右上「展示」里可切 <b>家数 / 占比</b> · '
             '点任一项的 ★ = 放大那一行。想知道「什么条件配什么图」（三道闸）点右边按钮。')
GATES_HELP_TEXT = (
    '三道闸（决定"这个条件能不能用事件图看"）\n\n'
    '① 稀疏度闸：命中【天数】占比 = 有命中的交易日 / 全部交易日（不是命中家数占比）\n'
    '   · < 5%  ⇒ 像"事件" ⇒ 可以做事件对齐图 / K 线色带\n'
    '   · 5%~30% ⇒ 半稀疏 ⇒ 用"占比分 5 档 + 前向收益"\n'
    '   · > 30% ⇒ 几乎天天命中 = 市场的"状态"，不是"事件" ⇒ 只看占比 / IC / 回归\n'
    '   （例：你的"情绪≥80"≈2%、"情绪<20"≈3% ⇒ 适合事件图；"QSD>0 且 GLX>0"≈34% ⇒ 不适用）\n\n'
    '② 独立性闸：一段行情会连续命中几十天 ⇒ n 会虚高。所以同时给两个 n：\n'
    '   "全部命中日"与"独立事件"（与上一个被接受事件相隔 ≥ 5 个交易日才算新事件）。\n\n'
    '③ 多重检验闸：一次比较了几组（条件 × 窗口）就如实说，并给置换检验 p 值\n'
    '   （把命中日期随机打乱反复重算 ⇒ 回答"随机情况下能不能也凑出这个差"）。\n\n'
    '关键坑：把"命中家数"当事件数会严重虚高（同一天全市场同向 ⇒ 1500 只其实只有 1 个观测，\n'
    'n 会被放大上千倍、p 值失去意义）。n 要按【天】或【独立事件】算。\n\n'
    '这三个阈值都可以在 设置 → 回测与扫描默认（M3 稀疏闸 / 频密闸 / 独立事件间隔）里调，\n'
    '也可以在相关页面就地调；改完立即生效、【不会重跑扫描】。')

# 抽屉几何（与 scan_layout / backtest.py 同款口径，§11.5-26）
DRAWER_MIN_WIDTH = 420
DRAWER_MAX_WIDTH = 560


def _chip(text: str, tooltip: str = '', state: str = 'on') -> QPushButton:
    """摘要条胶囊 —— ★1.64 起**与 M1/M2 同源**（`summary_chip.build_chip`，四态药丸）。

    旧版各写一份、且引恒绿的 `CHIP_QSS_ON` ⇒ 同一个零件三张脸（用户报的"三套设计语言"）。
    """
    return build_chip(text, tooltip, state)


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

        self.chk_smooth = QCheckBox('叠加均线（柱是量感 / 线是趋势）')
        self.chk_smooth.setToolTip('对广度序列做 5 周滚动平均，看趋势不看单日抖动')
        # ★1.73 / §7-B16 期 1：**柱口径默认「占比 %」**（用户 2026-10-12 拍板）——
        #   多行小图里各行量级差很多（情绪≥80 约 2% vs QSD&GLX 约 34%），
        #   占比才是**跨行可比**的口径；家数仍可一键切回（取消勾选），切换**不重扫**。
        self.chk_ratio = QCheckBox('柱口径用「占比 %」（默认；取消勾选 = 家数）')
        self.chk_ratio.setChecked(True)
        self.chk_ratio.setToolTip('占比的分母 = **有效样本**（命中 + 未命中），不是全市场只数'
                                  ' —— 新上市 / 数据不足的票不进分母（三态铁律，E 节）。\n'
                                  '切换它只是换个画法，**不会重扫**。')
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
                                       '想看大一点的指数图：改下面的「副图高度」（120~400px）。')
        istyle_row.addWidget(self.cb_index_style, 1)
        istyle_row.addStretch()
        self.body_lay.addLayout(istyle_row)

        # —— ★1.73 / §7-B16 期 1 收尾：**副图高度可调**（用户拍板"必须有调整入口、不许写死"）——
        #   与 v6.43 的"拖分界线调高"的取舍：拖动只改 `_stretch`，而固定高度把 min==max 钉死
        #   ⇒ 二者互斥。本版选**数值框**：精确、能记住，且与"副图不被行数压扁"这条硬规则并存。
        h_row = QHBoxLayout()
        h_row.setSpacing(6)
        h_row.addWidget(mini_label('副图高度'))
        self.spin_index_h = NoWheelSpinBox()
        self.spin_index_h.setRange(int(INDEX_HEIGHT_RANGE[0]), int(INDEX_HEIGHT_RANGE[1]))
        self.spin_index_h.setSingleStep(10)
        self.spin_index_h.setValue(int(INDEX_PANE_HEIGHT))
        self.spin_index_h.setSuffix(' px')
        self.spin_index_h.setMinimumWidth(96)
        self.spin_index_h.setToolTip(
            '指数副图的固定高度 —— **不随统计项行数变化**（行数多时行区自己滚动，副图不被压扁）。\n'
            f'范围 {INDEX_HEIGHT_RANGE[0]}~{INDEX_HEIGHT_RANGE[1]}px；想看大一点的指数图就把它调大。\n'
            '改完立即重画，**不会重跑扫描**。')
        h_row.addWidget(self.spin_index_h)
        h_row.addWidget(hint_icon('为什么是固定高度：行数一多，若副图按比例分空间就会被压成一条线\n'
                                 '（"指数图看不见了"）。固定高度 + 行区滚动，两边都保住。'))
        h_row.addStretch()
        self.body_lay.addLayout(h_row)

        # —— ★1.74 期 2：**均线窗口可调**（用户 2026-10-15 拍板「要也给用户调」）——
        ma_row = QHBoxLayout()
        ma_row.setSpacing(6)
        ma_row.addWidget(mini_label('均线窗口'))
        self.spin_ma = NoWheelSpinBox()
        self.spin_ma.setRange(0, 60)
        self.spin_ma.setValue(int(MA_WINDOW_DEFAULT))
        self.spin_ma.setSuffix(' 日')
        self.spin_ma.setMinimumWidth(96)
        self.spin_ma.setToolTip(
            '柱上方那条线 = **N 日均线**（把每天的噪声抹掉看趋势）。\n'
            '0 = 只画柱不画线（想看"每天实际有多少"的原始量感时用）。\n'
            '改完立即重画，**不会重跑扫描**。')
        ma_row.addWidget(self.spin_ma)
        ma_row.addWidget(hint_icon('为什么默认 5：一周 5 个交易日 —— 比"每天"平滑、又不至于钝到看不出拐点。\n'
                                   '换窗口只影响**画法**，不影响命中判定与任何数字。'))
        ma_row.addStretch()
        self.body_lay.addLayout(ma_row)

        # —— ★1.74 期 2：**三道闸阈值（就地可调）** —— 与「设置 → 回测与扫描默认」**同一份偏好**。
        #   放这里而不是新开页面：用户拍板"必须在相关页面给调整按钮"；改完立即重算徽标与闸条、**不重扫**。
        self.gate_row = GateThresholdRow()
        self.body_lay.addWidget(self.gate_row)

        # 两个控件不许打架：「叠加均线」关掉 ⇒ 窗口输入框禁用（值仍记住，下次勾上还是它）
        self.chk_smooth.toggled.connect(self.spin_ma.setEnabled)
        self.spin_ma.setEnabled(self.chk_smooth.isChecked())

        # —— ★1.75 期 3：**命中色带叠加**（用户拍板：色带做成"指数副图的叠加选项"，不新增视图）——
        self.chk_bands = QCheckBox('指数副图上叠加**命中色带**（每个统计项一条）')
        self.chk_bands.setToolTip(
            '把每个统计项的**命中日**画成指数副图底部的一条色带（按项配色）。\n'
            '判断"命中日是不是聚在拐点附近"用它可以一眼看出来。\n'
            '⚠ 被三道闸判为"太频繁"的条件，色带会连成一片 —— 那种条件请看「🧮 关系卡」，'
            '别靠色带读。改完立即重画，**不会重跑扫描**。')
        self.body_lay.addWidget(self.chk_bands)


# ==========================================
# ④ 📋 统计项（★1.73 / §7-B16 期 1；抽屉最后一张卡 —— 前四张下标不动）
# ==========================================
class BreadthItemsPane(EditPane):
    """上屏**哪几个判定变量**（每项一行）。只管控件，不碰数据。

    ⚠ 与「📈 平滑与展示」的分工：本卡管"**看哪几条**"（选择），展示卡管"**每条怎么画**"（画法）。
    """
    def __init__(self, parent=None):
        super().__init__('items', '📋 统计项（每项一行 · 柱 + 均线）', '#1976D2', '📋 统计项', parent,
                         )
        self.panel = BreadthItemsPanel()
        self.body_lay.addWidget(self.panel)
        tip = QLabel('同一段公式里可以有**多个判定变量**（每条 `名字 := 表达式` 都是一个）。'
                     '选中的变量会在**同一次扫描**里全部算出来（读盘只发生一次），'
                     '各占一行、各自统计家数/占比 —— 这样"两个极端"才能同屏对比。')
        tip.setWordWrap(True)
        tip.setStyleSheet('font-size: 11px; color: #8A94A6;')
        self.body_lay.addWidget(tip)


# ==========================================
# 装配器
# ==========================================
class BreadthLayout:
    """M3 页的版式装配（只造控件 / 排布局；行为在 `breadth_flow`，**多行小图**在 `breadth_rows`）。"""

    def __init__(self, page):
        self.page = page

    # ---------- L1 操作轴 ----------
    def build_top_bar(self) -> QHBoxLayout:
        p = self.page
        lay = QHBoxLayout()
        lay.setSpacing(8)

        # ★1.64：范围那组（统计范围 / 指数 / N 只）已搬进 🌐 统计范围卡（与 M2 **同一张卡**，
        #   一份实现两页共用）—— 本行只留"看多长 + 口径 + 配置入口"。
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

        # —— ★1.75 期 3：**视图切换**（用户拍板：L1 分段控件切三视图，不新开页面）——
        #   三视图共用同一份结果 ⇒ 切换是**纯渲染**；「关系卡」里有导出 PNG/CSV。
        p.seg_view = SegmentedControl(VIEWS, current=VIEW_ROWS)
        p.seg_view.setToolTip('同一份扫描结果，换一种看法（切换**不会重扫**）：\n'
                              '· 📊 多行小图 = 每个统计项一行（柱 + 均线），看"每天多少"\n'
                              '· 🧪 事件对齐 = 把命中日对齐，看"命中前后指数怎么走"\n'
                              '· 🧮 关系卡 = 把"有没有关系、多强、是不是巧合"写成数字（可导出）')
        lay.addWidget(p.seg_view)

        lay.addStretch()
        p.btn_config = _flat_btn('⚙ 配置',
                                 '打开配置抽屉（筛选条件 / 粗筛 / 展示 / 统计范围 —— '
                                 '也可以直接点摘要条上的胶囊）')
        lay.addWidget(p.btn_config)
        return lay

    # ---------- L2 摘要条 ----------
    def build_summary_bar(self) -> QHBoxLayout:
        p = self.page
        lay = QHBoxLayout()
        lay.setSpacing(6)

        p.chip_formula = _chip('ƒ 条件 —', '筛选条件（与 M2/M1 同一套引擎）')
        p.chip_filter = _chip('🎚 粗筛 —', '粗筛阈值')
        p.chip_scope = _chip('🌐 范围 —', '统计范围（标的域与只数）')
        p.chip_display = _chip('📈 展示 —', '柱口径（占比/家数）/ 均线 / 指数副图')
        # ★1.73 / §7-B16 期 1：**统计项**（上屏哪几个判定变量）—— 与"展示"分开：
        #   前者管"看哪几条"，后者管"每条怎么画"。
        p.chip_items = _chip('📋 统计项 —', '上屏的判定变量（同一段公式可多选，一次扫描全部拿到）')
        # ★1.64：胶囊**可点开对应配置**（与 M1/M2 同一手感：点开、再点收起、开着的那张高亮）
        for chip, key in ((p.chip_formula, 'fn'), (p.chip_filter, 'filter'),
                          (p.chip_scope, 'scope'), (p.chip_display, 'display'),
                          (p.chip_items, 'items')):
            chip.setToolTip(chip.toolTip() + ' —— 点击打开这张配置卡（再点收起）')
            chip.clicked.connect(lambda _=False, k=key: p.open_pane(k))
            lay.addWidget(chip)

        # ★1.61 / §7-B16：旧「📚 载入 / 💾 存为 / 管理」已退役 —— 统一收进「ƒ 库」浮窗
        #   （与 M2 同一套；两页共用一份方案池 ⇒ 入口与长相也必须同源）。
        lay.addStretch()

        p.lbl_receipt = QLabel('还没有扫描过 —— 选好范围与条件后点「▶ 开始扫描」')
        p.lbl_receipt.setStyleSheet('font-size: 11.5px; color: #8A94A6;')
        # 窄屏不撑窗：水平 Ignored ⇒ 长文本不抬高窗口最小宽度（详情走 tooltip / 结果区）
        p.lbl_receipt.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(p.lbl_receipt, 1)

        # ★1.61 / §7-B16 H6：**函数总库入口**（常驻可见，与 M2 同款同位置 —— 两页共用一份方案池，
        #   入口与长相也必须同源）。此前它只长在抽屉里的公式卡片上，抽屉默认关着 ⇒ 看不到。
        p.btn_hub = QPushButton('ƒ 库')
        p.btn_hub.setStyleSheet(SUMMARY_GHOST_QSS)      # ★1.64：与 M1/M2 的次级动作同一张脸
        p.btn_hub.setCursor(Qt.CursorShape.PointingHandCursor)
        p.btn_hub.setToolTip('打开「ƒ 函数总库」浮窗：选一个函数载入到本页，'
                             '或把本页正在写的条件存进总库（管理与编辑在左轨「ƒ 函数库」页）')
        lay.addWidget(p.btn_hub)

        # ★1.61 / §7-B16 H4：「⤒ 用最新版」**默认隐藏**（与 M2 同款、同观感 —— 两页共用一份方案池，
        #   提示与动作也必须同源）。不点它 ⇒ 方案里的函数保持原样（红线②，默认动作）。
        p.btn_apply_latest = QPushButton('⤒ 用最新版')
        p.btn_apply_latest.setStyleSheet(FLAT_QSS)
        p.btn_apply_latest.setCursor(Qt.CursorShape.PointingHandCursor)
        p.btn_apply_latest.setToolTip('把总库里这条函数的最新版本取过来替换筛选条件；'
                                      '粗筛阈值 / 统计范围 / 复权口径等配置一字不动。')
        p.btn_apply_latest.hide()
        lay.addWidget(p.btn_apply_latest)

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
        p.btn_sync = _flat_btn(SYNC_ACTION_LABEL,        # ★1.64：样式随后改成 **chip**（见下）
                               '把当前范围的数据补齐/更新到最近一个已收盘定稿的交易日。\n'
                               '已是最新的标的会**自动跳过、不发请求**。\n'
                               '⚠ 它只**下载数据**；下载完还要点「⚡ 只补新交易日」把广度续算上去。\n'
                               '⚠ 口径固定 = **前复权**日线（`kline_daily`），'
                               '与行情页当前选的口径无关；不复权那份在「🗄 数据管理」单独维护。')
        # ★1.64：做成 **chip 样式**（用户实测："单独一段字看着比较难受"）—— 与 M2 同款同观感
        p.btn_sync.setStyleSheet(chip_qss('on'))
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
        # ★1.64：主操作与 M1/M2 **同一枚**（蓝底实心）—— 旧版三页各写一份、观感不一
        p.btn_run.setStyleSheet(SUMMARY_RUN_QSS)
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
        # ★1.73 收尾：**常驻说明入口**（ⓘ 三道闸 + 怎么看图）—— 说明**不许只存在首次弹窗里**
        p.hint_icon = hint_icon(GATES_HELP_TEXT)
        head.addWidget(p.hint_icon)
        lay.addLayout(head)

        # —— 首次引导条（一次性、可关闭；用户原话"没有引导根本不知道这个阈值到底是啥"）——
        p.hint_bar = QFrame()
        p.hint_bar.setStyleSheet('QFrame { background: #F1F7FF; border: 1px solid #CFE3FF;'
                                 ' border-radius: 8px; }')
        _hb = QHBoxLayout(p.hint_bar)
        _hb.setContentsMargins(10, 6, 8, 6)
        _hb.setSpacing(8)
        p.lbl_hint = QLabel(HINT_TEXT)
        p.lbl_hint.setWordWrap(True)
        p.lbl_hint.setStyleSheet('font-size: 11.5px; color: #33475B; border: none;')
        _hb.addWidget(p.lbl_hint, 1)
        p.btn_gates_help = QPushButton('三道闸是什么？')
        p.btn_gates_help.setStyleSheet(FLAT_QSS)
        p.btn_gates_help.setCursor(Qt.CursorShape.PointingHandCursor)
        p.btn_gates_help.setToolTip('1 分钟看完：什么样的条件配什么样的图（以及 n 该怎么算）')
        _hb.addWidget(p.btn_gates_help)
        p.btn_hint_ok = QPushButton('知道了')
        p.btn_hint_ok.setStyleSheet(FLAT_QSS)
        p.btn_hint_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        p.btn_hint_ok.setToolTip('收起这条引导（只提示这一次；之后随时点右上 ⓘ 再看）')
        _hb.addWidget(p.btn_hint_ok)
        lay.addWidget(p.hint_bar)

        # —— 闸条（★1.74 期 2：**只在有统计项被三道闸拦下时**出现；与引导条同一张脸）——
        #   三要素由 `GateHintBar.set_blocked` 保证：原因（带数字）· 替代 · 动作。
        p.gate_bar = GateHintBar()
        lay.addWidget(p.gate_bar)

        # —— L0 主角：**多行小图**（吃满剩余高度；★1.73 收尾：**行区自己滚动**）——
        #   ★1.73 / §7-B16 期 1：从"一主一副双窗格"升级为"**每统计项一行 + 底部指数副图**"。
        #   ⚠ 属性名仍是 `p.chart`（页面/流程/断言都按它引），只换实现类。
        #   行数多时：`p.chart` 的最小高 = 行数×行高下限 + 副图高 ⇒ 滚动条出现，
        #   副图**不被压扁**、整页**也不跟着滚**（设计稿硬规则②）。
        p.chart = BreadthRowsChart()
        p.chart_scroll = QScrollArea()
        p.chart_scroll.setWidgetResizable(True)
        p.chart_scroll.setFrameShape(QFrame.Shape.NoFrame)
        p.chart_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        p.chart_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        p.chart_scroll.setWidget(p.chart)

        # —— ★1.75 期 3：三视图**堆叠**（0 = 多行小图 / 1 = 事件对齐 / 2 = 关系卡）——
        #   为什么用 `QStackedWidget` 而不是各建一块：三视图**共用**同一份结果与同一条区间切片，
        #   堆叠只换"看哪一张脸"，切换零成本；关系卡自己带滚动（它比一屏高）。
        p.event_chart = EventStudyChart()
        p.relation_card = RelationCard()
        p.card_scroll = QScrollArea()
        p.card_scroll.setWidgetResizable(True)
        p.card_scroll.setFrameShape(QFrame.Shape.NoFrame)
        p.card_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        p.card_scroll.setWidget(p.relation_card)
        p.view_stack = QStackedWidget()
        for _view_widget in (p.chart_scroll, p.event_chart, p.card_scroll):
            p.view_stack.addWidget(_view_widget)
        p.view_stack.setCurrentIndex(VIEW_INDEX[VIEW_ROWS])
        lay.addWidget(p.view_stack, 1)

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
        # ★1.73/1.75：图 · 行区滚动容器 · **三视图堆叠** 一起显隐（见 `BreadthResult._show_chart`）
        p.view_stack.hide()

        # —— 口径脚注 ——
        p.lbl_foot = QLabel('口径：前复权 · 粗筛后精算 · 数据不足不计入命中 · '
                            '广度占比的分母 = 有效样本（命中 + 未命中），不是全市场只数')
        p.lbl_foot.setStyleSheet('font-size: 11px; color:#B4BECB;')
        lay.addWidget(p.lbl_foot)
        return card

    # ---------- L3 配置抽屉（覆盖层；必须**最后**创建 —— 堆叠顺序 = 创建顺序）----------
    def build_overlays(self) -> None:
        p = self.page
        # ★1.64：多一张「🌐 统计范围」卡（从 L1 搬进来；**与 M2 同一张卡类**）——
        #   前三张的下标不动（`_formula_pane` / `_filter_pane` / `_display_pane` 引用照旧）。
        p._panes = [ScanFormulaPane(), ScanFilterPane(), BreadthDisplayPane(), ScanScopePane(p),
                    BreadthItemsPane()]          # ★1.73：统计项卡**追加在最后**（前四张下标不动）
        p._formula_pane = p._panes[0]
        p._filter_pane = p._panes[1]
        p._display_pane = p._panes[2]
        p._items_pane = p._panes[4]          # ★1.73：统计项卡（第 5 张）
        p._scrim = ClickCatcher(p)
        p._scrim.setStyleSheet('QFrame { background: rgba(15, 22, 34, 0.28); }')
        p._scrim.hide()
        p._drawer = EditDrawer(p._panes, p)
        p._drawer.hide()
