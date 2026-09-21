# ui/widgets/desk_formula.py
"""ƒ 用户公式：编辑 / 编译 / 资产化 / 互送（1.23 自 `ui/views/trading_desk.py` 拆出 · §7-B6 STEP 6）。

【职责】把"用户贴进来的函数文本"变成"面板状态 + 可渲染的图层"：
  ① 编辑（`FormulaOverlayDialog`）→ 段与参数进页面状态；
  ② 编译成 programs（**失败不炸页面**，只写回执）；
  ③ 资产化（存配方 / 配方库载入 —— `data/formula_store.py` 门面）；
  ④ 与「📐 市场回测」互送（经主窗口转交，两个页面互不 import）。

【求值/落笔不在这里】`_formula_layers` / `_paint_layers` 属渲染装配，在
`ui/widgets/desk_layers.py`（本模块只负责"编译 + 回执 + 资产化"）。

【约定】状态留页面：`_formula_segments / _formula_params_text / _formula_programs /
_formula_error / _formula_store / lbl_formula_status / _sub_visible`，
本模块只承载行为，读写一律走 `self.page.X`。

★v6.24（§7-B8 R13）：显示开关（原 `cb_formula`）也**不再是控件** —— 它就是
`layer_model` 里的**草稿槽**（`DRAFT_KEY`），由 `_register_draft()` 登记、chips 负责投影。
"""
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QDialog, QInputDialog, QListWidgetItem, QMessageBox

from core.formula.program import FormulaProgramError, parse_program
from core.utils import parse_params_text
from data.formula_store import (SOURCE_MARKET, make_formula, segments_as_tuples)
from ui.dialogs.formula_overlay import FormulaOverlayDialog
from ui.dialogs.indicator_params import IndicatorParamsDialog
from ui.widgets.chart_layers import scale_mismatch_hint
from ui.widgets.custom_widgets import RecipeChip
from ui.widgets.formula_library import FormulaLibraryDialog
from ui.widgets.layer_model import DRAFT_KEY, TARGET_LABELS, TARGET_ORDER, LayerModel


class DeskFormula:
    """公式的编辑/编译/资产化/互送（页面持状态，本类持行为）。"""

    def __init__(self, page):
        self.page = page

    # ==========================================
    # 编辑 + 编译
    # ==========================================
    def edit_formula(self):
        p = self.page
        dialog = FormulaOverlayDialog(p, segments=p._formula_segments,
                                      params_text=p._formula_params_text)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        p._formula_segments = dialog.result_segments()
        p._formula_params_text = dialog.params_text()
        self._register_draft()
        self._compile_formula()
        p.render_charts()
        p._refresh_chips()      # 段变了 ⇒ "公式副图 N"的候选也跟着变

    def _register_draft(self, force_visible: bool = False) -> None:
        """把当前 `_formula_segments` 登记为**草稿槽**（模型里那个 `draft` 条目）。

        【为什么会有"没有记忆就默认可见"这一条】旧实现里那个总开关（`cb_formula`）
        **默认是开的** ⇒ "贴了函数就该看得见"。换成模型之后，如果偏好里**还没有这个键**
        （升级 / 首次运行），必须沿用这个默认 —— 否则老用户升级后会以为"公式丢了"，
        那是**行为回归**，不是改进。
        """
        p = self.page
        if not p._formula_segments:
            p.layer_model.set_draft(None)
            return
        p.layer_model.set_draft(p._formula_segments)
        remembered = p._desk_ui.get("layer_enabled")
        if force_visible or not remembered:
            p.layer_model.set_enabled(DRAFT_KEY, True)
        self.refresh_recipe_page()      # 草稿槽变了 ⇒ 配方库页跟着变（草稿也是一条 chip）

    def _compile_formula(self):
        """把 (函数文本, 目标窗格) 编译成 programs（顺序与 `_formula_segments` 一一对应）。

        ⚠ 这里顺手**登记草稿槽**（"编译了什么，草稿就是什么"）—— 放在这一个入口，
        而不是依赖每个调用方记得登记：直接赋值 `_formula_segments` 的路径（测试、将来的
        外部调用）也会因此拿到一致的模型状态。
        """
        p = self.page
        self._register_draft()
        p._formula_programs = []
        p._formula_error = ""
        if not p._formula_segments:
            self._set_formula_status(True, "未设置")
            return
        for index, (text, _target) in enumerate(p._formula_segments, start=1):
            try:
                p._formula_programs.append(parse_program(text))
            except FormulaProgramError as e:
                p._formula_error = f"函数段 {index}: {e}"
                return

    # ==========================================
    # 回执（★STEP 5：一行摘要 + tooltip 详解）
    # ==========================================
    def _report_formula_status(self, df):
        """写面板状态：图层数 + 落点分布，必要时补一句"该放副图"的引导。"""
        p = self.page
        if not p._formula_programs:
            return
        if not any(p._layer_formula.values()):
            return          # 已由 _formula_layers 写过 ❌，不覆盖
        main_count = len(p._layer_formula.get('main', []))
        sub_targets = sorted(t for t in p._layer_formula
                             if t != 'main' and p._layer_formula[t])
        message = (f"✓ {sum(len(v) for v in p._layer_formula.values())} 个图层 · "
                   f"主图 {main_count} · 副图 {len(sub_targets)} 格")
        hint = None
        if main_count and not df.empty:
            hint = scale_mismatch_hint(p._layer_formula.get('main', []),
                                       float(df['low'].min()), float(df['high'].max()))
        if hint:
            self._set_formula_status(
                True, message + "\n⚠ 主图部分与股价量级相差很大 · 建议改用副图", warn=True)
            p.lbl_formula_status.setToolTip(hint)
        else:
            self._set_formula_status(True, message)

    def _set_formula_status(self, ok: bool, message: str, *, warn: bool = False,
                            detail: str = ""):
        """公式回执（★STEP 5：**一行可读摘要**，窄面板不再靠 `\\n` 折行）。

        ⚠ 单行消息时 `toolTip()` 必须与 `text()` **逐字相同** —— 既有断言就是这么比的
        （§11.7：回执升级不许把既有口径改坏）。
        """
        p = self.page
        line = " · ".join(part.strip() for part in str(message or "").splitlines()
                          if part.strip())
        p.lbl_formula_status.setText(line)
        p.lbl_formula_status.setToolTip(str(detail or message or line).strip())
        color = '#E65100' if warn else ('#4CAF50' if ok else '#F44336')
        p.lbl_formula_status.setStyleSheet(f"font-size: 11px; color: {color};")

    # ==========================================
    # 资产化 + 互送（P7 · §7-B3 P7）
    # ==========================================
    def save_formula_as(self):
        p = self.page
        if not p._formula_segments:
            QMessageBox.information(
                p, "暂无公式",
                "先在「✏️ 编辑公式…」里粘贴并应用一段函数，再保存为配方。")
            return
        name, ok = QInputDialog.getText(p, "保存为配方", "配方名称（同名即覆盖）：")
        if not ok:
            return
        try:
            formula = make_formula(name, p._formula_segments,
                                   params_text=p._formula_params_text,
                                   source=SOURCE_MARKET)
        except ValueError as e:
            QMessageBox.warning(p, "无法保存", str(e))
            return
        saved = p._formula_store.upsert(formula)
        # 存完**立刻让它生效**（否则"存了却看不见"），并重建模型让新配方出现在对应分区
        self._rebuild_model()
        p.layer_model.set_enabled(f"formula:{saved['id']}", True)
        p._on_layer_switch_changed()
        self.refresh_recipe_page()
        self._set_formula_status(True, f"✓ 已存入配方库：{saved['name']}")

    # ==========================================
    # 配方库页（§7-B8 R6/R13）：分区 chip 即开关，管理模式才给改名/删除
    # ==========================================
    def refresh_recipe_page(self) -> None:
        """按 `layer_model` **重建**两个分区的配方 chip。

        【为什么每次整块重建，而不是增量改】配方随时可能被加/删/改名（本页、保存、外部互送），
        增量维护必然出现"删了还留着""改名了显示还是旧的"（§11.5-11 的老毛病）。
        重建的代价 = 十几个控件，可以忽略；换来的是"界面永远等于模型"这条不变量。
        """
        p = self.page
        lays = getattr(p, "formula_chip_lays", None)
        if not lays:
            return          # 页面还没建好（构造期早于本调用）
        model = p.layer_model
        for target in TARGET_ORDER:
            items = model.items_for(target)
            p.formula_section_labels[target].setText(
                f"{TARGET_LABELS[target]}配方 · {len(items)} 条")
            lay = lays[target]
            while lay.count():
                item = lay.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.setParent(None)
                    widget.deleteLater()
            for entry in items:
                chip = RecipeChip(entry["key"], entry["name"], entry["target"],
                                  builtin=entry.get("builtin", False),
                                  has_params=model.has_params(entry["key"]))
                chip.set_on(model.enabled(entry["key"]))
                chip.set_manage(getattr(p, "_formula_manage", False))
                chip.sigToggled.connect(p.toggle_recipe)
                chip.sigParams.connect(p.open_params)      # ★R16：有参数的才有这个入口
                if not entry.get("builtin"):
                    chip.sigRename.connect(p.rename_recipe)
                    chip.sigDelete.connect(p.delete_recipe)
                lay.addWidget(chip)
            p.formula_chip_hosts[target].sync_height()
        enabled = len(model.enabled_list())
        p.card_formula_lib.set_state(f"生效 {enabled} 条 · 共 {len(model.items)} 条")

    def open_params(self, key: str) -> None:
        """`⚙` 参数窗口（§7-B8 R16）。

        · **没参数的条目直接返回**（`成交量`）——不摆假入口，也不假弹窗；
        · 校验用**页面上正在看的那份行情**（比哑数据更有意义），"不另起一套试算"
          落在**直接调 `TAEngine`**（与图上渲染同源的引擎）；
        · 改完必须**重算**：内置走 `prepared_df`（引擎），用户配方清编译缓存（§11.5-11）。
        """
        p = self.page
        if not p.layer_model.has_params(key):
            return
        sample = p.current_df if (p.current_df is not None and len(p.current_df)) else None
        dialog = IndicatorParamsDialog(
            p.layer_model, key, parent=p, sample_df=sample,
            sample_label=(p.current_name or p.current_symbol) if sample is not None else "")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        p._recipe_programs = {}
        p._on_layer_switch_changed()
        self.refresh_recipe_page()
        values = "、".join(f"{name}={value}"
                          for name, value in p.layer_model.params_of(key).items())
        # 回执写在渲染**之后**（否则会被 `_report_formula_status` 的图层统计覆盖）
        self._set_formula_status(True, f"✓ 已应用参数：{values}")

    def toggle_recipe(self, key: str) -> None:
        """点配方 chip = 开/关。真源只有一处，翻过来之后走**同一条回流**（重渲染 + chips）。"""
        p = self.page
        if not p.layer_model.toggle(key):
            return
        p._on_layer_switch_changed()
        self.refresh_recipe_page()

    def set_formula_manage(self, on: bool) -> None:
        """管理模式（危险动作的开关）。**内置项永远不显示操作** —— 那是刻意的。"""
        p = self.page
        p._formula_manage = bool(on)
        p.btn_formula_manage.setText("✓ 管理模式（已开）" if p._formula_manage else "✏ 管理模式")
        self.refresh_recipe_page()

    def rename_recipe(self, key: str) -> None:
        p = self.page
        entry = p.layer_model.item(key)
        if not entry or entry.get("builtin"):
            return          # 内置不改名（连管理模式也改不了）
        new_name, confirmed = QInputDialog.getText(p, "配方改名", "新名称：",
                                                   text=str(entry.get("name") or ""))
        if not confirmed:
            return
        if not p._formula_store.rename(entry.get("formula_id"), new_name):
            QMessageBox.warning(p, "无法改名", "名称为空，或已经有同名的配方。")
            return
        self._rebuild_model()
        self._set_formula_status(True, f"✓ 已改名为「{str(new_name).strip()}」")

    def delete_recipe(self, key: str) -> None:
        """删除配方。**必须说清"它会同时从图上移除"**（否则用户以为删的只是存档、图还在）。"""
        p = self.page
        entry = p.layer_model.item(key)
        if not entry or entry.get("builtin"):
            return
        name = str(entry.get("name") or "")
        was_on = p.layer_model.enabled(key)
        detail = "\n· 它正在图上生效 —— 删除后会**同时从图上消失**" if was_on else ""
        answer = QMessageBox.question(
            p, "删除配方",
            f"删除配方「{name}」？\n\n· 配方存档会被删除（不可撤销）{detail}")
        if answer != QMessageBox.StandardButton.Yes:
            return
        p._formula_store.delete(entry.get("formula_id"))
        p.layer_model.set_enabled(key, False)
        self._rebuild_model()
        self._set_formula_status(True, f"✓ 已删除配方「{name}」")

    def _rebuild_model(self) -> None:
        """配方库变了（改名 / 删除 / 新存）⇒ **重建模型**，并保住开关、参数与副图顺序。

        ⚠ 只重建、不重设：`enabled` / `params` / `sub_order` 从旧模型原样搬过去，
        被删掉的那条 key 由模型**自己清洗掉**（§11.5-18：坏值不许进界面）；
        新增的副图配方不在旧序里 ⇒ 由 `_reorder_group` 自动排到末尾。
        """
        p = self.page
        p.layer_model = LayerModel(formulas=p._formula_store.all(),
                                   enabled=p.layer_model.enabled_list(),
                                   params=p.layer_model.params_snapshot(),
                                   draft=p._formula_segments,
                                   order=p.layer_model.sub_order_keys())
        p._recipe_programs = {}
        p._on_layer_switch_changed()
        self.refresh_recipe_page()

    def open_formula_library(self):
        p = self.page
        dialog = FormulaLibraryDialog(p._formula_store, p)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        formula = dialog.selected_formula()
        if not formula:
            return
        self.receive_formula(segments_as_tuples(formula), formula.get("params_text", ""),
                             source_label=f"配方库「{formula['name']}」")

    def send_formula_to_backtest(self) -> int:
        """行情页 → 回测页（由主窗口转交，两个页面互不 import）；返回送过去的段数。"""
        p = self.page
        if not p._formula_segments:
            QMessageBox.information(
                p, "暂无公式", "先在「✏️ 编辑公式…」里写好函数，再送去回测。")
            return 0
        count = p.main_win.send_formula_to_backtest(
            p._formula_segments, p._formula_params_text)
        if count:
            self._set_formula_status(True, f"✓ 已把 {count} 段函数送到「📐 市场回测」")
        return count

    def receive_formula(self, segments, params_text: str = "",
                        source_label: str = "外部") -> int:
        """接收外来配方（回测页 / 配方库）并立即生效。

        :return: 实际载入的段数（0 = 内容为空，什么都没做）
        """
        p = self.page
        pairs = [(str(text), str(target)) for text, target in (segments or [])
                 if str(text or "").strip()]
        if not pairs:
            return 0
        p._formula_segments = pairs
        p._formula_params_text = str(params_text or "")
        p._sub_visible = {"sub1": True, "sub2": True, "sub3": True}   # 外来公式：副图先全开
        self._register_draft(force_visible=True)   # 刚送来的公式就该看得见（旧行为一致）
        self._compile_formula()
        p.render_charts()
        p._refresh_chips()
        # 回执写在渲染**之后**：否则会被 `_report_formula_status` 的图层统计覆盖
        self._set_formula_status(True, f"✓ 已从{source_label}载入 {len(pairs)} 段函数")
        return len(pairs)

    def _restore_last_formula(self):
        """开机自动恢复"上次用过的配方" —— §7-B3 P7 要解决的"公式重启就丢"。"""
        p = self.page
        formula = p._formula_store.last_used()
        if not formula:
            return
        pairs = segments_as_tuples(formula)
        if not pairs:
            return
        p._formula_segments = pairs
        p._formula_params_text = formula.get("params_text", "")
        self._register_draft()
        self._compile_formula()
        self._set_formula_status(True, f"✓ 已自动载入上次配方「{formula['name']}」"
                                       f"（{len(pairs)} 段）")

    # ==========================================
    # 副图换序（§7-B8 R7）：⬆⬇ 版（附图少 ⇒ 规格里 ⬆⬇ 就够；拖拽留后续）。
    #   口径：换序只改**显示格位**，绝不改公式段的 target；
    #   每次移动→落模型→走 `_on_layer_switch_changed`（即时重渲染 + 持久化 sub_order）。
    # ==========================================
    def set_formula_sort_mode(self, on: bool) -> None:
        p = self.page
        on = bool(on)
        p._formula_sort_mode = on
        btn = getattr(p, "btn_formula_sort", None)
        if btn is not None:
            btn.setText("✓ 换序中（点此退出）" if on else "⇅ 副图换序")
        for attr in ("formula_sort_bar", "formula_sort_list"):
            widget = getattr(p, attr, None)
            if widget is not None:
                widget.setVisible(on)
        lst = getattr(p, "formula_sort_list", None)
        if lst is not None:
            lst.set_sort_mode(on)          # 闸 1：非排序模式时 DragHandleListWidget 根本不响应拖
        if on:
            p._formula_sort_backup = list(p.layer_model.sub_order_keys())
            self._rebuild_sort_list()
        else:
            p._formula_sort_backup = None

    def _rebuild_sort_list(self) -> None:
        """按当前副图先后重建 ⬆⬇ 列表（一行一格；未启用置灰但仍占格位）。"""
        p = self.page
        lst = getattr(p, "formula_sort_list", None)
        if lst is None:
            return
        current = lst.currentRow()
        lst.clear()
        for pos, key in enumerate(p.layer_model.sub_order_keys()):
            name = p.layer_model.label(key) or key
            suffix = "" if p.layer_model.enabled(key) else "（未启用）"
            item = QListWidgetItem(f"⣿ {pos + 1}. {name}{suffix}")
            item.setData(Qt.ItemDataRole.UserRole, key)
            lst.addItem(item)
        if 0 <= current < lst.count():
            lst.setCurrentRow(current)
        elif lst.count():
            lst.setCurrentRow(0)

    def move_formula_sort(self, delta: int) -> None:
        p = self.page
        if not getattr(p, "_formula_sort_mode", False):
            return
        lst = getattr(p, "formula_sort_list", None)
        if lst is None:
            return
        row = lst.currentRow()
        keys = p.layer_model.sub_order_keys()
        if row < 0 or row >= len(keys):
            return
        key = keys[row]
        if p.layer_model.move_sub(key, int(delta)):
            p._on_layer_switch_changed()      # 即时重渲染 + 持久化 sub_order
            self._rebuild_sort_list()
            new_keys = p.layer_model.sub_order_keys()
            if key in new_keys:
                lst.setCurrentRow(new_keys.index(key))

    def undo_formula_sort(self) -> None:
        p = self.page
        backup = getattr(p, "_formula_sort_backup", None)
        if not backup:
            return
        if p.layer_model.set_sub_order(backup):
            p._on_layer_switch_changed()
        self._rebuild_sort_list()

    def on_formula_rows_moved(self, *_args) -> None:
        """拖拽**结束**才回写：延迟到下一轮事件循环。

        ⚠ 此刻列表模型正在发 `rowsMoved`，当场重建 = 边发信号边改模型
        （Qt 会崩 / 丢行）—— 与自选股 R15 `on_watch_rows_moved` 同一条纪律。
        """
        p = self.page
        if not getattr(p, "_formula_sort_mode", False):
            return
        QTimer.singleShot(0, self.apply_formula_sort)

    def apply_formula_sort(self) -> None:
        """把当前列表顺序写回模型 → 走统一回流（即时重渲染 + 持久化 sub_order）。"""
        p = self.page
        if not getattr(p, "_formula_sort_mode", False):
            return
        lst = getattr(p, "formula_sort_list", None)
        if lst is None:
            return
        order = [str(lst.item(row).data(Qt.ItemDataRole.UserRole) or "")
                 for row in range(lst.count())]
        if p.layer_model.set_sub_order(order):
            p._on_layer_switch_changed()
        self._rebuild_sort_list()

    def finish_formula_sort(self) -> None:
        p = self.page
        btn = getattr(p, "btn_formula_sort", None)
        if btn is not None and btn.isChecked():
            btn.setChecked(False)             # 触发 toggled → set_formula_sort_mode(False)
        else:
            self.set_formula_sort_mode(False)
