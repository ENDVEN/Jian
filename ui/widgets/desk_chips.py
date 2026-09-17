# ui/widgets/desk_chips.py
"""工具行 chips（"最近使用优先"）（1.23 自 `ui/views/trading_desk.py` 拆出 · §7-B6 STEP 6）。

【规则与解析在别处】排序 / 上限 / 隐藏项由 `ui/widgets/chip_mru.py`（纯函数、零 Qt）回答；
本模块只做**投影与回流**：
  真源（`layer_model` 的开关；草稿的逐窗格显示开关） --投影--> 工具行 chips
  点 chip --> 只改真源 --> 真源回流刷新 chips（**单一状态源**，绝不两套状态）

★v6.24（§7-B8 R13）：真源**不再是 5 个 QCheckBox**，而是 `ui/widgets/layer_model.py`。
  ⚠ 随之而来的一个真实差异：以前"改状态"顺带靠 `QCheckBox.stateChanged` 触发重渲染，
  现在**没有那个信号了** ⇒ `toggle_chip` 必须显式走 `_on_layer_switch_changed()`。
  （测试侧同理，见 `smoke_pages_overlay._layer()` 的注释：漏了就会写出"改了状态图不动"的假测试。）

【状态留页面】`_chip_recent`（最近使用历史）/ `_chip_seen` / `_sub_visible` / `_ui_ready`
/ `_desk_ui` 都在页面上；本模块只读写 `self.page.X`。

【僵尸控件坑（§11.5）】重建 chips 时必须 `setParent(None)` + `deleteLater()` ——
只 `removeWidget` 的话，旧按钮在事件循环真正删除前**仍是可见子控件**（1.22 在对话框里真踩过）。
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMenu, QPushButton

from ui.widgets.chip_mru import (CHIP_LIMIT, chip_kind, chip_label, hidden_keys,
                                 push_recent, resolve_chips)
from ui.widgets.layer_model import DRAFT_KEY, TARGET_MAIN, TARGET_SUB
from ui.widgets.custom_widgets import CHIP_MORE_QSS, CHIP_QSS_OFF, CHIP_QSS_ON


# 草稿的"副图格位"键（只有草稿用得上；已存配方是"一条一个窗格"，不占这些名字）
_SUB_PANE_KEYS = ("sub1", "sub2", "sub3")


class DeskChips:
    """工具行 chips 的投影/回流（页面持状态，本类持行为）。"""

    def __init__(self, page):
        self.page = page

    # ==========================================
    # 真源 <-> chip 键的映射
    # ==========================================
    # chip 键 -> `layer_model` 的键。**"公式"这个 chip 就是草稿槽**（老 `cb_formula` 的等价物）
    _CHIP_TO_MODEL = {"ma": "ma", "boll": "boll", "volume": "volume",
                      "macd": "macd", "formula": DRAFT_KEY}

    def _model_key(self, key: str) -> str:
        """chip 键 -> `layer_model` 的键（"公式"这个 chip 就是**草稿槽**）。"""
        return self._CHIP_TO_MODEL.get(str(key), str(key))

    def _kind_of(self, key: str) -> str:
        """这个键属于哪个池（`main` / `sub`；未知返回空串）。

        ⚠ 必须"先查静态表、再问模型"：`chip_kind` 只认识 `CHIP_POOLS` 那张**静态表**，
        而 v6.24 之后候选池是**动态的**（配方 key 只有 `layer_model` 认识）——
        漏了这一步的后果是**"点配方 chip 没反应"**（`toggle_chip` 会当成未知键提前返回），
        而且不报错、不抛异常，只是什么都没发生。
        """
        kind = chip_kind(key)
        if kind:
            return kind
        target = self.page.layer_model.pool_of_key(self._model_key(key))
        return "main" if target == TARGET_MAIN else ("sub" if target == TARGET_SUB else "")

    def _is_on(self, key: str) -> bool:
        key = str(key)
        if key in _SUB_PANE_KEYS:      # 草稿的"副图 N"格位：开 = 草稿开着 且 这一格没被单独关掉
            return (self.page.layer_model.enabled(DRAFT_KEY)
                    and bool(self.page._sub_visible.get(key, True)))
        return bool(self.page.layer_model.enabled(self._model_key(key)))

    def _set_on(self, key: str, value: bool) -> None:
        key = str(key)
        if key in _SUB_PANE_KEYS:
            if value:
                self.page.layer_model.set_enabled(DRAFT_KEY, True)   # 要看这一格 ⇒ 先把草稿打开
            self.page._sub_visible[key] = bool(value)
            return
        self.page.layer_model.set_enabled(self._model_key(key), bool(value))

    def _label(self, key: str) -> str:
        """chip 上写什么字。

        ★v6.24（R14 的顺带收益）：**用户配方直接显示配方名** —— 用户一眼知道那一格是什么，
        而不是"公式副图 1"。草稿在工具行里仍叫「公式」（它的配方名在配方库页上看）。
        """
        key = str(key)
        if key in _SUB_PANE_KEYS:
            return chip_label(key)
        model_key = self._model_key(key)
        model = self.page.layer_model
        if model_key == DRAFT_KEY:
            return "公式"
        if model.has(model_key):
            return model.label(model_key)
        return chip_label(key)

    def _chip_candidates(self, kind: str) -> tuple:
        """该池**当前有可能显示**的键。

        ★v6.24（R13）：候选池**从模型动态取**，不再硬编码 ——
        "配方库加一条 → 工具行立刻能选到它"就是靠这里。
        仍然保留"不给死 chip"的纪律：草稿的"副图 N"只在真有那一段时才出现，
        没有草稿时也不摆「公式」这个 chip（点了没反应的 chip 比不显示更糟）。
        """
        p = self.page
        target = TARGET_MAIN if kind == "main" else TARGET_SUB
        keys = [("formula" if model_key == DRAFT_KEY else model_key)
                for model_key in p.layer_model.pool_for(target)
                if not (kind == "sub" and model_key == DRAFT_KEY)]
        if kind == "main" and p.layer_model.has_draft():
            # 草稿的"总开关"一直挂在**主图**池里（与老 `cb_formula` chip 的位置一致）
            keys.append("formula")
        if kind == "sub":
            keys += [key for key in _SUB_PANE_KEYS if key in p._layer_formula]
        return tuple(keys)

    def _chip_enabled_keys(self, kind: str) -> list:
        """当前**已启用**的键。真源 = `layer_model`（内置、草稿槽、已存配方都从它读）。"""
        return [key for key in self._chip_candidates(kind) if self._is_on(key)]

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
        key = str(key)
        if key not in _SUB_PANE_KEYS and not p.layer_model.has(self._model_key(key)):
            return          # 未知键：什么都不做（别假装生效）
        # ⚠ 以前靠 `QCheckBox.setChecked` 的 `stateChanged` 触发重渲染；真源换成模型之后
        #   必须**显式**走同一条回流路径（否则"点了 chip 图不动"）
        self._set_on(key, not self._is_on(key))
        self._remember_chip(key)
        self._on_layer_switch_changed()

    def _remember_chip(self, key: str) -> None:
        p = self.page
        kind = self._kind_of(key)
        if not kind:
            return
        # ⚠ 必须带上**动态池**：不然配方 key 会被 `normalize_recent` 当池外键丢掉
        #   （"用过了却不进最近使用"，且不报错）
        p._chip_recent[kind] = push_recent(p._chip_recent.get(kind, []), key,
                                           pool=self._chip_candidates(kind))
        p._save_desk_ui(main_chips=p._chip_recent["main"],
                        sub_chips=p._chip_recent["sub"])

    def _on_layer_switch_changed(self, *_):
        """任一"叠加层开关"变化 → 记历史 → 重渲染 → 刷新工具行 chips（chips 只是投影）。"""
        p = self.page
        if not getattr(p, "_ui_ready", False):
            return          # 构造期各控件是先后创建的，未建齐前不要回流
        self._sync_chip_history()
        # ★ 开关/参数变了就记偏好 —— **唯一落点**（别处不许各自 `_save_desk_ui` 记一半）
        persist = getattr(p, "_persist_layer_state", None)
        if callable(persist):
            persist()
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
            label = self._label(key)
            button = QPushButton(label)
            button.setStyleSheet(CHIP_QSS_ON if on else CHIP_QSS_OFF)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(
                (f"{label}：已开启（点一下关闭）" if on
                 else f"{label}：已关闭（点一下打开）")
                + "\n工具行只放「最近用过的 3 个」，完整候选池在右侧「＋ 更多」。")
            button.clicked.connect(lambda _checked=False, k=key: self.toggle_chip(k))
            box.addWidget(button)
        self._rebuild_more_menu(kind, enabled)

    def _rebuild_more_menu(self, kind: str, enabled: list) -> None:
        """★v6.24（R14）：这个菜单是**配方库的镜像** —— 同一份真源、同一批条目，
        按「内置 / 你的配方」两段列出，并标出`已开 / 已关`。

        ⚠ **投影不是第二份状态**：这里一个字段都不存，全部现算自 `layer_model`；
        在配方库里新增 / 删除 / 开关一条，这里立刻跟着变（§7-B6-D 第 6 条）。
        """
        p = self.page
        menu = p._main_more_menu if kind == "main" else p._sub_more_menu
        menu.clear()
        shown = self.chips_for(kind)
        pool = self._chip_candidates(kind)
        groups = (("内置", [k for k in pool if p.layer_model.is_builtin(self._model_key(k))]),
                  ("你的配方", [k for k in pool
                             if not p.layer_model.is_builtin(self._model_key(k))]))
        for title, keys in groups:
            keys = [key for key in keys if key not in shown]     # 已显示在工具行上的不重复列
            if not keys:
                continue
            menu.addSection(title)
            for key in keys:
                on = key in enabled
                action = menu.addAction(
                    f"{self._label(key)}　{'已开' if on else '已关'}")
                action.setCheckable(True)
                action.setChecked(on)
                action.triggered.connect(lambda _checked=False, k=key: self.toggle_chip(k))
        if menu.isEmpty():
            menu.addAction("（没有更多可选项）").setEnabled(False)
