# ui/dialogs/portfolio_edit.py
"""🧺 组合「编辑成分」对话框（★1.87 补漏：**手工增删改成分**）。

【为什么必须补】P0 只做了"从自选股组导入"一条路 —— 用户建了空组合后**没有任何办法**把票加进去
（"麟平组合 0 只"就是这么来的）。导入是"整组搬"，本对话框是"逐只调"，两者互补。

【口径（不许静默改数）】
  · 权重合计 + 现金 **必须 = 100.00%**，差一点就拦下并给出「一键归一」；
  · 「等权」= `(100 − 现金) / n`（余数补第一个，保证 100.00）；
  · **市值权重**目前只做"占位"：本机没有市值快照 ⇒ 选它会**明确说明**"按等权占位，市值接入后生效"，
    绝不假装算过（§10-4）；
  · 改完只在"确定"时写回，取消零副作用。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QComboBox, QDialog, QDoubleSpinBox, QHBoxLayout, QHeaderView,
                             QLineEdit, QSizePolicy,
                             QInputDialog, QLabel, QMessageBox, QPushButton,
                             QTableWidget, QTableWidgetItem, QVBoxLayout)

from core.portfolio_stats import market_of
from data.portfolio_store import (DEFAULT_BASE, REBALANCE_LABELS, WEIGHT_LABELS,
                                  normalize_weights)
from data.watchlist_store import WatchlistStore

_QSS = (
    "QDialog { background:#F7F9FC; }"
    "QLabel { color:#3A4250; font-size:12.5px; }"
    "QTableWidget { background:white; border:1px solid #E4E9F0; border-radius:9px;"
    " gridline-color:#F1F4F9; font-size:12.5px; }"
    "QHeaderView::section { background:#F7F9FC; border:none; border-bottom:1px solid #E4E9F0;"
    " padding:6px 8px; color:#7A8598; font-weight:600; }")
_BTN = ("QPushButton { background:#F5F5F5; border:1px solid #E0E0E0; border-radius:6px;"
        " padding:7px 14px; color:#424242; }QPushButton:hover { background:#EDEDED; }")
_BTN_P = ("QPushButton { background:#1976D2; color:white; border:none; border-radius:6px;"
          " padding:8px 18px; font-weight:bold; }QPushButton:hover { background:#1565C0; }"
          "QPushButton:disabled { background:#B9CFE6; color:#EEF4FB; }")


class PortfolioEditDialog(QDialog):
    """编辑一个组合的成分与权重（返回**新的** portfolio 字典，不改入参）。"""

    def __init__(self, portfolio: dict, parent=None, name_lookup=None):
        super().__init__(parent)
        self._pf = dict(portfolio)
        self._lookup = name_lookup        # 外部注入的"代码→名称"（组合页给的是花名册门面）
        self._members = [dict(m) for m in (portfolio.get("members") or [])]
        self.setWindowTitle(f"编辑成分 · {portfolio.get('name') or '组合'}")
        self.setMinimumWidth(560)
        self.setStyleSheet(_QSS)
        self._build()
        self._fill()

    # ---------------- 版式 ----------------
    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(9)

        tip = QLabel("加/减标的、改权重。**合计（含现金）必须 = 100.00%**；改完点「确定」才生效。")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.btn_add = QPushButton("＋ 添加代码")
        self.btn_add.setStyleSheet(_BTN)
        self.btn_add.clicked.connect(self._on_add)
        row.addWidget(self.btn_add)
        self.btn_del = QPushButton("－ 删除选中")
        self.btn_del.setStyleSheet(_BTN)
        self.btn_del.clicked.connect(self._on_del)
        row.addWidget(self.btn_del)
        self.btn_equal = QPushButton("一键等权")
        self.btn_equal.setStyleSheet(_BTN)
        self.btn_equal.setToolTip("按 (100 − 现金) / 只数 平均分配，余数补第一只，保证合计 100.00%")
        self.btn_equal.clicked.connect(self._on_equal)
        row.addWidget(self.btn_equal)
        row.addStretch(1)
        row.addWidget(QLabel("权重模式："))
        self.cmb_mode = QComboBox()
        for key in ("equal", "cap", "custom"):
            self.cmb_mode.addItem(WEIGHT_LABELS[key], key)
        self.cmb_mode.currentIndexChanged.connect(self._on_mode)
        row.addWidget(self.cmb_mode)
        lay.addLayout(row)

        self.tbl = QTableWidget(0, 4)
        self.tbl.setHorizontalHeaderLabels(["代码", "名称", "权重 %", "市场"])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        # ★1.87：**表格必须吃满宽度**（否则窗口拉大后右侧一大片空白，用户实测）
        self.tbl.setMinimumHeight(220)
        _h = self.tbl.horizontalHeader()
        _h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        _h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        _h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        _h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.tbl.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self.tbl, 1)

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        row2.addWidget(QLabel("现金："))
        self.sp_cash = QDoubleSpinBox()
        self.sp_cash.setRange(0.0, 100.0)
        self.sp_cash.setDecimals(2)
        self.sp_cash.setSuffix(" %")
        self.sp_cash.valueChanged.connect(self._refresh_total)
        row2.addWidget(self.sp_cash)
        self.lbl_total = QLabel("")
        self.lbl_total.setWordWrap(True)
        row2.addWidget(self.lbl_total, 1)
        lay.addLayout(row2)

        # ---- 组合设置（★1.87：基准可选指数/个股 · 再平衡 买入持有/按月）----
        cand = QHBoxLayout()
        cand.setSpacing(6)
        cand.addWidget(QLabel("基准"))
        self.in_base_code = QLineEdit()
        self.in_base_code.setPlaceholderText("代码（如 000300 / 600519）")
        self.in_base_code.setMaximumWidth(150)
        cand.addWidget(self.in_base_code)
        self.in_base_name = QLineEdit()
        self.in_base_name.setPlaceholderText("名称（留空则自动/用代码）")
        cand.addWidget(self.in_base_name, 1)
        for _code, _name in (("000300", "沪深300"), ("000905", "中证500"),
                             ("000001", "上证指数")):
            _b = QPushButton(_name)
            _b.setStyleSheet(_BTN)
            _b.setCursor(Qt.CursorShape.PointingHandCursor)
            _b.clicked.connect(lambda _c=False, c=_code, n=_name: (
                self.in_base_code.setText(c), self.in_base_name.setText(n)))
            cand.addWidget(_b)
        lay.addLayout(cand)
        reb = QHBoxLayout()
        reb.setSpacing(6)
        reb.addWidget(QLabel("再平衡"))
        self.cmb_reb = QComboBox()
        for _k, _t in (("buy_hold", "买入持有（不再平衡）"), ("monthly", "按月再平衡")):
            self.cmb_reb.addItem(_t, _k)
        reb.addWidget(self.cmb_reb)
        reb.addStretch(1)
        lay.addLayout(reb)

        row3 = QHBoxLayout()
        row3.addStretch(1)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setStyleSheet(_BTN)
        self.btn_cancel.clicked.connect(self.reject)
        row3.addWidget(self.btn_cancel)
        self.btn_ok = QPushButton("确定")
        self.btn_ok.setStyleSheet(_BTN_P)
        self.btn_ok.clicked.connect(self._on_ok)
        row3.addWidget(self.btn_ok)
        lay.addLayout(row3)

    # ---------------- 数据 ----------------
    def _names(self) -> dict:
        """名称：**自选股映射 + 花名册**（后者由组合页注入）。

        ★1.87：只用自选股映射 ⇒ 手工加的票名字永远是空的（用户实测）。
        """
        out = {}
        try:
            out.update(WatchlistStore().names_map() or {})
        except Exception:                      # noqa: BLE001
            pass
        if callable(self._lookup):
            try:
                for s in [m.get("symbol") for m in self._members]:
                    if s and not out.get(str(s)):
                        n = str(self._lookup(str(s)) or "")
                        if n:
                            out[str(s)] = n
            except Exception:                  # noqa: BLE001
                pass
        return out

    def _fill(self) -> None:
        mode = str(self._pf.get("weight_mode") or "equal")
        idx = max(0, self.cmb_mode.findData(mode))
        self.cmb_mode.blockSignals(True)
        self.cmb_mode.setCurrentIndex(idx)
        self.cmb_mode.blockSignals(False)
        self.sp_cash.blockSignals(True)
        self.sp_cash.setValue(float(self._pf.get("cash") or 0.0))
        self.sp_cash.blockSignals(False)
        _base = self._pf.get("base") or DEFAULT_BASE
        self.in_base_code.setText(str(_base.get("code") or ""))
        self.in_base_name.setText(str(_base.get("name") or ""))
        _ri = max(0, self.cmb_reb.findData(str(self._pf.get("rebalance") or "monthly")))
        self.cmb_reb.setCurrentIndex(_ri)
        self._render_rows()
        self._refresh_total()

    def _render_rows(self) -> None:
        self.tbl.blockSignals(True)
        self.tbl.setRowCount(len(self._members))
        _nm = self._names()          # ★1.87：名称列必须走这里（否则手工加的票永远空着）
        for r, m in enumerate(self._members):
            _sym = str(m.get("symbol") or "")
            for c, txt in enumerate([_sym, str(m.get("name") or _nm.get(_sym) or ""),
                                     f"{float(m.get('weight') or 0):.2f}",
                                     {"sh": "沪", "sz": "深", "bj": "北", "other": "其他"}
                                     .get(market_of(m.get("symbol")), "其他")]):
                it = QTableWidgetItem(txt)
                if c >= 2:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if c in (0, 1, 3):
                    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.tbl.setItem(r, c, it)
        self.tbl.blockSignals(False)
        # 反写名字（只补空值；不覆盖用户已有名称）
        for m in self._members:
            if not str(m.get("name") or "").strip():
                n = _nm.get(str(m.get("symbol") or ""))
                if n:
                    m["name"] = n

    def _refresh_total(self) -> None:
        total = sum(float(m.get("weight") or 0.0) for m in self._members) + float(self.sp_cash.value())
        ok = abs(total - 100.0) < 0.05
        self.lbl_total.setText(
            f"合计（含现金）<b>{total:.2f}%</b>" + ("　✓" if ok else "　⚠ 必须 = 100.00%"))
        self.lbl_total.setStyleSheet("font-size:12.5px;color:%s;" % ("#2E7D32" if ok else "#C62828"))
        self.btn_ok.setEnabled(ok and bool(self._members))

    # ---------------- 交互 ----------------
    def _on_item_changed(self, item) -> None:
        if item is None or item.column() != 2:
            return
        try:
            val = max(0.0, float(str(item.text()).replace("%", "").strip() or 0))
        except ValueError:
            val = 0.0
        self._members[item.row()]["weight"] = round(val, 2)
        # 手改权重 ⇒ 模式自动降级为"自定义"（**不许**标着等权却各不相等）
        if self.cmb_mode.currentData() != "custom":
            self.cmb_mode.blockSignals(True)
            self.cmb_mode.setCurrentIndex(self.cmb_mode.findData("custom"))
            self.cmb_mode.blockSignals(False)
        self._refresh_total()

    def _on_mode(self, _idx) -> None:
        mode = self.cmb_mode.currentData()
        if mode == "cap":
            QMessageBox.information(
                self, "市值权重暂未接入",
                "本机还没有市值快照 ⇒ 先按**等权占位**，市值接入（P2）后生效。\n"
                "口径不假装：这一档现在不会替你「按市值算」。")
            self._on_equal()
            self.cmb_mode.blockSignals(True)
            self.cmb_mode.setCurrentIndex(self.cmb_mode.findData("custom"))
            self.cmb_mode.blockSignals(False)
            return
        if mode == "equal":
            self._on_equal()
        self._refresh_total()

    def _on_equal(self) -> None:
        n = len(self._members)
        if not n:
            return
        cash = float(self.sp_cash.value())
        target = max(0.0, 100.0 - cash)
        each = round(target / n, 2)
        for m in self._members:
            m["weight"] = each
        self._members[0]["weight"] = round(target - each * (n - 1), 2)
        self._render_rows()
        self._refresh_total()

    def _on_add(self) -> None:
        code, ok = QInputDialog.getText(self, "添加成分", "股票/ETF 代码（6 位）：")
        code = str(code or "").strip()
        if not ok or not code:
            return
        if any(str(m.get("symbol")) == code for m in self._members):
            QMessageBox.information(self, "已经在了", f"{code} 已在这个组合里。")
            return
        name = str(self._names().get(code) or "")
        # TODO(市值 P2)：`weight_mode='cap'` 的**真实实现**要接市值数据源
        #   （`engine` 的 spot 估值/东财快照）。现在选「市值」只作占位并明确提示，
        #   **绝不拿假市值算权重**。接线点：本文件 `_on_mode()` + `data/portfolio_store.WEIGHT_MODES`。
        # 新票权重先给"剩下的"，再由用户/等权调整
        used = sum(float(m.get("weight") or 0.0) for m in self._members)
        rest = max(0.0, 100.0 - float(self.sp_cash.value()) - used)
        self._members.append({"symbol": code, "name": name, "weight": round(rest, 2)})
        self._render_rows()
        self._refresh_total()

    def _on_del(self) -> None:
        rows = sorted({i.row() for i in self.tbl.selectedIndexes()}, reverse=True)
        if not rows:
            QMessageBox.information(self, "没选", "先在表格里点一行（可 Ctrl/Shift 多选）。")
            return
        for r in rows:
            if 0 <= r < len(self._members):
                self._members.pop(r)
        self._render_rows()
        self._refresh_total()

    def _on_ok(self) -> None:
        members = [dict(m) for m in self._members]
        # ★1.89：**不再自动归一**。旧版先按 (100 − 现金) 把成员拉满 ⇒ 合计永远 = 100，
        #   "差额留作现金"这条分支永远走不到（用户实测）。现在差额由用户选。
        self._members = members
        self._render_rows()
        self._refresh_total()
        _total = sum(float(m.get("weight") or 0) for m in members) + float(self.sp_cash.value())
        if abs(_total - 100.0) > 0.02:
            # ★1.89：差额**让用户选**（旧版只会警告，等于逼用户自己算）
            _gap = round(100.0 - _total, 2)
            if _gap > 0:
                _box = QMessageBox(self)
                _box.setWindowTitle("合计不足 100%")
                _box.setText(f"当前合计 {_total:.2f}%，还差 **{_gap:.2f}%**。")
                _box.setInformativeText("要把这 {:.2f}% 留作现金吗？".format(_gap))
                _b_cash = _box.addButton("留作现金", QMessageBox.ButtonRole.AcceptRole)
                _box.addButton("我再调调", QMessageBox.ButtonRole.RejectRole)
                _box.exec()
                if _box.clickedButton() is not _b_cash:
                    return
                self.sp_cash.setValue(min(100.0, float(self.sp_cash.value()) + _gap))
                self._refresh_total()
            else:
                QMessageBox.warning(
                    self, "合计超过 100%",
                    f"当前合计 {_total:.2f}%（超出 {- _gap:.2f}%）—— 请减少权重或现金。")
                return
        self.accept()

    # ---------------- 结果 ----------------
    def result_portfolio(self) -> dict:
        out = dict(self._pf)
        out["members"] = [dict(m) for m in self._members]
        out["cash"] = round(float(self.sp_cash.value()), 2)
        out["weight_mode"] = str(self.cmb_mode.currentData() or "custom")
        # 基准：常见指数自动命名 + 归类；其余按个股处理（**不假装是指数**）
        _code = str(self.in_base_code.text() or "").strip()
        _name = str(self.in_base_name.text() or "").strip()
        _known = {"000300": "沪深300", "000905": "中证500", "000001": "上证指数",
                  "399001": "深证成指", "399006": "创业板指"}
        if not _code and not _name:
            out["base"] = dict(DEFAULT_BASE)
        else:
            _is_idx = _code in _known
            out["base"] = {"kind": "index" if _is_idx else "symbol", "code": _code,
                           "name": _name or _known.get(_code) or _code}
        out["rebalance"] = str(self.cmb_reb.currentData() or "monthly")
        return out


__all__ = ["PortfolioEditDialog"]
