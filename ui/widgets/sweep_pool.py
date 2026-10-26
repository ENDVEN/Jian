# ui/widgets/sweep_pool.py
"""池化（组合层）—— **设置进「研究设置」，结果进结果区**（★1.87 重做）。

【为什么重做（用户 2026-10-26 指出的结构错误）】
  旧版把"选组合 + 折数 + 运行"塞在**结果页最下面**，等于结果区里又出现一组设置；
  而"研究谁（个股 / 组合）"本来是与"个股标的"**同级**的研究前提 ⇒ 必须住在**研究设置第①步**。

【现在的分工】
  · `build_target_block(page)` → 插进左栏「研究设置 › ①标的」标题下方（紧凑，不另起卡片）；
  · `build_result_card(page)` → 结果区只放**表格 + 导出 + 状态**（无任何可配置项）。

【口径（用户 2026-10-26 拍板）】池 = **组合全部成分** · 折数默认 **4** · 扩张窗口 walk-forward ·
  输出每只一行 + **组合加权一行** + 逐折行 · 可导出 CSV。
【诚实】缺数据的票跳过并标注；有效组合 < 3 组时该折 IC/收益写「—」，**不补 0**。
"""
from __future__ import annotations

import csv

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QComboBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
                             QLabel, QMessageBox, QPushButton, QSizePolicy, QSpinBox,
                             QTableWidget, QTableWidgetItem, QVBoxLayout)

from core.portfolio_sweep import FOLDS_DEFAULT, aggregate, csv_rows, make_folds
from data.market_db import DataLakeManager
from data.portfolio_store import PortfolioStore
from ui.widgets.custom_widgets import COMBO_QSS_SMALL, NoWheelComboBox
from ui.widgets.styles import (SEC_HINT_QSS, SUMMARY_GHOST_QSS, SUMMARY_RUN_QSS,
                               TABLE_HEAD_QSS, WARN_HINT_QSS)
from ui.widgets.sweep_parts import panel_card, panel_head

POOL_COLS = ["类型", "代码", "权重 %", "IC 中位数", "收益中位数", "亏损折数"]


def _reload_portfolios(cmb: QComboBox) -> int:
    """填组合下拉；返回可选条目数。**空就写清空**（空下拉会让人以为坏了）。"""
    cmb.clear()
    try:
        items = PortfolioStore().list()
    except Exception:                      # noqa: BLE001
        items = []
    for p in items:
        cmb.addItem(f"{p.get('name')}（{len(p.get('members') or [])} 只）", p)
    if not items:
        cmb.addItem("（还没有组合 —— 先去「组合」建一个）", None)
    return len(items)


def folds_within(page, days, folds: int):
    """按**页面上的样本区间**切折：返回 `(folds, lo, hi)`。

    ⚠ 唯一口径：UI 与测试都走这里。旧版拿全 history 切折 ⇒ 池化跑的不是用户设的区间
      （实测首折落在 2010→2015，而用户在界面上设的是 2024–2026）。
    """
    iv = getattr(page, "_interval", None)
    lo = str(getattr(iv, "is_start", "") or "")
    hi = str(getattr(iv, "oos_end", "") or "")
    ds = [str(d) for d in (days or [])]
    if lo or hi:
        ds = [d for d in ds if (not lo or d >= lo) and (not hi or d <= hi)]
    return make_folds(ds, int(folds)), lo, hi


def build_target_block(page) -> QFrame:
    """「研究设置 › ①标的」下方的**标的类型**块（个股 / 组合）。"""
    blk = QFrame()
    blk.setStyleSheet("QFrame { background: transparent; }")
    lay = QVBoxLayout(blk)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)

    row = QHBoxLayout()
    row.setSpacing(6)
    cap = QLabel("标的类型")
    cap.setStyleSheet(SEC_HINT_QSS)
    row.addWidget(cap)
    # ★1.87：必须用**全站下拉**（裸 QComboBox 在深色 QSS 环境里会渲染成黑条）
    # ★1.87：**两选一不用下拉**（下拉在部分深色 QSS 下会渲染成黑条，且两选项本来就适合分段按钮）
    btn_single = QPushButton("个股")
    btn_pool = QPushButton("组合")
    for _b in (btn_single, btn_pool):
        _b.setCheckable(True)
        _b.setCursor(Qt.CursorShape.PointingHandCursor)
        _b.setStyleSheet(SUMMARY_GHOST_QSS + " QPushButton:checked { background:#1976D2;"  " color:#FFFFFF; border-color:#1976D2; }")
        row.addWidget(_b)
    btn_single.setToolTip("个股：用下面填的代码做单只回测")
    btn_pool.setToolTip("组合：用「组合」页里那一篮子，逐只 × 逐折跑（池化）")
    btn_single.setChecked(True)
    row.addStretch(1)
    lay.addLayout(row)

    pool_row = QHBoxLayout()
    pool_row.setSpacing(6)
    pool_row.addWidget(QLabel("组合"))
    cmb_pool = NoWheelComboBox()
    cmb_pool.setStyleSheet("QComboBox { background:#FFFFFF; border:1px solid #DDE3EC;"
                           " border-radius:6px; padding:2px 8px; color:#3A4250; }")
    cmb_pool.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    cmb_pool.setMinimumContentsLength(8)
    cmb_pool.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    pool_row.addWidget(cmb_pool, 1)
    lay.addLayout(pool_row)

    fold_row = QHBoxLayout()
    fold_row.setSpacing(6)
    fold_row.addWidget(QLabel("折数"))
    _info = QLabel("ⓘ")
    _info.setStyleSheet(SEC_HINT_QSS + "color:#1976D2;")
    _info.setToolTip("折数 = 把历史按时间切成 N+1 段：\n"
                     "第 1 折用第 1 段挑参数、紧跟的第 2 段验证；\n"
                     "第 2 折用前 2 段挑参数、第 3 段验证 …… 依此类推。\n"
                     "4 折 = 换 4 个不同时间段各验一次（默认 4：够稳、又不会太慢）。")
    fold_row.addWidget(_info)
    spin = QSpinBox()
    spin.setRange(2, 8)
    spin.setValue(FOLDS_DEFAULT)
    spin.setToolTip("扩张窗口：第 k 折 = 前 k 段做样本内、紧随其后一段做样本外（默认 4 折）")
    fold_row.addWidget(spin)
    btn_run = QPushButton("▶ 跑池化")
    btn_run.setStyleSheet(SUMMARY_RUN_QSS)
    btn_run.setCursor(Qt.CursorShape.PointingHandCursor)
    fold_row.addWidget(btn_run, 1)
    lay.addLayout(fold_row)
    fold_help = QLabel("折数越多，验证越严格但越慢。默认 4 折：拿 4 个不同时间段各验一次，避免「只在某一段好看」。")
    fold_help.setWordWrap(True)
    fold_help.setStyleSheet(SEC_HINT_QSS)
    lay.addWidget(fold_help)

    hint = QLabel("池 = 组合**全部成分**；结果给「每只一行 + 组合加权一行」。")
    hint.setWordWrap(True)
    hint.setStyleSheet(SEC_HINT_QSS)
    lay.addWidget(hint)

    def _toggle() -> None:
        is_pool = btn_pool.isChecked()
        for w in (cmb_pool, spin, btn_run, hint, fold_help):
            w.setVisible(is_pool)
        # ★1.87：切到「组合」时，**个股那几行必须让位**（用户实测：两套同时显示）
        form = getattr(page, "form", None)
        if form is not None and hasattr(form, "set_target_mode"):
            form.set_target_mode(is_pool)
        if is_pool:
            _reload_portfolios(cmb_pool)
        if hasattr(page, "_refresh_run_enabled"):
            page._refresh_run_enabled()      # ★1.87：切模式立刻刷新「跑样本内」的可用性

    def _run() -> None:
        p = cmb_pool.currentData()
        if not p:
            QMessageBox.information(blk, "没有组合", "先去「组合」建一个组合并加成分。")
            return
        if getattr(page, "_spec", None) is None or getattr(page, "_grid", None) is None:
            QMessageBox.information(blk, "还没有研究规格",
                                    "先把策略 / 网格 / 区间配好，让「样本内」可跑，再回来选组合。")
            return
        members = [(str(m.get("symbol")), float(m.get("weight") or 0.0))
                   for m in (p.get("members") or []) if str(m.get("symbol") or "").strip()]
        if not members:
            QMessageBox.information(blk, "这个组合没有成分", "去「组合 → ✏ 编辑成分」加几只票。")
            return
        df = DataLakeManager().load_data("kline_daily", members[0][0])
        if df is None or not len(df):
            QMessageBox.information(blk, "读不到日线",
                                    f"{members[0][0]} 本机没有日线 —— 先去「数据管理」补齐。")
            return
        # ★1.87 修：折窗**必须落在用户设的样本区间内**。
        #   旧版拿这只票的**全 history** 切折（实测首折落在 2010→2015），
        #   与左栏「样本区间 2024–2026」完全不一致 ⇒ 池化跑的根本不是你设的那段。
        _days = [str(d) for d in df["date"].astype(str).tolist()]
        folds, _lo, _hi = folds_within(page, _days, int(spin.value()))
        _days = [d for d in _days if (not _lo or d >= _lo) and (not _hi or d <= _hi)]
        if not folds:
            QMessageBox.information(
                blk, "区间内数据太短",
                f"在样本区间（{_lo or '最早'} → {_hi or '最新'}）里只有 {len(_days)} 个交易日，"                f"切不出 {spin.value()} 折（需要约 {(int(spin.value()) + 1) * 2} 天）。\n"
                "可以减小折数，或把样本区间放宽。")
            return
        start_pool_run(page, members, folds, p)      # 统一由页面调度（结果写进结果卡）

    btn_single.clicked.connect(lambda: (btn_single.setChecked(True),
                                      btn_pool.setChecked(False), _toggle()))
    btn_pool.clicked.connect(lambda: (btn_pool.setChecked(True),
                                    btn_single.setChecked(False), _toggle()))
    btn_run.clicked.connect(_run)

    # 对外暴露（页面运行时要读）
    blk.btn_single, blk.btn_pool = btn_single, btn_pool
    blk.cmb_pool, blk.sp_folds, blk.btn_run = cmb_pool, spin, btn_run
    blk.is_pool_mode = lambda: btn_pool.isChecked()
    _reload_portfolios(cmb_pool)      # ★1.87：**始终装载**（个股模式下也填好，切过去即用）
    _toggle()
    return blk


def build_result_card(page) -> QFrame:
    """结果区：**只有结果**（表格 + 导出 + 状态），不含任何设置项。"""
    card = panel_card()
    lay = QVBoxLayout(card)
    lay.setContentsMargins(10, 8, 10, 10)
    lay.setSpacing(6)
    head = panel_head("池化结果（组合层）", "每只一行 + 组合加权一行")
    lay.addWidget(head)

    status = QLabel("在左栏「研究设置 › ①标的」里选「组合」并点「▶ 跑池化」，结果会出现在这里。")
    status.setWordWrap(True)
    status.setStyleSheet(SEC_HINT_QSS)
    lay.addWidget(status)

    tbl = QTableWidget(0, len(POOL_COLS))
    tbl.setHorizontalHeaderLabels(POOL_COLS)
    tbl.verticalHeader().setVisible(False)
    tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    tbl.setStyleSheet(TABLE_HEAD_QSS)
    tbl.setMinimumHeight(150)
    h = tbl.horizontalHeader()
    for c in range(len(POOL_COLS)):
        h.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
    h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    lay.addWidget(tbl)

    row = QHBoxLayout()
    row.addStretch(1)
    btn_out = QPushButton("导出 CSV")
    btn_out.setStyleSheet(SUMMARY_GHOST_QSS)
    btn_out.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_out.setEnabled(False)
    row.addWidget(btn_out)
    lay.addLayout(row)

    state = {"result": None}

    def set_result(agg: dict, note: str = "") -> None:
        state["result"] = agg
        rows = list(agg.get("rows") or [])
        wgt = agg.get("weighted") or {}
        tbl.setRowCount(len(rows) + 1)
        for r, row_ in enumerate(rows):
            vals = ["标的", row_["symbol"], f"{row_['weight']:.2f}", _fmt(row_["ic_med"]),
                    _fmt(row_["ret_med"]), str(row_["loss_folds"])]
            for c, txt in enumerate(vals):
                it = QTableWidgetItem(txt)
                if c >= 2:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                tbl.setItem(r, c, it)
        last = len(rows)
        for c, txt in enumerate(["组合加权", "（全部成分）", "100.00", _fmt(wgt.get("ic_med_cross")),
                                 _fmt(wgt.get("ret_med_cross")), str(wgt.get("loss_folds") or 0)]):
            it = QTableWidgetItem(txt)
            if c >= 2:
                it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            tbl.setItem(last, c, it)
        status.setText(note or (f"完成：{len(rows)} 只 · 组合加权 IC {_fmt(wgt.get('ic_med_cross'))} / "
                                f"收益 {_fmt(wgt.get('ret_med_cross'))}"))
        btn_out.setEnabled(True)

    def set_status(text: str) -> None:
        status.setText(text)

    def _export() -> None:
        agg = state.get("result")
        if not agg:
            return
        path, _ = QFileDialog.getSaveFileName(card, "导出池化结果", "组合池化.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                csv.writer(f).writerows(csv_rows(agg))
            status.setText(f"已导出：{path}")
        except Exception as exc:            # noqa: BLE001
            QMessageBox.warning(card, "导出失败", str(exc))

    btn_out.clicked.connect(_export)
    card.set_result = set_result
    card.set_status = set_status
    return card


def _fmt(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    return "—" if f != f else f"{f:+.4f}"


__all__ = ["build_target_block", "build_result_card", "folds_within", "start_pool_run",
           "apply_pool_result", "POOL_COLS", "aggregate"]



def start_pool_run(page, members, folds, portfolio=None) -> None:
    """由左栏「标的类型 = 组合」触发：逐只 × 逐折跑（QThread，不卡界面）。

    ⚠ 调度放在本模块（而不是页面）—— 页面有行数上限（§10-5），
      而"池化怎么跑"本来就属于池化这一块。
    """
    card = getattr(page, "_pool_card", None)
    worker = getattr(page, "_pool_worker", None)
    if worker is not None and worker.isRunning():
        if card is not None:
            card.set_status("上一轮还在跑 —— 等它结束再发起。")
        return
    if getattr(page, "_spec", None) is None or getattr(page, "_grid", None) is None:
        if card is not None:
            card.set_status("还没有研究规格：先配好策略/网格/区间。")
        return
    if card is not None:
        card.set_status(f"正在池化：{len(members)} 只 × {len(folds)} 折 …")
    from ui.workers import PoolSweepWorker
    w = PoolSweepWorker(page._spec, page._grid, members, folds, parent=page)
    page._pool_worker = w
    if card is not None:
        w.progress.connect(lambda d, t, note: card.set_status(f"{note}（{d}/{t}）"))
        w.failed.connect(lambda msg: card.set_status(f"池化失败：{msg}"))
    w.finished.connect(lambda res: apply_pool_result(page, res, members, folds))
    w.start()


def apply_pool_result(page, res, members, folds) -> None:
    """把 worker 的结果聚合成表（每只 + 组合加权），写进结果卡。"""
    agg = aggregate(res, {s: w for s, w in members}, [s for s, _w in members])
    wgt = agg.get("weighted") or {}
    card = getattr(page, "_pool_card", None)
    if card is None:
        return
    card.set_result(
        agg,
        f"完成：{len(agg.get('rows') or [])} 只 · {len(folds)} 折 · "
        f"组合加权 IC {(wgt.get('ic_med_cross') or 0):+.4f} / "
        f"收益 {(wgt.get('ret_med_cross') or 0):+.4f}")
