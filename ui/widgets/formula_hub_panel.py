# ui/widgets/formula_hub_panel.py
"""ƒ 函数总库的**统一浮窗**（★1.61 / §7-B16 · 设计稿 = `design/1.60-formula-hub/b-全局浮窗`）。

【它是什么】M1 / M2·M3 / 行情页**共用的一个入口**（各页只留一个「ƒ 库」按钮）。浮窗里两区：

  · **ƒ 函数** —— 列表 / 详情 / 紧凑编辑（`hub_float_fn.FloatFunctionPane`）；
    还能「💾 存当前函数」把**页面上正在写的函数**取过来存（不能逼用户跑去总库重抄一遍）。
  · **📚 本页方案** —— 当前页的**策略库 / 筛选方案库**（M1 策略 · M2/M3 筛选方案）：
    载入 / 存为 / 删除。**同一份库、同一张行脸** —— 用户一眼就知道背后是一回事。

【为什么必须"样式统一"】后台早就打通（同一份 `formula_store`），但如果 M1 有自己一排按钮、
M2 有另一排、浮窗又是第三种长相，**用户根本感知不到它们是同一个东西**；
于是"存哪儿了 / 去哪儿找"永远说不清（用户原话：必须统一，否则各自为战）。

【形态与纪律】照 `download_queue_panel`：**主窗口内的 QFrame 浮层**（不是 QDialog）——
  非模态、不进任务栏、随主窗口走、不持有任何线程；位置 / 开合 / 上次选中记 `hub_ui`。
【红线①】没有任何"运行"入口：载入之后跑图 / 跑回测 / 跑扫描都在功能页完成。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QFrame, QGraphicsDropShadowEffect, QHBoxLayout,
                             QLabel, QPushButton, QScrollArea, QStackedWidget,
                             QVBoxLayout, QWidget)

from ui.widgets.custom_widgets import FLAT_QSS, OUTLINE_QSS
from ui.widgets.hub_float_fn import FloatFunctionPane
from ui.widgets.hub_layout import build_plain_row

PANEL_WIDTH = 470
HUB_PANEL_GAP_RIGHT = 18        # 距内容区右缘（与下载浮层同一基准线）
HUB_PANEL_TOP = 20              # 距内容区顶缘 —— 挂右上（下载浮层在右下，互不重叠）

_PANEL_QSS = ("QFrame#HubFloat { background:#FFFFFF; border:1px solid #E4E9F0;"
              " border-radius:12px; }"
              "QLabel { background:transparent; }")
# 两区分段（选中态 = 蓝底白字；未选 = 透明灰字）
_SEG_ON = ("QPushButton { background:#1976D2; color:#FFFFFF; border:none; border-radius:9px;"
           " padding:5px 14px; font-size:12.5px; font-weight:600; }")
_SEG_OFF = ("QPushButton { background:transparent; color:#616B7A; border:none; border-radius:9px;"
            " padding:5px 14px; font-size:12.5px; font-weight:600; }"
            "QPushButton:hover { background:#F2F5F9; }")


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
    """统一浮窗：`ƒ 函数`（三态）+ `📚 本页方案`（策略 / 筛选方案）。"""

    sig_load = pyqtSignal(dict)          # ⤓ 载入到本页（参数 = 资产 dict；路由在主窗口）
    sig_open_hub = pyqtSignal()          # ✏ 去总库编辑（切到 A 页并选中）
    sig_dragged = pyqtSignal(int, int)   # 标题栏拖动：逐次位移（主窗口据此累加偏移并重摆）
    sig_drag_finished = pyqtSignal()     # 松手：此刻才把偏移写进偏好
    sig_closed = pyqtSignal()            # **用户主动点 ✕**（开合记忆据此置 open=False）

    # 两个由主窗口注入的取口（浮窗是跨页的，"当前页是谁"只有主窗口知道）
    draft_provider = None                # () -> 当前页函数草稿 | None
    plan_provider = None                 # () -> {'noun','hint','plans','plan_label','load','save','delete'} | None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('HubFloat')
        self.setStyleSheet(_PANEL_QSS)
        self.setFixedWidth(PANEL_WIDTH)
        self._selected_plan_id = ''
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(31, 36, 48, 40))
        self.setGraphicsEffect(shadow)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(8)

        # ---------- 标题栏（可拖）+ ✕ ----------
        self.head = _DragHeader(self._on_drag, self.sig_drag_finished.emit, parent=self)
        head = QHBoxLayout(self.head)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        title = QLabel('ƒ 函数总库')
        title.setStyleSheet("font-size:13.5px; font-weight:bold; color:#1F2430;")
        head.addWidget(title)
        head.addStretch()
        self.btn_close = QPushButton('✕')
        self.btn_close.setFlat(True)
        self.btn_close.setStyleSheet("QPushButton { color:#8A94A6; border:none; font-size:14px; }"
                                     "QPushButton:hover { color:#1F2430; }")
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setToolTip('收起浮窗（不会改动任何函数；下次不再自动弹出）')
        head.addWidget(self.btn_close)
        root.addWidget(self.head)

        # ---------- 两区分段 ----------
        seg = QHBoxLayout()
        seg.setSpacing(4)
        self.btn_zone_fn = QPushButton('ƒ 函数')
        self.btn_zone_plan = QPushButton('📚 本页方案')
        for btn in (self.btn_zone_fn, self.btn_zone_plan):
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            seg.addWidget(btn)
        seg.addStretch()
        self.lbl_zone = QLabel('')
        self.lbl_zone.setStyleSheet('font-size:11px; color:#8A94A6;')
        seg.addWidget(self.lbl_zone)
        root.addLayout(seg)

        # ---------- 两区内容 ----------
        self.fn = FloatFunctionPane()
        self.fn.draft_provider = lambda: self.draft_provider() if callable(self.draft_provider) else None
        self.fn.sig_load.connect(self.sig_load)
        self.fn.sig_open_hub.connect(self.sig_open_hub)
        self.fn.sig_say.connect(self.say)
        self.zone_stack = QStackedWidget()
        self.zone_stack.addWidget(self.fn)
        self.zone_stack.addWidget(self._build_plan_zone())
        root.addWidget(self.zone_stack, 1)

        # ---------- 回执一行 ----------
        self.lbl_stat = QLabel('')
        self.lbl_stat.setStyleSheet('font-size:11px; color:#8A94A6;')
        self.lbl_stat.setWordWrap(True)
        root.addWidget(self.lbl_stat)

        # ---------------- 接线 ----------------
        self.btn_close.clicked.connect(self._on_close)
        self.btn_zone_fn.clicked.connect(lambda: self.show_zone(0))
        self.btn_zone_plan.clicked.connect(lambda: self.show_zone(1))
        self.btn_plan_load.clicked.connect(self._on_plan_load)
        self.btn_plan_save.clicked.connect(self._on_plan_save)
        self.btn_plan_del.clicked.connect(self._on_plan_del)
        self.show_zone(0)
        self.refresh()

    # ==========================================
    # 方案区（M1 策略 / M2·M3 筛选方案）
    # ==========================================
    def _build_plan_zone(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        self.lbl_plan_title = QLabel('')
        self.lbl_plan_title.setStyleSheet('font-size:12.5px; font-weight:600; color:#20242C;')
        outer.addWidget(self.lbl_plan_title)
        self.lbl_plan_hint = QLabel('')
        self.lbl_plan_hint.setStyleSheet('font-size:11px; color:#8A94A6;')
        self.lbl_plan_hint.setWordWrap(True)
        outer.addWidget(self.lbl_plan_hint)

        host = QWidget()
        self.plan_lay = QVBoxLayout(host)
        self.plan_lay.setContentsMargins(0, 0, 0, 0)
        self.plan_lay.setSpacing(6)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

        acts = QHBoxLayout()
        acts.setSpacing(6)
        self.btn_plan_load = QPushButton('📚 载入')
        self.btn_plan_load.setStyleSheet(FLAT_QSS)
        self.btn_plan_load.setToolTip('把选中方案整体还原进当前页（函数 + 条件 / 阈值 / 区间）')
        self.btn_plan_save = QPushButton('💾 存为')
        self.btn_plan_save.setStyleSheet(FLAT_QSS)
        self.btn_plan_save.setToolTip('把当前页的配置存成命名方案（同名覆盖）')
        self.btn_plan_del = QPushButton('🗑 删除')
        self.btn_plan_del.setStyleSheet(FLAT_QSS)
        self.btn_plan_del.setToolTip('删除选中方案（会二次确认）')
        for btn in (self.btn_plan_load, self.btn_plan_save, self.btn_plan_del):
            acts.addWidget(btn)
        acts.addStretch()
        outer.addLayout(acts)
        return page

    def refresh_plans(self, keep: str = '') -> None:
        """重建方案列表（页面切换 / 切子页签时由主窗口调用）。"""
        api = self.plan_provider() if callable(self.plan_provider) else None
        lay = self.plan_lay
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if not api:
            self.lbl_plan_title.setText('本页没有方案库')
            self.lbl_plan_hint.setText('方案区只对「📐 市场回测」里的 M1 单股回测 / M2 全市场筛选 / '
                                       'M3 广度统计有效 —— 请切到那边再打开本浮窗。')
            for btn in (self.btn_plan_load, self.btn_plan_save, self.btn_plan_del):
                btn.setEnabled(False)
            lay.addStretch()
            return
        for btn in (self.btn_plan_load, self.btn_plan_save, self.btn_plan_del):
            btn.setEnabled(True)
        noun = str(api.get('noun') or '方案')
        plans_fn = api.get('plans')
        plans = plans_fn() if callable(plans_fn) else []
        self.lbl_plan_title.setText(f'{noun}库（{len(plans)} 条）')
        self.lbl_plan_hint.setText(str(api.get('hint') or ''))
        ids = {str(p.get('id')) for p in plans}
        if keep:
            self._selected_plan_id = keep
        elif self._selected_plan_id not in ids:
            self._selected_plan_id = str(plans[0].get('id')) if plans else ''
        if not plans:
            empty = QLabel(f'还没有保存过{noun} —— 在页面上配好之后点「💾 存为」。')
            empty.setWordWrap(True)
            empty.setStyleSheet('font-size:11.5px; color:#8A94A6;')
            lay.addWidget(empty)
        label_of = api.get('plan_label')
        for plan in plans:
            pid = str(plan.get('id'))
            meta = label_of(plan) if callable(label_of) else ''
            lay.addWidget(build_plain_row(pid, str(plan.get('name') or '未命名'), meta,
                                          self._select_plan, pid == self._selected_plan_id))
        lay.addStretch()

    def _select_plan(self, plan_id: str) -> None:
        self._selected_plan_id = plan_id
        self.refresh_plans(keep=plan_id)

    def _plan_api(self):
        return self.plan_provider() if callable(self.plan_provider) else None

    def _on_plan_load(self) -> None:
        api = self._plan_api()
        if not api or not self._selected_plan_id:
            return
        noun = str(api.get('noun') or '方案')
        ok = api['load'](self._selected_plan_id)
        self.say(f'📚 已载入{noun}' if ok else f'⚠ 没能载入这个{noun}（可能已被删除）')
        self.refresh_plans()

    def _on_plan_save(self) -> None:
        api = self._plan_api()
        if not api:
            return
        api['save']()                     # 名字输入 / 空内容提示都在各自的桥接里（同一实现）
        self.refresh_plans()

    def _on_plan_del(self) -> None:
        api = self._plan_api()
        if not api or not self._selected_plan_id:
            return
        noun = str(api.get('noun') or '方案')
        ok = api['delete'](self._selected_plan_id)
        self.say(f'✅ 已删除{noun}' if ok else f'⚠ 没删除（可能取消或被拒绝）')
        self._selected_plan_id = ''
        self.refresh_plans()

    # ==========================================
    # 分区切换 / 回执
    # ==========================================
    def show_zone(self, index: int) -> None:
        index = 1 if index else 0
        self.zone_stack.setCurrentIndex(index)
        self.btn_zone_fn.setChecked(index == 0)
        self.btn_zone_plan.setChecked(index == 1)
        self.btn_zone_fn.setStyleSheet(_SEG_ON if index == 0 else _SEG_OFF)
        self.btn_zone_plan.setStyleSheet(_SEG_ON if index == 1 else _SEG_OFF)
        self.lbl_zone.setText('函数资产（全站唯一真源）' if index == 0 else '当前页的方案 / 策略')
        if index == 1:
            self.refresh_plans(keep=self._selected_plan_id)

    def say(self, text: str) -> None:
        self.lbl_stat.setText(text or '')
        self.lbl_stat.setToolTip(text or '')

    # ==========================================
    # 拖动 / 关闭（位置与开合的入口）
    # ==========================================
    def _on_drag(self, dx: int, dy: int) -> None:
        """标题栏拖动：**只搬自己**，并把位移交给主窗口累加进 `hub_ui.offset`。"""
        self.move(self.x() + dx, self.y() + dy)
        self.sig_dragged.emit(int(dx), int(dy))

    def _on_close(self) -> None:
        self.hide()
        self.sig_closed.emit()

    # ==========================================
    # 对外（主窗口用）
    # ==========================================
    def refresh(self, keep: str = None) -> None:
        self.fn.refresh(keep=keep)

    def select(self, asset_id: str) -> None:
        self.show_zone(0)
        self.fn.select(asset_id)

    def selected_id(self) -> str:
        return self.fn.selected_id()

    def begin_save_current(self, draft: dict) -> None:
        """把当前页的函数草稿预填进「ƒ 函数」区的编辑器（主窗口路由进来）。"""
        self.show_zone(0)
        self.fn.begin_save_current(draft)
