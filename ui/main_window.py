# ui/main_window.py
import logging
from datetime import datetime
from PyQt6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, 
                             QVBoxLayout, QPushButton, QFrame, QStackedWidget,
                             QDialog, QMessageBox, QFileDialog, QLabel,
                             QApplication)
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QEventLoop, Qt, QThread, QUrl

from config import settings
from core.analyzer import TradeAnalyzer
from core.engine import DataEngine
from core.preferences import preferences      # ★1.61 §7-B16：浮窗界面态（hub_ui）
from core.updater import UpdateCheckerThread
# P7：函数配方互送用的纯函数（把各种形态的"函数段"统一成页面各自要的形状）
from data.formula_store import (get_formula_store, segments_as_texts,
                                segments_as_tuples)

from ui.download_hub import DownloadHub
from ui.widgets.download_bar import DownloadBar
from ui.widgets.download_queue_panel import (DOWNLOAD_PANEL_GAP_BOTTOM,
                                             DOWNLOAD_PANEL_GAP_RIGHT,
                                             DownloadQueuePanel)
from ui.views.dashboard import DashboardView
from ui.views.records import RecordsView
from ui.views.review import ReviewView
from ui.views.trading_desk import TradingDeskView
from ui.views.backtest_module import BacktestModule
from ui.views.data_manager import DataManagerView
from ui.views.formula_hub import FormulaHubView   # ★1.61 / §7-B16：函数总库（左轨第 6 项）
from ui.widgets.formula_hub_panel import (HUB_PANEL_GAP_RIGHT, HUB_PANEL_MIN_H,
                                          HUB_PANEL_TOP, FormulaHubPanel)
from ui.widgets.hub_float_list import FN_KIND   # ★H7：浮窗列表里"函数行"的类型标记
from data.hub_assets import asset_texts

# 【高内聚、低耦合的体现】：从各自独立的文件中按需引入模块
from ui.dialogs.list_manager import ListManagerDialog
from ui.dialogs.manual_entry import ManualEntryDialog
from ui.dialogs.import_futures import FuturesImportDialog
from ui.views.settings_view import SettingsView      # ★v6.73 / §7-B13 S2-0：设置页（S2 双栏）

logger = logging.getLogger(__name__)

# ★1.61 / §7-B16 护栏6：函数总库浮窗的界面态偏好键（唯一真源 = `core.preferences.DEFAULTS`）。
#   内容 = {"offset": [dx, dy], "open": bool, "asset_id": str}；**只存界面态，不存函数内容**。
HUB_UI_KEY = 'hub_ui'


class JianMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle(settings.APP_NAME)
        self.resize(settings.MAIN_WINDOW_WIDTH, settings.MAIN_WINDOW_HEIGHT) 
        
        self.setStyleSheet("""
            QMainWindow { background-color: #FAFAFA; font-family: -apple-system, sans-serif; }
            QFrame#Sidebar { background-color: #FFFFFF; border-right: 1px solid #E0E0E0; }
            QPushButton.NavBtn { background-color: transparent; color: #424242; text-align: left; padding: 15px 20px; border-radius: 8px; font-size: 15px; font-weight: bold; border: none; margin: 2px 10px;}
            QPushButton.NavBtn:hover { background-color: #F5F5F5; }
            QPushButton.NavBtn:checked { background-color: #E3F2FD; color: #1976D2; }
        """)
        
        self.engine = DataEngine()

        # ★v1.43 / §7-B11：**后台下载队列**归主窗口（与 engine 同级）。
        # 【为什么不能在弹窗里】旧版 `SyncWorker(parent=弹窗)` ⇒ 线程随弹窗生灭，
        #   所以"下载中关窗"只能硬等 15 秒，用户被要求守在旁边。
        #   任务归属搬到这一层后：弹窗只收集参数，下载与界面解绑，切页/关窗都不影响它。
        # ⚠ 必须在各页面**构造之前**建好（页面构造期就可能取 `main_win.downloads`）。
        self.downloads = DownloadHub(self)
        # ★v6.70 / §9-F①：关窗重入闸门（退出等待现在会转事件循环，不再有“物理上不可能重入”）
        self._exiting = False
        # ★1.61 / §7-B16 护栏6：函数总库浮窗的**位置偏移**（拖出来的，记进 `hub_ui`）。
        #   必须在**任何 `resizeEvent` 之前**就位 —— 重摆浮窗的路径会读它。
        self._hub_offset = (0, 0)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # --- 左侧导航栏构建 ---
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(200)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 20, 0, 20)
        
        self.btn_overview = QPushButton("📊 资金与表现")
        self.btn_records = QPushButton("📝 交易流水")
        self.btn_review = QPushButton("💡 深度复盘")
        self.btn_market = QPushButton("📈 市场行情")
        self.btn_backtest = QPushButton("📐 市场回测")
        # ★1.61 / §7-B16：「ƒ 函数库」插队（用户拍板的落位 = 回测与数据管理之间）——
        #   它是函数资产的"中立的家"；设置页"最下方固定"的口径不受影响（仍加在 addStretch 之后）。
        self.btn_hub = QPushButton("ƒ 函数库")
        self.btn_data = QPushButton("🗄 数据管理")
        
        for btn in [self.btn_overview, self.btn_records, self.btn_review, self.btn_market,
                    self.btn_backtest, self.btn_hub, self.btn_data]:
            btn.setProperty("class", "NavBtn")
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            sidebar_layout.addWidget(btn)
        self.btn_overview.setChecked(True)

        # ★v6.73 / §7-B13 S2-0：`⚙ 设置` **固定在最下方**（用户定的位置）——
        #   ⚠ 必须加在 `addStretch()` **之后**：无论上方功能怎么增减，它都停在底部、不上移。
        self.btn_settings = QPushButton("⚙ 设置")
        self.btn_settings.setProperty("class", "NavBtn")
        self.btn_settings.setCheckable(True)
        self.btn_settings.setAutoExclusive(True)
        self.btn_settings.setToolTip("系统项 / 登录 / 个性化 —— 唯一入口")
        sidebar_layout.addStretch()
        sidebar_layout.addWidget(self.btn_settings)
        
        # --- 右侧主内容栈构建 ---
        self.content_area = QStackedWidget()
        self.content_area.setContentsMargins(20, 20, 20, 20)
        
        self.page_overview = DashboardView(self)
        self.page_records = RecordsView(self)
        self.page_review = ReviewView(self) 
        # ⚠ 属性名仍叫 page_market（导航第 4 页的历史名字），实现已换成 P8 的行情工作台
        self.page_market = TradingDeskView(self)
        self.page_backtest = BacktestModule(self)
        # ★1.61 / §7-B16：函数总库页（A 管理台：列表 + 详情 ⇄ 编辑器；只管资产不管运行）
        self.page_hub = FormulaHubView(self)
        self.page_data = DataManagerView(self)
        # ★v6.73 / §7-B13 S2-0：设置页（S2「系统设置双栏」）—— **只渲染注册表**，页面不写设置项
        self.page_settings = SettingsView(self)
        
        self.content_area.addWidget(self.page_overview)
        self.content_area.addWidget(self.page_records)
        self.content_area.addWidget(self.page_review) 
        self.content_area.addWidget(self.page_market)
        self.content_area.addWidget(self.page_backtest)
        self.content_area.addWidget(self.page_hub)           # ← index 5（ƒ 函数库）
        self.content_area.addWidget(self.page_data)          # ← index 6
        self.content_area.addWidget(self.page_settings)      # ← index 7（设置）
        
        main_layout.addWidget(sidebar)
        # --- 右侧 = 内容栈 + 底部下载条（下载条只在有任务时出现，平时零高度）---
        self.download_bar = DownloadBar(self.downloads, self)
        self.download_bar.sig_detail.connect(self.show_download_queue)
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)
        right_lay.addWidget(self.content_area, 1)
        right_lay.addWidget(self.download_bar)
        main_layout.addWidget(right)
        # 下载队列浮层的宿主（样板把它钉在内容区右下角，见 `_place_download_panel`）
        self._right_panel = right
        self.downloads.jobs_changed.connect(self._place_download_panel)

        # --- 导航角标：下载中在「🗄 数据管理」上亮一个小圆点 ---
        # 【为什么要它】下载条在底部，用户在行情页看图时视线扫不到 ⇒
        #   "有没有活在跑"必须一眼可瞥；点角标 = 切到数据管理页并展开队列面板。
        self.nav_badge = QLabel(self.btn_data)
        self.nav_badge.setObjectName("NavBadge")
        # 样板：9px 橙点 + 3px 浅橙光晕，贴在导航项**右侧竖居中**
        self.nav_badge.setFixedSize(15, 15)
        self.nav_badge.setStyleSheet(
            "QLabel#NavBadge { background:#FB8C00; border:3px solid #FFF3E0;"
            " border-radius:7px; }")
        self.nav_badge.setToolTip("有数据任务在后台下载 —— 点击打开下载队列")
        self.nav_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.nav_badge.hide()
        # 角标是按钮的子件 ⇒ 子件的事件**不会**冒泡到父件的过滤器，两个都要装
        self.btn_data.installEventFilter(self)     # Resize ⇒ 重摆角标
        self.nav_badge.installEventFilter(self)    # 点击 ⇒ 切页 + 开队列面板
        self.downloads.activity_changed.connect(self._on_download_activity)
        
        self.btn_overview.clicked.connect(lambda: self.content_area.setCurrentIndex(0))
        self.btn_records.clicked.connect(lambda: self.content_area.setCurrentIndex(1))
        self.btn_review.clicked.connect(lambda: self.content_area.setCurrentIndex(2))
        self.btn_market.clicked.connect(lambda: self.content_area.setCurrentIndex(3))
        self.btn_backtest.clicked.connect(lambda: self.content_area.setCurrentIndex(4))
        self.btn_hub.clicked.connect(lambda: self.content_area.setCurrentIndex(5))
        # ★1.61 / §7-B16：统一浮窗的「📚 本页方案」区跟着**当前页 / 当前子页签**走
        self.content_area.currentChanged.connect(self._on_page_changed)
        self.page_backtest.tabs.currentChanged.connect(self._on_page_changed)
        self.btn_data.clicked.connect(lambda: self.content_area.setCurrentIndex(6))
        self.btn_settings.clicked.connect(lambda: self.content_area.setCurrentIndex(7))
        
        self.render_all_data()
        self.check_for_updates()
        # ★1.61 / §7-B16 护栏6：按偏好还原总库浮窗（偏移 / 上次选中 / 是否开着）。
        #   ⚠ 放在**最后**：它只碰浮窗自己，不该插进页面构造与数据渲染之间。
        self._load_hub_ui_state()

    # ==========================================
    # 页面切换 + 函数配方互送（P7 · §7-B3 P7）
    # ==========================================
    # 【为什么互送要放在主窗口】两个页面**不应该互相 import**（否则耦合、也容易循环引用）。
    # 主窗口本来就是"组件装配与事件分发"的地方（§3），由它当唯一的传话筒最干净：
    #   行情页 ──send_formula_to_backtest──▶ 主窗口 ──▶ 回测页.load_formula_from_external()
    #   回测页 ──send_formula_to_market────▶ 主窗口 ──▶ 行情页.receive_formula()
    _PAGE_INDEX = {"market": 3, "backtest": 4, "hub": 5, "data": 6, "settings": 7}

    def switch_to(self, key: str) -> None:
        """按名字切页（互送后直接把用户带到目标页，省得他自己找）。"""
        index = self._PAGE_INDEX.get(str(key))
        if index is not None:
            self.content_area.setCurrentIndex(index)

    # ==========================================
    # 后台下载（v1.43 · §7-B11）：队列属主窗口，界面只是它的三个视图
    # ==========================================
    # 下载条（底部）/ 导航角标（左侧）/ 队列面板（非模态）全部订阅同一个 hub，
    # **任何一处都不存任务数据** —— 否则就是"三套进度各自为政"（§11.5-11）。
    _download_panel = None

    def show_download_queue(self) -> None:
        """打开（或置顶）下载队列**浮层**。懒建：不开下载就不多一块界面。

        ⚠ 形态按样板：**主窗口内的浮层**（不是 `QDialog`）—— 它天生不抢焦点、
          不进任务栏、不能被拖到主窗口外面，也不会盖住整个界面。
        """
        if self._download_panel is None:
            self._download_panel = DownloadQueuePanel(self.downloads, self._right_panel)
        self._download_panel.refresh()
        self._place_download_panel()
        self._download_panel.show()
        self._download_panel.raise_()

    def _place_download_panel(self) -> None:
        """把浮层钉在**内容区右下角**（样板 `right:18 / bottom:52`，正好落在下载条上方）。

        主窗口缩放、或队列增删导致面板高度变化时都要重算（`jobs_changed` 已挂）。
        """
        panel = getattr(self, '_download_panel', None)
        host = getattr(self, '_right_panel', None)
        if panel is None or host is None:
            return
        panel.adjustSize()
        x = max(0, host.width() - panel.width() - DOWNLOAD_PANEL_GAP_RIGHT)
        y = max(0, host.height() - panel.height() - DOWNLOAD_PANEL_GAP_BOTTOM)
        panel.move(x, y)

    def resizeEvent(self, event):  # noqa: N802 —— Qt 命名
        super().resizeEvent(event)
        self._place_download_panel()
        self._place_hub_panel()          # ★1.61 §7-B16：浮窗跟着窗口走（含用户拖动偏移）

    # ==========================================
    # ƒ 函数总库（★1.61 / §7-B16）：**页面内**悬浮列表 + 载入路由
    # ==========================================
    # 【形态与纪律】照 download_queue_panel 的浮层范式（非模态、不持线程、位置主窗口算）；
    #   "载入到本页"只回填函数区（红线②：配置区一字不动）。
    # ★H7 改口径（用户实测）：**页面内悬浮** —— 宿主 = 打开它的那个页面（切页随页收起），
    #   不再是"跨页全局悬浮"（用户："全局没有意义，我只需要它在对应页面悬浮"）。
    #   ⇒ `hub_ui` 只留**位置偏移 + 上次选中**；"开合记忆"随全局形态一起退役：页面内的浮窗
    #     不会跨页活到下次启动，开机自动弹一块浮层只会在仪表盘上白占地方。
    _formula_hub_panel = None
    _hub_host = None                 # 浮窗当前挂在哪个页面（页面内悬浮的宿主）
    _BT_TAB_LABELS = ('M1 单股回测', 'M2 全市场筛选', 'M3 广度统计')

    def _hub_ui(self) -> dict:
        """读浮窗界面态 —— **坏数据逐字段回落**（§9-D：绝不因为一个坏键把浮窗搞没）。"""
        raw = preferences.get(HUB_UI_KEY)
        data = dict(raw) if isinstance(raw, dict) else {}
        offset = data.get('offset')
        if not (isinstance(offset, (list, tuple)) and len(offset) == 2
                and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                        for v in offset)):
            offset = [0, 0]
        return {'offset': [int(offset[0]), int(offset[1])],
                'asset_id': str(data.get('asset_id') or '')}

    def _save_hub_ui(self, **changes) -> None:
        """写浮窗界面态（只改传进来的字段，其余保持）—— 落点唯一，别处不许直接写这个键。"""
        data = self._hub_ui()
        data.update(changes)
        preferences.set(HUB_UI_KEY, data)

    def _page_label(self, page=None) -> str:
        """当前页的人话名（浮窗标题旁那枚上下文胶囊）。

        ⚠ 并成一个列表之后，"这些方案属于哪一页"就只剩这枚胶囊能说清 —— 在 M1 打开却以为
          在看 M2 的方案 = 静默错配（§11.5-11 同族）。
        """
        page = page if page is not None else self.content_area.currentWidget()
        if page is self.page_backtest:
            idx = self.page_backtest.tabs.currentIndex()
            return self._BT_TAB_LABELS[idx] if 0 <= idx < len(self._BT_TAB_LABELS) else '回测'
        for attr, label in (('page_market', '市场行情'), ('page_hub', 'ƒ 函数库'),
                            ('page_overview', '资金与表现'), ('page_records', '交易流水'),
                            ('page_review', '深度复盘'), ('page_data', '数据管理'),
                            ('page_settings', '设置')):
            if page is getattr(self, attr, None):
                return label
        return ''

    def show_formula_hub_panel(self, keep: str = None) -> None:
        """打开（或置顶）函数总库浮窗 —— 懒建 + **挂到当前页**（页面内悬浮）。

        :param keep: 要预选中的行（资产 id 或方案 id）；None = 保持当前选中项。
        """
        page = self.content_area.currentWidget()
        if page is None:
            return
        if self._formula_hub_panel is None:
            self._formula_hub_panel = FormulaHubPanel(page)
            self._formula_hub_panel.sig_load.connect(self.load_into_current)
            self._formula_hub_panel.sig_open_hub.connect(self._open_hub_page)
            self._formula_hub_panel.sig_dragged.connect(self._on_hub_dragged)
            self._formula_hub_panel.sig_drag_finished.connect(self._on_hub_drag_finished)
            self._formula_hub_panel.sig_closed.connect(self._on_hub_closed)
            # 两个取口："当前页是谁 / 当前页有哪些方案"只有主窗口知道（浮窗自己不找页面）
            self._formula_hub_panel.draft_provider = self.current_formula_draft
            self._formula_hub_panel.plan_provider = self.current_plan_api
        panel = self._formula_hub_panel
        if panel.parent() is not page:
            # ★H7：换宿主（Qt 的 `setParent` 会把子件从旧宿主摘走 ⇒ 旧页面里不会留残影）
            panel.setParent(page)
        self._hub_host = page
        panel.set_context(self._page_label(page))
        keep = keep if keep is not None else panel.selected_id()
        panel.refresh(keep=keep)
        self._place_hub_panel()
        panel.show()
        panel.raise_()

    def _on_page_changed(self, *_a) -> None:
        """页面 / 子页签变了 ⇒ 页面内悬浮的浮窗跟着走：
        **同一页换子页签**（M1↔M2↔M3）= 上下文变了 ⇒ 就地刷新（方案与标题胶囊一起换）；
        **换到别的页** = 它已不属于当前页 ⇒ 收起（用户下次点「ƒ 库」会把它挂到新页上）。
        """
        panel = getattr(self, '_formula_hub_panel', None)
        if panel is None:
            return
        page = self.content_area.currentWidget()
        if panel.parent() is page:
            panel.set_context(self._page_label(page))
            panel.refresh(keep=panel.selected_id())
        else:
            panel.hide()

    def _place_hub_panel(self) -> None:
        """浮窗钉在**宿主页右上角**（下载浮层在右下，两者互不重叠），再叠加用户拖动偏移。

        ⚠ 夹回宿主页内：窗口缩小 / 用户拖太远 ⇒ 不许"飞到看不见的地方"
          （那样浮窗看起来像是丢了，用户只能重启）；并按宿主高度封顶（页面矮 ⇒ 列表自己滚）。
        """
        panel = getattr(self, '_formula_hub_panel', None)
        host = getattr(self, '_hub_host', None)
        if panel is None or host is None:
            return
        panel.setMaximumHeight(max(HUB_PANEL_MIN_H, host.height() - 2 * HUB_PANEL_TOP))
        panel.adjustSize()
        dx, dy = self._hub_offset
        x = host.width() - panel.width() - HUB_PANEL_GAP_RIGHT + dx
        y = HUB_PANEL_TOP + dy
        x = min(max(0, x), max(0, host.width() - panel.width()))
        y = min(max(0, y), max(0, host.height() - panel.height()))
        panel.move(x, y)

    def _on_hub_dragged(self, dx: int, dy: int) -> None:
        """标题栏拖动：把位移累加进偏移并重摆（**拖动过程不写盘**，松手才落）。"""
        ox, oy = self._hub_offset
        self._hub_offset = (ox + dx, oy + dy)
        self._place_hub_panel()

    def _on_hub_drag_finished(self) -> None:
        self._save_hub_ui(offset=[int(self._hub_offset[0]), int(self._hub_offset[1])])

    def _on_hub_closed(self) -> None:
        """**用户主动点 ✕** ⇒ 记住上次选中的那条（下次打开接着看它）。"""
        panel = getattr(self, '_formula_hub_panel', None)
        self._save_hub_ui(asset_id=(panel.selected_id() if panel is not None else ''))

    def _load_hub_ui_state(self) -> None:
        """开机把浮窗**位置偏移**读进来。

        ⚠ 不再"自动弹开"（旧版 `hub_ui.open` 的语义已随全局悬浮一起退役）：页面内的浮窗
          活不到下次启动，而在仪表盘上自动弹一块函数浮层纯属噪音 —— 要看就点「ƒ 库」。
        """
        ui = self._hub_ui()
        self._hub_offset = (ui['offset'][0], ui['offset'][1])

    def _open_hub_page(self) -> None:
        """浮窗「✏ 去总库编辑」：切到 A 页并选中浮窗当前选中的**函数**（编辑落点唯一）。

        ⚠ 选中的是本页方案时**不带 id 过去**：方案不是资产，`reveal_asset` 找不到它，
          带过去只会把 A 页的选中态清空（看起来像"点了没反应"）。
        """
        panel = getattr(self, '_formula_hub_panel', None)
        asset_id = ''
        if panel is not None and panel.selected_kind() == FN_KIND:
            asset_id = panel.selected_id()
        self.switch_to('hub')
        if asset_id:
            self.page_hub.reveal_asset(asset_id)

    def load_into_current(self, asset: dict) -> int:
        """浮窗「⤓ 载入到本页」：把资产回填到**当前页**的函数区。

        ⚠ 红线②：只回填函数段与参数 —— 条件/风控/门控/成交/阈值/范围等配置**一字不动**。
        :return: 实际载入的段数（0 = 当前页没有函数区；负值不出现）
        """
        texts = asset_texts(asset)
        params = str(asset.get('params_text') or '')
        cur = self.content_area.currentWidget()
        n = 0
        if cur is self.page_market:
            pairs = segments_as_tuples({"segments": asset.get("segments")})
            n = self.page_market.receive_formula(pairs, params, source_label="函数总库")
        elif cur is self.page_backtest:
            idx = self.page_backtest.tabs.currentIndex()
            if idx == 0:
                n = self.page_backtest.backtest_single.load_formula_from_external(texts, params)
            elif idx == 1:
                n = self.page_backtest.page_scan.load_formula_from_hub(texts, params)
            elif idx == 2:
                n = self.page_backtest.page_breadth.load_formula_from_hub(texts, params)
        if n:
            get_formula_store().touch(asset.get('id'))   # 载入即 used_at（列表的"最近使用"据此排）
            self._hub_say(f'⤓ 已载入「{asset.get("name")}」到本页（{n} 段）—— '
                          '配置区一字未动；跑图 / 跑回测 / 跑扫描在页面上完成')
            panel = getattr(self, '_formula_hub_panel', None)
            if panel is not None:
                panel.refresh(keep=asset.get('id'))      # used_at 变了 ⇒ 列表"最近使用"跟着重排
        else:
            self._hub_say('⚠ 当前页没有可载入的函数区 —— 请切到行情 / 回测（M1） / 扫描（M2·M3）页')
        return n

    def _hub_say(self, text: str) -> None:
        """把一句话写到浮窗的回执行（浮窗没建出来就静默 —— 例如 A 页「送 ↗」走的是另一条路）。

        ⚠ 载入**必须有可见回执**：用户实测"点了半天页面纹丝不动"里，有一半是**没有任何反馈**
          （浮窗既不说话、页面也不变）—— 于是分不清"没成功"还是"没反应"。
        """
        panel = getattr(self, '_formula_hub_panel', None)
        if panel is not None:
            panel.say(text)

    # ==========================================
    # ★1.61 / §7-B16：「统一浮窗」的两个取口（**当前页提供，浮窗不自己找页面**）
    #   浮窗是"跨页"的（从哪页开都一样），所以"当前页是谁"这件事只有主窗口知道。
    #   页面侧一律**只读**（各页的 `current_formula_draft()` 不改任何状态）。
    # ==========================================
    def current_formula_draft(self) -> dict | None:
        """当前页"正在编辑的函数"草稿（浮窗「💾 保存当前函数」用）；无函数区 = None。

        :return: `{'name_hint', 'segments': [{text,target}], 'params_text', 'source'}`
        """
        cur = self.content_area.currentWidget()
        if cur is self.page_market:
            return self.page_market._formula.current_formula_draft() or None
        if cur is self.page_backtest:
            view = self.page_backtest
            idx = view.tabs.currentIndex()
            if idx == 0:
                return view.backtest_single.current_formula_draft()
            if idx == 1:
                return view.page_scan.current_formula_draft()
            if idx == 2:
                return view.page_breadth.current_formula_draft()
        return None

    def current_plan_api(self) -> dict | None:
        """当前页的「方案 / 策略库」三件事（浮窗「📚 本页方案」区用）；无 = None。

        :return: `{'kind','noun','hint','plans','plan_label','load','save','delete'}`
                 —— 全是**可调用对象**（页面/桥接的实现，浮窗只负责画与转发）。
        """
        cur = self.content_area.currentWidget()
        if cur is not self.page_backtest:
            return None
        view = self.page_backtest
        idx = view.tabs.currentIndex()
        if idx == 0:
            br = view.backtest_single.strategy
            return {'kind': 'M1', 'noun': '策略',
                    'hint': '策略 = 函数 + 买卖条件 + 风控 + 区间；每条的结果在「🗂 运行历史」里',
                    'plans': br.plans, 'plan_label': br.plan_label,
                    'load': br.load_plan, 'save': br.save, 'delete': br.delete_plan}
        if idx in (1, 2):
            page = view.page_scan if idx == 1 else view.page_breadth
            br = page._strategy
            return {'kind': 'M2M3', 'noun': '筛选方案',
                    'hint': '筛选方案 = 函数 + 粗筛阈值 + 统计范围 + 复权口径（M2 / M3 共用一份池）',
                    'plans': br.plans, 'plan_label': br.plan_label,
                    'load': br.load_plan, 'save': br.save, 'delete': br.delete_plan}
        return None

    def send_asset_to_page(self, asset: dict, target: str) -> int:
        """总库「送 ↗」：切到目标页并载入（**只回填，绝不运行** —— 红线①）。"""
        texts = asset_texts(asset)
        params = str(asset.get('params_text') or '')
        n = 0
        if target == 'market':
            self.switch_to('market')
            pairs = segments_as_tuples({"segments": asset.get("segments")})
            n = self.page_market.receive_formula(pairs, params, source_label="函数总库")
        elif target == 'backtest':
            self.switch_to('backtest')
            self.page_backtest.tabs.setCurrentIndex(0)
            n = self.page_backtest.backtest_single.load_formula_from_external(texts, params)
        elif target == 'scan':
            self.switch_to('backtest')
            self.page_backtest.tabs.setCurrentIndex(1)
            n = self.page_backtest.page_scan.load_formula_from_hub(texts, params)
        if n:
            get_formula_store().touch(asset.get('id'))
        return n

    def _on_download_activity(self, busy: bool) -> None:
        self.nav_badge.setVisible(bool(busy))
        self._place_badge()

    def _place_badge(self) -> None:
        """角标贴在「数据管理」按钮**右侧竖居中**（样板位置）；按钮尺寸变了就得跟着重摆。"""
        btn = self.btn_data
        self.nav_badge.move(btn.width() - self.nav_badge.width() - 8,
                            max(0, (btn.height() - self.nav_badge.height()) // 2))
        self.nav_badge.raise_()

    def eventFilter(self, obj, event):  # noqa: N802
        """一个过滤器干两件事：按钮尺寸变化时重摆角标；点角标 = 切页 + 开队列面板。"""
        if obj is self.btn_data and event.type() == event.Type.Resize:
            self._place_badge()
        elif obj is self.nav_badge and event.type() == event.Type.MouseButtonPress:
            self.content_area.setCurrentIndex(6)
            self.btn_data.setChecked(True)
            self.show_download_queue()
            return True                           # 吞掉：点角标不该只切页不开面板
        return super().eventFilter(obj, event)

    def closeEvent(self, event):  # noqa: N802
        """退出守卫：队列非空时确认一次，然后**等线程真结束**再走。

        ⚠ 【为什么必须等】QThread 运行中被销毁 = 崩溃。旧弹窗为这件事写过
          "中断 + wait(15s)"（`bulk_download._try_stop_worker`）；任务搬到 hub 后，
          同样的约束落在主窗口上（hub 是 worker 的 parent）。
        ⚠ 【为什么要 `_exiting` 闸门（★v6.70 / §9-F①）】等待从“一次 `wait(15s)` 阻塞”
          改成“分片 + `processEvents`”后，关闭期间事件循环仍在转 ⇒ 用户再点一次 X 会
          **重入本函数**（旧形态下不可能）。重入直接忽略 —— 否则会弹第二个确认框、
          再套一层等待（而第二层里 `QApplication.processEvents()` 就是无限套娃的入口）。
        """
        if self._exiting:
            event.ignore()                # 已经在关了，忽略重入的关闭请求
            return
        self._exiting = True
        try:
            if self.downloads.has_unfinished():
                n = self.downloads.pending_count()
                reply = QMessageBox.question(
                    self, "下载仍在进行",
                    f"还有 {n} 个下载任务在跑。\n\n"
                    "退出会中断它们（已下载的部分会保留，下次重跑同范围会自动跳过）。\n"
                    "确定现在退出吗？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                if reply != QMessageBox.StandardButton.Yes:
                    event.ignore()
                    return
            # ★v6.70 / §9-F①：先等队列（它会刷“正在停止…”），再扫其余页面级 worker。
            #   顺序不能反：`_shutdown_background_threads` 对每个在跑线程是一次性
            #   `wait(3000)` 的静默阻塞，排在前面就等于“先闷三秒再说话”——
            #   而下载 worker 本来就是 hub 的孩子，hub 先停干净后它已不在跑，后排自然跳过。
            self._wait_downloads_to_stop()
            self._shutdown_background_threads(on_wait=self._paint_stopping)
            super().closeEvent(event)
        finally:
            self._exiting = False         # “不退出”那条路要能把闸门放下（下次还能正常关）

    def _paint_stopping(self, waited_ms: int = 0) -> None:
        """把「正在停止…」画出来并转一拍事件循环（§9-F①：退出等待不再是静默阻塞）。

        ★v6.70 加固（二次修改）：`processEvents` 显式**挡掉用户输入**
        （`ExcludeUserInputEvents`）—— 分片等待期间转循环，若还收鼠标/键盘事件，用户能在
        "正在退出"的窗口上点出新动作（新任务入口虽被 `hub._closing` 关掉，别的按钮不收：
        例如页面「更新到最新」会把页面置成"进行中"却永远等不到回包）。
        **退出路径上只许看、不许动**；重画与排队的信号照常投递（回执要能刷出来）。
        """
        self.download_bar.show_stopping(waited_ms)
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def _wait_downloads_to_stop(self) -> None:
        """★v6.70 / §9-F①：分片等后台下载停手，**并让“正在停止…”真画出来**。

        【还的是什么债】旧版直接 `hub.shutdown()` = 主线程一次 `wait(15000)`：
        期间界面完全不动，用户无法区分“正在收尾”与“程序死了”。
        现在 hub 每片醒一次回调 `_tick`，刷回执 + 转一拍事件循环。
        重入安全靠两层：本函数只从 `closeEvent`（已带 `_exiting` 闸门）进来，
        且 `hub._closing` 已置位 ⇒ 转循环期间新任务会被 `submit()` 直接拒收。
        """
        if not self.downloads.shutdown(on_tick=self._paint_stopping):
            # 超时：hub 已把这只线程摘 parent + 握住引用（不会带着它在跑的线程去销毁）。
            #   对用户只说一句人话，并给出路 —— 下次重跑同范围会从断点续上。
            self.download_bar.lbl_name.setToolTip(
                "还有一只请求没回来，已让它脱离窗口生命周期（不影响下次续传）")

    def _shutdown_background_threads(self, timeout_ms: int = 3000, on_wait=None) -> None:
        """★v6.69：关窗前**取消并等停**所有在跑的 QThread（行业分页 / 估值快照 / 扫描体…）。

        【为什么必须做】用户实测日志里出现过
          `QThread: Destroyed while thread '' is still running`
        —— 那是**页面销毁时后台 worker 还在跑**（行业分页一批 3 页 × 0.5s 间隔 ≈ 2~3 秒，
        刚好落在"点完扫描就关窗"的时间窗里）。Qt 对"运行中的 QThread 被销毁"是**硬崩级**
        （与 §11.5-95 那次偶发 fastfail 同源），所以这里统一收口：
        `cancel()`（各 worker 自己实现，页与页之间生效）+ `wait()`（等它真退出）。
        找不到的对象（无 parent 的线程）不在 `findChildren` 里 —— 那是它们自己的责任，
        本函数至少保证**页面持有的**那些不会带病销毁。
        """
        for thread in self.findChildren(QThread):
            if not thread.isRunning():
                continue
            cancel = getattr(thread, 'cancel', None)
            if callable(cancel):
                try:
                    cancel()
                except Exception as e:  # noqa: BLE001 —— 取消失败不该拦住关窗
                    logger.warning(f"取消后台线程失败({type(thread).__name__}): {e}")
            if on_wait is not None:
                on_wait()                 # ★v6.70 §9-F①：等之前先把“正在停止…”画出来
            thread.wait(timeout_ms)

    def send_formula_to_backtest(self, segments, params_text: str = "") -> int:
        """行情页 → 回测页：把函数送进①函数段编辑区并切页，返回段数（0 = 内容为空）。

        ⚠ **目标窗格不随行**：回测页没有副图概念，只带函数文本与参数。
        需要连窗格一起保留时请用「💾 存为配方」（配方里存了 target，行情页载入即还原）。
        """
        texts = segments_as_texts({"segments": segments})
        if not texts:
            return 0
        self.page_backtest.backtest_single.load_formula_from_external(texts, params_text)
        self.switch_to("backtest")
        return len(texts)

    def send_formula_to_market(self, segments, params_text: str = "") -> int:
        """回测页 → 行情页：每段默认落「主图」（回测侧没有窗格信息），切页并立即渲染。"""
        pairs = segments_as_tuples({"segments": segments})
        if not pairs:
            return 0
        self.page_market.receive_formula(pairs, params_text, source_label="回测页")
        self.switch_to("market")
        return len(pairs)

    def check_for_updates(self):
        self.updater_thread = UpdateCheckerThread()
        self.updater_thread.update_available.connect(self.show_update_dialog)
        self.updater_thread.start()

    def show_update_dialog(self, version: str, notes: str, download_url: str):
        msg = f"当前版本: {settings.APP_VERSION}\n最新版本: {version}\n\n更新说明:\n{notes}\n\n是否立即前往浏览器下载新版本？"
        reply = QMessageBox.question(self, "✨ 发现新版本", msg, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes and download_url:
            QDesktopServices.openUrl(QUrl(download_url))

    def render_all_data(self):
        if self.engine.df.empty: 
            self.page_overview.clear_view()
            self.page_records.clear_view()
            self.page_review.refresh_review_filters()
            return

        analyzer = TradeAnalyzer(self.engine.df)
        raw_report = analyzer.generate_raw_report()
        
        if raw_report:
            self.page_overview.update_view(raw_report, analyzer.df)
            self.page_records.refresh_records_filters()
            self.page_review.refresh_review_filters()
            self.page_review.update_review_view()

    # ==========================================
    # 数据流与弹窗调度器 (完全解耦调用)
    # ==========================================
    
    def _show_import_result(self, stats: dict, source_label: str, gaps: list = None):
        """
        统一的导入防呆反馈：既报告新增/拦截量，
        也把"疑似漏月"这类影响数据完整性的情况明确告知用户。
        """
        msg = (f"操作完成！\n\n📄 共解析到{source_label}：{stats['total']} 笔\n"
               f"✅ 成功新增入库：{stats['inserted']} 笔")
        if stats['ignored'] > 0:
            msg += f"\n🛡️ 拦截重复数据：{stats['ignored']} 笔 (已跳过)"
        QMessageBox.information(self, "导入结果", msg)

        if gaps:
            self._warn_coverage_gaps(gaps)

    def _warn_coverage_gaps(self, gaps: list):
        """
        漏月告警：资金链条接不上，说明中间可能存在未导入的月份。

        【绝不阻断】数据照常入库、照常可用，漏月只是提示而非错误；
        用户可以选择"稍后处理"，也可以把该月登记为"确无交易"以免重复打扰。
        """
        for gap in gaps:
            month = gap.get('missing_month') or gap['month']
            box = QMessageBox(self)
            box.setWindowTitle("⚠️ 检测到导入断层")
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText(
                f"账户【{gap['account']}】的 {gap['month']} 月报显示：\n"
                f"　　上月结存 ￥{gap['prev_balance']:,.2f}\n\n"
                f"该数值与已导入月份的资金期末值都对不上，"
                f"说明中间很可能漏导了 {month} 的交割单。\n\n"
                f"漏导会让更早月份建立的仓位被误判为「遗留单」，"
                f"进而缺少开仓价与持仓时长。建议补齐后再继续。"
            )
            btn_fix = box.addButton("立即补导", QMessageBox.ButtonRole.AcceptRole)
            btn_skip = box.addButton(f"{month} 确无交易，不再提醒",
                                     QMessageBox.ButtonRole.DestructiveRole)
            btn_later = box.addButton("稍后处理", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(btn_later)
            box.exec()

            if box.clickedButton() is btn_skip:
                self.engine.confirm_coverage_gap(gap['account'], month)
            elif box.clickedButton() is btn_fix:
                self.open_futures_import()   # 递归补导，处理完即返回
                return

    def open_futures_import(self):
        dialog = FuturesImportDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted and getattr(dialog, 'parsed_result', None):
            # 解析已在子线程完成，这里只在主线程做轻量落库，线程安全
            pkg = self.engine.commit_cfmmc(dialog.parsed_result)
            self.render_all_data()
            self._show_import_result(pkg['stats'], "闭环交易", pkg.get('gaps'))

    def open_manual_entry(self):
        # v1.2.1：归属账户只列出真实存在的账户（来自已导入数据），不预置虚构账户
        df = self.engine.df
        accounts = (sorted({str(a) for a in df['account'].dropna().unique()})
                    if not df.empty else [])
        dialog = ManualEntryDialog(self.engine.strategies, accounts, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and getattr(dialog, 'new_trades', None):
            self.engine.add_trades(dialog.new_trades)
            self.render_all_data()
            
    def export_data(self):
        if self.engine.df.empty:
            QMessageBox.warning(self, "提示", "当前没有任何数据可以导出！")
            return

        default_name = f"Jian_Backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        file_path, _ = QFileDialog.getSaveFileName(self, "导出数据备份", default_name, "CSV 数据表 (*.csv)")
        
        if file_path:
            try:
                export_df = self.engine.df.copy()
                if 'internal_id' in export_df.columns:
                    export_df = export_df.drop(columns=['internal_id'])

                # v1.2：导出时补算净额，让 CSV 与界面口径保持一致
                if {'net_profit', 'commission'}.issubset(export_df.columns):
                    export_df['net_amount'] = export_df['net_profit'] - export_df['commission']

                cols_order = ['trade_id', 'account', 'symbol', 'direction', 'trade_time',
                              'exit_fill_time', 'entry_fill_time', 'time_source',
                              'entry_price', 'exit_price', 'multiplier', 'is_orphan',
                              'lots', 'net_profit', 'commission', 'net_amount',
                              'strategy_tag', 'entry_reason', 'reflection', 'screenshot_paths']
                export_cols = [c for c in cols_order if c in export_df.columns]
                export_df = export_df[export_cols]
                
                export_df.to_csv(file_path, index=False, encoding='utf-8-sig')
                QMessageBox.information(self, "导出成功", f"恭喜！所有复盘数据已成功导出至：\n\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "导出失败", f"文件保存时发生错误：\n{str(e)}")

    def manage_accounts(self):
        if self.engine.df.empty: return
        accounts = self.engine.df['account'].dropna().unique().tolist()
        dialog = ListManagerDialog("管理账户", accounts, self._delete_account_action, self)
        dialog.exec()

    def _delete_account_action(self, acc_name):
        reply = QMessageBox.question(self, "危险", f"确定清空【{acc_name}】？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            if self.engine.clear_account(acc_name):
                self.render_all_data()
            return True
        return False

    def manage_strategies(self):
        strats = [s for s in self.engine.strategies if s != settings.DEFAULT_STRATEGY]
        if not strats: return
        dialog = ListManagerDialog("管理策略", strats, self._delete_strategy_action, self)
        dialog.exec()

    def _delete_strategy_action(self, st_name):
        reply = QMessageBox.question(self, "删除", f"确定删除策略【{st_name}】？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            if self.engine.delete_strategy(st_name):
                self.render_all_data()
            return True
        return False