# ui/views/backtest_history.py
"""
🗂 运行历史（§7-A4 · v1.37 立 · **v1.46 按样板重做**）—— 市场回测页第 4 个子页。

【本文件是"薄壳"】与 1.22（`ui/views/backtest.py`）/ 1.26（`review.py`）/ STEP 4-5
（`scan_view.py` / `breadth_view.py`）同款约定：**状态与接线留页面、版式与渲染搬模块**。
  · 版式 / 列表 / 预览渲染 → `ui/widgets/backtest_history_ui.py`
  · kind 差异（列 / 过滤轴 / 可用动作）→ `ui/widgets/history_kinds.py`
  · 存档读写 / 淘汰 / 防注入 → `data/backtest_archive.py`
  本页只做四件事：① 把索引喂给列表；② 把动作接到 M1 视图 / M2·M3 扫描页 / 主窗口；
  ③ 维护选中态；④ **把 kind 声明表翻译成界面**（列、过滤轴标题、动作可见性）。

【v1.46 修掉的三处真 bug】
  ① 旧版动作层**没有 kind 守卫** —— 只靠按钮 `setEnabled(False)`；状态一漂移就会拿
     M2 存档去喂 M1 的"只读回放"。现在每个动作**入口先校验 kind**（防御写在页面里）。
  ② 旧版「重跑」对「指数成分」范围**必然点了没反应**（成分股异步解析，`_symbols` 还是空
     ⇒ 早退）+ 同步范围会弹"体检未完成"框。现在走扫描页的 `request_run()`（等名单 + 体检）。
  ③ 旧版自动存档**纯静默**、范围名**丢指数**；两处都在扫描侧修好（`scope_snapshot`）。
"""

from __future__ import annotations

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox, QWidget

from core.preferences import preferences
from data.backtest_archive import KIND_M1, KIND_M2, KIND_M3, BacktestArchive
from ui.widgets.backtest_history_ui import build_history_layout
from ui.widgets.history_kinds import spec_of

_KIND_PAGE = {KIND_M2: "M2 全市场筛选", KIND_M3: "M3 广度统计"}
SEARCH_DEBOUNCE_MS = 220      # 搜索防抖：旧版每敲一个字就重读索引 + 重建整张表


class BacktestHistoryView(QWidget):
    """运行历史子页：列表 + 预览 + 动作（读存档、回调各 kind 的页面）。"""

    def __init__(self, main_win):
        super().__init__()
        self.main_win = main_win
        self.archive = BacktestArchive()

        self._entries: list = []           # 当前过滤后的索引条目
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
        self.cmb_facet = self.filter_bar.cmb_facet
        self.ed_search = self.filter_bar.ed_search
        self.chk_auto = self.settings.chk_auto
        self.lbl_head = self.preview.lbl_head

        self.chk_auto.blockSignals(True)
        self.chk_auto.setChecked(bool((preferences.get("backtest_archive") or {}).get("auto", True)))
        self.chk_auto.blockSignals(False)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self.refresh)

    def _wire(self):
        self.filter_bar.btn_refresh.clicked.connect(self.refresh)
        self.cmb_kind.currentIndexChanged.connect(self.refresh)
        self.chk_pinned.toggled.connect(self.refresh)
        self.cmb_facet.currentIndexChanged.connect(self.refresh)
        self.ed_search.textChanged.connect(lambda _t: self._search_timer.start())
        self.chk_auto.toggled.connect(self._on_auto_toggled)

        self.table.sig_selection_changed.connect(self._on_selection)

        self.preview.action_button('view').clicked.connect(self._on_view)
        self.preview.action_button('reuse').clicked.connect(self._on_reuse)
        self.preview.action_button('rerun').clicked.connect(self._on_rerun)
        self.preview.action_button('send').clicked.connect(self._on_send_to_market)
        self.preview.action_button('pin').clicked.connect(self._on_pin)
        self.preview.action_button('del').clicked.connect(self._on_delete)

    # ==========================================
    # 列表刷新 / 选中
    # ==========================================
    def refresh(self) -> None:
        """按当前过滤条件重建列表；尽量保住选中项。"""
        spec = spec_of(self.cmb_kind.currentData())
        keep_id = self._current.get("id") if self._current else None

        self.filter_bar.apply_spec(spec)
        self.filter_bar.set_options(self.archive.filter_options(kind=spec.kind),
                                    facet_label=spec.facet_label)
        self._entries = self.archive.list(
            kind=spec.kind,
            symbol=self.filter_bar.current_facet() if spec.kind == KIND_M1 else None,
            scope=self.filter_bar.current_facet() if spec.kind != KIND_M1 else None,
            keyword=self.ed_search.text().strip(),
            only_pinned=self.chk_pinned.isChecked())
        self.table.populate(self._entries, spec.kind)

        if keep_id and self.table.select_by_id(keep_id):   # 选中恢复会触发 _on_selection
            pass
        else:
            # 必须显式清选中：`setRowCount` 缩表后 Qt 可能把 selection 留在某个下标上，
            # 于是"删掉一行"之后仍然"选中着"另一行 —— 幽灵选中（实测）。
            self.table.clearSelection()
            self._current = None
            self.preview.clear()
        self._refresh_caps()
        self._maybe_hint_empty(spec)

    def _maybe_hint_empty(self, spec) -> None:
        """列表为空 ⇒ 给**下一步动作**（旧版只有一片空白表头，用户不知道去哪存）。"""
        if self._entries:
            return
        if self.chk_pinned.isChecked():
            self.settings.set_receipt("没有「★ 重点」存档 —— 取消勾选可看全部。")
            return
        if self.ed_search.text().strip() or self.filter_bar.current_facet():
            self.settings.set_receipt("当前过滤下没有存档 —— 清空搜索 / 选「全部」再试。")
            return
        self.settings.set_receipt(
            f"还没有 {spec.tab_label} 的存档 —— 去对应子页跑一次（开着「自动存档」就会出现在这里）。")

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

    def _scan_page_for(self, kind: str):
        """按 kind 找到对应的扫描页（M2 全市场筛选 / M3 广度统计）。"""
        pb = self.main_win.page_backtest
        return pb.page_scan if kind == KIND_M2 else pb.page_breadth if kind == KIND_M3 else None

    def _kind(self) -> str:
        if not self._current:
            return KIND_M1
        return str(self._current.get("kind") or KIND_M1)

    def _goto_m1(self) -> None:
        self.main_win.page_backtest.tabs.setCurrentWidget(self._single_view())

    def _on_view(self) -> None:
        """载入查看 = 在 M1 结果区**只读回放**（只对 M1 有意义：它有净值与逐笔）。"""
        if not self._current:
            return
        if self._kind() != KIND_M1:      # ★v1.46 防御：不靠按钮灰不灰，动作自己校验
            self.settings.set_receipt(
                "这份快照是横截面/广度扫描，没有可回放的净值与逐笔 —— 用「↺ 复用参数」或「▶ 重跑」。")
            return
        self._single_view().show_archived(self._current)
        self._goto_m1()
        self.settings.set_receipt("已载入这份存档做只读回放；在结果区点「退出预览」即可回到当前结果。")

    def _on_reuse(self) -> None:
        """复用参数 = 把存档配置灌回编辑器（不自动跑）。M2/M3 路由到对应扫描页。"""
        if not self._current:
            return
        kind = self._kind()
        if kind in (KIND_M2, KIND_M3):
            page = self._scan_page_for(kind)
            if page is None:
                return
            page.apply_config(self._current.get("config") or {})
            self.main_win.page_backtest.tabs.setCurrentWidget(page)
            self.settings.set_receipt(
                f"已把这份参数复用进「{_KIND_PAGE[kind]}」，可调整后「▶ 开始扫描」。")
            return
        self._single_view().load_archive_config(self._current)
        self._goto_m1()
        self.settings.set_receipt("已把这份存档的参数复用进编辑器，可调整后「▶ 开始回测」。")

    def _on_rerun(self) -> None:
        """重跑 = 复用参数 + 立即跑。★v1.46：M2/M3 走 `request_run()`（等名单/体检就绪）。"""
        if not self._current:
            return
        kind = self._kind()
        if kind in (KIND_M2, KIND_M3):
            page = self._scan_page_for(kind)
            if page is None:
                return
            page.apply_config(self._current.get("config") or {})
            self.main_win.page_backtest.tabs.setCurrentWidget(page)
            self.settings.set_receipt(f"已切到「{_KIND_PAGE[kind]}」并复用参数，开始扫描…")
            page.request_run()
            return
        view = self._single_view()
        view.load_archive_config(self._current)
        self._goto_m1()
        self.settings.set_receipt("已复用参数并按当前行情重跑（会自动补齐最新数据）…")
        view.start_backtest()

    def _formula_payload(self) -> tuple:
        """这份存档要送出行情页的 `(函数段, 参数)` —— **只服务 M1**（§7-B12 P8）。

        M2/M3 是统计口径（一批标的），"送去行情页看单只图"没有意义 ⇒ 动作层直接拒
        （见 `_on_send_to_market`），这里也不再为它们拼装 payload。
        """
        record = self._current or {}
        config = record.get("config") or {}
        meta = record.get("meta") or {}
        texts = [t for t in (config.get("segments") or meta.get("segments") or [])
                 if str(t).strip()]
        return texts, str(config.get("params_text") or meta.get("params_text") or "")

    def _on_send_to_market(self) -> None:
        """把这份存档的函数段送到「📈 市场行情」看图（经主窗口转交，两页互不 import）。

        ⚠ **只对 M1 开放**：M2/M3 是统计口径、不针对个股 —— 动作层**自己校验 kind**
        （不靠"按钮被隐藏/置灰"，§7-B12 P8），被拒时给**诚实回执**而不是静默无反应。
        """
        if not self._current:
            return
        kind = self._kind()
        if kind != KIND_M1:
            self.settings.set_receipt(
                f"「{_KIND_PAGE.get(kind, kind)}」是统计口径（一批标的），不针对个股 —— "
                "没有可送去行情页的单只标的（该动作已仅供单股回测使用）。")
            return
        texts, params = self._formula_payload()
        if not texts:
            QMessageBox.information(self, "暂无函数", "这份存档里没有可送出的函数段。")
            return
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
        kind = self._kind()
        if kind == KIND_M1:
            meta = self._current.get("meta") or {}
            label = (f"{meta.get('name') or ''} {meta.get('symbol') or ''}".strip()
                     or "（未知标的）")
        else:
            scope = self._current.get("scope") or {}
            label = f"{_KIND_PAGE.get(kind, kind)} · {scope.get('label') or '（未知范围）'}"
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
            "已开启自动存档：每次回测 / 扫描会落一份快照。" if on
            else "已关闭自动存档（仍可在结果区「💾 存为历史快照」手动存）。")
