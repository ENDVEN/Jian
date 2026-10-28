# ui/widgets/portfolio_changes.py
"""🧺 组合「调仓记录」的**列表渲染件**（★1.90 从富文本改成控件，用户 2026-10-28：
"现在的文字都在一堆挤着不好分辨"，并给了一张参考图 —— 日期一行、每笔一行、左标签右数值）。

【长什么样】每条记录 = 一个块：
    `10-28 19:52`
    `增持  振华重工     30.00% > 35.00%`
    `      600320        变化 +5.00`
    `现金 10.00% > 15.00%`
⇒ 左「增持/减持/新增/剔除」彩色标签（**买 = 蓝 / 卖 = 橙**，与行情页习惯一致），
   中间是名称 + 代码两行，右侧是"原来 > 现在"和变化量两行 —— **数值右对齐**，扫一眼就能对。

【纪律】
· 本文件**纯显示**：不吃数据、不算统计；记录由 `PortfolioView._change_records()` 备好。
· 记录**永久保存**（用户 2026-10-28："除非删除组合，不要上限"）⇒ 这里用 `QScrollArea`
  限高 + 可滚：条数再多也不撑破右栏，也不删任何一条（§11.5-137：宁可滚动，不许看不见）。
· 空态/提示走 `hint` 文本，不画假行。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy,
                             QVBoxLayout, QWidget)

__all__ = ["ChangeList", "build_records"]


def build_records(changes, events=(), name_of=None) -> list:
    """组合的 `changes` + 再平衡事件 → `ChangeList` 的记录（**新 → 旧**）。

    · 手动改成分：`增持/减持 30.00% > 35.00%（变化 +5.00）` / `新增` / `剔除`
    · 月末再平衡：`增持/减持 调整 1.50%` + 换手/成本备注
    ⚠ 纯整形，不算任何统计（数字来自存储的 `changes` 与 `nav_with_costs` 的 events）。
    """
    _nm = name_of if callable(name_of) else (lambda _s: str(_s))
    out = []
    for c in reversed(list(changes or [])):
        items = []
        for x in (c.get("moved") or []):
            _d = float(x.get("delta") or 0.0)
            items.append({"badge": "增持" if _d > 0 else "减持",
                          "kind": "buy" if _d > 0 else "sell",
                          "name": x.get("name") or _nm(str(x.get("symbol"))),
                          "symbol": str(x.get("symbol") or ""),
                          "main": (f"{float(x.get('before') or 0):.2f}% > "
                                   f"{float(x.get('after') or 0):.2f}%"),
                          "sub": f"变化 {_d:+.2f}"})
        for x in (c.get("added") or []):
            items.append({"badge": "新增", "kind": "buy",
                          "name": x.get("name") or _nm(str(x.get("symbol"))),
                          "symbol": str(x.get("symbol") or ""),
                          "main": f"{float(x.get('weight') or 0):.2f}%",
                          "sub": "纳入组合"})
        for x in (c.get("removed") or []):
            items.append({"badge": "剔除", "kind": "sell",
                          "name": x.get("name") or _nm(str(x.get("symbol"))),
                          "symbol": str(x.get("symbol") or ""),
                          "main": f"原 {float(x.get('weight') or 0):.2f}%",
                          "sub": "移出组合"})
        _c0, _c1 = float(c.get("cash_before") or 0.0), float(c.get("cash_after") or 0.0)
        out.append({"at": str(c.get("at") or "—"), "items": items,
                    "note": (f"现金 {_c0:.2f}% > {_c1:.2f}%" if abs(_c1 - _c0) >= 0.005 else ""),
                    "tag": "从自选股组导入" if str(c.get("kind")) == "import" else ""})
    for e in reversed(list(events or [])):
        items = []
        for t in (e.get("trades") or []):
            _d = float(t.get("delta_pct") or 0.0)
            items.append({"badge": str(t.get("action") or ("增持" if _d > 0 else "减持")),
                          "kind": "buy" if _d > 0 else "sell",
                          "name": _nm(str(t.get("symbol"))),
                          "symbol": str(t.get("symbol") or ""),
                          "main": f"调整 {abs(_d):.2f}%", "sub": "月末再平衡"})
        out.append({"at": str(e.get("date") or ""), "items": items, "tag": "再平衡",
                    "note": f"换手 {float(e.get('turnover_pct') or 0):.2f}% · "
                            f"成本 {float(e.get('cost') or 0) * 10000:.2f}‱"})
    return out

_KIND_COLOR = {"buy": "#1565C0", "sell": "#E65100", "mute": "#8A94A6"}
_MAX_NAME = 7          # 右栏只有 ~300px：名字超长截断（完整名在 tooltip 里）


class _Row(QFrame):
    """一条明细：标签 + 名称/代码 + 原>现/变化。"""

    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        _col = _KIND_COLOR.get(str(item.get("kind") or "mute"), _KIND_COLOR["mute"])
        badge = QLabel(str(item.get("badge") or ""))
        badge.setFixedWidth(38)
        badge.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        badge.setStyleSheet(f"color:{_col};font-size:11.5px;font-weight:700;background:transparent;")
        lay.addWidget(badge, 0)

        name = str(item.get("name") or item.get("symbol") or "—")
        _shown = name if len(name) <= _MAX_NAME else name[:_MAX_NAME - 1] + "…"
        mid = QVBoxLayout()
        mid.setContentsMargins(0, 0, 0, 0)
        mid.setSpacing(1)
        lbl_name = QLabel(_shown)
        lbl_name.setToolTip(name)
        lbl_name.setStyleSheet("color:#1F2A37;font-size:12px;font-weight:600;background:transparent;")
        lbl_name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        mid.addWidget(lbl_name)
        lbl_code = QLabel(str(item.get("symbol") or ""))
        lbl_code.setStyleSheet("color:#9AA6B8;font-size:10.5px;background:transparent;")
        mid.addWidget(lbl_code)
        lay.addLayout(mid, 1)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(1)
        lbl_main = QLabel(str(item.get("main") or ""))
        lbl_main.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl_main.setStyleSheet("color:#1F2A37;font-size:11.5px;background:transparent;")
        # ★1.90：右列**给足最小宽度**（旧版被挤 ⇒ 只显示 "> 24.98%"，前半截被裁掉，用户实测）
        lbl_main.setMinimumWidth(104)
        lbl_main.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        right.addWidget(lbl_main)
        lbl_sub = QLabel(str(item.get("sub") or ""))
        lbl_sub.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl_sub.setStyleSheet(f"color:{_col};font-size:10.5px;background:transparent;")
        right.addWidget(lbl_sub)
        lay.addLayout(right, 0)


class _Block(QFrame):
    """一条记录：日期 + 若干明细 + 一行备注。"""

    def __init__(self, rec: dict, first: bool, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        if not first:                       # 记录之间一条淡分隔线（不要每行都画框）
            self.setStyleSheet("QFrame { border-top:1px solid #EFF3F8; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0 if first else 7, 0, 0)
        lay.setSpacing(3)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        lbl_at = QLabel(str(rec.get("at") or "—"))
        lbl_at.setStyleSheet("color:#7A8598;font-size:11px;background:transparent;")
        head.addWidget(lbl_at, 0)
        head.addStretch(1)
        _tag = str(rec.get("tag") or "")
        if _tag:
            lbl_tag = QLabel(_tag)
            lbl_tag.setStyleSheet("color:#9AA6B8;font-size:10.5px;background:transparent;")
            head.addWidget(lbl_tag, 0)
        lay.addLayout(head)

        for it in (rec.get("items") or []):
            lay.addWidget(_Row(it, self))
        if rec.get("note"):
            lbl_note = QLabel(str(rec.get("note")))
            lbl_note.setWordWrap(True)
            lbl_note.setStyleSheet("color:#8A94A6;font-size:10.5px;background:transparent;")
            lay.addWidget(lbl_note)


class ChangeList(QScrollArea):
    """调仓记录列表：**限高可滚**，条数不设上限（记录永久保留）。"""

    MIN_H = 160        # ★1.90：**自适应填满**右栏剩余高度（不再设上限；记录多就滚动）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setMinimumHeight(self.MIN_H)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.setStyleSheet("QScrollArea { background:transparent; }")
        self._body = QWidget()
        self._body.setStyleSheet("background:transparent;")
        self._lay = QVBoxLayout(self._body)
        self._lay.setContentsMargins(0, 0, 2, 0)
        self._lay.setSpacing(2)
        self._lay.addStretch(1)
        self.setWidget(self._body)
        self._n = 0

    # ---------- 对外 ----------
    def set_records(self, records, hint: str = "") -> None:
        """`records` 已是**显示顺序**（新 → 旧）；空表 ⇒ 整个列表隐藏（提示交给调用方的 QLabel）。"""
        self._clear()
        recs = list(records or [])
        self._n = len(recs)
        if not recs:
            self.setVisible(False)
            return
        self.setVisible(True)
        for i, rec in enumerate(recs):
            self._lay.insertWidget(i, _Block(rec, i == 0, self._body))
        # ★1.90：**不再按条数封顶** —— 高度交给布局（右栏拉伸），内容超出就出滚动条；
        #   记录本身永久保留，不为了"好看"删数据。

    def count(self) -> int:
        return self._n

    def all_text(self) -> str:
        """所有可见文本拼起来（冒烟断言与"复制"用；不参与渲染）。"""
        return "\n".join(w.text() for w in self._body.findChildren(QLabel) if w.text())

    def _clear(self) -> None:
        while self._lay.count() > 1:                  # 末尾那条 stretch 保留
            it = self._lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
