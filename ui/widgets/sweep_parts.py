# ui/widgets/sweep_parts.py
"""
🧪 参数研究 —— **表单构件原语**（★R2 拆件）。

左栏由三件组成：`sweep_form`（口径/网格/区间的编排）、`sweep_run_form`（⑤ 门槛 + ⑥ 运行）、
本件（两边共用的**构件原语**：提示行 / 节标题 / 步号徽标 / 分隔线 / 可收缩包装）。

【为什么单独成件】原语本来长在 `sweep_form.py` 里，拆出运行面板后两边都要用 ⇒ 若各留一份
就是两份版式纪律（§10-9 单一出口）。这里**保留原名**（`_hint` / `_sep` / `_shrink` /
`_step_title` / `_title`）再导出 ⇒ `sweep_form.py` 里几十处调用点一行都不用改。

【纪律】样式常量一律从 `ui.widgets.styles` 取（不就地写 QSS）；定宽面板里的控件都必须
`_shrink`（横向 Ignored），否则 306px 会出现横向滚动条（§10-14）。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QSizePolicy, QWidget)

from ui.widgets.styles import (PANEL_CARD_QSS, PANEL_HEAD_QSS, SEC_HINT_QSS,
                              SEC_META_QSS, SEC_TITLE_QSS, STEP_BADGE_QSS,
                              WARN_HINT_QSS)

__all__ = ["_hint", "_sep", "_shrink", "_step_title", "_title", "_warn",
           "_widen_popup", "panel_card", "panel_head"]


def panel_card() -> QFrame:
    """白卡（`PANEL_CARD_QSS` 的**唯一出口**）—— 全 app 的卡只有这一种长相（★R1）。

    ⚠ 页面不许再自造卡：`QFrame()` + 自己 `setStyleSheet` 会立刻和 M1/M2/M3 漂成两种观感
      （§11.5-112 同族：同一个零件三处三张脸）。
    """
    f = QFrame()
    f.setObjectName("panelCard")
    f.setStyleSheet(PANEL_CARD_QSS)
    return f


def panel_head(title: str, meta: str = "") -> QFrame:
    """卡片头条（标题 + 灰色说明）—— 需要右侧控件时 `head.layout().addWidget(btn)`。

    返回的 `QFrame` 上挂着 `title_label` / `meta_label` 两个把手（调用方要改文字时用它们，
    别去按索引摸 layout 里的第 0 个控件）。
    """
    head = QFrame()
    head.setObjectName("panelHead")
    head.setStyleSheet(PANEL_HEAD_QSS)
    lay = QHBoxLayout(head)
    lay.setContentsMargins(12, 7, 12, 7)
    head.title_label = _title(title)
    head.meta_label = QLabel(str(meta or ""))
    head.meta_label.setStyleSheet(SEC_META_QSS)
    lay.addWidget(head.title_label)
    lay.addWidget(head.meta_label, 1)
    return head


def _hint(text: str = "") -> QLabel:
    """灰色提示行（会换行）。可选初值 —— 与 `_title(text)` 同形，免得两处调用两种写法。"""
    lab = QLabel(str(text or ""))
    lab.setStyleSheet(SEC_HINT_QSS)
    lab.setWordWrap(True)
    return lab


def _shrink(w: QWidget) -> QWidget:
    """横向可收缩（Ignored）—— 306px 定宽面板里不许出现横向滚动条（§10-14 版式纪律）。"""
    w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    return w


def _warn(text: str = "") -> QLabel:
    """**拦住提示行**（橙底警告样式）：闸门拒绝、参数不合规这类"必须看得见"的话放这里。

    ★用户 2026-10-01 实测：网格被拒只在灰字里说 ⇒ "我怎么点都没反应"。灰字等于没说。
    """
    lab = QLabel(str(text or ""))
    lab.setStyleSheet(WARN_HINT_QSS)
    lab.setWordWrap(True)
    lab.setVisible(bool(str(text or "").strip()))
    return lab


def _widen_popup(cb, min_px: int = 420) -> None:
    """把下拉**弹层**加宽（默认弹层与控件同宽 ⇒ 长标签后半截看不见，用户实测）。

    ⚠ 只改弹层宽度，不改控件本身宽度（306px 定宽面板的版式纪律不受影响）。
    """
    view = cb.view()
    if view is not None:
        view.setMinimumWidth(int(min_px))


def _title(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet(SEC_TITLE_QSS)
    return lab


def _step_title(no: int, text: str) -> QWidget:
    """节标题 = 步号徽标 + 粗体标题（设计稿 `.step-no` + `.sec h4`）。"""
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    badge = QLabel(str(no))
    badge.setStyleSheet(STEP_BADGE_QSS)
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(badge)
    lay.addWidget(_title(text))
    lay.addStretch(1)
    return row


def _sep() -> QFrame:
    """节间浅分隔线（设计稿 `.sec` 的 dashed border 的 Qt 近似）。"""
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet("QFrame { background: #F2F5F9; border: none; }")
    return line
