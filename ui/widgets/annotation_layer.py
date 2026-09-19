# ui/widgets/annotation_layer.py
"""用户标注交互层（§7-B3 ④ · P6）—— 画线 / 选中 / **逐个独立删除**。

【职责边界 · 三条纪律】
  1. **只管管线 B**（用户手绘）。公式叠层是管线 A，两者的数据与生命周期**绝不混用**
     （§7-B3 C / §10-12）：本层对象**持久化**到 `(标的, 周期)`，而叠层随参数重算即消失。
  2. 对象模型与持久化在 `data/annotations.py`（零 Qt）；本文件只做"Qt 图元 + 交互"。
     这里**不写 JSON、不碰路径** —— 迁移存储实现时本文件一行都不用改。
  3. 本文件是**全 app 唯一的标注交互入口**：行情页现在用它，将来复盘页回放 / P8 重做
     也复用它，**禁止各页面各写一套**（§9-O7「改一处漏三处」的教训）。

【★v6.25：画法不在这里】
  目录 32 种里已实现的 27 种，画法全部登记在 **`ui/widgets/annotation_shapes.py`**
  （一种类型一个 `ShapeSpec`：画法 / 回读坐标 / 默认落点 / 是否重建附属图元）。
  本文件只做三件事：**画前准备上下文 → 交给规格表 → 存 / 删 / 选中**。
  ⇒ 加一种画线类型**不用改本文件**（§11.5-11「改一处漏一处」的反面教材）。

【图元选型（都挂到 `ChartPane` 的标注容器；选型在规格表里，此处只讲纪律）】
  因为走的是 `add_annotation()`，所以换公式时的 `clear_overlays()` **不会误删标注**，
  重渲染时的 `clear_annotations()` 也**不会碰到公式叠层** —— 两条管线物理隔离。

【★v6.26：怎么"加"一条标注也变了（§7-B9）】
  不再"先生成一条默认线再让用户拖"（用户实测：完全不合体验），改由
  **`ui/widgets/annotation_draw_session.py`** 的绘制会话接管：选类型 ⇒ 在图上依次点锚点
  ⇒ 点够就落库。本层只给它三个口子：`commit_draw()` / `draw_preview()` / `set_annotations_mouse_enabled()`。

【拖动即保存】ROI 用 `sigRegionChangeFinished`、InfiniteLine 用
`sigPositionChangeFinished`：只在**松手后**落盘一次，不在拖动过程中疯狂写文件。
"""
from __future__ import annotations

import logging

import pyqtgraph as pg
from PyQt6.QtCore import Qt

from data.annotations import (AUTO_TEXT_KINDS, DEFAULT_COLOR, KIND_LABELS, PERIOD_DAILY,
                              AnnotationStore, DateAxis, initial_text, make_annotation,
                              price_text, requires_text)
from ui.widgets import annotation_shapes as shapes
from ui.widgets.annotation_draw_session import DrawSession
# ⚠ 下面这几个名字**历史上在本文件定义**，既有 import（含冒烟脚本）仍从此处取 ⇒ 再导出一份，
#    真源已搬到 `annotation_items`（§11.7：公共面改名会立刻红，所以只搬实现不改名）。
from ui.widgets.annotation_items import (FIB_COLORS, FIB_LEVEL_WIDTH,  # noqa: F401
                                         LINE_WIDTH, PREVIEW_COLOR, SELECTED_COLOR,
                                         SELECTED_WIDTH, TRENDLINE_SPAN, _ClickableText,
                                         pixel_scale)

logger = logging.getLogger(__name__)

# 工具栏可创建的标注类型（**唯一事实来源 = 规格表**；目录的 `implemented` 必须与它一致）
DRAWABLE_KINDS = shapes.DRAWABLE_KINDS

# 拾取标注时允许的像素误差（1px 的细线肉眼根本点不中，§11.5-51）
HIT_TOLERANCE = 6.0


class AnnotationLayer:
    """把「某标的 + 某周期」的用户标注画到一个图表宿主上，并提供增删交互。

    :param host:  `ui/widgets/chart_host.py` 的 ChartHost（标注固定落在**主图**上）
    :param store: `data/annotations.py` 的 AnnotationStore
    :param on_changed: 内容变化回调（页面据此刷新"N 条标注"回执）
    :param ask_text: 需要用户填文字时（文字 / 评论气泡）的提问口子 `(kind) -> str | None`；
                     **None 由页面给**（本层不持 QWidget，不负责弹窗）。返回 None = 用户放弃
    :param on_finished: 画完一条后的回调（页面据此**回到浏览模式**，§7-B9 拍板① 防手残）
    """

    def __init__(self, host, store: AnnotationStore, *, period: str = PERIOD_DAILY,
                 on_changed=None, ask_text=None, on_finished=None):
        self._host = host
        self._store = store
        self._period = str(period or PERIOD_DAILY)
        self._on_changed = on_changed
        self._ask_text = ask_text
        self._on_finished = on_finished
        self._symbol = ""
        self._axis = DateAxis([])
        self._tool = ""          # 当前工具（'' = 浏览模式，不新建）
        self._selected = ""
        self._items: dict = {}   # id -> 主图元（可拖/可点选的那一个）
        self._extras: dict = {}  # id -> [附属图元]（斐波那契的各档水平位与标签）
        # ★v6.26 绘制会话（§7-B9 STEP 1）
        self._session = DrawSession(self)
        self._closes = None              # 收盘价序列（只有回归通道用，`bind()` 喂进来）
        self._mouse_muted = False          # 绘制期：已有标注不吃鼠标
        self._saved_buttons: dict = {}     # 图元 -> 它原本接受的鼠标键（恢复时用）
        self._view_hooks: dict = {}        # id -> 缩放重算的钩子（"依赖视图"的类型）
        self._view_scale = (0.0, 0.0)     # 上次重算时的像素比例（节流用）
        self._scene_hooked = None          # 已挂信号的场景对象（None = 还没挂）

    # ==========================================
    # 绑定 / 渲染
    # ==========================================
    def bind(self, symbol: str, dates, period: str = None, closes=None) -> int:
        """切换标的 / 周期 / 数据窗口后重新绑定并重绘，返回画出的条数。

        每次重渲染都调它 —— 标注**从存储里读回来重画**，所以"切走再切回"不会丢。

        :param period: 给出则一并切换周期（行情工作台的日/周/月）。
            标注按 `(标的, **周期**)` 分开存是本项目的既定设计（§7-B3 P6）：
            日线上画的线不该出现在周线上 —— 两种周期的横轴根本不是同一批 bar。
        :param closes: 收盘价序列（**只有回归通道要用**，§7-B9 STEP 4）。
            与 §7-B6 STEP 5「读数条只认本次渲染的那份 df」同一条纪律 —— 不另开数据链路。
        """
        self._symbol = str(symbol or "")
        if period:
            self._period = str(period)
        # ⚠ 不能写 `dates or []`：dates 常直接来自 `df['date']`（Series），布尔求值会抛异常
        self._axis = DateAxis(dates if dates is not None else [])
        self._closes = list(closes) if closes is not None else None
        self._session.cancel()          # 换标的/周期 ⇒ 手上没点完的半截绘制直接作废
        self._selected = ""
        self._hook_scene()              # 场景信号要等图表真的建好才挂得上（幂等）
        return self.render()

    def render(self) -> int:
        """按当前绑定从存储读全量并重画（幂等，可安全重复调用）。"""
        self.clear_view()
        drawn = 0
        for item in self._store.list(self._symbol, self._period):
            if self._draw_item(item) is not None:
                drawn += 1
        if self._selected and self._selected in self._items:
            self._highlight(self._selected)
        return drawn

    def clear_view(self) -> None:
        """只清"画在图上的东西"，**不动存储**（重渲染 / 切标的时用）。"""
        pane = self._host.main_pane
        for item_id in list(self._items):
            self._forget(item_id)
        self._items.clear()
        self._extras.clear()
        self._saved_buttons.clear()

    def _forget(self, item_id: str) -> None:
        """把一个标注的**主图元 + 全部附属图元**从窗格摘掉（图元与容器必须同步，§11.5-15）。"""
        pane = self._host.main_pane
        graphic = self._items.pop(item_id, None)
        if graphic is not None:
            self._saved_buttons.pop(graphic, None)
            pane.remove_annotation(graphic)
        for extra in self._extras.pop(item_id, []):
            self._saved_buttons.pop(extra, None)
            pane.remove_annotation(extra)
        # "依赖视图"的类型：摘掉时必须**断掉**缩放钩子（否则缩放时会对着已删图元重算）
        hook = self._view_hooks.pop(item_id, None)
        if hook is not None:
            try:
                self._host.main_pane.view_box.sigRangeChanged.disconnect(hook)
            except (TypeError, RuntimeError):
                pass

    # ==========================================
    # 工具与新建（★v6.26：新建 = 在图上点出来）
    # ==========================================
    @property
    def tool(self) -> str:
        return self._tool

    @property
    def drawing(self) -> bool:
        """是不是正在"点出来"的过程中（页面据此显示分步提示）。"""
        return self._session.active

    def session_hint(self) -> str:
        """绘制中的分步提示（人话，§10-10）。"""
        return self._session.hint()

    def set_tool(self, kind: str) -> None:
        """选工具 —— **全 app 唯一入口**（目录 tile / 数字键 / Esc 都走这里）。

        ★v6.26：选中即**进入绘制态**（用户随后在图上点锚点）；空串 = 浏览模式（顺带取消绘制）。
        """
        self._tool = str(kind or "")
        if self._tool:
            # ★自愈：`bind()` 时图表可能还没建好（那时 `scene()` 是 None ⇒ 信号挂不上），
            #   用户点工具的这一刻是**最后的机会** —— 不补挂就会"点了没反应"且不报错。
            self._hook_scene()
            self._session.arm(self._tool)
        else:
            self._session.cancel()

    def commit_draw(self, kind: str, points) -> dict | None:
        """绘制会话点够锚点后的**落库**（唯一的"新建"出口，§7-B9 STEP 1）。

        :param points: 用户点出来的 `[[日期, 价], ...]`（已是真实坐标，不再是"默认落点"）
        """
        kind = str(kind or "")
        if kind not in DRAWABLE_KINDS or not self._symbol or not points:
            return None
        text = ""
        if requires_text(kind):
            text = self._ask_text(kind) if callable(self._ask_text) else ""
            if text is None:            # 用户在输入框点了取消 ⇒ 不落库、不留东西
                return None
        try:
            # ★v6.29：有的类型主图元是**算出来的**（回归通道的中线 = 对收盘价回归的结果）
            #   ⇒ 落库前先把"点出来的锚点"规范化成存储口径。⚠ 必须是**纯计算**：
            #   图元刚加进场景时 Qt 还没重算它的场景变换，这时候去"回读图元"会读到
            #   过期坐标（实测：把 104 读成了 13089 —— §11.5-53 的第二个坑）。
            spec = shapes.spec_of(kind)
            if spec is not None and spec.normalize is not None:
                ctx = self._ctx({"id": "", "kind": kind, "points": points,
                                 "color": DEFAULT_COLOR})
                normalized = spec.normalize(ctx, points) if ctx is not None else None
                if normalized:
                    points = normalized
            item = self._store.upsert(make_annotation(
                self._symbol, kind, points, period=self._period, text=text))
        except ValueError as e:  # 锚点/文字非法 → 不落库（绝不存一条画不出来的记录）
            logger.warning(f"新建标注失败: {e}")
            return None
        self.render()
        self.select(item["id"])
        self._notify()
        return item

    def finish_draw(self) -> None:
        """画完一条 ⇒ 通知页面**回到浏览模式**（用户拍板：必须防手残）。"""
        if callable(self._on_finished):
            self._on_finished()

    # ---- 绘制会话需要的三个口子 ----
    def spec_of(self, kind: str):
        """规格表查询（会话不 import 规格表，保持它零依赖）。"""
        return shapes.spec_of(kind)

    def draw_preview(self, fake_item: dict) -> list:
        """按"已落锚点 + 鼠标位置"画**临时预览**（画法复用规格表 ⇒ 预览 == 落库后）。

        ⚠⚠ **预览图元一律不许吃鼠标**（v6.27 真事故）：预览的锚点就画在**鼠标当前位置**上
        ⇒ 用户点下去的那一下很可能正落在预览图元（`_ClickableText` 起点标记 / ROI 手柄）上，
        被它 `accept()` 掉之后**场景就不再发 `sigMouseClicked`**（§11.5-42 同一条机制，
        只是那次我只静音了"已有标注"、漏了"预览"）⇒ 表现为"**预览一直跟着光标，
        但怎么点都落不了地**"（用户报"扇形线无法在图片中画出"）。
        """
        ctx = self._ctx(fake_item, preview=True)
        if ctx is None:
            return []
        built = shapes.build_annotation(ctx)
        if built is None:
            return []
        primary, extras = built
        pane = self._host.main_pane
        for graphic in [primary] + list(extras):
            self._mute_preview(graphic)
        pane.add_annotation(primary)
        for extra in extras:
            pane.add_annotation(extra)
        return [primary] + list(extras)

    def remove_preview(self, graphics) -> None:
        """无条件摘掉预览图元（done / cancel 都调，§11.5-15：不留无主图元）。"""
        for graphic in graphics or []:
            try:
                self._host.main_pane.remove_annotation(graphic)
            except Exception:  # noqa: BLE001 —— 预览图元可能已被重渲染带走
                pass

    def set_annotations_mouse_enabled(self, enabled: bool) -> None:
        """绘制期让已有标注**不吃鼠标**。

        ⚠ 为什么必须做（v6.27 用探针实测坐实的机制）：**文字类图元（`pg.TextItem`）在按下时
        `accept()` 掉事件 ⇒ `GraphicsScene` 根本不会发 `sigMouseClicked`**
        （实测：压在文字上 = 收不到；压在 ROI 手柄上 = 收得到，带 `isAccepted=False`）。
        用户已拍板"点到已有的算落点"，所以绘制期间一律让它们闭嘴，结束再逐个还原。
        ⚠ **预览图元同理**（见 `draw_preview`：它正好画在光标下，不静音就永远点不下去）。
        """
        self._mouse_muted = not bool(enabled)
        graphics = list(self._items.values())
        for extras in self._extras.values():
            graphics.extend(extras)
        for graphic in graphics:
            self._mute(graphic, not enabled)

    def _mute_preview(self, graphic) -> None:
        """让**预览图元**彻底不响应鼠标（**不记入 `_saved_buttons`** —— 预览每动一下鼠标
        就重建一批，记进去会把那张表撑爆；它们本来就随预览一起丢弃，不需要还原）。"""
        try:
            graphic.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        except Exception:  # noqa: BLE001 —— 少数图元不支持时忽略
            pass

    def _mute(self, graphic, muted: bool) -> None:
        try:
            if muted:
                self._saved_buttons[graphic] = graphic.acceptedMouseButtons()
                graphic.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            else:
                saved = self._saved_buttons.pop(graphic, Qt.MouseButton.LeftButton)
                graphic.setAcceptedMouseButtons(saved)
        except Exception:  # noqa: BLE001 —— 图元已被摘掉/不是 Qt 图元时忽略
            pass

    # ==========================================
    # 场景信号（绘制会话的输入）
    # ==========================================
    def _hook_scene(self) -> None:
        """挂 `sigMouseClicked` / `sigMouseMoved`（**幂等替换**；图表建好后才挂得上）。

        ⚠ 记住上次挂的场景对象：图表被重建时 `scene()` 会换一个 ⇒ 不换挂就会**挂到旧场景上**
        （表现为"点了没反应"，且不报错）。与 §7-B4 坐标轴自适应的"幂等替换"同一条纪律。
        """
        scene = self._host.main_pane.plot_item.scene()
        if scene is None or scene is self._scene_hooked:
            return
        if self._scene_hooked is not None:
            for signal, slot in ((self._scene_hooked.sigMouseClicked, self._on_scene_click),
                                 (self._scene_hooked.sigMouseMoved, self._on_scene_move)):
                try:
                    signal.disconnect(slot)
                except (TypeError, RuntimeError):
                    pass                            # 旧场景已销毁时忽略
        scene.sigMouseClicked.connect(self._on_scene_click)
        scene.sigMouseMoved.connect(self._on_scene_move)
        self._scene_hooked = scene

    def _on_scene_click(self, event) -> None:
        """图上点击：绘制中 ⇒ 落锚点；浏览中 ⇒ **选中点到的那条标注**。"""
        if not self._session.active:
            # ★v6.28：不再只靠各图元自己的 `sigClicked` —— 那条路有洞（见 `_pick`）。
            if event.button() == Qt.MouseButton.LeftButton:
                item_id = self._pick(event.scenePos())
                if item_id:
                    self.select(item_id)
            return
        view_box = self._host.main_pane.view_box
        try:
            if not view_box.sceneBoundingRect().contains(event.scenePos()):
                return                      # 点在副图上 ⇒ 不落锚点
            view = view_box.mapSceneToView(event.scenePos())
        except Exception:  # noqa: BLE001
            return
        date_label = self._axis.index_to_date(view.x())
        if not date_label:
            return
        cancel = event.button() != Qt.MouseButton.LeftButton
        self._session.on_click(date_label, float(view.y()), cancel_button=cancel)
        self._notify()

    def _pick(self, scene_pos) -> str:
        """点到谁身上了 —— **按画出来的形状判定**，主图元优先、附属图元次之。

        【为什么要自己拾取，不靠图元的 `sigClicked`】三条实测出来的洞（§11.5-51）：
          · `pg.ROI` 默认 `acceptedMouseButtons=NoButton` ⇒ 它的 `sigClicked` **永不发**；
          · `PolyLineROI` 的线段是**子图元**（`LineSegmentROI`），点线段不会走父 ROI 的信号；
          · 附属图元（斐波档位线 / 扇形射线 / 标签）本来就没人给它们挂点击。
        用户的实际期待很朴素：**"点在这条标注的任何一处，都算选中它"**。所以按形状拾取 ——
        形状取自 Qt 图元自己的 `shape()`（线是描边后的路径、带是区域、文字是文字框），
        再按 `HIT_TOLERANCE` 放宽一点（1px 的线肉眼根本点不中）。
        """
        for primary_pass in (True, False):
            for item_id in self._items:
                graphics = [self._items[item_id]] if primary_pass else self._graphics_of(item_id)
                for graphic in graphics:
                    if self._hits(graphic, scene_pos):
                        return item_id
        return ""

    def _graphics_of(self, item_id: str) -> list:
        """一条标注**画在图上的全部图元**：附属图元 + 折线 ROI 的线段子图元。"""
        graphics = list(self._extras.get(item_id, []))
        primary = self._items.get(item_id)
        segments = getattr(primary, "segments", None) if primary is not None else None
        if segments:
            graphics.extend(list(segments))
        return graphics

    def _unit_per_pixel(self) -> tuple:
        """1 像素 = 多少**数据单位**（x / y 分开算）。

        ⚠ 拾取容差必须按**像素**说：图元坐标是数据坐标，"6 个数据单位"在一只
        3 元的票上（y 量程 0.2）等于半屏 —— 那样"点哪儿都算选中"，选谁都错
        （v6.29 自查发现，§11.5-54）。
        """
        try:
            size = self._host.main_pane.view_box.viewPixelSize()
            return (max(float(size[0]), 1e-12), max(float(size[1]), 1e-12))
        except Exception:  # noqa: BLE001 —— 布局还没落定时给一个"不为零"的兜底
            return (1.0, 1.0)

    def _hits(self, graphic, scene_pos) -> bool:
        """`scene_pos` 是否落在这个图元上（含 `HIT_TOLERANCE` **像素**的宽容）。"""
        try:
            local = graphic.mapFromScene(scene_pos)
            unit_x, unit_y = self._unit_per_pixel()
            pad_x, pad_y = HIT_TOLERANCE * unit_x, HIT_TOLERANCE * unit_y
            path = graphic.shape()
            if path.isEmpty():                   # 没有形状（少见）⇒ 包围盒命中就算
                return graphic.boundingRect().adjusted(
                    -pad_x, -pad_y, pad_x, pad_y).contains(local)
            if path.contains(local):
                return True
            if not graphic.boundingRect().adjusted(
                    -pad_x, -pad_y, pad_x, pad_y).contains(local):
                return False
            # 1px 细线在 `contains` 眼里是"零面积"路径，点它身上也是 False ⇒
            # 按两个尺度的均值把它加粗成一个"带"再判（加粗量已换算成数据单位）
            stroker = pg.QtGui.QPainterPathStroker()
            stroker.setWidth(2.0 * HIT_TOLERANCE * (unit_x + unit_y) / 2.0)
            return stroker.createStroke(path).contains(local)
        except Exception:  # noqa: BLE001 —— 图元已被摘掉 / 形状算不出来 ⇒ 当没命中
            return False

    def _on_scene_move(self, pos) -> None:
        """鼠标移动 ⇒ 更新橡皮筋预览。"""
        if not self._session.active:
            return
        view_box = self._host.main_pane.view_box
        try:
            view = view_box.mapSceneToView(pos)
        except Exception:  # noqa: BLE001
            return
        date_label = self._axis.index_to_date(view.x())
        if not date_label:
            return
        self._session.on_move(date_label, float(view.y()))

    def tool_label(self) -> str:
        return KIND_LABELS.get(self._tool, "") if self._tool else ""

    def create_default(self, kind: str = None, *, text: str = "") -> dict | None:
        """在当前**可视窗口**放一条默认标注并落盘（用户随后拖动微调）。

        ⚠ **v6.26 起它不再是用户路径**（§7-B9：用户原话"添加标注直接删除"）——
        用户现在走"在图上点出来"（`commit_draw`）。保留它是因为：
        ① 离屏冒烟需要"不模拟点击也能造一条数据"；② 它同时是"默认落点"的唯一实现。
        **别再给它接任何按钮。**

        :param text: 文字标注的内容（`KIND_TEXT` 必填；空内容会被模型层拒绝）
        :return: 落库后的标注对象；未绑定标的 / 无数据 / 内容非法时返回 None。
        """
        kind = str(kind or self._tool or "")
        if kind not in DRAWABLE_KINDS or not self._symbol:
            return None
        if self._axis.size == 0:
            return None

        (x_min, x_max), (y_min, y_max) = self._view_range()
        spec = shapes.spec_of(kind)
        if spec is None or spec.place is None:
            return None
        # ★v6.25：默认落点由**规格表**回答（一种类型一个落法，本文件不再 if/elif 堆类型）
        place = shapes.PlaceCtx(axis=self._axis, x0=x_min, x1=x_max, y0=y_min, y1=y_max,
                                size=self._axis.size, closes=self._closes)
        points = spec.place(place)
        if not points:
            return None
        # 文字：用户填的由页面给；派生的（价格标签）与符号类（▲/●）由模型层算
        text = text or initial_text(kind, points[0][1])

        try:
            item = self._store.upsert(make_annotation(
                self._symbol, kind, points, period=self._period, text=text))
        except ValueError as e:  # 锚点/文字非法 → 不落库、不画（绝不存一条画不出来的记录）
            logger.warning(f"新建标注失败: {e}")
            return None

        self.render()
        self.select(item["id"])
        self._notify()
        return item

    # ==========================================
    # 选中 / 删除
    # ==========================================
    @property
    def selected_id(self) -> str:
        return self._selected

    def select(self, item_id: str) -> None:
        """选中（空串 = 取消选中）。**逐个独立删除**就靠它定位目标。"""
        self._selected = str(item_id or "")
        for known_id in self._items:
            self._highlight(known_id)
        self._notify()      # 让页面刷新"删除选中"按钮的可用状态

    def delete(self, item_id: str) -> bool:
        """删除**指定**一条标注（存储 + 图元同时移除；复合标注连附属图元一起）。"""
        self._forget(item_id)
        removed = self._store.delete(self._symbol, self._period, item_id)
        if self._selected == item_id:
            self._selected = ""
        self._notify()
        return removed

    def delete_selected(self) -> bool:
        return self.delete(self._selected) if self._selected else False

    def clear_all(self) -> int:
        """清空当前标的的全部标注（页面侧需先向用户二次确认，§10-10）。"""
        removed = self._store.clear(self._symbol, self._period)
        self.clear_view()
        self._selected = ""
        self._notify()
        return removed

    def count(self) -> int:
        return self._store.count(self._symbol, self._period)

    # ==========================================
    # 内部：绘制 / 回写
    # ==========================================
    def _view_range(self):
        view_range = self._host.main_pane.view_box.viewRange()
        return (float(view_range[0][0]), float(view_range[0][1])), \
               (float(view_range[1][0]), float(view_range[1][1]))

    def _x(self, date_label):
        """日期 -> bar 序号；不在轴内返回 None（该条标注本次不画，绝不画到错位置）。"""
        position = self._axis.date_to_index(date_label)
        return None if position is None else float(position)

    def _pen(self, color: str, selected: bool = False, dashed: bool = False):
        return pg.mkPen(color=SELECTED_COLOR if selected else (color or DEFAULT_COLOR),
                        width=SELECTED_WIDTH if selected else LINE_WIDTH,
                        style=pg.QtCore.Qt.PenStyle.DashLine if dashed
                        else pg.QtCore.Qt.PenStyle.SolidLine)

    def _preview_pen(self, color: str, selected: bool = False, dashed: bool = False):
        """预览专用笔：**一律虚线**（"这条还没落地"，与已存标注一眼可分）。"""
        return pg.mkPen(color or PREVIEW_COLOR, width=LINE_WIDTH,
                        style=pg.QtCore.Qt.PenStyle.DashLine)

    def _ctx(self, item: dict, *, preview: bool = False) -> "shapes.DrawCtx | None":
        """准备"画一条标注"的上下文 —— **规格表只吃这个**，它不认识交互层的任何状态。

        :param preview: 画的是**预览**（还没落地）⇒ 一律用虚线笔，与"已存的标注"一眼可分。
        """
        kind = str(item.get("kind") or "")
        spec = shapes.spec_of(kind)
        if spec is None:
            return None
        item_id = str(item.get("id") or "")
        # ★v6.26 H-7：**只要存在附属图元，拖动后就重建**（文字/档位/标签全是锚点的派生物，
        #   不跟着动 = 用户实测的"改了点位文字停原地"）。不再让每种类型自己声明 `rebuild`。
        handler = (lambda: self._rebuild(item_id)) if spec.deco \
            else (lambda: self._persist_from_view(item_id))
        return shapes.DrawCtx(
            kind=kind,
            item=item,
            color=item.get("color") or DEFAULT_COLOR,
            axis=self._axis,
            view_box=self._host.main_pane.view_box,
            size=self._axis.size,
            pen=self._preview_pen if preview else self._pen,
            on_change=handler,
            on_persist=lambda: self._persist_from_view(item_id),
            on_select=lambda: self.select(item_id),
            closes=self._closes)

    def _highlight(self, item_id: str) -> None:
        stored = self._store.get(self._symbol, self._period, item_id) or {}
        graphic = self._items.get(item_id)
        if graphic is None:
            return
        shapes.highlight(graphic, stored.get("color") or DEFAULT_COLOR,
                         item_id == self._selected, self._pen)

    def _draw_item(self, item: dict):
        """按**规格表**画一条标注（主图元 + 附属图元都登记进本层的两个容器）。"""
        ctx = self._ctx(item)
        if ctx is None:
            return None      # 目录里标"待实现"的类型：这里本来就不会被调用到，兜个底
        built = shapes.build_annotation(ctx)
        if built is None:    # 锚点不在当前数据窗口内 ⇒ 本次不画（绝不画到错位置）
            return None
        primary, extras = built
        pane = self._host.main_pane
        pane.add_annotation(primary)
        for extra in extras:
            pane.add_annotation(extra)
        self._items[item["id"]] = primary
        self._extras[item["id"]] = list(extras)
        # ① 绘制期新建的图元也要跟着"闭嘴"（否则用户点第二下会被它吃掉）
        if self._mouse_muted:
            self._mute(primary, True)
            for extra in extras:
                self._mute(extra, True)
        # ② "依赖视图"的类型（甘氏扇形 / 斐波弧）：缩放 ⇒ 重算附属图元
        spec = shapes.spec_of(item.get("kind"))
        if spec is not None and spec.view_dependent:
            self._hook_view_range(item["id"])
        if isinstance(primary, pg.TextItem):
            primary.setToolTip(
                f"{KIND_LABELS.get(item.get('kind'), '标注')}：{item.get('text') or ''}\n"
                "拖动可移动、松手自动保存；点它选中，Delete 删除")
        return primary

    def _hook_view_range(self, item_id: str) -> None:
        """给"依赖视图"的类型挂缩放重算（幂等：同一条只挂一次）。

        与 §7-B4 坐标轴自适应**同一条纪律**：一处挂接、幂等替换，别多处各挂一份。
        """
        if item_id in self._view_hooks:
            return
        hook = lambda *_a, **_k: self._on_view_changed(item_id)  # noqa: E731
        self._host.main_pane.view_box.sigRangeChanged.connect(hook)
        self._view_hooks[item_id] = hook

    def _on_view_changed(self, item_id: str) -> None:
        """缩放/平移后重算依赖视图的画法（**只重画、不落盘** —— 落盘会把缩放变成写文件）。"""
        scale = pixel_scale(self._host.main_pane.view_box)
        # 节流：像素比例变化不到 2% 就跳过（否则每 1px 缩放都重建一遍图元）
        last = self._view_scale
        if last[0] and abs(scale[0] - last[0]) / last[0] < 0.02 \
                and abs(scale[1] - last[1]) / last[1] < 0.02:
            return
        self._view_scale = scale
        self._refresh_deco(item_id)

    def _rebuild(self, item_id: str) -> None:
        """拖动结束 → 回写坐标 → **把主图元贴回它该在的地方** → 重建附属图元。

        ★v6.29：`reshape` 这一步专治"主图元本身是算出来的"类型（回归通道的中线由回归决定）——
        不贴回去就会出现"中线在 A、上下轨在 B"的分裂（§11.5-53）。
        """
        self._persist_from_view(item_id)
        item = self._store.get(self._symbol, self._period, item_id) or {}
        primary = self._items.get(item_id)
        spec = shapes.spec_of(item.get("kind"))
        if primary is not None and spec is not None and spec.reshape is not None:
            ctx = self._ctx(item)
            if ctx is not None:
                spec.reshape(ctx, primary)
        self._refresh_deco(item_id)

    def _refresh_deco(self, item_id: str) -> None:
        """只按存储里的锚点**重画附属图元**（不动存储）—— 拖动后与缩放后共用。"""
        item = self._store.get(self._symbol, self._period, item_id)
        primary = self._items.get(item_id)
        spec = shapes.spec_of((item or {}).get("kind", ""))
        if item is None or primary is None or spec is None or spec.deco is None:
            return
        ctx = self._ctx(item)
        if ctx is None:
            return
        pane = self._host.main_pane
        for extra in self._extras.pop(item_id, []):
            pane.remove_annotation(extra)
        extras = list(spec.deco(ctx, primary) or [])
        for extra in extras:
            pane.add_annotation(extra)
        self._extras[item_id] = extras

    def _persist_from_view(self, item_id: str) -> None:
        """把用户拖动后的**真实坐标**回写到存储（松手后触发一次）。"""
        item = self._store.get(self._symbol, self._period, item_id)
        graphic = self._items.get(item_id)
        if item is None or graphic is None:
            return
        spec = shapes.spec_of(item.get("kind"))
        points = self._points_from_graphic(item, graphic)
        if not points:
            return
        item["points"] = points
        # 文字由坐标派生的类型（价格标签）：价位变了，标签上的字也得跟着变
        if item.get("kind") in AUTO_TEXT_KINDS:
            item["text"] = price_text(points[0][1])
        try:
            self._store.upsert(item)
        except ValueError as e:  # noqa: BLE001 —— 坐标异常时不写坏数据，保留原值
            logger.warning(f"标注回写失败: {e}")
            return
        if item.get("kind") in AUTO_TEXT_KINDS and isinstance(graphic, pg.TextItem):
            graphic.setText(item["text"])
        # 有"回正"规则的类型（水平射线：拖斜了要拉回水平）
        if spec is not None and spec.snap is not None:
            ctx = self._ctx(item)
            if ctx is not None:
                spec.snap(ctx, graphic)
        self._notify()

    def _points_from_graphic(self, item: dict, graphic) -> list | None:
        """图元 → `[[日期, 价], ...]`（**读法也在规格表里**，本文件不认识任何具体类型）。"""
        ctx = self._ctx(item)
        spec = shapes.spec_of(item.get("kind"))
        if ctx is None or spec is None or spec.read is None:
            return None
        try:
            return spec.read(ctx, graphic, self._extras.get(str(item.get("id") or ""), []))
        except Exception as e:  # noqa: BLE001 —— 图元已被摘掉/坐标异常 ⇒ 不写坏数据
            logger.warning(f"标注坐标回读失败: {e}")
            return None

    def _notify(self) -> None:
        if callable(self._on_changed):
            self._on_changed()
