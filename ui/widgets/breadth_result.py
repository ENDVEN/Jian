# ui/widgets/breadth_result.py
"""📊 M3「广度统计」—— 结果区状态（空态 / 忙碌态；L0 的图表本体在 `breadth_chart`）。

【与 M2 `scan_result` 同一套约定】三种空态都给下一步动作（未就绪 / 无数据 / 失败），
**禁止静默**（E 节）；"忙碌"时把上一轮结果收起来，避免被误读成本轮的。
M3 没有 KPI 行与结果表 —— 逐日四态家数全部画在 `breadth_chart` 的广度线上，
口径摘要（有效 N/M · 范围 · 前复权）由 `breadth_flow` 写进标题行的 `lbl_cal`。
"""
from __future__ import annotations

__all__ = ['BreadthResult']


class BreadthResult:
    """结果区状态（只读写 `p.X`，不存状态）。"""

    def __init__(self, page):
        self.page = page

    # ---------- 空态（三种空态都给下一步动作，E 节） ----------
    def set_empty(self, text: str, action_text: str = '', on_action=None) -> None:
        p = self.page
        p.lbl_empty.setText(text)
        p.empty_box.show()
        p.chart.hide()
        if action_text:
            p.btn_empty_action.setText(action_text)
            p.btn_empty_action.show()
            try:
                p.btn_empty_action.clicked.disconnect()
            except TypeError:
                pass                            # 本来就没连过
            if on_action is not None:
                p.btn_empty_action.clicked.connect(on_action)
        else:
            p.btn_empty_action.hide()

    def set_busy(self, text: str) -> None:
        """扫描中：结果区收起（避免上一轮结果被误读成本轮的）。"""
        self.page.lbl_empty.setText(text)
        self.page.empty_box.show()
        self.page.chart.hide()
