# ui/dialogs/portfolio_edit.py
"""🧺 组合「编辑成分」对话框（★1.87 补漏：**手工增删改成分**）。

【为什么必须补】P0 只做了"从自选股组导入"一条路 —— 用户建了空组合后**没有任何办法**把票加进去
（"麟平组合 0 只"就是这么来的）。导入是"整组搬"，本对话框是"逐只调"，两者互补。

【口径（不许静默改数）】
  · 权重合计 + 现金 **超过 100% 拦下**；**不足 100% 的差额点「确定」自动计入现金**（★1.90，
    旧版把「确定」直接禁用 ⇒ 用户只能自己拿计算器凑，他实测 80% 时连提示都没有）；
  · 「等权」= `(100 − 现金) / n`（余数补第一个，保证 100.00）；
  · **市值权重 = 流通市值**（★1.90 真接）：最新收盘 × 最新流通股本（`outstanding_share`）；
    缺这一列的票记「数据不足」并**点名**，权重记 0 让用户手补 —— 绝不按剩下的重新归一冒充整个组合；
  · 表格三列对照 **原权重 / 新权重 / 变化**（`▲ +x.xx` / `▼ -x.xx` / `＋ 新增`），
    删掉的票在上方摘要里点名（否则"改了什么都不记得"）；
  · 改完只在"确定"时写回，取消零副作用。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QComboBox, QDialog, QDoubleSpinBox, QHBoxLayout, QHeaderView,
                             QLineEdit, QSizePolicy,
                             QInputDialog, QLabel, QMessageBox, QPushButton,
                             QTableWidget, QTableWidgetItem, QVBoxLayout)

from core.portfolio_stats import cap_weights, market_of
from data.portfolio_store import (DEFAULT_BASE, REBALANCE_LABELS, WEIGHT_LABELS,
                                  diff_members, normalize_weights)
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

    def __init__(self, portfolio: dict, parent=None, name_lookup=None, cap_provider=None):
        super().__init__(parent)
        self._pf = dict(portfolio)
        self._lookup = name_lookup        # 外部注入的"代码→名称"（组合页给的是花名册门面）
        self._cap_provider = cap_provider  # ★1.90：`symbols -> ({symbol: 流通市值}, [缺失])`（组合页注入）
        self._members = [dict(m) for m in (portfolio.get("members") or [])]
        # ★1.90：打开时的**原始快照** —— 表格要显示"原来多少 → 现在多少"（用户 2026-10-28 要求）
        self._orig_members = [dict(m) for m in (portfolio.get("members") or [])]
        self._orig_cash = float(portfolio.get("cash") or 0.0)
        self._orig_mode = str(portfolio.get("weight_mode") or "equal")
        self.setWindowTitle(f"编辑成分 · {portfolio.get('name') or '组合'}")
        self.setMinimumWidth(660)
        self.setStyleSheet(_QSS)
        self._build()
        self._fill()

    # ---------------- 版式 ----------------
    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(9)

        tip = QLabel("加/减标的、改权重。<b>合计（含现金）超过 100% 会被拦下；"
                     "不足 100% 的差额，点「确定」时自动计入现金</b>（不用自己算）。")
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

        # ★1.90：**原权重 / 新权重 / 变化** 三列并排 —— 用户要一眼看清"之前多少、现在多少、变了几个点"
        self.tbl = QTableWidget(0, 6)
        self.tbl.setHorizontalHeaderLabels(["代码", "名称", "原权重 %", "新权重 %", "变化", "市场"])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        # ★1.87：**表格必须吃满宽度**（否则窗口拉大后右侧一大片空白，用户实测）
        self.tbl.setMinimumHeight(220)
        _h = self.tbl.horizontalHeader()
        _h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        _h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for _c in (2, 3, 4, 5):
            _h.setSectionResizeMode(_c, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.tbl.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self.tbl, 1)

        # 变更摘要（删除的票不在表里了，必须在这里点名，否则"改了什么都不记得"）
        self.lbl_diff = QLabel("")
        self.lbl_diff.setWordWrap(True)
        self.lbl_diff.setStyleSheet("font-size:12px;color:#5A6577;")
        lay.addWidget(self.lbl_diff)

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        row2.addWidget(QLabel("现金："))
        self.sp_cash = QDoubleSpinBox()
        self.sp_cash.setRange(0.0, 100.0)
        self.sp_cash.setDecimals(2)
        self.sp_cash.setSuffix(" %")
        self.sp_cash.valueChanged.connect(self._on_cash_changed)
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

    def _diff(self) -> dict:
        """与"打开时"相比的差异（表里显示"原权重 → 新权重 → 变化"，删掉的票走摘要行）。"""
        return diff_members(self._orig_members, self._orig_cash,
                            self._members, float(self.sp_cash.value()))

    def _render_rows(self) -> None:
        self.tbl.blockSignals(True)
        self.tbl.setRowCount(len(self._members))
        _nm = self._names()          # ★1.87：名称列必须走这里（否则手工加的票永远空着）
        _d = self._diff()
        _added = {str(x.get("symbol")) for x in _d["added"]}
        _orig_w = {str(x.get("symbol")): float(x.get("weight") or 0.0)
                   for x in self._orig_members}
        for r, m in enumerate(self._members):
            _sym = str(m.get("symbol") or "")
            _w = float(m.get("weight") or 0.0)
            if _sym in _added:
                _orig_txt, _delta_txt, _tone = "—（新增）", "＋ 新增", "#1976D2"
            else:
                _o = round(float(_orig_w.get(_sym, 0.0)), 2)
                _dv = round(_w - _o, 2)
                _orig_txt = f"{_o:.2f}"
                _tone = "#2E7D32" if _dv > 0 else ("#C62828" if _dv < 0 else "#8A94A6")
                _delta_txt = (f"▲ +{_dv:.2f}" if _dv > 0
                              else (f"▼ {_dv:.2f}" if _dv < 0 else "—"))
            for c, txt in enumerate([_sym, str(m.get("name") or _nm.get(_sym) or ""),
                                     _orig_txt, f"{_w:.2f}", _delta_txt,
                                     {"sh": "沪", "sz": "深", "bj": "北", "other": "其他"}
                                     .get(market_of(m.get("symbol")), "其他")]):
                it = QTableWidgetItem(txt)
                if c >= 2 and c != 5:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if c != 3:                       # 只有「新权重」可编辑
                    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if c == 4:
                    it.setForeground(QColor(_tone))
                self.tbl.setItem(r, c, it)
        self.tbl.blockSignals(False)
        # 反写名字（只补空值；不覆盖用户已有名称）
        for m in self._members:
            if not str(m.get("name") or "").strip():
                n = _nm.get(str(m.get("symbol") or ""))
                if n:
                    m["name"] = n
        self._refresh_diff(_d)

    def _refresh_diff(self, d: dict = None) -> None:
        """变更摘要：改权重 N 只 · 新增 · **删除的票要在这里点名**（它们已不在表里）· 现金变化。"""
        d = d if d is not None else self._diff()
        if not d.get("has_change"):
            self.lbl_diff.setText("与打开时相比还没有改动。")
            return
        _bits = []
        if d["moved"]:
            _bits.append(f"改权重 {len(d['moved'])} 只")
        if d["added"]:
            _bits.append(f"新增 {len(d['added'])} 只")
        if d["removed"]:
            _bits.append(f"删除 {len(d['removed'])} 只")
        if abs(float(d["cash_after"]) - float(d["cash_before"])) >= 0.005:
            _bits.append(f"现金 {d['cash_before']:.2f}% → {d['cash_after']:.2f}%")
        _rm = "、".join(f"{x['symbol']}（原 {x['weight']:.2f}%）" for x in d["removed"])
        self.lbl_diff.setText("本次变更：" + " · ".join(_bits) + (f"　｜　删除：{_rm}" if _rm else ""))

    def _refresh_total(self) -> None:
        total = sum(float(m.get("weight") or 0.0) for m in self._members) + float(self.sp_cash.value())
        if not self._members:
            self.lbl_total.setText("还没有成分 —— 先「＋ 添加代码」")
            self.lbl_total.setStyleSheet("font-size:12.5px;color:#C62828;")
            self.btn_ok.setEnabled(False)
            return
        _gap = round(100.0 - total, 2)
        if _gap > 0.05:
            # ★1.90（用户 2026-10-28）：**差额不用自己算** —— 写明"点确定就自动进现金"
            _cash_new = min(100.0, round(float(self.sp_cash.value()) + _gap, 2))
            self.lbl_total.setText(
                f"合计（含现金）<b>{total:.2f}%</b>　·　还差 <b>{_gap:.2f}%</b>"
                f" ⇒ 点「确定」自动计入现金（现金 {float(self.sp_cash.value()):.2f}% → {_cash_new:.2f}%）")
            self.lbl_total.setStyleSheet("font-size:12.5px;color:#B26A00;")
            self.btn_ok.setEnabled(True)
        elif _gap < -0.05:
            self.lbl_total.setText(
                f"合计（含现金）<b>{total:.2f}%</b>　·　⚠ 超出 {- _gap:.2f}%，请减少权重或现金")
            self.lbl_total.setStyleSheet("font-size:12.5px;color:#C62828;")
            self.btn_ok.setEnabled(False)
        else:
            self.lbl_total.setText(f"合计（含现金）<b>{total:.2f}%</b>　✓")
            self.lbl_total.setStyleSheet("font-size:12.5px;color:#2E7D32;")
            self.btn_ok.setEnabled(True)

    # ---------------- 交互 ----------------
    def _on_cash_changed(self) -> None:
        self._refresh_total()
        self._refresh_diff()

    def _on_item_changed(self, item) -> None:
        if item is None or item.column() != 3:      # ★1.90：可编辑列变成「新权重 %」
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
        self._render_rows()
        self._refresh_total()

    def _revert_mode(self) -> None:
        """市值档用不了时退回原模式（**不假装**已经按市值算过）。"""
        _back = self._orig_mode if self._orig_mode in ("equal", "custom") else "custom"
        self.cmb_mode.blockSignals(True)
        self.cmb_mode.setCurrentIndex(self.cmb_mode.findData(_back))
        self.cmb_mode.blockSignals(False)

    def _on_mode(self, _idx) -> None:
        mode = self.cmb_mode.currentData()
        if mode == "cap":
            # ★1.90：**真算**（旧版只弹"暂未接入"）。市值 = 最新收盘 × 最新流通股本。
            _syms = [str(m.get("symbol") or "") for m in self._members if str(m.get("symbol") or "")]
            if not _syms:
                QMessageBox.information(self, "先加成分", "空组合没法按市值分配 —— 先「＋ 添加代码」。")
                self._revert_mode()
                return
            if not callable(self._cap_provider):
                QMessageBox.warning(self, "市值权重用不了",
                                    "这个入口没接上行情数据 —— 请从「组合」页打开「✏ 编辑成分」。")
                self._revert_mode()
                return
            try:
                caps, miss = self._cap_provider(_syms)
            except Exception as exc:           # noqa: BLE001
                QMessageBox.warning(self, "取市值失败", f"{type(exc).__name__}: {exc}")
                self._revert_mode()
                return
            _w = cap_weights(caps, _syms, float(self.sp_cash.value()))
            if not _w:
                QMessageBox.information(
                    self, "这几只都没有流通股本",
                    "本机日线里缺 `流通股本` 这一列（东财兜底源不给它）⇒ 没法算市值。\n"
                    "换个数据源重新下载后再选这一档；现在先按自定义权重。")
                self._revert_mode()
                return
            for m in self._members:
                m["weight"] = round(float(_w.get(str(m.get("symbol") or ""), 0.0)), 2)
            self._render_rows()
            self._refresh_total()
            if miss:
                _nm = self._names()
                _txt = "、".join(f"{s}（{_nm.get(s) or '—'}）" for s in miss[:5])
                QMessageBox.information(
                    self, f"{len(miss)} 只缺流通股本",
                    f"{_txt}\n\n这几只**没有**市值数据 ⇒ 权重暂记 0%，"
                    "请手工补权重，或补数据后再选一次。其余票已按流通市值分配。")
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
        # ★1.90：市值权重已接（`_on_mode('cap')` 走 `cap_provider`）；新票权重先给"剩下的"，
        #   用户可再点「市值」档重算，或手改成自定义。
        # 新票权重先给"剩下的"，再由用户/等权调整
        used = sum(float(m.get("weight") or 0.0) for m in self._members)
        rest = max(0.0, 100.0 - float(self.sp_cash.value()) - used)
        self._members.append({"symbol": code, "name": name, "weight": round(rest, 2)})
        self._after_members_changed()

    def _after_members_changed(self) -> None:
        """增/删成分之后：**等权模式就重新均分**。

        ★1.90：旧版增删后只是重画 ⇒ 标着「等权」却变成 33/33/34 或 66%（用户无从判断哪份是真的）。
        「自定义」模式保持用户手填的数不动（那是他的意图）。
        """
        if str(self.cmb_mode.currentData() or "") == "equal":
            self._on_equal()
            return
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
        self._after_members_changed()

    def _on_ok(self) -> None:
        members = [dict(m) for m in self._members]
        if not members:
            QMessageBox.information(self, "还没有成分", "至少加一只票，或点「取消」。")
            return
        self._members = members
        _total = sum(float(m.get("weight") or 0) for m in members) + float(self.sp_cash.value())
        # ★1.90（用户 2026-10-28）：旧版这里**根本走不到** —— `_refresh_total` 在合计≠100 时
        #   直接把「确定」禁用了（他实测：80% 时按钮是灰的，没有任何提示）。现在：
        #   · 不足 100% ⇒ **自动把差额计入现金**（提示语已写在合计行里，不用用户拿计算器）；
        #   · 超过 100% ⇒ 拦下并说清超出多少（按钮此时本来就是灰的，这里再兜一道）。
        _gap = round(100.0 - _total, 2)
        if _gap < -0.05:
            QMessageBox.warning(self, "合计超过 100%",
                                f"当前合计 {_total:.2f}%（超出 {- _gap:.2f}%）—— 请减少权重或现金。")
            return
        if _gap > 0.005:
            self.sp_cash.blockSignals(True)
            self.sp_cash.setValue(min(100.0, round(float(self.sp_cash.value()) + _gap, 2)))
            self.sp_cash.blockSignals(False)
            self._render_rows()
            self._refresh_total()
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
