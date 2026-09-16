# ui/widgets/desk_chips.py
"""工具行 chips（"最近使用优先"）（1.23 自 `ui/views/trading_desk.py` 拆出 · §7-B6 STEP 6）。

【规则与解析在别处】候选池 / 排序 / 上限 / 隐藏项全部由 `ui/widgets/chip_mru.py`
（纯函数、零 Qt）回答；本模块只做**投影与回流**：
  真源（那几个 QCheckBox + 逐窗格显示开关） --投影--> 工具行 chips
  点 chip --> 只改真源 --> 真源回流刷新 chips（**单一状态源**，绝不两套状态）

【状态留页面】`_chip_recent`（最近使用历史）/ `_chip_seen` / `_sub_visible` / `_ui_ready`
/ `_desk_ui` 都在页面上；本模块只读写 `self.page.X`。

【僵尸控件坑（§11.5）】重建 chips 时必须 `setParent(None)` + `deleteLater()` ——
只 `removeWidget` 的话，旧按钮在事件循环真正删除前**仍是可见子控件**（1.22 在对话框里真踩过）。
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMenu, QPushButton

from ui.widgets.chip_mru import (CHIP_LIMIT, CHIP_POOLS, chip_kind, chip_label,
                                 hidden_keys, push_recent, resolve_chips)
from ui.widgets.custom_widgets import CHIP_MORE_QSS, CHIP_QSS_OFF, CHIP_QSS_ON


class DeskChips:
    """工具行 chips 的投影/回流（页面持状态，本类持行为）。"""

    def __init__(self, page):
        self.page = page

    # ==========================================
    # 真源 <-> chip 键的映射
    # ==========================================
    def _chip_control(self, key: str):
        """chip 键 -> 它背后的**真源控件**（QCheckBox）。

        ⚠ 用 `getattr` 惰性取：构造期各控件是**先后**创建的，急着组 dict 会在
        "前一个控件的 stateChanged 已经连上、后一个还没建好"时炸掉。
        """
        p = self.page
        name = {"ma": "cb_ma", "boll": "cb_boll", "formula": "cb_formula",
                "volume": "cb_vol", "macd": "cb_macd"}.get(str(key))
        return getattr(p, name, None) if name else None

    def _chip_candidates(self, kind: str) -> tuple:
        """该池**当前有可能显示**的键。

        公式副图 1/2/3 只在"函数里真有段指向它"时进候选 —— 否则工具行会摆一个
        点了没反应的 chip（那比不显示更糟）。
        """
        p = self.page
        if kind == "main":
            return tuple(CHIP_POOLS["main"])
        return ("volume", "macd") + tuple(
            target for target in ("sub1", "sub2", "sub3") if target in p._layer_formula)

    def _chip_enabled_keys(self, kind: str) -> list:
        """当前**已启用**的键（真源 = 那几个复选框；公式副图再加逐窗格显示开关）。"""
        p = self.page
        if kind == "main":
            return [key for key in CHIP_POOLS["main"]
                    if (control := self._chip_control(key)) is not None and control.isChecked()]
        enabled = [key for key in ("volume", "macd")
                   if (control := self._chip_control(key)) is not None and control.isChecked()]
        formula = self._chip_control("formula")
        if formula is not None and formula.isChecked():
            enabled += [target for target in ("sub1", "sub2", "sub3")
                        if target in p._layer_formula and p._sub_visible.get(target, True)]
        return enabled

    def chips_for(self, kind: str) -> list:
        """工具行上**当前显示**的 chip 键（供断言与人眼核对）。"""
        p = self.page
        return resolve_chips(p._chip_recent.get(kind, []), self._chip_enabled_keys(kind),
                             limit=CHIP_LIMIT, pool=self._chip_candidates(kind))

    def chips_hidden(self, kind: str) -> list:
        """被挤进「＋ 更多」菜单的键（池内、但没显示在工具行上）。"""
        p = self.page
        return hidden_keys(p._chip_recent.get(kind, []), self._chip_enabled_keys(kind),
                           limit=CHIP_LIMIT, pool=self._chip_candidates(kind))

    # ==========================================
    # 点 chip / 记历史
    # ==========================================
    def toggle_chip(self, key: str) -> None:
        """点 chip：只改**真源**（复选框 / 逐窗格开关），chips 由真源回流刷新（单一状态源）。

        注意：关闭**不**清"最近使用"记录 —— 它会变灰留在原位（§7-B6-D 规则 3）。
        """
        p = self.page
        kind = chip_kind(key)
        if not kind:
            return
        if str(key).startswith("sub"):
            formula = self._chip_control("formula")
            if formula is not None and not formula.isChecked():
                # 点「公式副图 N」就是要看它 ⇒ 顺手把总开关打开（否则点了像没反应）
                formula.setChecked(True)
            p._sub_visible[str(key)] = not p._sub_visible.get(str(key), True)
            self._remember_chip(str(key))
            p.render_charts()
            self._rebuild_chips("sub")
            return
        control = self._chip_control(key)
        if control is None:
            return
        control.setChecked(not control.isChecked())    # stateChanged → 重渲染 + chips 回流
        self._remember_chip(str(key))

    def _remember_chip(self, key: str) -> None:
        p = self.page
        kind = chip_kind(key)
        if not kind:
            return
        p._chip_recent[kind] = push_recent(p._chip_recent.get(kind, []), key)
        p._save_desk_ui(main_chips=p._chip_recent["main"],
                        sub_chips=p._chip_recent["sub"])

    def _on_layer_switch_changed(self, *_):
        """任一"叠加层开关"变化 → 记历史 → 重渲染 → 刷新工具行 chips（chips 只是投影）。"""
        p = self.page
        if not getattr(p, "_ui_ready", False):
            return          # 构造期各控件是先后创建的，未建齐前不要回流
        self._sync_chip_history()
        p.render_charts()
        self._refresh_chips()

    def _sync_chip_history(self) -> None:
        """把**刚被打开**的叠加层记进「最近使用」—— 左栏复选框与工具行 chip 是同一条路径。

        【为什么必须有它】若只在"点 chip"时记历史，用户从左栏把 MACD 打开再关掉，
        工具行里就不会留它的灰态位 ⇒ "关掉就再也点不回来"，违背 §7-B6-D 规则 3。
        """
        p = self.page
        changed = False
        for kind in ("main", "sub"):
            enabled = set(self._chip_enabled_keys(kind))
            for key in sorted(enabled - p._chip_seen.get(kind, set())):
                p._chip_recent[kind] = push_recent(p._chip_recent.get(kind, []), key)
                changed = True
            p._chip_seen[kind] = enabled
        if changed:
            p._save_desk_ui(main_chips=p._chip_recent["main"],
                            sub_chips=p._chip_recent["sub"])

    # ==========================================
    # 重建（投影）
    # ==========================================
    def _refresh_chips(self) -> None:
        """两个池一起刷新（公式段变化后"公式副图 N"的候选也会变，所以要重算）。"""
        self._rebuild_chips("main")
        self._rebuild_chips("sub")

    def _rebuild_chips(self, kind: str) -> None:
        """按"最近使用优先"重建该池的 chip（≤3 个）+ 刷新「＋ 更多」菜单。

        ⚠ 重建时必须**先 setParent(None) 再 deleteLater()**：只 removeWidget 的话，
        旧按钮在事件循环真正删除前**仍是可见子控件** ⇒ 界面上会出现两排同名 chip
        （§11.5 的僵尸控件坑，1.22 在对话框里真踩过）。
        """
        p = self.page
        if not getattr(p, "_ui_ready", False):
            return
        box = p._main_chips_lay if kind == "main" else p._sub_chips_lay
        while box.count():
            item = box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        enabled = self._chip_enabled_keys(kind)
        for key in self.chips_for(kind):
            on = key in enabled
            button = QPushButton(chip_label(key))
            button.setStyleSheet(CHIP_QSS_ON if on else CHIP_QSS_OFF)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(
                (f"{chip_label(key)}：已开启（点一下关闭）" if on
                 else f"{chip_label(key)}：已关闭（点一下打开）")
                + "\n工具行只放「最近用过的 3 个」，完整候选池在右侧「＋ 更多」。")
            button.clicked.connect(lambda _checked=False, k=key: self.toggle_chip(k))
            box.addWidget(button)
        self._rebuild_more_menu(kind, enabled)

    def _rebuild_more_menu(self, kind: str, enabled: list) -> None:
        p = self.page
        menu = p._main_more_menu if kind == "main" else p._sub_more_menu
        menu.clear()
        for key in self._chip_candidates(kind):
            if key in self.chips_for(kind):
                continue                      # 已经显示在工具行上的不重复列
            action = menu.addAction(chip_label(key))
            action.setCheckable(True)
            action.setChecked(key in enabled)
            action.triggered.connect(lambda _checked=False, k=key: self.toggle_chip(k))
        if menu.isEmpty():
            menu.addAction("（没有更多可选项）").setEnabled(False)
