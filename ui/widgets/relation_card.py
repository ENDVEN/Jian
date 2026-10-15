# ui/widgets/relation_card.py
"""🧮 M3「与指数的关系」量化卡（★1.75 / §7-B16 期 3 · 设计稿 D 页右半）。

【它把什么端上桌】四项固定同屏，全部**带样本量**：
  ① 条件前向收益（命中之后 vs 全样本基线，窗口 5/10/20）· ② 领先滞后（峰值在哪、多强）
  · ③ Rank IC（占比 vs 未来 N 期收益）· ④ 置换检验 p（"随机也能凑出来"的概率）。

【三条诚实纪律 · 写在卡上、不是写在注释里】
  ① **样本不足必须明说**（`enough=False` ⇒ 那一行标"样本不足，仅参考"）；
  ② **绝对不比 p 值大小**：一次比较了几组就如实写出来（多方案 × 多窗口 ⇒ 提醒 Bonferroni）；
  ③ **幸存者偏差**：花名册是"今天的名单"⇒ 回看历史有偏差，这一行**常驻**。

【导出】PNG（`grab()` —— 卡长什么样就存什么样）与 CSV（**表里就是屏幕上那些数**）。
  导出按钮只发信号，落盘由页面做（§9-D：widgets 不碰文件系统）。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                             QVBoxLayout, QWidget)

from ui.widgets.relation_chart import LeadLagChart
from ui.widgets.styles import FLAT_QSS

__all__ = ['RelationCard', 'WINDOWS']

WINDOWS = (5, 10, 20)          # 条件前向收益的窗口（交易日）—— 与图表/导出**同一份**

_SURVIVOR = ('幸存者偏差提醒：花名册是「今天的名单」——用它回看历史会漏掉当年还没上市、'
             '后来退市的票，结论偏向"活下来的那批"。别把这里的数字当成无偏历史统计。')
_CAUSAL = ('相关 ≠ 因果：本卡只回答"同期 / 领先 N 期有多相关"，不回答"能不能预测"。'
           '多方案 × 多窗口一起比较时，请按比较次数收紧显著性（例：3 条件 × 3 窗口 = 9 次 '
           '⇒ Bonferroni 需 p < 0.0056）。')


class RelationCard(QWidget):
    """量化卡（纯展示；数据由页面喂）。"""

    export_png_requested = pyqtSignal()
    export_csv_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(6)
        self.lbl_title = QLabel('与指数的关系')
        self.lbl_title.setStyleSheet('font-size: 12.5px; font-weight: 600; color: #4A5568;')
        head.addWidget(self.lbl_title, 1)
        self.btn_png = QPushButton('⤓ 导出 PNG')
        self.btn_csv = QPushButton('⤓ 导出 CSV')
        for _b, _tip in ((self.btn_png, '把这张卡**原样**存成图片（会上会发的就是它）'),
                         (self.btn_csv, '把卡上的数字存成 CSV（可直接进 Excel 复算）')):
            _b.setStyleSheet(FLAT_QSS)
            _b.setCursor(Qt.CursorShape.PointingHandCursor)
            _b.setToolTip(_tip)
            head.addWidget(_b)
        self.btn_png.clicked.connect(self.export_png_requested.emit)
        self.btn_csv.clicked.connect(self.export_csv_requested.emit)
        root.addLayout(head)

        # ① 条件前向收益（表格用 QGridLayout：列少、行数随项数，别上 QTableWidget）
        self.body = QWidget()
        self._body_lay = QVBoxLayout(self.body)
        self._body_lay.setContentsMargins(0, 0, 0, 0)
        self._body_lay.setSpacing(8)
        root.addWidget(self.body)

        self.lbl_note = QLabel('')
        self.lbl_note.setWordWrap(True)
        self.lbl_note.setStyleSheet('font-size: 11px; color: #8A94A6;')
        root.addWidget(self.lbl_note)

        self.lbl_honest = QLabel(f'{_CAUSAL}\n{_SURVIVOR}')
        self.lbl_honest.setWordWrap(True)
        self.lbl_honest.setStyleSheet(
            'font-size: 11px; color: #8A5A00; background: #FFFDF7; border: 1px solid #F5D5A8;'
            ' border-radius: 8px; padding: 6px 8px;')
        root.addWidget(self.lbl_honest)
        self._rows: list[dict] = []          # CSV 导出的**唯一来源**（屏幕上有什么就导什么）
        self.set_report(None)

    # ==========================================
    # 喂数据（页面 → 卡，单向）
    # ==========================================
    def set_report(self, report: dict = None) -> None:
        """`report` 见 `BreadthFlow.relation_report()`；`None` / 空 ⇒ 显示"还没扫描"。"""
        while self._body_lay.count():
            _it = self._body_lay.takeAt(0)
            _w = _it.widget()
            if _w is not None:
                _w.deleteLater()
        self._rows = list((report or {}).get('items') or [])
        if not self._rows:
            tip = QLabel('还没有可算的关系 —— 先「▶ 开始扫描」。'
                         '（本卡需要**命中序列** + 指数收盘：前者来自扫描，后者来自副图那个指数）')
            tip.setWordWrap(True)
            tip.setStyleSheet('font-size: 11.5px; color: #8A94A6;')
            self._body_lay.addWidget(tip)
            self.lbl_note.setText('')
            return

        self.lbl_title.setText(f"与指数的关系 · {report.get('index_label') or '指数'}"
                               f"（{report.get('range_label') or ''}）")
        # ① 条件前向收益
        self._body_lay.addWidget(self._section('① 命中之后指数怎么走（条件 vs 全样本基线）'))
        for it in self._rows:
            self._body_lay.addWidget(self._fwd_block(it))
        # ② 领先滞后
        self._body_lay.addWidget(self._section('② 领先滞后（峰值在负侧 = 指标领先指数）'))
        self.chart_leadlag = LeadLagChart()
        self.chart_leadlag.setMinimumHeight(190)
        self._body_lay.addWidget(self.chart_leadlag)
        self.chart_leadlag.render([(it.get('label') or it.get('key'),
                                    it.get('color') or '#1E88E5',
                                    it.get('leadlag') or {})
                                   for it in self._rows])
        # ③ Rank IC + ④ 置换检验
        self._body_lay.addWidget(self._section('③ Rank IC（占比 vs 未来收益）· ④ 置换检验 p'))
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(3)
        for col, text in enumerate(('统计项', 'Rank IC（5/10/20 期）', '置换检验 p（20 期）',
                                    '有效点', '结论')):
            lab = QLabel(text)
            lab.setStyleSheet('font-size: 11px; color: #6B7684; font-weight: 600;')
            grid.addWidget(lab, 0, col)
        for r, it in enumerate(self._rows, start=1):
            _ic = it.get('ic') or {}
            _perm = it.get('perm') or {}
            _vals = [self._fmt(_ic.get(str(w), _ic.get(w)), nd=3) for w in WINDOWS]
            grid.addWidget(self._cell(it.get('label') or it.get('key'), bold=True), r, 0)
            grid.addWidget(self._cell(' / '.join(_vals)), r, 1)
            _p = _perm.get('p')
            _ptxt = self._fmt(_p, nd=3) if _p is not None else (str(_perm.get('reason') or '—'))
            _plab = self._cell(_ptxt)
            if _p is not None and float(_p) < 0.05:
                _plab.setStyleSheet('font-size: 11.5px; color: #2E7D32;')
            grid.addWidget(_plab, r, 2)
            grid.addWidget(self._cell(str(_perm.get('n') or '—')), r, 3)
            grid.addWidget(self._cell(str(it.get('verdict_text') or '')), r, 4)
        holder = QWidget()
        holder.setLayout(grid)
        self._body_lay.addWidget(holder)
        self.lbl_note.setText('　'.join(filter(None, [
            f"{len(self._rows)} 个统计项参与比较",
            '样本不足的行已标注（其数字仅供参考）',
            '份额外口径：' + str(report.get('note') or '') if report.get('note') else ''])))

    # ---------- 内部 ----------
    @staticmethod
    def _section(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setStyleSheet('font-size: 11.5px; color: #4A5568; font-weight: 600;')
        return lab

    @staticmethod
    def _cell(text, *, bold: bool = False) -> QLabel:
        lab = QLabel(str(text))
        lab.setStyleSheet('font-size: 11.5px;' + (' font-weight: 600;' if bold else ''))
        return lab

    @staticmethod
    def _fmt(value, *, nd: int = 3) -> str:
        """**NaN / None ⇒ "—"**（绝不冒充 0 —— 与仓库 IC 口径同源纪律）。"""
        try:
            fv = float(value)
        except (TypeError, ValueError):
            return '—'
        return '—' if fv != fv else f'{fv:+.{nd}f}'

    def _fwd_block(self, it: dict) -> QWidget:
        box = QFrame()
        box.setStyleSheet('#fwd { background: #FBFCFE; border: 1px solid #E7EAF0;'
                          ' border-radius: 8px; }')
        box.setObjectName('fwd')
        lay = QGridLayout(box)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setHorizontalSpacing(12)
        name = QLabel(f"<span style='color:{it.get('color') or '#1E88E5'};'>●</span> "
                      f"{it.get('label') or it.get('key')}"
                      f"（命中天数占比 {self._fmt(it.get('ratio_pct'), nd=1)}%）")
        name.setStyleSheet('font-size: 11.5px; font-weight: 600;')
        lay.addWidget(name, 0, 0, 1, 4)
        for col, text in enumerate(('窗口', '命中之后', '全样本基线', '差值')):
            lab = QLabel(text)
            lab.setStyleSheet('font-size: 10.5px; color: #6B7684;')
            lay.addWidget(lab, 1, col)
        fwd = it.get('fwd') or {}
        for row, w in enumerate(WINDOWS, start=2):
            cell = fwd.get(str(w), fwd.get(w)) or {}
            lay.addWidget(self._cell(f'+{w} 日'), row, 0)
            lay.addWidget(self._cell(self._pct(cell.get('mean'))), row, 1)
            lay.addWidget(self._cell(self._pct(cell.get('baseline_mean'))), row, 2)
            _diff = cell.get('diff')
            _dlab = self._cell(self._pct(_diff, signed=True))
            if _diff is not None and _diff == _diff:
                _dlab.setStyleSheet('font-size: 11.5px; color: '
                                    + ('#2E7D32' if float(_diff) > 0 else '#C62828'))
            lay.addWidget(_dlab, row, 3)
        if not any((fwd.get(str(w), fwd.get(w)) or {}).get('enough', False) for w in WINDOWS):
            warn = QLabel('样本不足（命中 < 30 次）⇒ 这些数字仅供参考，不要据此下结论')
            warn.setStyleSheet('font-size: 10.5px; color: #B26A00;')
            lay.addWidget(warn, len(WINDOWS) + 2, 0, 1, 4)
        return box

    def _pct(self, value, *, signed: bool = False) -> str:
        try:
            fv = float(value) * 100.0
        except (TypeError, ValueError):
            return '—'
        if fv != fv:
            return '—'
        return f'{fv:+.2f}%' if signed else f'{fv:.2f}%'

    # ---------- 给导出用（**屏幕上有什么就导什么**）----------
    def rows_for_csv(self) -> list[dict]:
        """CSV 行：每项 × 每窗口一行 + 领先滞后峰值 + IC + p（列名用中文，给人看）。"""
        out = []
        for it in self._rows:
            fwd = it.get('fwd') or {}
            ic = it.get('ic') or {}
            for w in WINDOWS:
                cell = fwd.get(str(w), fwd.get(w)) or {}
                out.append({
                    '统计项': str(it.get('label') or it.get('key') or ''),
                    '判定变量': str(it.get('key') or ''),
                    '命中天数占比%': it.get('ratio_pct'),
                    '前向窗口(交易日)': w,
                    '条件均值%': self._num(cell.get('mean')),
                    '基线均值%': self._num(cell.get('baseline_mean')),
                    '差值%': self._num(cell.get('diff')),
                    '样本n(命中日)': cell.get('n'),
                    '样本足够': bool(cell.get('enough')),
                    'RankIC': self._num(ic.get(str(w), ic.get(w))),
                    '置换p(20日)': self._num((it.get('perm') or {}).get('p')),
                    '领先峰值lag': (it.get('lead_peak') or [None, None])[0],
                    '领先峰值r': self._num((it.get('lead_peak') or [None, None])[1]),
                    '闸结论': str(it.get('verdict_text') or ''),
                })
        return out

    @staticmethod
    def _num(value):
        try:
            fv = float(value)
        except (TypeError, ValueError):
            return ''
        return '' if fv != fv else fv
