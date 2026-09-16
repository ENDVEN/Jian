# ui/widgets/desk_layout.py
"""行情工作台的**版式装配**：顶栏两行 + 左栏（图标轨 + 五页）（1.23 自 `ui/views/trading_desk.py` 拆出 · §7-B6 STEP 6）。

【职责】只做"把控件摆到该去的地方"，不承载任何业务规则：
  · 第 1 行（L1）：标题 + 查阅 + 云端同步；
  · 第 2 行（L2）：周期（含分钟二级档位）/ 复权 分段控件 + 工具行 chips + 标注胶囊
    （**常驻行数 ≤3**，§10-14：其余低频配置一律进左栏面板）；
  · 左栏：`IconRail`（52px 图标轨）+ `DeskPanel`（5 页：★自选 / ƒ公式 / ◫图层 / ✎标注 / ⛁数据）。

【搬家不重建（§11.5 / 1.22 已验证）】控件对象与**变量名一个都不动**，只是 `addWidget`
到新的容器里 ⇒ 既有 234 项页面断言的访问口径零改动。

【常量归属】`RAIL_ITEMS` / `PANEL_DEFAULT_WIDTH` / `RAIL_TOTAL_WIDTH` 定义在这里
（它们描述"版式"），`ui/views/trading_desk.py` 里保留同名 re-export
（既有 `from ui.views.trading_desk import RAIL_ITEMS` 的用法零改动，§11.7）。
"""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QMenu, QPushButton, QVBoxLayout, QWidget)

from data.annotations import PERIOD_DAILY
from data.sync_service import ADJUST_CHOICES, ADJUST_LABELS
from ui.widgets.adaptive_axis import AdaptiveAxes
from ui.widgets.annotation_layer import AnnotationLayer
from ui.widgets.chart_host import AXIS_NO_VALUES, ChartHost
from ui.widgets.custom_widgets import CHIP_MORE_QSS, SegmentedControl
from ui.widgets.desk_annotations import TOOL_SEGMENTS
from ui.widgets.desk_data import MINUTE_SEGMENTS, PERIOD_GROUPS
from ui.widgets.desk_panel import DeskPanel, IconRail

# ★STEP 4：左栏 = 图标轨（52px）+ 分页面板（5 页）。顺序即显示顺序。
RAIL_ITEMS = (
    ("watch", "★", "自选股"),
    ("formula", "ƒ", "公式与配方"),
    ("layer", "◫", "主图叠加 / 附图"),
    ("anno", "✎", "标注工具（画线都在这）"),
    ("data", "⛁", "数据与口径"),
)

# ---- 页面内的样式（与 §10-9 一致：能给具名常量的就不就地写字符串）----
_CARD_QSS = "QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }"
_BTN_QSS = ("QPushButton { background:#F5F5F5; border:1px solid #E0E0E0; border-radius:4px; "
            "padding:5px; font-weight:bold; color:#424242; }"
            "QPushButton:hover { background:#EDEDED; }")
_BTN_PRIMARY_QSS = ("QPushButton { font-size:13px; font-weight:bold; color:white; "
                    "background:#1976D2; padding:7px 14px; border:none; border-radius:6px; }"
                    "QPushButton:hover { background:#1565C0; }")
_BTN_DANGER_QSS = ("QPushButton { background:#FFEBEE; border:1px solid #FFCDD2; border-radius:4px; "
                   "padding:5px; font-weight:bold; color:#D32F2F; }")
_SECTION_QSS = "font-weight:bold; color:#757575; font-size:12px;"


def section(text: str) -> QLabel:
    """左栏各页的小标题（样式单一来源）。"""
    label = QLabel(text)
    label.setStyleSheet(_SECTION_QSS)
    return label


def hint_label(text: str) -> QLabel:
    """左栏各页的灰字说明（样式单一来源）。"""
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("font-size:11px; color:#8A94A6;")
    return label


class DeskLayout:
    """顶栏两行 + 左栏五页的装配（页面持状态，本类只摆控件）。"""

    def __init__(self, page):
        self.page = page

    # ==========================================
    # 第 1 行（L1）：标题 + 查阅 + 云端同步
    # ==========================================
    def build_top_bar(self) -> QHBoxLayout:
        p = self.page
        bar = QHBoxLayout()
        title = QLabel("行情工作台")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #212121;")
        bar.addWidget(title)
        bar.addStretch()

        p.txt_search = QLineEdit()
        p.txt_search.setPlaceholderText("输入代码或中文名 (如: 600519 或 茅台)")
        p.txt_search.setFixedWidth(250)
        p.txt_search.setStyleSheet(
            "QLineEdit { font-size: 14px; padding: 8px 15px; border: 1px solid #E0E0E0; "
            "border-radius: 6px; background: white; }")
        p.txt_search.returnPressed.connect(p.search_and_load)
        bar.addWidget(p.txt_search)

        p.btn_search = QPushButton("🔍 查阅")
        p.btn_search.setStyleSheet(_BTN_PRIMARY_QSS)
        p.btn_search.clicked.connect(p.search_and_load)
        bar.addWidget(p.btn_search)

        p.btn_sync = QPushButton("☁️ 云端同步")
        p.btn_sync.setStyleSheet(
            "QPushButton { font-size: 14px; font-weight: bold; color: #1976D2; background: #E3F2FD; "
            "padding: 8px 15px; border: 1px solid #BBDEFB; border-radius: 6px; margin-left: 10px; }")
        p.btn_sync.setToolTip(
            "本地有数据 → 只补下载缺失的最新几天（快）；\n"
            "本地没数据 → 直接整段抓取。\n\n"
            "需要「丢弃本地重新整段下载」时，请到「🗄 数据管理」页用「重新全量下载」。")
        p.btn_sync.clicked.connect(p.sync_cloud)
        bar.addWidget(p.btn_sync)

        p.lbl_sync_status = QLabel("")
        p.lbl_sync_status.setStyleSheet("font-size: 12px; color: #8A94A6; margin-left: 8px;")
        bar.addWidget(p.lbl_sync_status)
        return bar

    # ==========================================
    # 第 2 行（L2）：分段控件 + 摘要（★STEP 3b）
    # ==========================================
    def build_tool_row(self) -> QHBoxLayout:
        """周期（含分钟档位）/ 复权 的分段控件 + 口径说明 + 标注条数。

        常驻行数 ≤3（§10-14）：本行与上一行合计 2 行，其余低频配置全在左栏面板
        （STEP 4 会把左栏收成"图标轨 + 分页面板"）。
        """
        p = self.page
        row = QHBoxLayout()
        row.setSpacing(8)

        row.addWidget(p._row_label("周期"))
        p.seg_period = SegmentedControl(PERIOD_GROUPS)
        p.seg_period.setToolTip(
            "日/周/月由日线**就地聚合**（不额外下载数据）；\n"
            "**分钟**为独立取数（新浪源，各档位可回溯的交易日数不同，见右侧提示）。")
        p.seg_period.sigChanged.connect(p._on_period_group_clicked)
        row.addWidget(p.seg_period)

        # ---- 二级：分钟档位（只有一级选"分钟"时出现）----
        p.lbl_minute_unit = p._row_label("档位")
        p.seg_minute = SegmentedControl(MINUTE_SEGMENTS, current=p.current_minute)
        p.seg_minute.setToolTip("分钟各档位**各自取数**（历史深度不同，不能互相推导）。")
        p.seg_minute.sigChanged.connect(p._on_minute_clicked)
        row.addWidget(p.lbl_minute_unit)
        row.addWidget(p.seg_minute)
        p.lbl_minute_depth = QLabel("")
        p.lbl_minute_depth.setStyleSheet("font-size:11.5px; color:#8A94A6;")
        row.addWidget(p.lbl_minute_depth)

        row.addWidget(p._row_sep())
        row.addWidget(p._row_label("复权"))
        p.seg_adjust = SegmentedControl(
            [(value, ADJUST_LABELS[value]) for value in ADJUST_CHOICES],
            current=p.current_adjust)
        p.seg_adjust.setToolTip(
            "**前复权**（默认）：看长期趋势 / 算指标用它；**不复权**：看当年的真实价位。\n"
            "两份数据**各存一个分区**，来回切换不覆盖、也不会重复下载。")
        p.seg_adjust.sigChanged.connect(p._on_adjust_clicked)
        row.addWidget(p.seg_adjust)

        # 口径说明（分钟下复权不可用 —— 不是隐藏而是**禁用 + 说明**：
        # 藏起来用户会以为"前复权也在生效"，那是假口径）
        p.lbl_caliber_note = QLabel("")
        p.lbl_caliber_note.setStyleSheet("font-size:11.5px; color:#E65100;")
        row.addWidget(p.lbl_caliber_note)

        # ---- ★STEP 3c：工具行 chips（"最近使用优先"，见 ui/widgets/chip_mru.py）----
        row.addWidget(p._row_sep())
        row.addWidget(p._row_label("主图"))
        p._main_chips = QWidget()
        p._main_chips_lay = QHBoxLayout(p._main_chips)
        p._main_chips_lay.setContentsMargins(0, 0, 0, 0)
        p._main_chips_lay.setSpacing(6)
        row.addWidget(p._main_chips)
        p.btn_main_more = QPushButton("＋ 更多")
        p.btn_main_more.setStyleSheet(CHIP_MORE_QSS)
        p.btn_main_more.setCursor(Qt.CursorShape.PointingHandCursor)
        p.btn_main_more.setToolTip("主图叠加的**完整候选池**（工具行只放最近用过的 3 个）")
        p._main_more_menu = QMenu(p.btn_main_more)
        p.btn_main_more.setMenu(p._main_more_menu)
        row.addWidget(p.btn_main_more)

        row.addWidget(p._row_sep())
        row.addWidget(p._row_label("附图"))
        p._sub_chips = QWidget()
        p._sub_chips_lay = QHBoxLayout(p._sub_chips)
        p._sub_chips_lay.setContentsMargins(0, 0, 0, 0)
        p._sub_chips_lay.setSpacing(6)
        row.addWidget(p._sub_chips)
        p.btn_sub_more = QPushButton("＋ 更多")
        p.btn_sub_more.setStyleSheet(CHIP_MORE_QSS)
        p.btn_sub_more.setCursor(Qt.CursorShape.PointingHandCursor)
        p.btn_sub_more.setToolTip("附图与公式副图的**完整候选池**（工具行只放最近用过的 3 个）")
        p._sub_more_menu = QMenu(p.btn_sub_more)
        p.btn_sub_more.setMenu(p._sub_more_menu)
        row.addWidget(p.btn_sub_more)

        row.addStretch()
        # ★STEP 4：画线工具的家在左栏「✎ 标注」页 —— 工具行只留这个入口 + 条数胶囊
        p.btn_anno_tool = QPushButton("✎")
        p.btn_anno_tool.setStyleSheet(CHIP_MORE_QSS)
        p.btn_anno_tool.setCursor(Qt.CursorShape.PointingHandCursor)
        p.btn_anno_tool.setToolTip("打开左栏「✎ 标注工具」页（画线类型 / 添加 / 删除都在那里）")
        # 走 `on_rail_clicked`：面板折起时**先展开再切页**（与点图标轨同一个手感）
        p.btn_anno_tool.clicked.connect(lambda: p.on_rail_clicked("anno"))
        row.addWidget(p.btn_anno_tool)
        p.lbl_anno_pill = QLabel("")
        p.lbl_anno_pill.setStyleSheet(
            "font-size:11.5px; color:#5B6472; background:#F2F4F8; border-radius:9px;"
            " padding:3px 10px;")
        row.addWidget(p.lbl_anno_pill)

        p._sync_period_widgets()
        return row

    # ==========================================
    # 左栏：图标轨 + 分页面板 + 五页内容（★STEP 4）
    # ==========================================
    def build_control_panel(self) -> QFrame:
        """左栏 = **图标轨（52px）+ 分页面板**（★STEP 4 · §7-B6-C 的 L3 层）。

        5 个图标 = 5 页：★自选 / ƒ公式 / ◫图层 / ✎标注 / ⛁数据。
        ⚠ **搬家不重建**：控件对象与变量名一个都不动，只是 `addWidget` 到新的页容器里
        ⇒ 既有 213 项页面断言的访问口径**零改动**（1.22 已验证过这条）。
        """
        p = self.page
        holder = QFrame()
        holder.setStyleSheet("QFrame { background: transparent; border: none; }")
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        p.rail = IconRail([(key, icon, title) for key, icon, title in RAIL_ITEMS])
        p.rail.sigClicked.connect(p.on_rail_clicked)
        row.addWidget(p.rail)

        p.desk_panel = DeskPanel([(key, title) for key, _icon, title in RAIL_ITEMS])
        p.desk_panel.sigCollapseRequested.connect(lambda _key: p.set_panel_collapsed(True))
        row.addWidget(p.desk_panel, 1)

        # 五个页的**空容器** —— 下面几个 `build_*_page` 只负责往对应页里摆控件
        self.build_watch_page(p.desk_panel.body_layout("watch"))
        self.build_formula_page(p.desk_panel.body_layout("formula"))
        self.build_layer_page(p.desk_panel.body_layout("layer"))
        self.build_anno_page(p.desk_panel.body_layout("anno"))
        self.build_data_page(p.desk_panel.body_layout("data"))
        return holder

    # ---- 各页内容（★STEP 4：控件"搬家"，名字与连接一律不变）----
    def build_watch_page(self, lay: QVBoxLayout) -> None:
        """★ 自选股：列表 + 增删/调序。"""
        p = self.page
        lay.addWidget(section("📌 自选股"))
        p.lst_watch = QListWidget()
        p.lst_watch.setFixedHeight(150)
        p.lst_watch.itemDoubleClicked.connect(p._on_watch_activated)
        p.lst_watch.setToolTip("双击切换标的；下方按钮可加入/移除/调序")
        lay.addWidget(p.lst_watch)

        watch_row = QHBoxLayout()
        watch_row.setSpacing(4)
        p.btn_watch_add = QPushButton("★ 加入")
        p.btn_watch_add.setStyleSheet(_BTN_QSS)
        p.btn_watch_add.setToolTip("把当前标的加入自选（已在自选里则提示，不重复添加）")
        p.btn_watch_add.clicked.connect(p.add_to_watchlist)
        watch_row.addWidget(p.btn_watch_add)

        p.btn_watch_remove = QPushButton("🗑")
        p.btn_watch_remove.setStyleSheet(_BTN_DANGER_QSS)
        p.btn_watch_remove.setToolTip("从自选里移除选中项（不影响行情数据）")
        p.btn_watch_remove.clicked.connect(p.remove_from_watchlist)
        watch_row.addWidget(p.btn_watch_remove)

        p.btn_watch_up = QPushButton("⬆")
        p.btn_watch_up.setStyleSheet(_BTN_QSS)
        p.btn_watch_up.setToolTip("上移（顺序 = 你的关注顺序）")
        p.btn_watch_up.clicked.connect(lambda: p.move_watchlist(-1))
        watch_row.addWidget(p.btn_watch_up)

        p.btn_watch_down = QPushButton("⬇")
        p.btn_watch_down.setStyleSheet(_BTN_QSS)
        p.btn_watch_down.clicked.connect(lambda: p.move_watchlist(1))
        watch_row.addWidget(p.btn_watch_down)
        lay.addLayout(watch_row)
        lay.addWidget(hint_label("双击列表即切换标的；顺序 = 你的关注顺序。"))

    def build_formula_page(self, lay: QVBoxLayout) -> None:
        """ƒ 公式与配方：函数内容的编辑与资产化（**显示开关**在 ◫ 图层页）。"""
        p = self.page
        lay.addWidget(section("ƒ 当前公式"))
        p.lbl_formula_status = QLabel("未设置")
        p.lbl_formula_status.setWordWrap(True)
        p.lbl_formula_status.setStyleSheet("font-size: 11px; color: #8A94A6;")
        lay.addWidget(p.lbl_formula_status)

        p.btn_edit_formula = QPushButton("✏️ 编辑公式…")
        p.btn_edit_formula.setStyleSheet(_BTN_QSS)
        p.btn_edit_formula.setToolTip("粘贴通达信式函数，叠加到当前标的（每段可选主图/副图）")
        p.btn_edit_formula.clicked.connect(p.edit_formula)
        lay.addWidget(p.btn_edit_formula)

        for text, tip, slot in (
            ("💾 存为配方…", "把当前公式（含每段的主图/副图目标）存进配方库；同名即覆盖",
             p.save_formula_as),
            ("📚 配方库…", "浏览已保存的公式配方：载入 / 改名 / 删除", p.open_formula_library),
            ("📤 送去做回测", "把函数与参数送进「📐 市场回测」（回测不区分主图/副图）",
             p.send_formula_to_backtest),
        ):
            button = QPushButton(text)
            button.setStyleSheet(_BTN_QSS)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            lay.addWidget(button)
        lay.addWidget(hint_label(
            "配方 = 函数段 + 参数 + 每段目标窗格；开机自动恢复上次用过的配方。"))

    def build_layer_page(self, lay: QVBoxLayout) -> None:
        """◫ 主图叠加 / 附图：**显示开关**（真源就是这几个 QCheckBox，chips 只是投影）。"""
        p = self.page
        lay.addWidget(section("🎛 主图叠加"))
        p.cb_ma = QCheckBox("均线 (MA 5/20/60)")
        p.cb_boll = QCheckBox("布林带 (BOLL)")
        for checkbox in (p.cb_ma, p.cb_boll):
            checkbox.setStyleSheet("QCheckBox { font-size: 12px; color: #424242; }")
            # ★STEP 3c：走统一入口（重渲染 + 工具行 chips 回流），不要分散连 render_charts
            checkbox.stateChanged.connect(p._on_layer_switch_changed)
            lay.addWidget(checkbox)

        p.cb_formula = QCheckBox("自定义公式")
        p.cb_formula.setChecked(True)
        p.cb_formula.setStyleSheet("QCheckBox { font-size: 12px; color: #424242; }")
        p.cb_formula.setToolTip("显示/隐藏函数画出的线、状态柱、图标（与均线/布林带同一套图层协议）")
        p.cb_formula.stateChanged.connect(p._on_layer_switch_changed)
        lay.addWidget(p.cb_formula)

        lay.addSpacing(6)
        lay.addWidget(section("📊 附图"))
        p.cb_vol = QCheckBox("成交量")
        p.cb_vol.setChecked(True)
        p.cb_macd = QCheckBox("MACD")
        for checkbox in (p.cb_vol, p.cb_macd):
            checkbox.setStyleSheet("QCheckBox { font-size: 12px; color: #424242; }")
            checkbox.stateChanged.connect(p._on_layer_switch_changed)
            lay.addWidget(checkbox)
        lay.addWidget(hint_label(
            "振荡型指标（MACD/RSI/量能）放附图，主图 K 线才不会被压扁。\n"
            "工具行只显示最近用过的 3 个，其余在「＋ 更多」里。"))

    def build_anno_page(self, lay: QVBoxLayout) -> None:
        """✎ 标注工具：**画线工具的家**（用户 2026-09-16 拍板从工具行搬进来）。

        顶栏只留一个 ✎ 入口 + "N 条标注"胶囊，避免工具行在 1440px 下溢出。
        """
        p = self.page
        lay.addWidget(section("🛠 画线工具"))
        p.seg_tool = SegmentedControl(TOOL_SEGMENTS)
        p.seg_tool.setToolTip(
            "选好类型后点「➕ 添加标注」；拖动线条/端点调整，**松手自动保存**。\n\n"
            "画线按「日期」保存，所以增量更新、前复权修正都不会让它跑偏；\n"
            "并且按「标的 + 周期」分开存（日线/分钟/周线各画各的）。")
        p.seg_tool.sigChanged.connect(p._on_tool_clicked)
        lay.addWidget(p.seg_tool)

        p.btn_add_annotation = QPushButton("➕ 添加标注")
        p.btn_add_annotation.setStyleSheet(_BTN_QSS)
        p.btn_add_annotation.clicked.connect(p.add_annotation)
        lay.addWidget(p.btn_add_annotation)

        p.btn_delete_annotation = QPushButton("🧽 删除选中")
        p.btn_delete_annotation.setStyleSheet(
            "QPushButton { background:#FFF8E1; border:1px solid #FFE082; border-radius:4px; "
            "padding:5px; font-weight:bold; color:#E65100; }")
        p.btn_delete_annotation.setToolTip("先在图上点一下那条线（变橙色=已选中），"
                                           "再点这里 —— 也可以直接按 Delete 键")
        p.btn_delete_annotation.clicked.connect(p.delete_selected_annotation)
        lay.addWidget(p.btn_delete_annotation)

        p.btn_clear_lines = QPushButton("🗑️ 清空本标的标注")
        p.btn_clear_lines.setStyleSheet(_BTN_DANGER_QSS)
        p.btn_clear_lines.setToolTip("删除当前标的+周期下的全部标注（不可撤销，会二次确认）")
        p.btn_clear_lines.clicked.connect(p.clear_annotations)
        lay.addWidget(p.btn_clear_lines)

        p.lbl_annotation_status = QLabel("")
        p.lbl_annotation_status.setWordWrap(True)
        p.lbl_annotation_status.setStyleSheet("font-size: 11px; color: #8A94A6;")
        lay.addWidget(p.lbl_annotation_status)
        lay.addWidget(hint_label(
            "按标的 + 周期分开保存；坐标按日期锚定 ⇒ 增量更新与前复权修正都不会跑偏。"))

    def build_data_page(self, lay: QVBoxLayout) -> None:
        """⛁ 数据与口径：回执行（周期/复权的**入口**在顶栏第 2 行，这里只交代"现在看的是哪一份"）。"""
        p = self.page
        lay.addWidget(section("📐 数据口径"))
        p.lbl_adjust_hint = QLabel("")
        p.lbl_adjust_hint.setWordWrap(True)
        p.lbl_adjust_hint.setStyleSheet("font-size: 11px; color: #8A94A6;")
        lay.addWidget(p.lbl_adjust_hint)
        lay.addWidget(hint_label(
            "「☁️ 云端同步」按当前口径取数：日线本地有就增量、没有就整段；\n"
            "分钟数据每次取最近一段快照（各档位深度不同），且不接批量预下载。"))

    # ==========================================
    # 右栏：图表区（窗格宿主 + 自适应坐标轴 + 标注层）
    # ==========================================
    def build_chart_area(self) -> QFrame:
        p = self.page
        container = QFrame()
        container.setStyleSheet(_CARD_QSS)
        box = QVBoxLayout(container)
        box.setContentsMargins(5, 5, 5, 5)

        # 窗格编排交给 ChartHost（§10-12）：主图常驻 + 副图按需；跨窗格十字光标
        p.host = ChartHost(bottom_axis_mode=AXIS_NO_VALUES, crosshair=True)
        p.host.setBackground('w')
        # ★STEP 5：读数条**常驻** + 业务读数由本页提供（宿主不猜业务，§10-3）
        p.host.set_readout_provider(p._readout_for_pane)
        p.host.set_readout_visible(True)
        box.addWidget(p.host)

        # 自适应坐标轴总管（§7-B4）：本页只持有一个，每次重渲染 `attach` 一遍（幂等）
        p._axes = AdaptiveAxes(p.host)

        p.main_plot = p.host.main_pane.plot_item
        p._apply_pokorny_axis(p.main_plot)

        # 用户标注（管线 B）：宿主要建好才能挂；`on_changed` 让面板随时报"N 条标注"
        p._annotations = AnnotationLayer(
            p.host, p._annotation_store, period=PERIOD_DAILY,
            on_changed=p._refresh_annotation_status)
        p._refresh_annotation_status()

        # 键盘交互：Delete 删掉选中标注；Esc 回到浏览模式（免得手一抖在图上画出线）
        for key, slot in ((Qt.Key.Key_Delete, p.delete_selected_annotation),
                          (Qt.Key.Key_Escape, p._reset_tool)):
            QShortcut(QKeySequence(key), p).activated.connect(slot)
        return container
