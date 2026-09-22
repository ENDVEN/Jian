# ui/views/backtest_history.py
"""
🗂 运行历史（§7-A4 · v1.37）—— 市场回测页第 4 个子页。

【本文件是"薄壳"】与 1.22（`ui/views/backtest.py`）/ 1.26（`review.py`）/ STEP 4-5
（`scan_view.py` / `breadth_view.py`）同款约定：**状态与接线留页面、版式与渲染搬模块**。
  · 版式 / 列表 / 迷你曲线 / 预览渲染 → `ui/widgets/backtest_history_ui.py`
  · 存档读写 / 淘汰 / 防注入    → `data/backtest_archive.py`
  本页只做三件事：① 把存档的元数据喂给列表；② 把动作接到 M1 视图 / 主窗口；③ 维护选中态。

【为什么 pin 不整表重建】用户实测反馈"重点选不上"：pin 后若是 `refresh()`，
选中被清空、右侧动作全灰，看起来就像"没点上"。现在 pin 走**就地更新一行 + 保住选中**。

【kind 预留】本轮只列 M1；M2/M3 在过滤条里**置灰不可选**（数据本身也还没有）——
让"预留"看得见，而不是点进去一个空列表。
"""
from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox, QWidget

from core.preferences import preferences
from data.backtest_archive import KIND_M1, BacktestArchive
from ui.widgets.backtest_history_ui import build_history_layout


class BacktestHistoryView(QWidget):
    """运行历史子页：列表 + 预览 + 动作（读存档、回调 M1 视图）。"""

    def __init__(self, main_win):
        super().__init__()
        self.main_win = main_win
        self.archive = BacktestArchive()

        self._entries: list = []          # 当前过滤后的索引条目
        self._current: dict | None = None  # 当前选中/预览的完整记录

        self._build()
        self._wire()
        self.refresh()

    # ==========================================
    # 装配（版式在 ui/widgets/backtest_history_ui.py）
    # ==========================================
    def _build(self):
        parts = build_history_layout(self)
        self.filter_bar = parts["filter_bar"]
        self.table = parts["table"]
        self.preview = parts["preview"]
        self.settings = parts["settings"]
        self.splitter = parts["splitter"]

        # 常用控件的读写别名（页内与验收断言都按这些名字访问）
        self.cmb_kind = self.filter_bar.cmb_kind
        self.chk_pinned = self.filter_bar.chk_pinned
        self.cmb_symbol = self.filter_bar.cmb_symbol
        self.ed_search = self.filter_bar.ed_search
        self.chk_auto = self.settings.chk_auto
        self.lbl_head = self.preview.lbl_head

        self.chk_auto.blockSignals(True)
        self.chk_auto.setChecked(bool((preferences.get("backtest_archive") or {}).get("auto", True)))
        self.chk_auto.blockSignals(False)

    def _wire(self):
        self.filter_bar.btn_refresh.clicked.connect(self.refresh)
        self.cmb_kind.currentIndexChanged.connect(self.refresh)
        self.chk_pinned.toggled.connect(self.refresh)
        self.cmb_symbol.currentIndexChanged.connect(self.refresh)
        self.ed_search.textChanged.connect(self.refresh)
        self.chk_auto.toggled.connect(self._on_auto_toggled)

        self.table.sig_selection_changed.connect(self._on_selection)

        self.preview.btn_view.clicked.connect(self._on_view)
        self.preview.btn_reuse.clicked.connect(self._on_reuse)
        self.preview.btn_rerun.clicked.connect(self._on_rerun)
        self.preview.btn_send.clicked.connect(self._on_send_to_market)
        self.preview.btn_pin.clicked.connect(self._on_pin)
        self.preview.btn_del.clicked.connect(self._on_delete)

    # ==========================================
    # 列表刷新 / 选中
    # ==========================================
    def refresh(self) -> None:
        """按当前过滤条件重建列表；尽量保住选中项。"""
        kind = self.filter_bar.current_kind() or KIND_M1
        keep_id = self._current.get("id") if self._current else None

        self.filter_bar.set_symbols(self.archive.symbols(kind=kind))
        self._entries = self.archive.list(
            kind=kind,
            symbol=self.filter_bar.current_symbol(),
            keyword=self.ed_search.text().strip(),
            only_pinned=self.chk_pinned.isChecked())
        self.table.populate(self._entries)

        if keep_id and self.table.select_by_id(keep_id):   # 选中恢复会触发 _on_selection
            pass
        else:
            # 必须显式清选中：`setRowCount` 缩表后 Qt 可能把 selection 留在某个下标上，
            # 于是"删掉一行"之后仍然"选中着"另一行 —— 幽灵选中（实测）。
            self.table.clearSelection()
            self._current = None
            self.preview.clear()
        self._refresh_caps()

    def _refresh_caps(self) -> None:
        self.settings.render_caps(BacktestArchive.caps(), self.archive.stats())

    def _on_selection(self) -> None:
        rid = self.table.current_id()
        if not rid:
            self._current = None
            self.preview.clear()
            return
        record = self.archive.load(rid)
        if record is None:                       # 文件恰好被外部删掉：给出诚实提示并刷新
            self.settings.set_receipt("这份存档的文件已不存在，列表已刷新。")
            self.refresh()
            return
        self._current = record
        self.preview.render(record)
        self.preview.set_pinned_state(bool(record.get("pinned")))

    # ==========================================
    # 动作
    # ==========================================
    def _single_view(self):
        return self.main_win.page_backtest.single_view

    def _goto_m1(self) -> None:
        self.main_win.page_backtest.tabs.setCurrentWidget(self._single_view())

    def _on_view(self) -> None:
        """载入查看 = 在 M1 结果区**只读回放**（不覆盖编辑器里正在配的东西）。"""
        if not self._current:
            return
        self._single_view().show_archived(self._current)
        self._goto_m1()
        self.settings.set_receipt("已载入这份存档做只读回放；在结果区点「退出预览」即可回到当前结果。")

    def _on_reuse(self) -> None:
        """复用参数 = 把存档配置灌回 M1 编辑器（不自动跑）。"""
        if not self._current:
            return
        self._single_view().load_archive_config(self._current)
        self._goto_m1()
        self.settings.set_receipt("已把这份存档的参数复用进编辑器，可调整后「▶ 开始回测」。")

    def _on_rerun(self) -> None:
        """重跑 = 复用参数 + 立即按当前行情跑（走 §7-B10 滞后自动补）。"""
        if not self._current:
            return
        view = self._single_view()
        view.load_archive_config(self._current)
        self._goto_m1()
        self.settings.set_receipt("已复用参数并按当前行情重跑（会自动补齐最新数据）…")
        view.start_backtest()

    def _on_send_to_market(self) -> None:
        """把这份存档的函数段送到「📈 市场行情」看图（经主窗口转交，两页互不 import）。"""
        if not self._current:
            return
        meta = self._current.get("meta") or {}
        config = self._current.get("config") or {}
        texts = [t for t in (config.get("segments") or meta.get("segments") or []) if str(t).strip()]
        if not texts:
            QMessageBox.information(self, "暂无函数", "这份存档里没有可送出的函数段。")
            return
        params = str(config.get("params_text") or meta.get("params_text") or "")
        count = self.main_win.send_formula_to_market(texts, params)
        if count:
            self.settings.set_receipt(f"已把 {count} 段函数送到「📈 市场行情」。")

    def _on_pin(self) -> None:
        """标/取消「★ 重点」——**就地更新一行 + 保住选中**（不整表重建）。"""
        if not self._current:
            return
        rid = self._current.get("id")
        pinned = not bool(self._current.get("pinned"))
        if not self.archive.set_pinned(rid, pinned):
            self.settings.set_receipt("标记失败：这份存档文件已不存在。")
            self.refresh()
            return
        self._current["pinned"] = pinned
        self.table.update_row({"id": rid, "pinned": pinned,
                               "source": self._current.get("source")})
        self.preview.set_pinned_state(pinned)
        self.preview.lbl_head.setText(
            self.preview.lbl_head.text().replace(" · ★重点", "") + (" · ★重点" if pinned else ""))
        self.settings.set_receipt("已标为「★ 重点」：不被自动淘汰。" if pinned
                                  else "已取消「★ 重点」。")
        self._refresh_caps()

    def _on_delete(self) -> None:
        if not self._current:
            return
        meta = self._current.get("meta") or {}
        label = (f"{meta.get('name') or ''} {meta.get('symbol') or ''}".strip()
                 or "（未知标的）")
        warn = "\n\n（这是一份 ★重点 存档）" if self._current.get("pinned") else ""
        if QMessageBox.question(
                self, "删除存档",
                f"确认删除这份存档？\n{label} · {self._current.get('created_at') or ''}"
                f"{warn}\n\n删除的是那份不可变快照文件，不影响策略与当前回测。"
        ) != QMessageBox.StandardButton.Yes:
            return
        rid = self._current.get("id")
        ok = self.archive.delete(rid)
        self._current = None
        self.refresh()
        self.settings.set_receipt("已删除这份存档。" if ok else "删除失败：文件已不存在。")

    def _on_auto_toggled(self, on: bool) -> None:
        cfg = dict(preferences.get("backtest_archive") or {})
        cfg["auto"] = bool(on)
        preferences.set("backtest_archive", cfg)
        self.settings.set_receipt(
            "已开启自动存档：每次回测会落一份快照。" if on else "已关闭自动存档（仍可手动存）。")
