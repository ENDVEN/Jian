# ui/widgets/scan_result.py
"""🌐 M2「全市场筛选」—— 结果渲染（KPI 行 + 结果表 + 空态）。

【口径铁律的落地点】KPI 必须把 **数据不足** 单独列出来（E 节：橙 pill + 计数显式），
**有效样本数** 与**用时**一并展示 —— 绝不把"数据不足"并进"未命中"，
也绝不把分母写成"全市场只数"（core/cross_section.tally_status 是唯一口径）。

【为什么"说明/数值"列可能整体是 '—'】会话缓存只存**状态矩阵**（D3），
切日期后的状态来自 `status_on(date)`（零成本、逐位正确），
但**当日的数值快照与"为什么"明细只在扫描基准日有效**（D3 的使用纪律）。
所以切了日期就只显示状态，并在脚注/tooltip 里说清 —— 不许拿旧日期的数值冒充当日。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QTableWidget, QTableWidgetItem

from core.cross_section import FILTERED, HIT, INSUFFICIENT, MISS, STATUS_LABELS

__all__ = ['ScanResult', 'STATUS_BG', 'STATUS_FG']

# 三态 + 被剔除 的配色（E 节：命中主色实心 / 未命中灰 / 数据不足橙；跌与警示沿用现状色板）
STATUS_BG = {HIT: '#E8F5E9', MISS: '#F5F6F8', INSUFFICIENT: '#FFF3E0', FILTERED: '#F0F3F8'}
STATUS_FG = {HIT: '#2E7D32', MISS: '#8A94A6', INSUFFICIENT: '#E65100', FILTERED: '#B4BECB'}

_KPI_STYLE = {
    'hit': ('#E8F5E9', '#2E7D32', '命中（满足条件）'),
    'miss': ('#F5F6F8', '#5A6474', '未命中（有数据、条件不成立）'),
    'insufficient': ('#FFF3E0', '#E65100', '数据不足（无行/停牌/历史太短/缺列）—— **不是未命中**'),
    'filtered': ('#F0F3F8', '#8A94A6', '被粗筛剔除（数据没问题，只是不满足阈值）'),
    'valid': ('#E8F1FF', '#1976D2', '有效样本 = 命中 + 未命中 —— **广度占比的分母**'),
    'elapsed': ('#F5F6F8', '#8A94A6', '本次耗时；「缓存」表示这次没有重算（切日期/换窗口零成本）'),
}


def _num(value) -> str:
    """数值 → 展示文本（None/NaN → '—'；**用户量纲**由调用方换算好）"""
    try:
        if value is None:
            return '—'
        number = float(value)
    except (TypeError, ValueError):
        return '—'
    if number != number:                      # NaN
        return '—'
    return f'{number:,.2f}'.rstrip('0').rstrip('.') if abs(number) < 1e6 else f'{number:,.0f}'


class ScanResult:
    """结果区渲染（只读写 `p.X`，不存状态）。"""

    def __init__(self, page):
        self.page = page

    # ---------- 空态（三种空态都给下一步动作，E 节） ----------
    def set_empty(self, text: str, action_text: str = '', on_action=None) -> None:
        p = self.page
        p.lbl_empty.setText(text)
        p.empty_box.show()
        p.table.hide()
        if action_text:
            p.btn_empty_action.setText(action_text)
            p.btn_empty_action.show()
            try:
                p.btn_empty_action.clicked.disconnect()
            except TypeError:
                pass                            # 本来就没连过
            if on_action is not None:
                p.btn_empty_action.clicked.connect(on_action)
        else:
            p.btn_empty_action.hide()

    def set_busy(self, text: str) -> None:
        """扫描中：结果区收起（避免上一轮结果被误读成本轮的）。"""
        self.page.lbl_empty.setText(text)
        self.page.empty_box.show()
        self.page.table.hide()

    # ---------- KPI ----------
    def _render_kpis(self, counts: dict, elapsed_ms: float, cached: bool) -> None:
        p = self.page
        values = {
            'hit': counts.get(HIT, 0),
            'miss': counts.get(MISS, 0),
            'insufficient': counts.get(INSUFFICIENT, 0),
            'filtered': counts.get(FILTERED, 0),
            'valid': counts.get('valid', 0),
            'elapsed': elapsed_ms,
        }
        for key, (bg, fg, tip) in _KPI_STYLE.items():
            pill = p.kpi[key]
            value = values[key]
            if key == 'hit':
                text = f'命中 {value} · {counts.get("total", 0)} 只'
            elif key == 'valid':
                text = f'有效样本 {value}/{counts.get("total", 0)}'
            elif key == 'elapsed':
                seconds = (elapsed_ms or 0.0) / 1000.0
                text = ('缓存命中' if cached else f'用时 {seconds:.2f} s')
            else:
                text = f'{STATUS_LABELS["insufficient" if key == "insufficient" else key]} {value}'
            pill.setText(text)
            pill.setToolTip(tip)
            pill.setStyleSheet(
                f'font-size: 12px; font-weight: bold; color:{fg};'
                f'background:{bg}; border-radius:8px; padding:5px 10px;')

    # ---------- 表格 ----------
    def _render_table(self, status: dict, detail, snapshot, names: dict) -> None:
        p = self.page
        table: QTableWidget = p.table
        order = (HIT, MISS, INSUFFICIENT, FILTERED)
        rows = [sym for key in order for sym in sorted(status) if status[sym] == key]
        table.setRowCount(len(rows))
        for row, sym in enumerate(rows):
            state = status[sym]
            values = (snapshot or {}).get(sym) or {}
            cells = (
                sym,
                str(names.get(sym) or ''),
                _num(values.get('close')),
                _num((values.get('amount') / 1e4) if values.get('amount') is not None else None),
                _num((values.get('turnover') * 100.0)
                     if values.get('turnover') is not None else None),
                STATUS_LABELS.get(state, state),
                (detail or {}).get(sym, ''),
            )
            for col, text in enumerate(cells):
                item = QTableWidgetItem(str(text))
                if col == 5:                      # 状态 pill
                    item.setForeground(QColor(STATUS_FG.get(state, '#1F2430')))
                    item.setBackground(QColor(STATUS_BG.get(state, '#FFFFFF')))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                elif col == 6 and text:
                    item.setForeground(QColor('#8A94A6'))
                item.setToolTip(str(text) if text else '')
                table.setItem(row, col, item)

    # ---------- 主入口 ----------
    def render(self, counts: dict, status: dict, detail, snapshot, names: dict,
               elapsed_ms: float, cached: bool, date_label: str, scope_label: str) -> None:
        p = self.page
        self._render_kpis(counts, elapsed_ms, cached)
        self._render_table(status, detail, snapshot, names)
        p.empty_box.hide()
        p.table.show()
        # 口径印在标题上（E 节）
        p.lbl_title.setText(f'某一天的全市场筛选 · {date_label}')
        p.lbl_foot.setText(
            f'口径：{scope_label} · 前复权 · 粗筛后精算 · 数据不足不计入命中'
            + ('' if snapshot is not None
               else ' · 本日**只显示状态**（数值/明细以扫描基准日为准，见 D3 的缓存口径）')
            + ' · 双击任意一行 → 行情工作台打开该股')
