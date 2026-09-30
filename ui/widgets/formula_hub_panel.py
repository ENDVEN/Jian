# ui/widgets/formula_hub_panel.py
"""ƒ 函数总库的**统一浮窗**（★1.61 / §7-B16 · H7「用户实测后重做」）。

【它是什么】M1 / M2·M3 / 行情页**共用的一个入口**（各页只留一个「ƒ 库」按钮）。
打开就是**当前页该看到的东西**：本页方案（M1 策略 / M2·M3 筛选方案）+ 函数资产，
**并成一个列表** —— 方案行带「📚 方案」徽标、函数行照旧带来源与引用数。
（用户实测原话大意："ƒ 函数 / 📚 本页方案 两个区**多此一举**，在哪个页面打开就列哪个页面
该看到的东西" ⇒ H7 把两区合并，连同分区切换控件一起删掉。）

【两处口径变更（都来自用户实测）】
  · **双击 = 用起来**：函数 ⇒ 回填当前页函数区；方案 ⇒ 整体还原进当前页。
    旧版把列表行做成"只选中"、把「载入」藏在**从列表进不去的详情页**里 ⇒ 用户报
    "双击根本点不进对应的函数页面 / f 库是个摆设"（真因：死胡同，不是没实现）。
  · **页面内悬浮**（不再是全局浮层）：宿主 = 打开它的那个页面；切页随页收起。
    旧版是"跨页全局悬浮"，用户实测后判定"全局没有意义"。

【形态与纪律】照 `download_queue_panel`：**主窗口内的 QFrame 浮层**（不是 QDialog）——
  非模态、不进任务栏、不持有任何线程；位置记偏好 `hub_ui.offset`（拖动即记）。
【红线①】没有任何"运行"入口：载入之后跑图 / 跑回测 / 跑扫描都在功能页完成。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QFrame, QGraphicsDropShadowEffect, QHBoxLayout,
                             QLabel, QPushButton, QVBoxLayout)

from ui.widgets.hub_float_list import FloatHubList

PANEL_WIDTH = 470
HUB_PANEL_GAP_RIGHT = 18        # 距**宿主页**右缘
HUB_PANEL_TOP = 20              # 距宿主页顶缘（下载浮层钉在右下，两者互不重叠）
HUB_PANEL_MIN_H = 260           # 宿主页太矮时的下限（再小就没法用了）

_PANEL_QSS = ("QFrame#HubFloat { background:#FFFFFF; border:1px solid #E4E9F0;"
              " border-radius:12px; }"
              "QLabel { background:transparent; }")


class _DragHeader(QFrame):
    """浮窗标题栏 —— 抓住它就能拖（**位置记忆**的唯一入口）。

    ⚠ 必须**子类覆写**鼠标事件：给实例赋属性不参与 Qt 的 C++ 事件派发
      （`download_queue_panel._ClickableLabel` / `hub_layout.HubItem` 同款教训，本仓已踩两次）。
    ⚠ 用 `globalPosition()` 的**逐次增量**（每次 move 都推进基准点），
      拿"按下点 → 当前点"的累计量会把窗口自身的位移算进去 ⇒ 拖拽正反馈抖动。
    """

    def __init__(self, on_drag, on_done, parent=None):
        super().__init__(parent)
        self._on_drag = on_drag
        self._on_done = on_done
        self._press = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip('按住这里拖动浮窗（位置会被记住）')

    def mousePressEvent(self, event):  # noqa: N802 —— Qt 命名
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._press is not None:
            now = event.globalPosition().toPoint()
            self._on_drag(now.x() - self._press.x(), now.y() - self._press.y())
            self._press = now
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._press is not None:
            self._press = None
            self._on_done()                      # 松手才落盘（拖动过程不写偏好）
        super().mouseReleaseEvent(event)


class FormulaHubPanel(QFrame):
    """统一浮窗：**一个列表**（本页方案 + 函数资产）+ 一行回执。"""

    sig_load = pyqtSignal(dict)          # ⤓ 载入到本页（参数 = 资产 dict；路由在主窗口）
    sig_open_hub = pyqtSignal()          # ✏ 去总库编辑（切到 A 页并选中）
    sig_dragged = pyqtSignal(int, int)   # 标题栏拖动：逐次位移（主窗口据此累加偏移并重摆）
    sig_drag_finished = pyqtSignal()     # 松手：此刻才把偏移写进偏好
    sig_closed = pyqtSignal()            # **用户主动点 ✕**

    # 两个由主窗口注入的取口（"当前页是谁"只有主窗口知道）
    draft_provider = None                # () -> 当前页函数草稿 | None
    plan_provider = None                 # () -> 当前页方案 API | None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('HubFloat')
        self.setStyleSheet(_PANEL_QSS)
        self.setFixedWidth(PANEL_WIDTH)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(31, 36, 48, 40))
        self.setGraphicsEffect(shadow)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(8)

        # ---------- 标题栏（可拖）：库名 + **当前页上下文** + ✕ ----------
        self.head = _DragHeader(self._on_drag, self.sig_drag_finished.emit, parent=self)
        head = QHBoxLayout(self.head)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        title = QLabel('ƒ 函数库')
        title.setStyleSheet("font-size:13.5px; font-weight:bold; color:#1F2430;")
        head.addWidget(title)
        # ⚠ 上下文必须写在**浮窗里**：并列表之后，"这些方案属于哪一页"只能靠它说清
        #   （在 M1 打开却以为在看 M2 的方案 = 静默错配）。
        self.lbl_ctx = QLabel('')
        self.lbl_ctx.setStyleSheet("font-size:11px; color:#1976D2; background:#E8F1FB;"
                                   " border-radius:7px; padding:1px 8px;")
        head.addWidget(self.lbl_ctx)
        head.addStretch()
        self.btn_close = QPushButton('✕')
        self.btn_close.setFlat(True)
        self.btn_close.setStyleSheet("QPushButton { color:#8A94A6; border:none; font-size:14px; }"
                                     "QPushButton:hover { color:#1F2430; }")
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setToolTip('收起浮窗（不会改动任何函数）')
        head.addWidget(self.btn_close)
        root.addWidget(self.head)

        # ---------- 一行用法（把"双击"这条最短路径说出来，别让用户猜）----------
        hint = QLabel('双击任意一行 = 直接用到本页（函数回填 / 方案还原）；单击选中后用下方按钮。')
        hint.setWordWrap(True)
        hint.setStyleSheet('font-size:11px; color:#8A94A6;')
        root.addWidget(hint)

        # ---------- 列表 ----------
        self.list = FloatHubList()
        self.list.draft_provider = (lambda: self.draft_provider()
                                    if callable(self.draft_provider) else None)
        self.list.plan_provider = (lambda: self.plan_provider()
                                   if callable(self.plan_provider) else None)
        self.list.sig_load.connect(self.sig_load)
        self.list.sig_open_hub.connect(self.sig_open_hub)
        self.list.sig_say.connect(self.say)
        root.addWidget(self.list, 1)

        # ---------- 回执一行（**本浮窗唯一**的一处反馈位）----------
        self.lbl_stat = QLabel('')
        self.lbl_stat.setStyleSheet('font-size:11px; color:#8A94A6;')
        self.lbl_stat.setWordWrap(True)
        root.addWidget(self.lbl_stat)

        # ---------------- 接线 ----------------
        self.btn_close.clicked.connect(self._on_close)

    # ==========================================
    # 对外（主窗口用）
    # ==========================================
    def set_context(self, text: str) -> None:
        """标题旁那枚上下文胶囊（如「M1 单股回测」）—— 由主窗口按当前页灌入。"""
        self.lbl_ctx.setText(str(text or ''))
        self.lbl_ctx.setVisible(bool(str(text or '')))

    def refresh(self, keep: str = None) -> None:
        self.list.refresh(keep=keep)

    def select(self, asset_id: str) -> None:
        self.list.show_list()
        self.list.select(asset_id)

    def selected_id(self) -> str:
        return self.list.selected_id()

    def selected_kind(self) -> str:
        return self.list.selected_kind()

    def begin_save_current(self, draft: dict) -> None:
        """把当前页的函数草稿预填进编辑器（主窗口路由进来）。"""
        self.list.show_list()
        self.list.begin_save_current(draft)

    def say(self, text: str) -> None:
        self.lbl_stat.setText(text or '')
        self.lbl_stat.setToolTip(text or '')

    # ==========================================
    # 拖动 / 关闭
    # ==========================================
    def _on_drag(self, dx: int, dy: int) -> None:
        """标题栏拖动：**只搬自己**，并把位移交给主窗口累加进 `hub_ui.offset`。"""
        self.move(self.x() + dx, self.y() + dy)
        self.sig_dragged.emit(int(dx), int(dy))

    def _on_close(self) -> None:
        self.hide()
        self.sig_closed.emit()
