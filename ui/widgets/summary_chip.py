# ui/widgets/summary_chip.py
"""摘要条胶囊（chip）的**唯一样式来源**（★1.64 · M2/M3 视觉重塑 STEP 1）。

【为什么要有它】M1 的 chip 是**四态药丸**（on/ok/off/sel + 左对齐 + 悬停高亮），而 M2/M3 各自在
自己版式里另写了一份 `_chip()`（渲染成**恒绿**的 `CHIP_QSS_ON`）——同一个零件三处三张脸，
用户看到的就是"三套设计语言"（用户 2026-09-30 实测口径）。这里收成**一份**：
状态色 / 内边距 / 圆角 / 字号**逐字沿用 M1 已定稿的值**（像素不变），M1/M2/M3 一律从这里取。

⚠ **不在收编范围**：行情页工具行的 chip（`desk_chips` + `CHIP_QSS_*` + MRU 规则）—— 那是
"最近使用优先"的另一族控件，形状与用途都不同，硬并会改观感（§10-9 只要求**同类**控件同一张脸）。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QPushButton

__all__ = ['CHIP_STATES', 'chip_qss', 'build_chip', 'set_chip_state']

# 四态：(底色, 边框, 字色) —— 与 M1（`backtest_summary_bar`）现状**逐值相同**
CHIP_STATES = {
    'on':  ('#FBFCFE', '#E7EAF0', '#3C4552'),
    'ok':  ('#F2FAF4', '#D6EEDA', '#256B34'),
    'off': ('#FAFBFC', '#E7EAF0', '#B4BECB'),
    'sel': ('#E8F2FE', '#A9C7EA', '#1257A8'),
}

_CHIP_QSS = ("QPushButton {{ text-align: left; padding: 5px 12px; border-radius: 14px;"
             " background: {bg}; border: 1px solid {bd}; color: {fg};"
             " font-size: 12.5px; font-weight: 600; }}"
             "QPushButton:hover {{ border-color: #A9C7EA; background: #F4F9FF; }}")


def chip_qss(state: str = 'on') -> str:
    """某状态下的完整 QSS（坏状态名回落 `on`，绝不产生"没有样式"的裸控件）。"""
    bg, bd, fg = CHIP_STATES.get(str(state), CHIP_STATES['on'])
    return _CHIP_QSS.format(bg=bg, bd=bd, fg=fg)


def build_chip(text: str, tooltip: str = '', state: str = 'on') -> QPushButton:
    """造一枚 chip（**三页共用**）。默认 `on` = 中性灰白，**不再是"恒绿"** ——
    恒绿等于"所有 chip 都声称自己处于警报态"，那是假状态（M2/M3 旧观感）。"""
    btn = QPushButton(str(text))
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(chip_qss(state))
    if tooltip:
        btn.setToolTip(str(tooltip))
    return btn


def set_chip_state(btn, state: str) -> None:
    """就地改一枚 chip 的状态（页面/流程用它表达 on / ok / off / sel）。"""
    if btn is not None:
        btn.setStyleSheet(chip_qss(state))
