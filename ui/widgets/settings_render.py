# ui/widgets/settings_render.py
"""设置项**控件工厂**（★v6.73 / §7-B13 · S2-0）—— "类型 → 控件" 的**唯一映射**。

【为什么单列一个件】S2 的详情区要容纳"开关 / 数值 / 枚举 / 只读…"各种形状。若在
  `ui/views/settings_view.py` 里写成一串 `if kind == ...`，就会重演 §11.5-89
  （**"形状不同"的东西塞进同一个壳 ⇒ 加一种就漏一处**）。这里用**注册表式工厂**：
  新类型 = 加一个函数 + 在 `_FACTORIES` 登记一行；页面**一行 `if` 都没有**。
【纪律】控件一律用全站工厂（`double_spin` / `int_spin` / `NoWheelComboBox`，§10-9 宽度不钉死、
  防滚轮误触），**不手搓** QSpinBox，也不在 QSS 里点名字体族（§10-15）。
【防呆】未知类型 ⇒ 退化成只读展示 + 一条日志（**绝不崩**）—— 这样 S2-1/S2-5 加新类型时，
  即使工厂还没写，页面也能打开、只是先把值显示出来。
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox, QLabel, QPushButton, QWidget

from ui import settings_registry as reg
from ui.widgets.custom_widgets import (FLAT_QSS, LINE_COMBO_QSS,
                                       NoWheelComboBox, double_spin, int_spin)

logger = logging.getLogger(__name__)


def build_control(item: reg.Item, on_change):
    """按声明造控件。`on_change(item, value)` 由页面提供（它只负责转交给注册表）。"""
    factory = _FACTORIES.get(item.kind)
    if factory is None:
        logger.warning(f"设置项 {item.key} 的类型 {item.kind!r} 还没有控件工厂 ⇒ 先按只读展示")
        factory = _make_readonly
    return factory(item, on_change)


def _make_toggle(item: reg.Item, on_change):
    box = QCheckBox()
    box.setChecked(bool(reg.get_value(item)))
    box.setCursor(Qt.CursorShape.PointingHandCursor)
    box.setToolTip(item.help or item.tip or '')
    box.toggled.connect(lambda checked: on_change(item, checked))   # ⚠ 建控件时先设值、后接线
    return box


def _make_number(item: reg.Item, on_change):
    _tip = item.help or item.tip or ''
    if item.decimals:
        spin = double_spin(value=float(reg.get_value(item)), lo=float(item.lo),
                           hi=float(item.hi), decimals=int(item.decimals),
                           step=float(item.step), tooltip=_tip)
    else:
        spin = int_spin(value=int(reg.get_value(item)), lo=int(item.lo),
                        hi=int(item.hi), step=int(item.step), tooltip=_tip)
    spin.valueChanged.connect(lambda v: on_change(item, v))
    return spin


def _make_enum(item: reg.Item, on_change):
    combo = NoWheelComboBox()
    combo.setStyleSheet(LINE_COMBO_QSS)
    for value, label in item.choices:
        combo.addItem(str(label), value)
    idx = combo.findData(reg.get_value(item))
    combo.setCurrentIndex(idx if idx >= 0 else 0)
    combo.setMinimumWidth(230)                                     # 只给下限，不钉死（§10-9）
    combo.setToolTip(item.help or item.tip or '')
    combo.currentIndexChanged.connect(lambda _i: on_change(item, combo.currentData()))
    return combo


def _make_readonly(item: reg.Item, on_change):
    label = QLabel(reg.value_text(item))          # 动态状态项（value_fn）这里现算 ⇒ 每次刷新都新鲜
    label.setStyleSheet("font-weight:600; color:#20242C;")
    label.setToolTip((item.help or item.tip or '')
                     + f"\n来源：{reg.describe_where(item)}")
    return label


def _make_action(item: reg.Item, on_change):
    """动作项（登录… / 退出登录 / 网络自检）：按钮**只报"被点了"**，真正执行在页面里。

    ⚠ 这样分工的理由：注册表负责"**声明有什么动作**"，页面负责"**执行 + 刷新 + 回执**"
      （§3：业务不写在声明里，声明不掺交互）。
    """
    btn = QPushButton(str(item.default or '执行'))
    btn.setStyleSheet(FLAT_QSS)                   # §9-F③ 样式唯一出口
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setToolTip(item.help or item.tip or '')
    btn.clicked.connect(lambda: on_change(item, None))     # None = "动作被点"，不是值变更
    return btn


# 【新类型在此登记一行即可】（S2-1：action=登录按钮；S2-5：path=数据目录选择）
_FACTORIES = {
    reg.KIND_TOGGLE: _make_toggle,
    reg.KIND_NUMBER: _make_number,
    reg.KIND_ENUM: _make_enum,
    reg.KIND_READONLY: _make_readonly,
    reg.KIND_ACTION: _make_action,
}
