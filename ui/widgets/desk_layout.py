# ui/widgets/desk_layout.py
"""行情工作台的**版式装配**：顶栏两行 + 左栏（图标轨 + 四页）（1.23 自 `ui/views/trading_desk.py` 拆出 · §7-B6 STEP 6）。

【职责】只做"把控件摆到该去的地方"，不承载任何业务规则：
  · 第 1 行（L1）：标题 + 查阅 + 云端同步；
  · 第 2 行（L2）：周期（含分钟二级档位）/ 复权 分段控件 + 工具行 chips + 标注胶囊
    （**常驻行数 ≤3**，§10-14：其余低频配置一律进左栏面板）；
  · 左栏：`IconRail`（52px 图标轨）+ `DeskPanel`（**4 页**：★自选 / ƒ公式 / ✎标注 / ⛁数据）。
    ★v6.24（§7-B8 R5）：原「◫ 主图叠加 / 附图」页已删 —— 该页的开关与顶栏 chips 完全重合，
    真源迁到 `ui/widgets/layer_model.py`。

【搬家不重建（§11.5 / 1.22 已验证）】控件对象与**变量名一个都不动**，只是 `addWidget`
到新的容器里 ⇒ 既有 234 项页面断言的访问口径零改动。

【常量归属】`RAIL_ITEMS` / `PANEL_DEFAULT_WIDTH` / `RAIL_TOTAL_WIDTH` 定义在这里
（它们描述"版式"），`ui/views/trading_desk.py` 里保留同名 re-export
（既有 `from ui.views.trading_desk import RAIL_ITEMS` 的用法零改动，§11.7）。
"""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QMenu, QPushButton, QVBoxLayout, QWidget)

from data.annotations import PERIOD_DAILY
from data.sync_service import ADJUST_CHOICES, ADJUST_LABELS
from ui.widgets.adaptive_axis import AdaptiveAxes
from ui.widgets.annotation_layer import AnnotationLayer
from ui.widgets.chart_host import AXIS_NO_VALUES, ChartHost
from ui.widgets.custom_widgets import (CHIP_MORE_QSS, COMBO_QSS_SMALL, AccordionCard,
                                       FlowHost, NoWheelComboBox, ScrollRegion,
                                       SegmentedControl)
from ui.widgets.layer_model import TARGET_ORDER
from ui.widgets.watch_row_delegate import WatchRowDelegate
from ui.widgets.watch_sort_list import DragHandleListWidget
from ui.widgets.annotation_tiles import StickyScrollArea, build_catalog_widget
from ui.widgets.desk_data import MINUTE_SEGMENTS, PERIOD_GROUPS
from ui.widgets.desk_panel import DeskPanel, IconRail

# ★STEP 4：左栏 = 图标轨（52px）+ 分页面板。顺序即显示顺序。
# ★v6.24（§7-B8 R5）：**5 页 → 4 页** —— 删掉「◫ 主图叠加 / 附图」页。
#   理由（用户原话）："顶栏横着的周期复权那一栏里**已经有 chips** 可以让用户选叠加主图/副图是什么，
#   侧边栏还专门留一栏，这两个功能完全重合"。
#   ⚠ 该页那 5 个开关**没有丢** —— 它们的职责迁给了 `ui/widgets/layer_model.py`
#   （内置指标 + 配方混排的单一真源），UI 入口仍在顶栏 chips 与「＋ 更多」里。
RAIL_ITEMS = (
    ("watch", "★", "自选股"),
    ("formula", "ƒ", "公式与配方"),
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

# ★v6.24（§7-B8 R11）：画线类型目录的**固定可视高度** ——
# 「面板高度不随类型数增长」是用户定的硬指标（"避免后续随着类型变多影响观感"）：
# 新增类型只是列表变长，版式一格不动。
ANNO_CATALOG_HEIGHT = 320

# ---- §7-B8 R1/R2：自选页（A 方案 v2）专用原子 ----
_QUICK_INPUT_QSS = ("QLineEdit { border:1px solid #E4E9F0; border-radius:7px; padding:6px 9px;"
                    " font-size:12.1px; color:#212121; background:#FFFFFF; }"
                    "QLineEdit:focus { border-color:#A9C7EA; }")
_BTN_PRIMARY_SMALL_QSS = ("QPushButton { font-size:12px; font-weight:bold; color:white;"
                          " background:#1976D2; padding:6px 12px; border:none; border-radius:7px; }"
                          "QPushButton:hover { background:#1565C0; }")
# 虚线框 = "这里将来会长出东西"（与"现在就可用"的实心控件一眼区分）
_PLANNED_QSS = ("QLabel { border:1px dashed #C9D6E5; border-radius:9px; background:#FAFCFF;"
                " color:#8A94A6; font-size:11.4px; padding:8px 10px; }")
_WATCH_LIST_QSS = ("QListWidget { border:1px solid #EAEFF6; border-radius:9px; background:#FFFFFF;"
                   " font-size:12.3px; color:#3A4250; outline:none; }"
                   "QListWidget::item { padding:7px 9px; border-bottom:1px solid #F4F7FB; }"
                   "QListWidget::item:hover { background:#F7FAFF; }"
                   "QListWidget::item:selected { background:#E8F2FE; color:#1565C0;"
                   " font-weight:bold; }")


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

        # 各页的**空容器** —— 下面几个 `build_*_page` 只负责往对应页里摆控件
        # （★v6.24 §7-B8 R5：`layer` 页已删，5 页 → 4 页）
        self.build_watch_page(p.desk_panel.body_layout("watch"))
        self.build_formula_page(p.desk_panel.body_layout("formula"))
        self.build_anno_page(p.desk_panel.body_layout("anno"))
        self.build_data_page(p.desk_panel.body_layout("data"))
        return holder

    # ---- 各页内容（★STEP 4：控件"搬家"，名字与连接一律不变）----
    def build_watch_page(self, lay: QVBoxLayout) -> None:
        """★ 自选股（§7-B8 R1/R2/R3 · A 方案 v2）。

        排布顺序 = **用户最常做的事从上往下**（不是按"控件类别"排）：
          ① **添加股票置顶**（用户 2026-09-17 明确要求：这是本页最主要的功能）；
          ② 分组胶囊（组名 + 组合当日涨跌，点一下切换清单）；
          ③ 成分清单（双击切标的 / 移出本组 / 组内调序）；
          ④ 虚线预留位（与将来同级的「组合配置」栏目互通）；
          ⑤ 分组管理（重命名 / 删组）—— 默认**收起**：它影响结构，不是日常动作。
        """
        p = self.page
        lay.setSpacing(8)
        # 内容区可滚（自选一多就不会把下面的东西顶出去）；本页没有钉底按钮 ⇒ 它是唯一子项
        p.scroll_watch = ScrollRegion()
        content = p.scroll_watch.content
        lay.addWidget(p.scroll_watch, 1)

        # ---- ① 添加股票（两种入口：敲代码/名称，或加入当前图上标的）----
        p.card_watch_add = AccordionCard("添加股票", "➕", open=True)
        p.card_watch_add.set_state("最主要功能")
        add_row = QHBoxLayout()
        add_row.setSpacing(5)
        p.txt_watch_quick = QLineEdit()
        p.txt_watch_quick.setPlaceholderText("输入代码或名称")
        p.txt_watch_quick.setStyleSheet(_QUICK_INPUT_QSS)
        p.txt_watch_quick.setToolTip("回车即加入自选（走花名册解析：600519 / 茅台 / sh600000 都行）")
        p.txt_watch_quick.returnPressed.connect(p.watch_quick_add)
        add_row.addWidget(p.txt_watch_quick, 1)

        p.cmb_watch_group = NoWheelComboBox()
        p.cmb_watch_group.setStyleSheet(COMBO_QSS_SMALL)
        p.cmb_watch_group.setMinimumWidth(86)
        p.cmb_watch_group.setToolTip("新增的股票归入哪个分组")
        add_row.addWidget(p.cmb_watch_group)

        p.btn_watch_add = QPushButton("★ 加入")
        p.btn_watch_add.setStyleSheet(_BTN_PRIMARY_SMALL_QSS)
        p.btn_watch_add.setToolTip("加入自选并归入左侧选中的分组：\n"
                                   "· 输入框有内容 ⇒ 按输入内容加入\n"
                                   "· 输入框为空 ⇒ 加入**当前图上正在看**的标的")
        p.btn_watch_add.clicked.connect(p.add_to_watchlist)
        add_row.addWidget(p.btn_watch_add)
        p.card_watch_add.body.addLayout(add_row)

        # 第二种添加入口：从**已有自选**里挑选，批量移组（不新建、不删除）
        p.btn_watch_pick = QPushButton("📋 从自选股里挑选…")
        p.btn_watch_pick.setStyleSheet(_BTN_QSS)
        p.btn_watch_pick.setToolTip("多选自选里的股票，批量移入某个分组\n"
                                    "（只改归类：不会新建、也不会删除任何自选股）")
        p.btn_watch_pick.clicked.connect(p.pick_watch_into_group)
        p.card_watch_add.body.addWidget(p.btn_watch_pick)
        content.addWidget(p.card_watch_add)

        # ---- ② 分组（胶囊由 desk_watch 动态重建：数量不定 ⇒ 用 FlowLayout 自动换行）----
        p.card_watch_groups = AccordionCard("分组", "🏷", open=True)
        # `FlowHost` 而不是裸 `QWidget`：它把 heightForWidth 透出去，
        # 否则"胶囊换到第二行"会被卡片裁掉（已在渲染探针里实测过这个坑）
        p.watch_chip_host = FlowHost(spacing=5)
        p.watch_chip_lay = p.watch_chip_host.flow
        p.card_watch_groups.body.addWidget(p.watch_chip_host)
        content.addWidget(p.card_watch_groups)

        # ---- ③ 成分清单 ----
        p.card_watch_list = AccordionCard("自选股", "📌", open=True)
        # `DragHandleListWidget`：平时**根本不响应拖动**（闸 1），排序模式下也只认行首 ⣿（闸 2）
        p.lst_watch = DragHandleListWidget()
        p.lst_watch.setStyleSheet(_WATCH_LIST_QSS)
        p.lst_watch.setMinimumHeight(150)
        # ★v6.24（§7-B8 R15 / 2b 余项）：三段式行绘制（名称 · 代码右对齐 · 涨跌列）。
        #   用 delegate 而不是 setItemWidget —— 后者会把**选中高亮盖掉**
        p.watch_row_delegate = WatchRowDelegate(p.lst_watch)
        p.lst_watch.setItemDelegate(p.watch_row_delegate)
        # 拖拽**结束**才落盘（不在 dragover 里一路写文件）
        p.lst_watch.model().rowsMoved.connect(p.on_watch_rows_moved)
        p.lst_watch.itemDoubleClicked.connect(p._on_watch_activated)
        p.lst_watch.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        p.lst_watch.customContextMenuRequested.connect(p.watch_list_menu)
        p.lst_watch.setToolTip("双击切换标的；右键可「移出本组 / 从自选删除」")
        p.card_watch_list.body.addWidget(p.lst_watch)

        watch_row = QHBoxLayout()
        watch_row.setSpacing(6)
        p.btn_watch_remove = QPushButton("↗ 移出本组")
        p.btn_watch_remove.setStyleSheet(_BTN_QSS)
        p.btn_watch_remove.setToolTip("按当前分组自动切换含义：\n"
                                      "· 正在看某个分组 ⇒ **只把它移出本组**（挪回默认分组）\n"
                                      "· 正在看「全部」⇒ 从自选里彻底删除")
        p.btn_watch_remove.clicked.connect(p.remove_from_watchlist)
        watch_row.addWidget(p.btn_watch_remove, 1)

        p.btn_watch_up = QPushButton("⬆")
        p.btn_watch_up.setStyleSheet(_BTN_QSS)
        p.btn_watch_up.setToolTip("上移 —— 只在**本组内**移动，不会把票挪进别的分组")
        p.btn_watch_up.clicked.connect(lambda: p.move_watchlist(-1))
        watch_row.addWidget(p.btn_watch_up)

        p.btn_watch_down = QPushButton("⬇")
        p.btn_watch_down.setStyleSheet(_BTN_QSS)
        p.btn_watch_down.setToolTip("下移 —— 只在**本组内**移动")
        p.btn_watch_down.clicked.connect(lambda: p.move_watchlist(1))
        watch_row.addWidget(p.btn_watch_down)

        p.btn_watch_sort = QPushButton("⇅ 排序")
        p.btn_watch_sort.setStyleSheet(_BTN_QSS)
        p.btn_watch_sort.setCheckable(True)
        p.btn_watch_sort.setToolTip(
            "进入**拖拽排序**模式（大分组 ⬆⬇ 点不过来时用它）。\n"
            "· 只认行首 ⣿ 手柄：点行本体不会误拖\n"
            "· 拖错了可以「↺ 撤销」回到原顺序")
        p.btn_watch_sort.toggled.connect(p.set_watch_sort_mode)
        watch_row.addWidget(p.btn_watch_sort)
        p.card_watch_list.body.addLayout(watch_row)

        # 排序模式的提示条（默认隐藏）：出现「↺ 撤销 / ✓ 完成」= 闸 3 的入口
        p.watch_sort_bar = QWidget()
        sort_bar = QHBoxLayout(p.watch_sort_bar)
        sort_bar.setContentsMargins(0, 0, 0, 0)
        sort_bar.setSpacing(6)
        sort_hint = QLabel("⣿ 拖行首手柄调顺序（只在组内）")
        sort_hint.setStyleSheet("font-size:11px; color:#8A94A6;")
        sort_bar.addWidget(sort_hint, 1)
        p.btn_watch_sort_undo = QPushButton("↺ 撤销")
        p.btn_watch_sort_undo.setStyleSheet(_BTN_QSS)
        p.btn_watch_sort_undo.setToolTip("回到进入排序模式之前的顺序")
        p.btn_watch_sort_undo.clicked.connect(p.undo_watch_sort)
        sort_bar.addWidget(p.btn_watch_sort_undo)
        p.btn_watch_sort_done = QPushButton("✓ 完成")
        p.btn_watch_sort_done.setStyleSheet(_BTN_PRIMARY_SMALL_QSS)
        p.btn_watch_sort_done.clicked.connect(p.finish_watch_sort)
        sort_bar.addWidget(p.btn_watch_sort_done)
        p.watch_sort_bar.setVisible(False)
        p.card_watch_list.body.addWidget(p.watch_sort_bar)
        # 清单卡**给拉伸**：自选越长越好，让它把内容区填满
        content.addWidget(p.card_watch_list, 1)

        # ---- ④ 预留位：与「组合配置」互通（§7-B8 R3）----
        p.lbl_watch_planned = QLabel("预留位 · 与「组合配置」互通\n"
                                     "今后在这里给成分股设权重，再对整组做回测。")
        p.lbl_watch_planned.setStyleSheet(_PLANNED_QSS)
        p.lbl_watch_planned.setWordWrap(True)
        content.addWidget(p.lbl_watch_planned)

        # ---- ⑤ 分组管理（默认**收起**：影响结构、不是日常动作）----
        p.card_watch_manage = AccordionCard("分组管理", "🗑", open=False)
        p.card_watch_manage.set_state("影响分组结构", "warn")
        manage_row = QHBoxLayout()
        manage_row.setSpacing(6)
        p.btn_watch_rename = QPushButton("✏ 重命名")
        p.btn_watch_rename.setStyleSheet(_BTN_QSS)
        p.btn_watch_rename.setToolTip("重命名当前分组（组内成分跟着一起改）")
        p.btn_watch_rename.clicked.connect(p.rename_watch_group)
        manage_row.addWidget(p.btn_watch_rename)

        p.btn_watch_delete_group = QPushButton("🗑️ 删除分组")
        p.btn_watch_delete_group.setStyleSheet(_BTN_DANGER_QSS)
        p.btn_watch_delete_group.setToolTip(
            "删除当前分组：成分**解绑回默认分组**，股票一只都不会删（会二次确认）")
        p.btn_watch_delete_group.clicked.connect(p.delete_watch_group)
        manage_row.addWidget(p.btn_watch_delete_group)
        p.card_watch_manage.body.addLayout(manage_row)
        content.addWidget(p.card_watch_manage)

    def build_formula_page(self, lay: QVBoxLayout) -> None:
        """ƒ 配方库（§7-B8 R5/R6/R13）—— **这里就是图层的真源页**。

        自上而下 = 用户在配方库里的动作顺序：
          ① 两个分区（主图配方 / 副图配方），每区 = 一排**可点即开关**的配方 chip；
          ② 图例一行（主图 = 叠在 K 线上 / 副图 = 主图下方单独成图）；
          ③ **管理模式**开关（改名/删除只在开启后出现 —— §10-10：危险动作不与高频操作同排）；
          ④ 主操作「＋ 新建 / 编辑公式…」**钉在底部**（A 方案）+ 存盘 + 送出去；
          ⑤ 回执 `lbl_formula_status`（迁移护栏要求它在本页）。
        """
        p = self.page
        lay.setSpacing(8)
        # 内容区（卡片放这里，放不下就滚）+ 底部主操作留在外层**钉住**（永远够得着）
        p.scroll_formula = ScrollRegion()
        content = p.scroll_formula.content
        lay.addWidget(p.scroll_formula, 1)

        p.card_formula_lib = AccordionCard("配方库", "ƒ", open=True)
        p.formula_chip_hosts = {}
        p.formula_chip_lays = {}
        p.formula_section_labels = {}
        for target in TARGET_ORDER:
            block = QVBoxLayout()
            block.setSpacing(5)
            label = section("")
            p.formula_section_labels[target] = label
            block.addWidget(label)
            # FlowHost：胶囊数量不定，必须能换行（且宿主自己会撑高度，见它的 docstring）
            host = FlowHost(spacing=5)
            p.formula_chip_hosts[target] = host
            p.formula_chip_lays[target] = host.flow
            block.addWidget(host)
            p.card_formula_lib.body.addLayout(block)

        p.lbl_formula_legend = QLabel("主图 = 叠在 K 线上　·　副图 = 主图下方单独成图")
        p.lbl_formula_legend.setStyleSheet("font-size:11px; color:#8A94A6;")
        p.lbl_formula_legend.setWordWrap(True)
        p.card_formula_lib.body.addWidget(p.lbl_formula_legend)
        # ⚠ **不给拉伸**：内容少的卡片一旦被拉满，就变成"标题悬在半空的巨大空框"；
        #   内容真多时由 ScrollRegion 负责让它滚（两头都不会难看）
        content.addWidget(p.card_formula_lib)
        content.addStretch()        # 卡片贴顶堆叠，多余空间留在下面（而不是撑开卡片）

        p.btn_formula_manage = QPushButton("✏ 管理模式")
        p.btn_formula_manage.setCheckable(True)
        p.btn_formula_manage.setStyleSheet(_BTN_QSS)
        p.btn_formula_manage.setToolTip(
            "开启后才出现改名 / 删除。\n"
            "⚠ 内置项（均线/布林带/成交量/MACD）**永远不会**出现改名或删除 ——\n"
            "内置就是给不熟的用户用的，给了修改权很可能改不回来。")
        p.btn_formula_manage.toggled.connect(p.set_formula_manage)
        lay.addWidget(p.btn_formula_manage)

        p.btn_edit_formula = QPushButton("＋ 新建 / 编辑公式…")
        p.btn_edit_formula.setStyleSheet(_BTN_PRIMARY_QSS)
        p.btn_edit_formula.setToolTip("粘贴通达信式函数，叠加到当前标的（每段可选主图/副图）")
        p.btn_edit_formula.clicked.connect(p.edit_formula)
        lay.addWidget(p.btn_edit_formula)

        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        p.btn_save_formula_as = QPushButton("💾 存为配方…")
        p.btn_save_formula_as.setStyleSheet(_BTN_QSS)
        p.btn_save_formula_as.setToolTip("把当前公式存进配方库；同名即覆盖。\n"
                                         "⚠ 一条公式只能去一个地方（主图或副图）—— 段目标不一致会被挡住")
        p.btn_save_formula_as.clicked.connect(p.save_formula_as)
        action_row.addWidget(p.btn_save_formula_as)
        p.btn_send_backtest = QPushButton("📤 送去做回测")
        p.btn_send_backtest.setStyleSheet(_BTN_QSS)
        p.btn_send_backtest.setToolTip("把函数与参数送进「📐 市场回测」（回测不区分主图/副图）")
        p.btn_send_backtest.clicked.connect(p.send_formula_to_backtest)
        action_row.addWidget(p.btn_send_backtest)
        lay.addLayout(action_row)

        p.lbl_formula_status = QLabel("未设置")
        p.lbl_formula_status.setWordWrap(True)
        p.lbl_formula_status.setStyleSheet("font-size: 11px; color: #8A94A6;")
        lay.addWidget(p.lbl_formula_status)

    def build_anno_page(self, lay: QVBoxLayout) -> None:
        """✎ 标注工具 = **画线类型目录**（§7-B8 R10/R11）。

        三条拍死的约束（不许动摇）：
          · **没有搜索栏**（用户原话："用户根本不会去用这个功能"）；
          · **32 种全部直出**，不折叠、不收纳 —— 设计空间只剩"怎么摆得不乱"；
          · **面板高度不随类型数增长**：滚动区固定高度（"避免后续类型变多影响观感"）。
        让"多"不显乱靠四件事：分类分组 / **每类一个色相** / 统一行式（图标·名称·编号）
        / 固定高度内滚 + **吸顶分类标题**。未实现的类型**照常出现并标注「待实现」**。
        """
        p = self.page
        lay.setSpacing(8)
        # 同自选页：内容区可滚，底部三颗操作按钮钉在面板底部
        p.scroll_anno = ScrollRegion()
        content = p.scroll_anno.content
        lay.addWidget(p.scroll_anno, 1)

        p.card_anno_tools = AccordionCard("画线工具", "✎", open=True)
        p.btn_anno_browse = QPushButton("✋ 浏览（不新建）")
        p.btn_anno_browse.setStyleSheet(_BTN_QSS)
        p.btn_anno_browse.setToolTip("浏览模式：点图只是选中/查看，不会新建标注（按 Esc 同效）")
        p.btn_anno_browse.clicked.connect(lambda: p.select_tool(""))
        p.card_anno_tools.body.addWidget(p.btn_anno_browse)

        p.anno_scroll = StickyScrollArea()
        # ⚠ 由"固定高"改成"最小高"：**面板高度仍然不随类型数增长**（外层 ScrollRegion 兜着），
        #   但目录可以**长高填满内容区** —— 否则卡片被拉伸时，目录下面又是一大片空框
        p.anno_scroll.setMinimumHeight(ANNO_CATALOG_HEIGHT)
        p.anno_tiles = {}
        p.anno_headers = {}
        p.anno_scroll.setWidget(build_catalog_widget(p.anno_tiles, p.anno_headers,
                                                    p.select_tool))
        p.card_anno_tools.body.addWidget(p.anno_scroll)
        # ★v6.25：**诚实标注"能画几种 / 共几种"**（灰色的那几种是登记了还没做的，
        #   不写清楚用户会以为是自己点不动 —— §10-4 不虚构的另一面：也不许含糊）
        p.card_anno_tools.set_state(
            f"{sum(1 for t in p.anno_tiles.values() if t.implemented)} 种可画"
            f" · 共 {len(p.anno_tiles)} 种")
        # 目录卡**给拉伸**：工具是"越长越好"的列表，让它把内容区填满
        content.addWidget(p.card_anno_tools, 1)

        # ★v6.26（§7-B9 拍板①）：**「➕ 添加标注」按钮已删除** —— 用户原话"添加标注直接删除"。
        #   现在的流程 = 选类型 ⇒ 在图上依次点锚点 ⇒ 点够就成（"先生成默认线再拖"被实测否掉）。
        #   ⚠ 连带：`TradingDeskView.add_annotation` 薄壳与「迁移护栏」里的同名断言已同批改掉。
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
            on_changed=p._refresh_annotation_status,
            # ★v6.26（§7-B9 STEP 1/3）：需要文字的类型（文字/评论气泡）由**页面**弹输入框
            #   （本层不持 QWidget）；画完一条 ⇒ 页面回到浏览模式（防手残，用户拍板）
            ask_text=p._annos.ask_annotation_text,
            on_finished=lambda: p.select_tool(""))
        p._refresh_annotation_status()

        # 键盘交互：Delete 删掉选中标注；Esc 回到浏览模式（免得手一抖在图上画出线）
        for key, slot in ((Qt.Key.Key_Delete, p.delete_selected_annotation),
                          (Qt.Key.Key_Escape, p._reset_tool)):
            QShortcut(QKeySequence(key), p).activated.connect(slot)

        # ★v6.24（§7-B8 R10）：**1–9 兼作数字快捷键**（按数字直接切画线类型）。
        # ⚠ 单键快捷键**不会抢输入框里的数字**：Qt 先给焦点控件发 `ShortcutOverride`，
        #   而 `QLineEdit` 对普通文本键**接受**它 ⇒ 快捷键不触发。所以"在搜索框里打 1"
        #   仍然是内容而不是切工具 —— 这点不写下来很容易被后人当成 bug 再"修"一遍。
        for number in range(1, 10):
            QShortcut(QKeySequence(str(number)), p).activated.connect(
                lambda n=number: p.select_tool_number(n))
        return container
