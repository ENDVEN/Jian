# ui/widgets/annotation_draw_session.py
"""「在图上点出来」的**绘制会话**（v6.26 · §7-B9 STEP 1）—— 纯交互状态机，零业务。

【为什么要这个文件】v6.25 及以前的流程是「点类型 → 点➕ → 先生成一条默认线 → 用户再拖端点」。
用户的实测反馈（原话）：
    **"需要精确定位的线，用户往往需要自行确认起点和终点还有方向，
      现在直接添加标注会直接在图上生成一个默认的线，这个完全是不符合用户体验的"**
⇒ 现在改成：**点类型 → 在图上依次点锚点 → 点够就成**。本文件就是这个状态机。

【四条已拍板的语义（不得擅自回退）】
  ① **画完立刻回浏览模式**（"画完直接回到浏览模式必须防止手残"）⇒ 不做连续绘制；
  ② 绘制时点到**已有标注 = 落点**（不算选中），且**允许点位重合** ⇒ 不许写去重逻辑；
  ③ **Esc / 右键 = 取消**，不留任何东西（含预览）；
  ④ 锚点数直接读 `ShapeSpec.points` ⇒ **加新类型不用改本文件**。

【零业务】不碰存储、不认识具体画法：落库交给 `AnnotationLayer.commit_draw()`，
预览图元直接复用规格表 `shapes.build_annotation()`（画成什么样，预览就是什么样）。
"""
from __future__ import annotations

from data.annotations import KIND_LABELS

from ui.widgets.annotation_items import PREVIEW_COLOR  # noqa: E402,F401
# ⚠ 预览的颜色与"一律虚线"都收敛在视觉件里（`annotation_items.PREVIEW_COLOR` +
#   `AnnotationLayer._preview_pen`）：预览必须和"已存标注"一眼可分。


class DrawSession:
    """一次"点出来"的生命周期：`armed → drawing → done / cancel`。

    :param layer: `ui.widgets.annotation_layer.AnnotationLayer`（ duck typing，不反向 import）
    """

    def __init__(self, layer):
        self._layer = layer
        self._kind = ""
        self._points: list = []          # [[日期, 价], ...] 已落的锚点
        self._cursor: list | None = None  # 鼠标当前位置（补成"最后一个锚点"画预览）
        self._preview: list = []          # 预览图元（与主图元一起无条件清理）
        self._active = False

    # ==========================================
    # 状态
    # ==========================================
    @property
    def active(self) -> bool:
        return self._active

    @property
    def kind(self) -> str:
        return self._kind if self._active else ""

    @property
    def placed(self) -> int:
        return len(self._points)

    def needed(self) -> int:
        """还差几个锚点（0 = 下一次点击就成）。"""
        spec = self._layer.spec_of(self._kind) if self._active else None
        return 0 if spec is None else max(spec.points - len(self._points), 0)

    def hint(self) -> str:
        """分步提示（状态栏用的**人话**，§10-10：不许甩术语）。"""
        if not self._active:
            return ""
        name = KIND_LABELS.get(self._kind, self._kind)
        total = self._layer.spec_of(self._kind).points
        done = len(self._points)
        steps = {0: "起点", 1: "终点", 2: "宽度", 3: "第 4 点", 4: "第 5 点"}
        next_step = steps.get(done, f"第 {done + 1} 点")
        if total == 1:
            return f"{name}：在图上点一下放在哪"
        return f"{name}：第 {done + 1}/{total} 步 —— 点{next_step}（Esc 取消）"

    # ==========================================
    # 生命周期
    # ==========================================
    def arm(self, kind: str) -> bool:
        """进入绘制态（选了类型就等着用户在图上点）。"""
        if self._layer.spec_of(kind) is None:
            return False
        self.cancel()
        self._kind = str(kind)
        self._points = []
        self._cursor = None
        self._active = True
        # ⚠ 绘制期必须让已有标注**不吃鼠标**，否则"点在旧线上"会没反应（§7-B9 C1 要点④）
        self._layer.set_annotations_mouse_enabled(False)
        return True

    def cancel(self) -> None:
        """取消（Esc / 右键 / 切工具）：预览与已落锚点全部丢弃，不留任何东西。"""
        self._clear_preview()
        was_active = self._active
        self._kind = ""
        self._points = []
        self._cursor = None
        self._active = False
        if was_active:
            self._layer.set_annotations_mouse_enabled(True)

    # ==========================================
    # 鼠标
    # ==========================================
    def on_move(self, date_label: str, price: float) -> None:
        """鼠标移动 ⇒ 更新预览（橡皮筋）。"""
        if not self._active:
            return
        self._cursor = [date_label, price]
        self._refresh_preview()

    def on_click(self, date_label: str, price: float, *, cancel_button: bool = False):
        """图上点击。

        :param cancel_button: 右键（取消）
        :return: 落库成功的标注对象；没点够 / 取消 / 用户放弃 ⇒ None
        """
        if not self._active:
            return None
        if cancel_button:
            self.cancel()
            return None
        # ② **允许点位重合**：不做任何"与上一点太近就忽略"的自以为是的手脚
        self._points.append([str(date_label)[:10], float(price)])
        if self.needed() > 0:
            self._cursor = [date_label, price]
            self._refresh_preview()
            return None
        return self._finish()

    # ==========================================
    # 内部
    # ==========================================
    def _finish(self):
        """点够锚点 ⇒ 落库 + 立刻回到浏览模式（① 防手残）。"""
        kind, points = self._kind, list(self._points)
        self.cancel()                                   # 先收干净（含恢复已有标注的鼠标）
        item = self._layer.commit_draw(kind, points)
        self._layer.finish_draw()                       # 通知页面回到浏览模式
        return item

    def _refresh_preview(self) -> None:
        """预览 = 用"已落锚点 + 鼠标当前位置"造一条**临时**标注来画。

        复用规格表 ⇒ 预览长什么样，落库后就长什么样（不会出现"预览是直线、落库变扇形"）。
        """
        self._clear_preview()
        if not self._active or self._cursor is None or self.needed() == 0:
            return
        spec = self._layer.spec_of(self._kind)
        if spec is None:
            return
        points = list(self._points) + [list(self._cursor)]
        fake = {"kind": self._kind, "points": points, "color": PREVIEW_COLOR,
                "text": "", "id": "__preview__"}
        self._preview = self._layer.draw_preview(fake)

    def _clear_preview(self) -> None:
        if self._preview:
            self._layer.remove_preview(self._preview)
        self._preview = []
