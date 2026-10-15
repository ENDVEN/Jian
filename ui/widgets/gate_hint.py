# ui/widgets/gate_hint.py
"""🚦 三道闸的**"看得见"部件**（★1.74 / §7-B16 期 2）。

【它把什么变成看得见的】"这个条件能不能用事件对齐图看"这件事，判据在
  `core/relation_stats.gate_decision`（纯函数，唯一真源）—— 本文件只做两件事：
  ① 把判定结果渲染成**徽标**（统计项每行右侧）与**闸条**（结果区，仅在有被禁用项时出现）；
  ② 给三项阈值一个**就地可调**的入口（与「设置 → 回测与扫描默认」**同一份偏好**）。

【三条纪律】
  · **判据不在这里**：任何"能不能用"的判断都调 `relation_stats`，本件不许自己算阈值边界
    （§11.5-112：同一事实只存一处；否则"设置里说能、页面上说不能"必然发生）。
  · **禁用态三要素**：原因（带数字）· 替代方案 · 动作（调阈值 / 看说明）—— 缺一不算完成。
  · **不许假入口**：闸条上的按钮全都接到真实动作（打开展示卡改阈值 / 打开三道闸说明）。
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                             QVBoxLayout, QWidget)

from core import relation_stats as rs
from ui.widgets.custom_widgets import NoWheelDoubleSpinBox, NoWheelSpinBox
from ui.widgets.styles import FLAT_QSS

__all__ = ['verdict_badge', 'GateThresholdRow', 'GateHintBar', 'BADGE_COLORS']

# 徽标配色（与设计稿 E 页同源：可用=绿 / 半稀疏=琥珀 / 禁用=红 / 没扫=灰）
BADGE_COLORS = {rs.MODE_EVENT: '#2E7D32', rs.MODE_BINNED: '#B26A00',
                rs.MODE_CONTINUOUS: '#C62828', rs.MODE_UNKNOWN: '#8A94A6'}


def verdict_badge(verdict: dict = None) -> tuple:
    """把 `gate_decision` 的结果渲染成 `(徽标文本, tooltip, 颜色)`。

    `verdict` = `{'mode','event_ok','ratio_pct','reason','suggest','hit_days','days'}`；
    缺 / 空 ⇒ 如实显示"还没扫描"（**不猜档位** —— §10-4 诚实性）。
    """
    # `gate_decision` 返回 dataclass；本函数也收 dict（页面把它摊平后给面板用）
    v = (asdict(verdict) if is_dataclass(verdict) and not isinstance(verdict, type)
         else dict(verdict or {}))
    mode = str(v.get('mode') or rs.MODE_UNKNOWN)
    color = BADGE_COLORS.get(mode, BADGE_COLORS[rs.MODE_UNKNOWN])
    if mode == rs.MODE_UNKNOWN:
        return '未扫描', '还没有这次扫描的占比 —— 点「▶ 开始扫描」后自动判定', color
    pct = v.get('ratio_pct')
    pct_text = f'{float(pct):.1f}%' if pct is not None else '—'
    if mode == rs.MODE_EVENT:
        text = f'事件图可用 {pct_text}'
    elif mode == rs.MODE_BINNED:
        text = f'半稀疏 {pct_text}'
    else:
        text = f'太频繁 {pct_text}'
    tip = [f'命中**天数**占比 {pct_text}',
           f"（{int(v.get('hit_days') or 0)} / {int(v.get('days') or 0)} 个交易日）"]
    if v.get('reason'):
        tip.append(str(v['reason']))
    if v.get('suggest'):
        tip.append('替代方案：' + str(v['suggest']))
    if not v.get('event_ok', False):
        tip.append('⚠ 事件对齐图 / K 线色带对该条件**不适用**')
    return text, '\n'.join(tip), color


class GateThresholdRow(QWidget):
    """三项阈值**就地可调**（与设置页**同一份偏好** `sweep3dense`）。

    改完 **立即重算徽标与闸条**（纯函数 ⇒ **不重扫**）；脏值/交叉由 `clamp_thresholds` 夹，
    夹完**如实显示实际生效值**（界面显示的必须 == 实际生效的，§11.5-132 同族）。
    """

    changed = pyqtSignal(dict)          # 实际生效值 {'sparse_max','freq_min','indep_gap'}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._blocked = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(6)
        lab = QLabel('三道闸阈值')
        lab.setStyleSheet('font-size: 12px; color: #5A6675;')
        head.addWidget(lab)
        self.btn_reset = QPushButton('↺ 恢复默认')
        self.btn_reset.setStyleSheet(FLAT_QSS)
        self.btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reset.setToolTip('回到出厂值：稀疏闸 5% · 频密闸 30% · 独立事件间隔 5 天')
        head.addWidget(self.btn_reset)
        head.addStretch()
        lay.addLayout(head)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.sp_sparse = self._spin(rs.DEFAULT_SPARSE_MAX, 0.5, 50.0, 0.5, 1, ' %',
                                    '命中**天数**占比低于它 ⇒ 够稀疏 ⇒ 事件对齐图 / 色带可用')
        row.addWidget(QLabel('稀疏闸'))
        row.addWidget(self.sp_sparse)
        self.sp_freq = self._spin(rs.DEFAULT_FREQ_MIN, 5.0, 99.0, 1.0, 0, ' %',
                                  '命中天数占比 ≥ 它 ⇒ 基本天天命中（"状态"）⇒ 事件图禁用，'
                                  '改走占比分档 / Rank IC')
        row.addWidget(QLabel('频密闸'))
        row.addWidget(self.sp_freq)
        self.sp_gap = self._spin(rs.DEFAULT_INDEP_GAP, 1, 60, 1, 0, ' 日',
                                 '连续命中要塌成"一个事件"：与上一个被接受事件相隔 ≥ 它才算独立')
        row.addWidget(QLabel('独立事件间隔'))
        row.addWidget(self.sp_gap)
        row.addStretch()
        lay.addLayout(row)

        self.lbl_note = QLabel('')
        self.lbl_note.setWordWrap(True)
        self.lbl_note.setStyleSheet('font-size: 11px; color: #B26A00;')
        lay.addWidget(self.lbl_note)

        for sp in (self.sp_sparse, self.sp_freq, self.sp_gap):
            sp.valueChanged.connect(self._emit)
        self.btn_reset.clicked.connect(self.reset_defaults)

    @staticmethod
    def _spin(value, lo, hi, step, decimals, suffix, tip):
        # ⚠ 必须用 `NoWheel*`：本卡住在**可滚动抽屉**里 —— 普通 SpinBox 会在滚动时
        #   被滚轮悄悄改值（这正是仓库里那对包装类存在的原因）。
        # ⚠ 整数档（`decimals == 0`）的边界/步长/初值都要给 **int** —— 传 float 会
        #   `TypeError: setRange(...): argument 1 has unexpected type 'float'`（本轮实测踩到）。
        if decimals:
            sp = NoWheelDoubleSpinBox()
            sp.setRange(float(lo), float(hi))
            sp.setSingleStep(float(step))
            sp.setDecimals(int(decimals))
            sp.setValue(float(value))
        else:
            sp = NoWheelSpinBox()
            sp.setRange(int(round(lo)), int(round(hi)))
            sp.setSingleStep(max(1, int(round(step))))
            sp.setValue(int(round(value)))
        sp.setSuffix(suffix)
        sp.setToolTip(tip)
        sp.setMinimumWidth(74)
        return sp

    # ---------- 读写 ----------
    def values(self) -> dict:
        return {'sparse_max': float(self.sp_sparse.value()),
                'freq_min': float(self.sp_freq.value()),
                'indep_gap': int(self.sp_gap.value())}

    @staticmethod
    def _put(sp, value) -> None:
        """按**控件类型**放值：int 档（`NoWheelSpinBox`）必须给 int ——
        `setValue(30.0)` 在 QSpinBox 上直接抛 `TypeError`（本轮实测踩到，两处同族）。"""
        if isinstance(sp, NoWheelDoubleSpinBox):
            sp.setValue(float(value))
        else:
            sp.setValue(int(round(float(value))))

    def set_values(self, values: dict, *, silent: bool = False) -> None:
        """回灌（**夹过域**：脏值/交叉由唯一真源处理，并把实际生效值显示出来）。"""
        fixed = rs.clamp_thresholds((values or {}).get('sparse_max'),
                                    (values or {}).get('freq_min'),
                                    (values or {}).get('indep_gap'))
        self._blocked = True
        try:
            self._put(self.sp_sparse, fixed['sparse_max'])
            self._put(self.sp_freq, fixed['freq_min'])
            self._put(self.sp_gap, fixed['indep_gap'])
        finally:
            self._blocked = False
        self.lbl_note.setText('　'.join(fixed.get('notes') or []))
        if not silent:
            self._emit()

    def reset_defaults(self) -> None:
        self.set_values({'sparse_max': rs.DEFAULT_SPARSE_MAX,
                         'freq_min': rs.DEFAULT_FREQ_MIN,
                         'indep_gap': rs.DEFAULT_INDEP_GAP})

    def _emit(self, *_a) -> None:
        if self._blocked:
            return
        self.changed.emit(self.values())


class GateHintBar(QFrame):
    """结果区的**闸条**（只在"有统计项被闸拦下"时出现；与首次引导条同一张脸）。

    三要素齐全：**原因（带数字）· 替代方案 · 动作**。没有可点的假按钮。
    """

    fix_requested = pyqtSignal()        # 去改阈值（页面打开「📈 展示」卡）
    why_requested = pyqtSignal()        # 看三道闸说明（与常驻 ⓘ 同一份文案）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet('QFrame { background: #FFFDF7; border: 1px solid #F5D5A8;'
                           ' border-radius: 8px; }')
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 8, 6)
        lay.setSpacing(8)
        self.lbl = QLabel('')
        self.lbl.setWordWrap(True)
        self.lbl.setStyleSheet('font-size: 11.5px; color: #8A5A00; border: none;')
        lay.addWidget(self.lbl, 1)
        self.btn_fix = QPushButton('调整阈值')
        self.btn_fix.setStyleSheet(FLAT_QSS)
        self.btn_fix.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_fix.setToolTip('在「📈 展示」卡里就地改三项阈值 —— 与设置页是**同一份**，'
                                '改完立即生效、**不用重扫**')
        self.btn_fix.clicked.connect(self.fix_requested.emit)
        lay.addWidget(self.btn_fix)
        self.btn_why = QPushButton('为什么？')
        self.btn_why.setStyleSheet(FLAT_QSS)
        self.btn_why.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_why.setToolTip('1 分钟看完：什么样的条件配什么样的图（以及 n 该怎么算）')
        self.btn_why.clicked.connect(self.why_requested.emit)
        lay.addWidget(self.btn_why)
        self.hide()

    def set_blocked(self, rows: list) -> None:
        """`rows` = `[(项名, verdict_dict)]`（只传**被禁用**的项）；空列表 ⇒ 收起整条。

        ⚠ 文案**不在这里重写**：原因/数字/替代方案一律用判据给的 `reason` / `suggest`
          （§11.5-112：同一事实只存一处 —— 否则"设置说 30%、闸条说 40%"必然发生）。
        """
        rows = list(rows or [])
        if not rows:
            self.hide()
            self.lbl.setText('')
            return
        parts = []
        for label, v in rows[:3]:
            reason = str((v or {}).get('reason') or '').strip() or '不适用'
            parts.append(f'<b>{label}</b>：{reason}')
        more = f'<br>… 另有 {len(rows) - 3} 项同样不适用' if len(rows) > 3 else ''
        sug = str((rows[0][1] or {}).get('suggest') or '').strip()
        # ⚠ 这个 QLabel 是 **rich text**（文案里有 `<br>`）⇒ 强调必须写 `<b>`：
        #   写 `**不适用**` 会**原样显示星号**（Tooltip 是纯文本、`**` 是那儿的既有风格，
        #   两种载体不能混用同一套记号）。
        self.lbl.setText('⛔ 事件对齐图 / K 线色带对下列条件 <b>不适用</b>：<br>'
                         + '<br>'.join(parts) + more
                         + (f'<br>替代方案：{sug}' if sug else ''))
        self.show()
