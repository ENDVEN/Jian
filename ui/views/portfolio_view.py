# ui/views/portfolio_view.py
"""🧺 组合页（★1.85 / §7-B17 · **P0 已交付 + P1 净值/持仓**）。

【P0（已交付）】组合列表（新建/删除）· 空态 · **从自选股组导入**（等权）· 保存/重载。
【P1（本期）】**净值曲线**（组合 vs 基准，基期 1.0000 + 总收益/年化/最大回撤）· **持仓表**
（代码/名称/权重/成本/最新/盈亏）。
【P2–P4】市场·行业分布 → 组合回测（含佣金与换手）→ 接 B15 池化。

【成分唯一来源】`main_win.page_market.watchlist`（`data/watchlist_store.WatchlistStore`），**只读**；
组合里只存**组名**（不存名单快照）⇒ 组改名/移组自动跟随；组被删 ⇒ 如实标「来源组已不存在」，**不静默清空**。

【诚实边界（写在卡面上，不藏）】
  · 净值 = **价格收益**（日线收盘 · 前复权）· **未含佣金**（组合回测在 P3 计入换手成本）；
  · 某只票整只没数据 ⇒ 持仓表写「数据不足」，**不当 0 收益**；
  · 图上标"日线（收盘）"，**不做实时**。
"""
from __future__ import annotations

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog,
                             QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                             QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout,
                             QWidget)

from core.portfolio_stats import (annualized, build_returns, holdings_rows, max_drawdown,
                                  nav_series, period_return)
from core.preferences import preferences
from data.market_db import DataLakeManager
from data.portfolio_store import (DEFAULT_BASE, REBALANCE_LABELS, WEIGHT_LABELS,
                                  PortfolioStore, members_from_entries, new_portfolio)
from ui.widgets.chart_host import ChartHost
from ui.widgets.styles import (EMPTY_STATE_QSS, SEC_HINT_QSS, SEC_TITLE_QSS,
                               SUMMARY_GHOST_QSS, SUMMARY_RUN_QSS, TABLE_HEAD_QSS,
                               WARN_HINT_QSS)
from ui.widgets.sweep_parts import panel_card, panel_head

UI_PREF_KEY = "portfolios_ui"
BASE_COLORS = {"nav": "#1976D2", "base": "#9AA6B8"}


class PortfolioView(QWidget):
    """组合页（P0 + P1）。宿主 = `JianMainWindow`。"""

    def __init__(self, main_win, parent=None):
        super().__init__(parent)
        self.main_win = main_win
        self._store = PortfolioStore()
        self._lake = DataLakeManager()
        self._current = ""
        self._cache = {}          # symbols 元组 → {symbol: DataFrame}
        self._nav = None          # 最近一次算出的净值（Series）—— 断言与调试都读它
        self._build()
        self._load_ui()
        self.refresh()

    # ================= 版式 =================
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("🧺 组合")
        title.setStyleSheet(SEC_TITLE_QSS + "font-size:15px;")
        head.addWidget(title)
        hint = QLabel("把「自选股组」变成可回测的组合 —— 成分只引用组，不复制名单")
        hint.setStyleSheet(SEC_HINT_QSS)
        head.addWidget(hint, 1)
        self.btn_new = QPushButton("＋ 新建组合")
        self.btn_new.setStyleSheet(SUMMARY_GHOST_QSS)
        self.btn_new.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_new.setToolTip("先建一个空组合，之后再导入成分")
        self.btn_new.clicked.connect(self._on_new)
        head.addWidget(self.btn_new)
        self.btn_import = QPushButton("↻ 从自选股组导入")
        self.btn_import.setStyleSheet(SUMMARY_RUN_QSS)
        self.btn_import.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_import.setToolTip("读行情页「自选股 → 组」的成分，按**等权**生成组合（只读，不改自选）")
        self.btn_import.clicked.connect(self._on_import)
        head.addWidget(self.btn_import)
        self.btn_del = QPushButton("删除")
        self.btn_del.setStyleSheet(SUMMARY_GHOST_QSS)
        self.btn_del.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_del.setEnabled(False)
        self.btn_del.clicked.connect(self._on_delete)
        head.addWidget(self.btn_del)
        root.addLayout(head)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)

        # ---- 左：组合列表 ----
        left = panel_card()
        bl = QVBoxLayout(left)
        bl.setContentsMargins(10, 8, 10, 10)
        bl.setSpacing(6)
        bl.addWidget(panel_head("我的组合", "新 → 旧"))
        self.lst = QListWidget()
        self.lst.setStyleSheet("QListWidget { border: 1px solid #EDF0F5; border-radius: 8px; }")
        self.lst.currentItemChanged.connect(self._on_select)
        bl.addWidget(self.lst, 1)
        left.setMinimumWidth(200)   # ★1.85：240→200（1000 窗不出横条）
        left.setMaximumWidth(300)
        grid.addWidget(left, 0, 0)

        # ---- 右：空态 / 详情 ----
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(10)

        self.empty = QFrame(right)
        el = QVBoxLayout(self.empty)
        el.setContentsMargins(0, 0, 0, 0)
        el.setSpacing(10)
        self.lbl_empty = QLabel(
            "还没有组合。\n\n"
            "「组合」= 一组标的 + 权重 + 基准 + 再平衡规则。\n"
            "成分来源只有一处：<b>行情页 → 自选股 → 组</b>（这里只引用，不复制名单）。")
        self.lbl_empty.setWordWrap(True)
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty.setStyleSheet(EMPTY_STATE_QSS)
        el.addWidget(self.lbl_empty, 1)
        self.btn_empty_import = QPushButton("↻ 从自选股组导入")
        self.btn_empty_import.setStyleSheet(SUMMARY_RUN_QSS)
        self.btn_empty_import.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_empty_import.clicked.connect(self._on_import)
        el.addWidget(self.btn_empty_import, 0, Qt.AlignmentFlag.AlignCenter)
        rl.addWidget(self.empty, 1)

        self.detail = QFrame(right)
        dl = QVBoxLayout(self.detail)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(10)

        # ① 设置摘要
        self.card_sum = panel_card()
        sl = QVBoxLayout(self.card_sum)
        sl.setContentsMargins(10, 8, 10, 10)
        sl.setSpacing(6)
        self.sum_head = panel_head("组合设置", "")
        sl.addWidget(self.sum_head)
        self.lbl_sum = QLabel("")
        self.lbl_sum.setWordWrap(True)
        self.lbl_sum.setStyleSheet(SEC_HINT_QSS)
        sl.addWidget(self.lbl_sum)
        self.lbl_warn = QLabel("")
        self.lbl_warn.setWordWrap(True)
        self.lbl_warn.setStyleSheet(WARN_HINT_QSS)
        self.lbl_warn.hide()
        sl.addWidget(self.lbl_warn)
        dl.addWidget(self.card_sum)

        # ② 净值曲线（P1）
        self.card_nav = panel_card()
        nl = QVBoxLayout(self.card_nav)
        nl.setContentsMargins(10, 8, 10, 10)
        nl.setSpacing(6)
        self.nav_head = panel_head("净值曲线", "日线（收盘）· 基期 1.0000")
        nl.addWidget(self.nav_head)
        self.lbl_nav_meta = QLabel("")
        self.lbl_nav_meta.setWordWrap(True)
        self.lbl_nav_meta.setStyleSheet(SEC_HINT_QSS)
        nl.addWidget(self.lbl_nav_meta)
        self.chart = ChartHost(self)
        self.chart.setMinimumHeight(220)
        self.chart.setMaximumHeight(300)
        nl.addWidget(self.chart, 1)
        self.lbl_nav_note = QLabel("")
        self.lbl_nav_note.setWordWrap(True)
        self.lbl_nav_note.setStyleSheet(SEC_HINT_QSS)
        nl.addWidget(self.lbl_nav_note)
        dl.addWidget(self.card_nav, 1)

        # ③ 持仓表（P1）
        self.card_hold = panel_card()
        hl = QVBoxLayout(self.card_hold)
        hl.setContentsMargins(10, 8, 10, 10)
        hl.setSpacing(6)
        self.hold_head = panel_head("持仓", "")
        hl.addWidget(self.hold_head)
        self.tbl_hold = QTableWidget(0, 6)
        self.tbl_hold.setHorizontalHeaderLabels(["代码", "名称", "权重 %", "成本", "最新", "盈亏 %"])
        self.tbl_hold.verticalHeader().setVisible(False)
        self.tbl_hold.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl_hold.setStyleSheet(TABLE_HEAD_QSS)
        self.tbl_hold.setMinimumHeight(140)
        _h = self.tbl_hold.horizontalHeader()
        _h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        _h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for _c in (2, 3, 4, 5):
            _h.setSectionResizeMode(_c, QHeaderView.ResizeMode.ResizeToContents)
        hl.addWidget(self.tbl_hold, 1)
        dl.addWidget(self.card_hold, 1)

        # ④ 成分（P0；保留：来源组删掉时仍能看到上次导入的成分）
        self.card_mem = panel_card()
        ml = QVBoxLayout(self.card_mem)
        ml.setContentsMargins(10, 8, 10, 10)
        ml.setSpacing(6)
        self.mem_head = panel_head("成分（导入时快照）", "")
        ml.addWidget(self.mem_head)
        self.tbl = QTableWidget(0, 3)
        self.tbl.setHorizontalHeaderLabels(["代码", "名称", "权重 %"])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl.setStyleSheet(TABLE_HEAD_QSS)
        self.tbl.setMinimumHeight(120)
        _h2 = self.tbl.horizontalHeader()
        _h2.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        _h2.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        _h2.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        ml.addWidget(self.tbl, 1)
        dl.addWidget(self.card_mem, 0)

        # ★1.85 P1：卡片变多了（设置/净值/持仓/成分）⇒ 详情列**必须能纵向滚**。
        #   本项目踩过"容器关掉滚动条 ⇒ 内容够不到"的坑（§11.5-137）：宁可出现滚动条，也不许看不见。
        _sa = QScrollArea(right)
        _sa.setWidgetResizable(True)
        _sa.setFrameShape(QFrame.Shape.NoFrame)
        _sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        _sa.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        _sa.setWidget(self.detail)
        self._detail_scroll = _sa
        rl.addWidget(_sa, 1)
        grid.addWidget(right, 0, 1)
        root.addLayout(grid, 1)

        self.detail.hide()

    # ================= 数据 =================
    def _watchlist(self):
        """成分来源（只读门面）—— 从行情页拿，**不自己建第二份**。"""
        page = getattr(self.main_win, "page_market", None)
        return getattr(page, "watchlist", None) if page is not None else None

    def refresh(self) -> None:
        """重读存储 + 重建列表（选中项尽量保持）。"""
        items = self._store.list()
        keep = self._current
        self.lst.blockSignals(True)
        self.lst.clear()
        for p in items:
            group = str(p.get("source_group") or "")
            missing = bool(group) and not self._group_exists(group)
            text = f"{p.get('name')}\n来源组：{group or '（未指定）'}" + ("（已不存在）" if missing else "")
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, str(p.get("id")))
            if missing:
                it.setToolTip("行情页里找不到这个自选股组了 —— 成分不再自动更新（点开看说明）")
            self.lst.addItem(it)
        self.lst.blockSignals(False)
        if not items:
            self._current = ""
            self.detail.hide()
            self.empty.show()
            self.btn_del.setEnabled(False)
            return
        row = 0
        for i in range(self.lst.count()):
            if self.lst.item(i).data(Qt.ItemDataRole.UserRole) == keep:
                row = i
                break
        self.lst.setCurrentRow(row)
        self._on_select(self.lst.currentItem(), None)

    def _group_exists(self, group: str) -> bool:
        wl = self._watchlist()
        try:
            return bool(wl is not None and group and group in (wl.groups() or []))
        except Exception:                      # noqa: BLE001
            return False

    def _frames(self, symbols) -> dict:
        """按需读日线（缓存：同一批标的只读一次）。缺失的票**不进** dict（由界面写"数据不足"）。"""
        key = tuple(str(s) for s in symbols)
        if key in self._cache:
            return self._cache[key]
        out = {}
        for s in key:
            try:
                df = self._lake.load_data("kline_daily", s)
            except Exception:                  # noqa: BLE001 —— 读失败按"没有数据"处理，如实显示
                df = None
            if df is not None and len(df):
                out[s] = df
        self._cache[key] = out
        return out

    def _on_select(self, cur, _prev) -> None:
        if cur is None:
            return
        pid = str(cur.data(Qt.ItemDataRole.UserRole) or "")
        p = self._store.load_one(pid) if pid else None
        if not p:
            return
        self._current = pid
        self.btn_del.setEnabled(True)
        self.empty.hide()
        self.detail.show()
        self._render(p)
        self._save_ui()

    def _render(self, p: dict) -> None:
        group = str(p.get("source_group") or "")
        members = p.get("members") or []
        base = p.get("base") or DEFAULT_BASE
        self.sum_head.title_label.setText(str(p.get("name") or "组合"))
        self.sum_head.meta_label.setText(f"共 {len(members)} 只 · {WEIGHT_LABELS.get(p.get('weight_mode'), '等权')}")
        self.lbl_sum.setText(
            f"来源组：<b>{group or '（未指定）'}</b>　·　"
            f"权重：<b>{WEIGHT_LABELS.get(p.get('weight_mode'), '等权')}</b>　·　"
            f"现金：<b>{float(p.get('cash') or 0):.2f}%</b>　·　"
            f"基准：<b>{base.get('name') or base.get('code')}</b>　·　"
            f"再平衡：<b>{REBALANCE_LABELS.get(p.get('rebalance'), '买入持有')}</b>"
            f"<br>成本口径：回测佣金（全局设置）—— 本页净值**不含佣金**（组合回测在 P3 计入换手成本）")
        missing = bool(group) and not self._group_exists(group)
        if missing:
            self.lbl_warn.setText("⚠ 来源组「" + group + "」在行情页已不存在（被删或改名）—— "
                                 "成分不会自动更新；请重新「从自选股组导入」，或先在行情页恢复该组。")
            self.lbl_warn.show()
        else:
            self.lbl_warn.hide()

        # 成分快照（P0 的导入结果；与持仓表的分工：这里是"当时导入了什么"，持仓表是"现在值多少"）
        self.mem_head.meta_label.setText(
            f"{len(members)} 只 · 合计 {sum(float(m.get('weight') or 0) for m in members):.2f}%")
        self.tbl.setRowCount(len(members))
        for r, m in enumerate(members):
            vals = [str(m.get("symbol") or ""), str(m.get("name") or ""), f"{float(m.get('weight') or 0):.2f}"]
            for c, txt in enumerate(vals):
                it = QTableWidgetItem(txt)
                if c == 2:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.tbl.setItem(r, c, it)
        self._render_p1(p)

    # ---------------- P1：净值 + 持仓 ----------------
    def _render_p1(self, p: dict) -> None:
        members = p.get("members") or []
        symbols = [str(m.get("symbol")) for m in members]
        names = {str(m.get("symbol")): str(m.get("name") or "") for m in members}
        weights = {str(m.get("symbol")): float(m.get("weight") or 0.0) for m in members}
        frames = self._frames(symbols) if symbols else {}
        self._nav = None
        self.chart.clear()
        if not symbols:
            self.nav_head.meta_label.setText("还没有成分")
            self.lbl_nav_meta.setText("先「↻ 从自选股组导入」—— 没有成分时**不画线**。")
            self.lbl_nav_note.setText("")
            self.hold_head.meta_label.setText("0 只")
            self.tbl_hold.setRowCount(0)
            return

        days, rets = build_returns(frames)
        missing = [s for s in symbols if s not in frames]
        if not days:
            self.nav_head.meta_label.setText("数据不足")
            self.lbl_nav_meta.setText(
                f"本机日线里没有这 {len(symbols)} 只的数据 —— 先去 🗄 数据管理 预下载（**不拿假数据凑图**）。")
            self.lbl_nav_note.setText("")
            self.hold_head.meta_label.setText(f"{len(symbols)} 只 · 全部缺数据")
            self._fill_holdings(holdings_rows(symbols, names, weights, {}, {}))
            return

        # ★1.85 · **诚实规则**：只要有成员**整只**没有数据 ⇒ **不画组合线**。
        #   `nav_series` 只会拿"有数据的"归一成 100% ⇒ 等于用剩余权重冒充整个组合（假净值）。
        if missing:
            self.nav_head.meta_label.setText(f"缺 {len(missing)} 只 · 不画")
            _miss_txt = "、".join(missing[:4]) + ("…" if len(missing) > 4 else "")
            self.lbl_nav_meta.setText(
                f"有 {len(missing)} 只在本机没有日线（{_miss_txt}）⇒ <b>不画组合线</b>："
                "用剩下的权重归一去画，等于把整个组合换成了另一只组合。"
                "先去 🗄 数据管理 补齐，再回来看。")
            self.lbl_nav_note.setText("")
            _fc, _lc = {}, {}
            for _s in symbols:
                _df = frames.get(_s)
                if _df is not None and len(_df):
                    try:
                        _fc[_s] = float(_df["close"].iloc[0])
                        _lc[_s] = float(_df["close"].iloc[-1])
                    except Exception:      # noqa: BLE001
                        pass
            self._fill_holdings(holdings_rows(symbols, names, weights, _fc, _lc))
            self.hold_head.meta_label.setText(
                f"{len(symbols)} 只 · 有数据 {len(_fc)} 只 · 合计 "
                f"{sum(float(w) for w in weights.values()):.2f}%")
            return

        nav = nav_series(days, rets, weights, float(p.get("cash") or 0.0),
                         str(p.get("rebalance") or "monthly"))
        self._nav = nav
        tot, ann, dd = period_return(nav), annualized(nav), max_drawdown(nav)
        self.nav_head.meta_label.setText(
            f"{len(days)} 个交易日 · {days[0]} → {days[-1]}" + (f" · 缺 {len(missing)} 只" if missing else ""))

        # 画线：组合 + 基准（基准有数据才画，**没有就不画**）
        # ⚠ `main_pane` / `plot_item` 都是 **property**（不是方法）—— 写成 `()` 会 TypeError
        pi = self.chart.main_pane.plot_item
        x = np.arange(len(nav), dtype=float)
        pi.plot(x, nav.to_numpy(dtype=float), pen={"color": BASE_COLORS["nav"], "width": 2},
                name="组合")
        base_name = ""
        try:
            bdf = self._lake.load_data("kline_daily", str((p.get("base") or {}).get("code") or ""))
        except Exception:                      # noqa: BLE001
            bdf = None
        if bdf is not None and len(bdf):
            bdays, brets = build_returns({"base": bdf})
            if bdays:
                _fill = {d: 0.0 for d in nav.index}
                _fill.update(brets["base"].to_dict())
                bnav = (1.0 + np.array([_fill.get(d, 0.0) for d in nav.index])).cumprod()
                pi.plot(x, bnav, pen={"color": BASE_COLORS["base"], "width": 1.6}, name="基准")
                base_name = str((p.get("base") or {}).get("name") or "")
        # 稀疏日期刻度（最多 6 个）
        step = max(1, len(nav) // 6)
        ticks = [(float(i), str(nav.index[i])[5:]) for i in range(0, len(nav), step)]
        pi.getAxis("bottom").setTicks([ticks])
        pi.showGrid(x=False, y=True, alpha=0.15)
        pi.setLabel("left", "净值（基期 1.0000）")
        self.lbl_nav_meta.setText(
            f"总收益 <b>{self._pct(tot)}</b>　·　年化 <b>{self._pct(ann)}</b>　·　"
            f"最大回撤 <b>{self._pct(-dd if dd == dd else float('nan'))}</b>　·　"
            f"基准 <b>{base_name or '（本机无数据）'}</b>")
        self.lbl_nav_note.setText(
            "口径：日线收盘（前复权）· 权重 = " + WEIGHT_LABELS.get(p.get("weight_mode"), "等权")
            + " · 再平衡 = " + REBALANCE_LABELS.get(p.get("rebalance"), "买入持有")
            + f" · 现金 {float(p.get('cash') or 0):.2f}%　·　<b>未含佣金</b>（P3 组合回测才会计入换手成本）"
            + (f"　·　⚠ {len(missing)} 只没有数据（已从曲线与持仓中如实标注）" if missing else ""))

        # 持仓：成本 = 基期收盘、最新 = 最后收盘
        first_close, last_close = {}, {}
        for s in symbols:
            df = frames.get(s)
            if df is None or not len(df):
                continue
            try:
                first_close[s] = float(df["close"].iloc[0])
                last_close[s] = float(df["close"].iloc[-1])
            except Exception:                  # noqa: BLE001
                continue
        rows = holdings_rows(symbols, names, weights, first_close, last_close)
        self._fill_holdings(rows)
        ok = sum(1 for r in rows if r.get("data_ok"))
        self.hold_head.meta_label.setText(f"{len(rows)} 只 · 有权重 {ok} 只 · 合计 "
                                          f"{sum(float(r.get('weight') or 0) for r in rows):.2f}%")

    def _fill_holdings(self, rows) -> None:
        self.tbl_hold.setRowCount(len(rows))
        for r, row in enumerate(rows):
            ok = bool(row.get("data_ok"))
            vals = [row.get("symbol") or "", row.get("name") or "",
                    f"{float(row.get('weight') or 0):.2f}",
                    f"{row['cost']:.3f}" if ok else "数据不足",
                    f"{row['last']:.3f}" if ok else "数据不足",
                    self._pct(row.get("pnl")) if ok else "—"]
            for c, txt in enumerate(vals):
                it = QTableWidgetItem(txt)
                if c >= 2:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if not ok and c >= 3:
                    it.setToolTip("这只票在本机数据湖里没有日线 —— 不拿 0 冒充（§10-4）")
                self.tbl_hold.setItem(r, c, it)

    @staticmethod
    def _pct(v) -> str:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return "—"
        return "—" if f != f else f"{f * 100:+.2f}%"

    # ================= 动作 =================
    def _on_new(self) -> None:
        name, ok = QInputDialog.getText(self, "新建组合", "组合名称：", text="新组合")
        if not ok or not str(name).strip():
            return
        pf = new_portfolio(str(name).strip(), "", [])
        if self._store.save(pf):
            self._current = pf["id"]
            self.refresh()

    def _on_import(self) -> None:
        wl = self._watchlist()
        if wl is None:
            QMessageBox.information(self, "暂时读不到自选股",
                                    "行情页还没准备好自选股存储 —— 切到「市场行情」再回来。")
            return
        try:
            groups = list(wl.groups() or [])
        except Exception as e:                 # noqa: BLE001
            QMessageBox.warning(self, "读自选股组失败", str(e))
            return
        if not groups:
            QMessageBox.information(self, "还没有自选股组",
                                    "先去「市场行情 → 自选股」建一个组并加几只票，再回来导入。")
            return
        group, ok = QInputDialog.getItem(self, "从自选股组导入", "选择自选股组：", groups, 0, False)
        if not ok or not group:
            return
        try:
            entries = wl.entries_in(str(group)) or []
        except Exception as e:                 # noqa: BLE001
            QMessageBox.warning(self, "读组成分失败", str(e))
            return
        members = members_from_entries(entries)
        if not members:
            QMessageBox.information(self, "这个组还没有成分",
                                    f"「{group}」里没有股票 —— 先在行情页把票加进这个组。")
            return
        name, ok2 = QInputDialog.getText(self, "命名组合", "组合名称：", text=str(group))
        if not ok2 or not str(name).strip():
            return
        pf = new_portfolio(str(name).strip(), str(group), members)
        if self._store.save(pf):
            self._current = pf["id"]
            self.refresh()
        else:
            QMessageBox.warning(self, "保存失败", "组合没能写入磁盘（详见日志）。")

    def _on_delete(self) -> None:
        if not self._current:
            return
        p = self._store.load_one(self._current)
        if not p:
            return
        if QMessageBox.question(self, "删除组合",
                                f"确定删除「{p.get('name')}」？\n（只删组合本身，**不动自选股组**）") \
                != QMessageBox.StandardButton.Yes:
            return
        if self._store.delete(self._current):
            self._current = ""
            self.refresh()

    # ================= 偏好 =================
    def _load_ui(self) -> None:
        try:
            data = preferences.get(UI_PREF_KEY) or {}
            self._current = str(data.get("last") or "")
        except Exception:                     # noqa: BLE001
            self._current = ""

    def _save_ui(self) -> None:
        try:
            preferences.set(UI_PREF_KEY, {"last": str(self._current or "")})
        except Exception:                     # noqa: BLE001
            pass


__all__ = ["PortfolioView", "UI_PREF_KEY"]
