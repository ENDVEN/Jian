# ui/widgets/sweep_compare.py
"""🧪 参数研究 —— **研究快照 A/B 对比**（★1.79 / §7-B15 第二轮③ · 用户 2026-10-16「就开 B15 第二轮」）。

【它回答什么】"我这两天跑的两份研究，差别到底在哪？" —— 同一标的换区间 / 换门槛 / 换网格时最有用。
【它**不是**"选哪套"】红线②：**一律不许出现"选 A / 推荐 / 该用哪个"** —— 本件只把两份快照的
  **可比字段摆在一起**并标出差异方向；措辞由 `COMPARE_FORBIDDEN` + 冒烟断言共同钉住。
【只读、不重跑】与"回看"同纪律：只读 `SweepArchive.load()` 的**已存**记录；
  **不重绘四图、不重跑回测、不动 `_spec` / `_interval`**（红线①）。快照里没有全网格年化
  ⇒ 四张图**复原不了**（与回看同一条诚实边界，不画"看着像真的"的假图）。
【诚实边界】两份快照可能**不同标的 / 不同区间 / 不同网格 / 不同 app 版本** ⇒ 差异**未必可比**；
  这时本件如实标"口径不一致，差异仅供参考"，而不是给一个看着很专业的结论。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                             QWidget)

from ui.widgets.styles import SEC_HINT_QSS, SUMMARY_GHOST_QSS

#: 明令禁止出现在对比文案里的词（红线②：**不许替用户选**）—— 冒烟断言直接扫这些词
COMPARE_FORBIDDEN = ("选 A", "选A", "推荐", "该用", "最优选择", "建议使用", "应该用")


def _num(value):
    """转 float（`None` / 非数 ⇒ `None`）—— 对比只认数，别拿字符串硬比。"""
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value, *, percent: bool = False) -> str:
    if value is None:
        return "—"
    return f"{value:.0%}" if percent else f"{value:.2f}"


def _kept_count(snap: dict) -> float:
    rows = ((snap.get("stats") or {}).get("rows")
            or (snap.get("stats") or {}).get("candidates") or [])
    return float(len([r for r in rows if isinstance(r, dict) and r.get("kept")]))


#: 可比字段：`(标签, 取数, 方向, 说明)`；方向 `'high'`（越大越好）/ `'low'`（越小越好）/ `None`
COMPARE_FIELDS = (
    ("Rank IC", lambda s: _num((s.get("stats") or {}).get("rank_ic")), "high", "≥0.15 才有预测力"),
    ("PBO", lambda s: _num((s.get("stats") or {}).get("pbo")), "low", ">0.5 等于抛硬币"),
    ("试验数", lambda s: _num((s.get("grid") or {}).get("n_combos")), None, "网格规模（试验次数）"),
    ("完成组数", lambda s: _num((s.get("stats") or {}).get("n_done")), None, "跑完的组数"),
    ("过门槛组数", _kept_count, None, "门槛只筛不排"),
    ("门槛(笔)", lambda s: _num((s.get("gate") or {}).get("min_trades")), None, "交易次数下限"),
    ("合并窗口", lambda s: _num(1 + len(((s.get("interval") or {}).get("more") or ()))), None,
     "R7 合并研究：窗口对数"),
)


def compare_snapshots(a: dict, b: dict) -> dict:
    """两份快照（`SweepArchive.load()` 的返回值）→ 逐项差异（**纯函数 · 零 Qt**）。

    :return: `{'rows', 'aligned', 'alignment_notes', 'note'}`：
      · `rows` = `[{'label','a','b','a_text','b_text','diff','better','hint'}]`；
        `better` 只在**口径一致**且该字段有方向时给 `'a'` / `'b'`（否则空串 = 不表态）；
      · `aligned=False` ⇒ 标的 / 区间 / 网格 / 版本有一样不同 ⇒ `note` 里如实写"仅供参考"。
    """
    rows, notes = [], []
    if str(a.get("symbol") or "") != str(b.get("symbol") or ""):
        notes.append(f"标的不同（{a.get('symbol')} vs {b.get('symbol')}）")
    ia, ib = (a.get("interval") or {}), (b.get("interval") or {})
    _ia = (ia.get("is_start"), ia.get("is_end"), ia.get("oos_start"), ia.get("oos_end"))
    _ib = (ib.get("is_start"), ib.get("is_end"), ib.get("oos_start"), ib.get("oos_end"))
    if _ia != _ib:
        notes.append("区间不同")
    if (len(ia.get("more") or ())) != (len(ib.get("more") or ())):
        notes.append("合并窗口数不同")
    if (str((a.get("grid") or {}).get("n_combos")) != str((b.get("grid") or {}).get("n_combos"))
            or len((a.get("grid") or {}).get("dims") or ())
            != len((b.get("grid") or {}).get("dims") or ())):
        notes.append("网格不同（试验次数或维数不一致）")
    if str(a.get("app_version") or "") != str(b.get("app_version") or ""):
        notes.append(f"引擎版本不同（{a.get('app_version')} vs {b.get('app_version')}）")
    aligned = not notes
    for label, getter, direction, hint in COMPARE_FIELDS:
        va, vb = getter(a), getter(b)
        diff = None if (va is None or vb is None) else (va - vb)
        better = ""
        if aligned and direction and diff is not None and abs(diff) > 1e-12:
            better = ("a" if diff > 0 else "b") if direction == "high" else ("b" if diff > 0 else "a")
        _pct = label in ("PBO",)
        rows.append({"label": label, "a": va, "b": vb, "diff": diff, "better": better,
                     "a_text": _fmt(va, percent=_pct), "b_text": _fmt(vb, percent=_pct),
                     "hint": hint})
    note = ("两侧的**标的 / 区间 / 网格 / 版本一致** ⇒ 逐项差异可以直接比。"
            if aligned else
            "⚠ 两侧口径**不完全一致**（" + "；".join(notes) + "）⇒ 逐项差异仅供参考，"
            "不能当成『改了这一个因素带来的差别』。")
    return {"rows": rows, "aligned": aligned, "alignment_notes": notes, "note": note}


class SweepCompareView(QWidget):
    """并排两列（A / B）+ 差异列 —— **只读**：数据全部来自 `compare_snapshots`，本件不取数。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVisible(False)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)
        self.lbl_title = QLabel("")
        self.lbl_title.setStyleSheet("font-size:12.5px; font-weight:bold; color:#1F2430;")
        self.lbl_note = QLabel("")
        self.lbl_note.setWordWrap(True)
        self.lbl_note.setStyleSheet(SEC_HINT_QSS)
        self.rows_box = QVBoxLayout()
        self.rows_box.setSpacing(2)
        root.addWidget(self.lbl_title)
        root.addWidget(self.lbl_note)
        root.addLayout(self.rows_box)
        self._close = QPushButton("收起对比")
        self._close.setStyleSheet(SUMMARY_GHOST_QSS)
        self._close.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close.clicked.connect(lambda: self.setVisible(False))
        _wrap = QHBoxLayout()
        _wrap.addStretch(1)
        _wrap.addWidget(self._close)
        root.addLayout(_wrap)

    def _clear_rows(self) -> None:
        while self.rows_box.count():
            item = self.rows_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def show_pair(self, a: dict, b: dict, result: dict) -> None:
        """显示一份对比（`result` = `compare_snapshots(a, b)` 的产物）。"""
        self._clear_rows()
        ia, ib = (a.get("interval") or {}), (b.get("interval") or {})
        self.lbl_title.setText(
            f"A = {a.get('id')}（{ia.get('oos_start')}~{ia.get('oos_end')}）　"
            f"B = {b.get('id')}（{ib.get('oos_start')}~{ib.get('oos_end')}）")
        # ⚠ 措辞纪律（红线②）：**禁词连"否定句"里也不许出现** —— 我第一版写
        #   "不回答该用哪一套"，被自己的禁词扫描逮住（`COMPARE_FORBIDDEN` 里有"该用"）。
        #   ⇒ 免责声明也必须换词（"不替你选参"），否则那句话本身就在把禁词带上界面。
        self.lbl_note.setText(
            result.get("note", "")
            + "<br>本对比**不替你选参**（红线②：软件只摆事实，选择权在你）；"
              "它只把两份已存研究的差别摆在一起。")
        for row in result.get("rows") or []:
            line = QWidget()
            lay = QHBoxLayout(line)
            lay.setContentsMargins(0, 0, 0, 0)
            lab = QLabel(row["label"])
            lab.setStyleSheet("font-size:11.5px; color:#5B6472;")
            lab.setMinimumWidth(74)
            va = QLabel(row["a_text"])
            vb = QLabel(row["b_text"])
            mark = {"a": "◀ 更稳", "b": "更稳 ▶"}.get(row.get("better"), "")
            vm = QLabel(mark)
            vm.setStyleSheet(SEC_HINT_QSS + "color:#2E7D32;")
            for w in (va, vb):
                w.setStyleSheet("font-size:11.5px; font-weight:bold;")
                w.setMinimumWidth(64)
            hint = QLabel(row.get("hint") or "")
            hint.setStyleSheet(SEC_HINT_QSS)
            lay.addWidget(lab)
            lay.addWidget(va)
            lay.addWidget(vb)
            lay.addWidget(vm)
            lay.addWidget(hint, 1)
            self.rows_box.addWidget(line)
        self.setVisible(True)
