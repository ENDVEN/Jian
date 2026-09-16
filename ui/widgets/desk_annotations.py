# ui/widgets/desk_annotations.py
"""✎ 用户标注（画线）行为（1.23 自 `ui/views/trading_desk.py` 拆出 · §7-B6 STEP 6）。

【职责】选工具 / 添加 / 逐个删除 / 清空 + 面板回执（"现在能画什么、已画了几条"）。
真正的持久化与图元管理在 `ui/widgets/annotation_layer.py`（管线 B），本模块**只做交互编排**。

【工具清单不手写第二份】分段控件的短标签由 `KIND_LABELS` 派生 —— 交互层加了新类型，
这里自动跟上（§10-7：口径不重复）。

【约定】状态留页面（`_annotations`、`current_symbol/current_period`、
`seg_tool`、`lbl_annotation_status`、`lbl_anno_pill`、`btn_delete_annotation`），
本模块只承载行为，读写一律走 `self.page.X`。
"""
from PyQt6.QtWidgets import QInputDialog, QMessageBox

from core.utils import period_label
from data.annotations import KIND_LABELS, KIND_TEXT
from ui.widgets.annotation_layer import DRAWABLE_KINDS

# 画线工具的分段控件（★STEP 4：从工具行搬进「✎ 标注」页；类型清单仍与交互层同源）。
# 分段控件窄，所以用短标签；**完整名以 `KIND_LABELS` 为准**（不手写第二份口径）。
_TOOL_SHORT_LABELS = {"trend": "趋势", "hline": "水平", "vline": "垂直",
                      "fib": "斐波", "text": "文字"}
TOOL_SEGMENTS = (("", "浏览"),) + tuple(
    (kind, _TOOL_SHORT_LABELS.get(kind, KIND_LABELS.get(kind, kind)))
    for kind in DRAWABLE_KINDS)


class DeskAnnotations:
    """画线工具的交互与回执（页面持状态，本类持行为）。"""

    def __init__(self, page):
        self.page = page

    # ==========================================
    # 选工具
    # ==========================================
    def select_tool(self, kind: str) -> None:
        """选画线工具（分段控件与测试**同一入口**）。空串 = 浏览（不新建）。"""
        p = self.page
        kind = str(kind or "")
        if kind and kind not in DRAWABLE_KINDS:
            return
        if not p.seg_tool.set_current(kind):
            return
        self._apply_tool(kind)

    def _on_tool_clicked(self, kind: str) -> None:
        self._apply_tool(str(kind))

    def _apply_tool(self, kind: str) -> None:
        p = self.page
        if p._annotations is None:
            return          # 构造期：本页先于图表区建好，容忍 layer 尚未就绪
        p._annotations.set_tool(kind)
        self._refresh_annotation_status()

    def _reset_tool(self):
        """Esc：回到浏览模式（避免误触在图上画出线）"""
        self.select_tool("")

    # ==========================================
    # 增 / 删 / 清空
    # ==========================================
    def add_annotation(self):
        """按当前工具在可视窗口放一条标注；拖好后**松手自动保存**。"""
        p = self.page
        if p._annotations is None:
            return
        tool = p._annotations.tool
        if not tool:
            QMessageBox.information(
                p, "先选择类型",
                "请在左侧「🛠 标注工具」里选择要画的类型"
                "（趋势线 / 水平线 / 垂直线 / 斐波那契 / 文字），再点「➕ 添加标注」。")
            return
        text = ""
        if tool == KIND_TEXT:
            text, ok = QInputDialog.getText(p, "文字标注", "要显示的文字：")
            if not ok:
                return
            if not str(text or "").strip():
                QMessageBox.information(p, "内容为空", "文字标注需要填写内容。")
                return
        if p._annotations.create_default(tool, text=text) is None:
            QMessageBox.information(p, "无法添加",
                                    "请先查阅一个标的并加载出 K 线，再添加标注。")
            return
        self._refresh_annotation_status()

    def delete_selected_annotation(self):
        """删除**当前选中**的那一条（逐个独立删除是管线 B 的硬要求）。"""
        p = self.page
        if p._annotations is None:
            return
        if not p._annotations.selected_id:
            self._refresh_annotation_status(hint="先在图上点一下要删除的线（变橙色=已选中）")
            return
        p._annotations.delete_selected()
        self._refresh_annotation_status()

    def clear_annotations(self):
        """清空当前 (标的, 周期) 的全部标注 —— 不可逆，先二次确认（§10-10）。"""
        p = self.page
        if p._annotations is None:
            return
        total = p._annotations.count()
        if not total:
            self._refresh_annotation_status()
            return
        answer = QMessageBox.question(
            p, "清空标注",
            f"确定删除 {p.current_symbol}（{period_label(p.current_period)}）"
            f"的全部 {total} 条标注吗？\n"
            f"此操作不可撤销（其它标的/周期的标注不受影响）。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            p._annotations.clear_all()
            self._refresh_annotation_status()

    # ==========================================
    # 回执（★STEP 5：一行摘要 + tooltip 详解）
    # ==========================================
    def _refresh_annotation_status(self, hint: str = ""):
        """面板回执：当前工具 + 本周期已存条数 + 下一步该干嘛（也是 layer 的 on_changed）"""
        p = self.page
        if p._annotations is None:
            return
        total = p._annotations.count()
        tool = p._annotations.tool_label()
        period = period_label(p.current_period)
        # ★STEP 5：**一行摘要**（选项 + 条数），操作说明与存储位置进 tooltip
        if hint:
            text = hint
        elif tool:
            text = f"工具：{tool} · {period} 已存 {total} 条"
        elif total:
            text = f"{period} 已存 {total} 条 · 点线选中，Delete 删除"
        else:
            text = f"{period} 暂无标注"
        p.lbl_annotation_status.setText(text)
        p.lbl_annotation_status.setToolTip(
            f"{text}\n"
            "—— 拖线 / 拖端点调整，**松手自动保存**；点线条选中（变橙）后按 Delete 删除。\n"
            "标注按「标的 + 周期」保存在 ~/.jian_data/annotations.json，每条独立可删；\n"
            "坐标按日期锚定 ⇒ 重渲染 / 增量更新 / 前复权修正都不会让它跑偏。")
        # ★STEP 3b：顶栏 2 行的"标注条数"胶囊 —— 它就是"管线 B 当前有多少条"的常显摘要
        # （画线工具本身在 STEP 4 会进左栏「✎ 标注」页，顶栏只留这个数字）。
        p.lbl_anno_pill.setText(f"{period}标注 {total} 条")
        p.lbl_anno_pill.setToolTip(
            f"当前标的 · {period}：已存 {total} 条标注\n"
            "标注按「标的 + 周期」分开保存：分钟画的线不会跑到日线上。")
        p.btn_delete_annotation.setEnabled(bool(p._annotations.selected_id))
