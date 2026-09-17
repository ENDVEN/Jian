# ui/views/trading_desk.py
"""📈 行情工作台（Trading Desk）—— §7-B3 **P8 行情页整体重做** + §7-B6 **1.23 版式收口**。

【本文件现在是什么（1.23 · §7-B6 STEP 6 拆分后）】**状态 + 接线**：
  · 页面是全部**状态的唯一所有者**：当前标的/周期/复权、可见 K 线、图层与公式段、
    工具行 chips 的"最近使用"、标注层与它的存储、界面偏好 `desk_ui`……
  · **行为**分居 `ui/widgets/desk_*.py`，本文件只保留**同名薄壳**（一个名字都没改）——
    这是本轮拆分的成功判据：同一套断言（`smoke_chart` + `smoke_pages_overlay`）零改动。
  · 分工（§10-12：新能力一律落 `ui/widgets/*`）：
      · 版式装配（顶栏两行 / 左栏五页 / 图表区） → `ui/widgets/desk_layout.py`
      · 图标轨 + 分页面板 + 折起               → `ui/widgets/desk_panel.py`
      · 取数 / 周期 / 复权 / 分钟档位           → `ui/widgets/desk_data.py`
      · 渲染装配（显示用行情 + 统一图层 + 坐标轴）→ `ui/widgets/desk_layers.py`
      · 公式（编辑 / 编译 / 资产化 / 互送）      → `ui/widgets/desk_formula.py`
      · 标注（画线工具 + 回执）                  → `ui/widgets/desk_annotations.py`
      · 工具行 chips（"最近使用优先"）           → `ui/widgets/desk_chips.py`
      · 自选股                                   → `ui/widgets/desk_watch.py`
      · 读数条文案                               → `ui/widgets/desk_readout.py`

【为什么新建文件而不是改 `market.py`】
  §10-12 / §9-L 的纪律：`market.py` 已 661 行越线，**禁止再往里堆**。
  P0–P7 已经把能力都做成了独立组件，所以 P8 是**"换壳不换芯"**：
  本页只做"装配 + 交互"，图表能力全部来自下面这些既有组件 ——
    · 窗格编排 / x 联动 / 日期轴 / 十字光标 → `ui/widgets/chart_host.py`
    · 公式叠层渲染（唯一渲染器）        → `ui/widgets/draw_overlay.py`
    · 内置指标 → 绘图 IR（统一图层协议）→ `ui/widgets/chart_layers.py`
    · 用户标注（管线 B：持久化 + 逐个删除）→ `ui/widgets/annotation_layer.py`
    · 量能 / MACD 副图内容              → `ui/widgets/indicator_panes.py`
    · 公式资产化 + 配方库               → `data/formula_store.py` + `ui/widgets/formula_library.py`
    · 数据同步（UI 不发网络）           → `ui/workers.py` → `data/sync_service.py`
  本文件**不新增任何绘图逻辑、不碰网络、不写 SQL**（§10-3）。

【P8 相对旧行情页的新增能力】
  ① **自选股**（`data/watchlist_store.py`）：列表/增删/上下移/双击切换；
  ② **周期切换**：日 / 周 / 月 / **分钟档位** —— 日周月由 `core.utils.resample_ohlcv` 就地聚合，
     列名与日线一致 ⇒ K 线/指标/公式/标注**全部零改动**；
     ⚠ 标注按 `(标的, **周期**)` 分开存：日线画的线不会跑到周线上（§7-B3 P6 的既定设计）；
  ③ **画线工具栏 5 类**：趋势线 / 水平线 / 垂直线 / 斐波那契 / 文字（家在左栏「✎ 标注」页）；
  ④ **1.23 版式收口（§7-B6 · 样板 A 骨架）**：顶栏两行（L1 查询 / L2 周期·复权·chips）+
     左栏图标轨（可折起，把宽度还给图表）+ 常驻读数条（日期/O/H/L/C/量/MA5/MA20）。

【坐标轴自适应（§7-B4）】
  横轴刻度与纵轴量程**不在这里手算** —— 全部交给 `ui/widgets/adaptive_axis.py`
  （见 `DeskLayers._adaptive_providers`）。

【兼容性 re-export（§11.7）】
  下面从 `ui/widgets/desk_*.py` 再导出的常量，是"拆分前从这里 import 的既有用法"的兼容层，
  测试与外部模块的 import 语句零改动。
"""
from __future__ import annotations

import logging

import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QSplitter, QVBoxLayout,
                             QWidget)

from core.preferences import preferences
from core.utils import MINUTE_PERIODS, normalize_period
from data.annotations import AnnotationStore
from data.formula_store import get_formula_store
from data.market_db import DataLakeManager
from data.sync_service import ADJUST_QFQ
from data.watchlist_store import WatchlistStore
from ui.widgets.chart_style import apply_pokorny_style
from ui.widgets.chip_mru import normalize_recent
from ui.widgets.desk_annotations import DeskAnnotations
from ui.widgets.desk_chips import DeskChips
from ui.widgets.desk_data import (MINUTE_SEGMENTS, PERIOD_CHOICES,  # noqa: F401
                                  PERIOD_GROUP_MIN, PERIOD_GROUPS, DeskData)
from ui.widgets.desk_formula import DeskFormula
from ui.widgets.desk_layers import (DEFAULT_VISIBLE_BARS,  # noqa: F401
                                    SUB_PLOT_HEIGHT, DeskLayers)
from ui.widgets.desk_layout import RAIL_ITEMS, DeskLayout
from ui.widgets.layer_model import LayerModel
from ui.widgets.desk_panel import (PANEL_DEFAULT_WIDTH,  # noqa: F401
                                   RAIL_TOTAL_WIDTH, DeskPanelController)
from ui.widgets.desk_readout import DeskReadout
from ui.widgets.desk_watch import DeskWatch

logger = logging.getLogger(__name__)

# 偏好键：行情工作台界面状态（与 `backtest_ui` 同源做法：记住上次 + 最近使用的 chips）
DESK_UI_KEY = "desk_ui"


class TradingDeskView(QWidget):
    """行情工作台：自选股 + 周期 + 指标/公式 + 画线工具 + 图表（复用 P0–P7 组件）。

    ⚠ 本类**只持状态 + 转发**：行为都在 `ui/widgets/desk_*.py`；
      方法名 / 控件名 / 私有状态名三者都**与拆分前逐字相同**（§11.7 迁移红线）。
    """

    def __init__(self, main_win):
        super().__init__()
        self.main_win = main_win
        self.data_lake = DataLakeManager()
        self.watchlist = WatchlistStore()
        # ★v6.24（§7-B8 R1）：**"我在看哪一组"是页面状态、不进存储** —— 存储里只回答
        #   "这只票属于哪一组"（§11.5-11 单一状态源）。None = 全部（聚合视图）。
        self.watch_group = None
        # ★v6.24（§7-B8 R3）：分组当日涨跌的快照缓存（带 TTL）。**懒建** ——
        #   它在第一次刷新时才需要 loader，而 loader 要用到 data_lake（此刻已就绪）。
        self.watch_change = None
        # ★v6.24（§7-B8 R15）：拖拽排序模式 + 闸 3 的顺序底片（进模式时拍一张）
        self.watch_sort_mode = False
        self._watch_sort_snapshot: list = []

        self.current_symbol = None
        self.current_name = ""
        self.current_df = pd.DataFrame()      # **原始行情**（周期切换的输入）
        # ★STEP 3b：`current_period` 始终是**真实生效的周期键**（D/W/M/1m…60m），
        # 而 `_period_group` 只描述分段控件停在哪一格（"分钟"是二级入口，不是周期键）。
        self.current_period = "D"
        self._period_group = "D"
        # 复权口径（v6.13 · P8 收尾）：qfq = 前复权（默认，读 kline_daily）/
        # "" = 不复权（读 kline_daily_raw）。**两份数据各存一个分区**，见 sync_service.zone_for_adjust
        self.current_adjust = ADJUST_QFQ
        # 界面偏好（记住上次）：与 `backtest_ui` 同源；坏值一律回落默认。
        self._desk_ui = self._load_desk_ui()
        self.current_minute = normalize_period(self._desk_ui.get("minute_period") or "5m")
        if self.current_minute not in MINUTE_PERIODS:
            self.current_minute = "5m"
        # ★STEP 5：读数条 provider 只认"本次真正渲染的那一份 df"（见 render_charts 末尾）
        self._rendered_df = pd.DataFrame()
        # ★STEP 3c：工具行 chips 的"最近使用"历史（记住上次）+ 公式副图逐窗格显示开关。
        # ⚠ 真源是 `layer_model`（**v6.24 起不再是 QCheckBox**）；chips 只是它的投影 ——
        #   见 `desk_chips.toggle_chip` 与 §11.5-11「单一状态源」。
        self._chip_recent = {
            "main": normalize_recent(self._desk_ui.get("main_chips")),
            "sub": normalize_recent(self._desk_ui.get("sub_chips")),
        }
        self._sub_visible = {"sub1": True, "sub2": True, "sub3": True}
        # "上次见到的已启用集合"：识别**刚被打开**的项（无论从复选框还是 chip 打开）
        self._chip_seen = {"main": set(), "sub": set()}

        # 统一图层（§7-B3 D4）：内置指标与用户公式都产出 DrawData → 同一个 OverlayPainter
        self._layer_builtin: list = []
        self._layer_formula: dict = {}         # 目标窗格 -> [DrawData]
        self._layer_bars = 0
        self._layer_items: list = []
        self.formula_plots: dict = {}          # 目标窗格 -> PlotItem（副图按需创建）
        self._formula_segments: list = []      # [(函数文本, 目标窗格)]
        self._formula_params_text = ""
        self._formula_programs: list = []
        self._formula_error = ""
        # ★v6.24（§7-B8 R13）：**已存配方**按 key 编译的缓存（草稿仍用 `_formula_programs`）
        self._recipe_programs: dict = {}
        # ★v6.24（§7-B8 R6）：配方库的「管理模式」（开启后才显示改名/删除；内置项永不显示）
        self._formula_manage = False
        # ★v6.24（§7-B8 R10）：当前画线工具 —— 取代旧 `seg_tool` 的"停在哪一格"
        #   （空串 = 浏览模式；tile 只是它的投影，§11.5-11）
        self.current_tool = ""
        self._formula_store = get_formula_store()      # 与回测页共用同一个实例
        # ★v6.24（§7-B8 R13）：图层/配方的**单一真源** —— 取代 `cb_ma/cb_boll/cb_formula/
        #   cb_vol/cb_macd` 这 5 个 QCheckBox（§11.5-11：同一件事不许两份状态）。
        #   内置 4 项 + 草稿槽 + 用户配方混排；开关与内置参数都记住上次。
        self.layer_model = LayerModel(
            formulas=self._formula_store.all(),
            enabled=self._desk_ui.get("layer_enabled"),
            params=self._desk_ui.get("layer_params"))

        self._annotation_store = AnnotationStore()
        self._annotations = None               # 需等 ChartHost 建好（见 _setup_ui）

        # 行为模块（1.23 · §7-B6 STEP 6）：页面持状态，行为分居各模块
        self._layout = DeskLayout(self)
        self._panel = DeskPanelController(self)
        self._data = DeskData(self)
        self._layers = DeskLayers(self)
        self._formula = DeskFormula(self)
        self._annos = DeskAnnotations(self)
        self._chips = DeskChips(self)
        self._watch = DeskWatch(self)
        self._readout = DeskReadout(self)

        self._setup_ui()
        # P7：开机自动恢复"上次用过的配方" —— 直接治好"公式重启就丢"
        self._restore_last_formula()
        # ★v6.24（§7-B8 R6）：配方库页开机就画一次 —— 配方库为空时也得把两个分区摆出来，
        #   否则用户看到的是"一片空白"，会以为功能坏了（幂等，可重复调用）
        self.refresh_recipe_page()
        self._refresh_watchlist()

    # ==========================================
    # 界面装配
    # ==========================================
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        layout.addLayout(self._build_top_bar())
        layout.addLayout(self._build_tool_row())      # ★STEP 3b：L2 分段控件 + 摘要

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_control_panel())
        splitter.addWidget(self._build_chart_area())
        # 左栏 = 图标轨 52 + 面板 ~320（★STEP 4）；存引用是因为"折起"要重排分栏宽度
        self.main_splitter = splitter
        splitter.setSizes([PANEL_DEFAULT_WIDTH, 1000])
        # 【v6.22 离屏实测修正】QSplitter 分配**富余宽度**时按子控件 stretch 走：
        #   不显式给 stretch 的话，窗口变宽时富余宽度会被**左栏**吃掉
        #   （1911px 窗口实测 left=969 / 图表只剩 698 —— 正是 §9-U 说的"图表被让渡宽度"）。
        #   ⇒ 0 号（左栏）stretch=0（只按内容宽度）、1 号（图表）stretch=1（吃满富余）。
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setCollapsible(1, False)      # 别让手一抖把图表拖成 0 宽（左栏允许折起）
        # 【§11.5-13】主区必须显式 stretch=1：否则顶部栏里的 QLabel 会吞掉整段富余高度
        layout.addWidget(splitter, 1)

        # ★STEP 3c：chips 必须在**叠加层开关建好之后**才建（否则反映不出真实状态）；
        # `_ui_ready` 也在这时打开 —— 构造期各控件是先后创建的，回流要等它们齐了再开始。
        self._ui_ready = True
        self._rebuild_chips("main")
        self._rebuild_chips("sub")
        self._chip_seen = {kind: set(self._chip_enabled_keys(kind)) for kind in ("main", "sub")}

        # ★STEP 4：恢复"上次停留的工具页 + 是否折起"（记住上次；与 chips 同一份偏好）
        self.show_rail_page(self._desk_ui.get("panel_page") or "watch")
        self.set_panel_collapsed(bool(self._desk_ui.get("rail_collapsed", False)))

    def _build_top_bar(self) -> QHBoxLayout:
        return self._layout.build_top_bar()

    def _build_tool_row(self) -> QHBoxLayout:
        return self._layout.build_tool_row()

    def _build_control_panel(self) -> QFrame:
        return self._layout.build_control_panel()

    def _build_chart_area(self) -> QFrame:
        return self._layout.build_chart_area()

    def _build_watch_page(self, lay: QVBoxLayout) -> None:
        self._layout.build_watch_page(lay)

    def _build_formula_page(self, lay: QVBoxLayout) -> None:
        self._layout.build_formula_page(lay)

    def _build_layer_page(self, lay: QVBoxLayout) -> None:
        self._layout.build_layer_page(lay)

    def _build_anno_page(self, lay: QVBoxLayout) -> None:
        self._layout.build_anno_page(lay)

    def _build_data_page(self, lay: QVBoxLayout) -> None:
        self._layout.build_data_page(lay)

    @staticmethod
    def _row_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-size:11.5px; color:#B4BECB; font-weight:700;")
        return label

    @staticmethod
    def _row_sep() -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color:#E4E9F0;")
        sep.setFixedHeight(18)
        return sep

    # ---- 界面偏好（记住上次）----
    @staticmethod
    def _load_desk_ui() -> dict:
        """行情工作台界面偏好（与 `backtest_ui` 同源做法）；坏值一律回落默认。"""
        raw = preferences.get(DESK_UI_KEY)
        data = dict(raw) if isinstance(raw, dict) else {}
        return {
            "minute_period": data.get("minute_period") or "5m",
            "main_chips": data.get("main_chips") or [],
            "sub_chips": data.get("sub_chips") or [],
            "rail_collapsed": bool(data.get("rail_collapsed", False)),
            "panel_page": data.get("panel_page") or "watch",
            # ★v6.24（§7-B8 R13）：图层开关与内置指标参数 —— 取代 5 个 QCheckBox 的记忆
            #   （坏值由 `LayerModel` 清洗：未知 key / 越界参数一律回落默认）
            "layer_enabled": data.get("layer_enabled") or [],
            "layer_params": data.get("layer_params") or {},
        }

    def _save_desk_ui(self, **changes) -> None:
        self._desk_ui.update(changes)
        preferences.set(DESK_UI_KEY, dict(self._desk_ui))

    def _persist_layer_state(self) -> None:
        """把图层真源（开关 + 内置指标参数）记进偏好 —— **唯一落点**（§11.5-11）。

        别处（chips / ⚙ 参数窗口 / 配方库）都只改 `layer_model`，由这里负责记忆；
        否则"改一处漏一处"必然发生（§7-B6-D 第 6 条同族）。
        """
        self._save_desk_ui(layer_enabled=self.layer_model.enabled_list(),
                           layer_params=self.layer_model.params_snapshot())

    # ==========================================
    # 图表区杂项（两处渲染共用的轴样式，§9-O7）
    # ==========================================
    @staticmethod
    def _apply_pokorny_axis(plot_item):
        """委托 `chart_style`（全 app 图表轴样式唯一来源，§9-O7）。

        注意：本页图表来自 `GraphicsLayoutWidget.addPlot()`，拿到的是 PlotItem 而非
        PlotWidget，`chart_style` 内部已兼容两种类型。
        """
        return apply_pokorny_style(plot_item, background=None, margins=0)

    # ==========================================
    # 图标轨 / 分页 / 折起（★STEP 4 → desk_panel.DeskPanelController）
    # ==========================================
    def on_rail_clicked(self, page: str) -> None:
        return self._panel.on_rail_clicked(page)

    def show_rail_page(self, page: str) -> None:
        return self._panel.show_rail_page(page)

    def set_panel_collapsed(self, collapsed: bool) -> None:
        return self._panel.set_panel_collapsed(collapsed)

    def is_panel_collapsed(self) -> bool:
        return self._panel.is_panel_collapsed()

    def toggle_panel_collapsed(self) -> None:
        return self._panel.toggle_panel_collapsed()

    # ==========================================
    # 自选股（→ desk_watch.DeskWatch）
    # ==========================================
    def _refresh_watchlist(self):
        return self._watch._refresh_watchlist()

    def _selected_watch_symbol(self) -> str:
        return self._watch._selected_watch_symbol()

    def add_to_watchlist(self):
        return self._watch.add_to_watchlist()

    def remove_from_watchlist(self):
        return self._watch.remove_from_watchlist()

    def move_watchlist(self, delta: int):
        return self._watch.move_watchlist(delta)

    # ---- §7-B8 R1/R2：分组筛选 / 快添加 / 右键菜单（薄壳，实现全在 desk_watch）----
    def watch_quick_add(self):
        return self._watch.watch_quick_add()

    def watch_group_selected(self, key):
        return self._watch.watch_group_selected(key)

    def watch_list_menu(self, pos):
        return self._watch.watch_list_menu(pos)

    def create_watch_group(self):
        return self._watch.create_watch_group()

    def rename_watch_group(self):
        return self._watch.rename_watch_group()

    def delete_watch_group(self):
        return self._watch.delete_watch_group()

    def invalidate_change_cache(self):
        return self._watch.invalidate_change_cache()

    # ---- §7-B8 R15：拖拽排序（三道闸）----
    def set_watch_sort_mode(self, on):
        return self._watch.set_watch_sort_mode(on)

    def undo_watch_sort(self):
        return self._watch.undo_watch_sort()

    def finish_watch_sort(self):
        return self._watch.finish_watch_sort()

    def on_watch_rows_moved(self, *args):
        return self._watch.on_watch_rows_moved(*args)

    def apply_watch_sort(self):
        return self._watch.apply_watch_sort()

    def pick_watch_into_group(self):
        return self._watch.pick_watch_into_group()

    def move_selected_to_group(self, symbols, group):
        return self._watch.move_selected_to_group(symbols, group)

    def _on_watch_activated(self, item):
        return self._watch._on_watch_activated(item)

    # ==========================================
    # 查询 / 取数 / 周期 / 复权（→ desk_data.DeskData）
    # ==========================================
    def search_and_load(self):
        return self._data.search_and_load()

    def _data_zone_and_key(self):
        return self._data._data_zone_and_key()

    def _loaded_is_minute(self) -> bool:
        return self._data._loaded_is_minute()

    def _reload_for_current_view(self) -> bool:
        return self._data._reload_for_current_view()

    def load_symbol(self, symbol: str, name: str = "") -> bool:
        return self._data.load_symbol(symbol, name)

    def sync_cloud(self):
        return self._data.sync_cloud()

    def _on_sync_finished(self, result: dict):
        return self._data._on_sync_finished(result)

    def select_period_group(self, group: str) -> None:
        return self._data.select_period_group(group)

    def _on_period_group_clicked(self, group: str) -> None:
        return self._data._on_period_group_clicked(group)

    def _apply_period_group(self, group: str) -> None:
        return self._data._apply_period_group(group)

    def select_minute(self, period: str) -> None:
        return self._data.select_minute(period)

    def _on_minute_clicked(self, period: str) -> None:
        return self._data._on_minute_clicked(period)

    def _apply_minute(self, period: str) -> None:
        return self._data._apply_minute(period)

    def _sync_period_widgets(self) -> None:
        return self._data._sync_period_widgets()

    def select_adjust(self, adjust: str) -> None:
        return self._data.select_adjust(adjust)

    def _on_adjust_clicked(self, adjust: str) -> None:
        return self._data._on_adjust_clicked(adjust)

    def _apply_adjust(self, adjust: str) -> None:
        return self._data._apply_adjust(adjust)

    def _adjust_warning(self) -> str:
        return self._data._adjust_warning()

    def _adjust_warning_short(self) -> str:
        return self._data._adjust_warning_short()

    def _refresh_adjust_hint(self, loaded_from_lake: bool = False, pending: bool = False):
        return self._data._refresh_adjust_hint(loaded_from_lake=loaded_from_lake,
                                               pending=pending)

    # ==========================================
    # 工具行 chips（★STEP 3c → desk_chips.DeskChips）
    # ==========================================
    def _chip_control(self, key: str):
        return self._chips._chip_control(key)

    def _chip_candidates(self, kind: str) -> tuple:
        return self._chips._chip_candidates(kind)

    def _chip_enabled_keys(self, kind: str) -> list:
        return self._chips._chip_enabled_keys(kind)

    def chips_for(self, kind: str) -> list:
        return self._chips.chips_for(kind)

    def chips_hidden(self, kind: str) -> list:
        return self._chips.chips_hidden(kind)

    def toggle_chip(self, key: str) -> None:
        return self._chips.toggle_chip(key)

    def _remember_chip(self, key: str) -> None:
        return self._chips._remember_chip(key)

    def _on_layer_switch_changed(self, *_):
        return self._chips._on_layer_switch_changed(*_)

    def _sync_chip_history(self) -> None:
        return self._chips._sync_chip_history()

    def _refresh_chips(self) -> None:
        return self._chips._refresh_chips()

    def _rebuild_chips(self, kind: str) -> None:
        return self._chips._rebuild_chips(kind)

    def _rebuild_more_menu(self, kind: str, enabled: list) -> None:
        return self._chips._rebuild_more_menu(kind, enabled)

    # ==========================================
    # 显示用行情 + 渲染 + 坐标轴（→ desk_layers.DeskLayers）
    # ==========================================
    def prepared_df(self) -> pd.DataFrame:
        return self._layers.prepared_df()

    def render_charts(self):
        return self._layers.render_charts()

    def _formula_layers(self, df) -> dict:
        return self._layers._formula_layers(df)

    def _paint_layers(self):
        return self._layers._paint_layers()

    def _title_text(self, df) -> str:
        return self._layers._title_text(df)

    def _adaptive_providers(self, df) -> dict:
        return self._layers._adaptive_providers(df)

    # ==========================================
    # 读数条（★STEP 5 → desk_readout.DeskReadout）
    # ==========================================
    def _readout_for_pane(self, pane_name: str, x: float, y: float) -> str:
        return self._readout._readout_for_pane(pane_name, x, y)

    def _readout_stamp_fmt(self) -> str:
        return self._readout._readout_stamp_fmt()

    def _refresh_readout_default(self) -> None:
        return self._readout._refresh_readout_default()

    # ==========================================
    # 用户公式（→ desk_formula.DeskFormula）
    # ==========================================
    def edit_formula(self):
        return self._formula.edit_formula()

    def _compile_formula(self):
        return self._formula._compile_formula()

    def _report_formula_status(self, df):
        return self._formula._report_formula_status(df)

    def _set_formula_status(self, ok: bool, message: str, *, warn: bool = False,
                            detail: str = ""):
        return self._formula._set_formula_status(ok, message, warn=warn, detail=detail)

    def save_formula_as(self):
        return self._formula.save_formula_as()

    def open_formula_library(self):
        return self._formula.open_formula_library()

    # ---- §7-B8 R6/R13：配方库页（分区 chip 即开关；管理模式才给改名/删除）----
    def refresh_recipe_page(self):
        return self._formula.refresh_recipe_page()

    def toggle_recipe(self, key):
        return self._formula.toggle_recipe(key)

    def set_formula_manage(self, on):
        return self._formula.set_formula_manage(on)

    def rename_recipe(self, key):
        return self._formula.rename_recipe(key)

    def delete_recipe(self, key):
        return self._formula.delete_recipe(key)

    def open_params(self, key):
        return self._formula.open_params(key)

    def send_formula_to_backtest(self) -> int:
        return self._formula.send_formula_to_backtest()

    def receive_formula(self, segments, params_text: str = "",
                        source_label: str = "外部") -> int:
        return self._formula.receive_formula(segments, params_text,
                                             source_label=source_label)

    def _restore_last_formula(self):
        return self._formula._restore_last_formula()

    # ==========================================
    # 用户标注（→ desk_annotations.DeskAnnotations）
    # ==========================================
    def select_tool(self, kind: str) -> None:
        return self._annos.select_tool(kind)

    def select_tool_number(self, number: int) -> None:
        """数字快捷键 1–9（§7-B8 R10）—— 走与 tile 完全同一条 `select_tool` 路径。"""
        return self._annos.select_tool_number(number)

    def _on_tool_clicked(self, kind: str) -> None:
        return self._annos._on_tool_clicked(kind)

    def _apply_tool(self, kind: str) -> None:
        return self._annos._apply_tool(kind)

    def _reset_tool(self):
        return self._annos._reset_tool()

    def add_annotation(self):
        return self._annos.add_annotation()

    def delete_selected_annotation(self):
        return self._annos.delete_selected_annotation()

    def clear_annotations(self):
        return self._annos.clear_annotations()

    def _refresh_annotation_status(self, hint: str = ""):
        return self._annos._refresh_annotation_status(hint)
