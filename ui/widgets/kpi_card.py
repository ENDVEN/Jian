# ui/widgets/kpi_card.py
"""
小号 KPI 卡的**唯一实现**（★R1：从 `scan_result` 抽出来，给参数研究页共用）。

【长什么样】一个 `QLabel` + 富文本：**灰标签 + 17px 彩值 + 灰副值**，底色由 `KPI_CARD_QSS` 出白卡。
（★1.64 定稿：KPI 当配角 —— 底色恒白、语义色只落在"值"上，整排不再是一片彩色药丸。）

【为什么抽出来】M2 结果区（`scan_result.kpi_card_html`）与 🧪 参数研究页（§7-B15）结论条都要
同一排卡；各写一份 ⇒ 字号/色值必然漂，用户看到"又是两套设计语言"（§11.5-112 同族）。所以：

- **本模块只认"标签 + 值 + 副值 + 颜色"** —— 与任何页面的语义无关；
- 各页自己把语义喂进来：`scan_result.kpi_card_html` 就是 M2 那层"key → 标签/颜色"的映射。

【纪律】富文本是刻意选的（一个控件做"标签小 / 值大 / 副值更小"，不必套三层布局）；
字体/颜色全部来自 `styles`（本模块不写死字号以外的样式）。
"""
from __future__ import annotations

from PyQt6.QtWidgets import QLabel

from ui.widgets.styles import KPI_CARD_QSS

#: 默认值色（中性深灰 = "既不好也不坏"，与 M2 KPI 的默认一致）
DEFAULT_KPI_FG = "#20242C"

__all__ = ["DEFAULT_KPI_FG", "kpi_html", "make_kpi_label", "set_kpi"]


def kpi_html(label: str, main: str, sub: str = "", color: str = DEFAULT_KPI_FG) -> str:
    """KPI 卡的富文本（唯一实现；逐字保留 M2 已定稿的字号/间距）。"""
    text = (f'<span style="font-size:11.5px;color:#8A94A6;">{label}</span>&nbsp;'
            f'<b style="font-size:17px;color:{color};">{main}</b>')
    if sub:
        text += f'&nbsp;<span style="font-size:11px;color:#8A94A6;">{sub}</span>'
    return text


def make_kpi_label(label: str, main: str = "—", sub: str = "",
                   color: str = DEFAULT_KPI_FG) -> QLabel:
    """造一枚 KPI 卡控件（白底卡 + 富文本）—— 页面把它放进一行 QC…Layout 即可。"""
    w = QLabel(kpi_html(label, main, sub, color))
    w.setStyleSheet(KPI_CARD_QSS)
    return w


def set_kpi(w, label: str, main: str, sub: str = "", color: str = DEFAULT_KPI_FG) -> None:
    """就地更新一枚 KPI 卡（坏控件 / None ⇒ 静默跳过，绝不把页面搞崩）。"""
    if w is not None:
        w.setText(kpi_html(label, main, sub, color))
