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
from PyQt6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem

from core.cross_section import FILTERED, HIT, INSUFFICIENT, MISS, STATUS_LABELS

__all__ = ['ScanResult', 'STATUS_BG', 'STATUS_FG', 'MAX_TABLE_ROWS']

# 表格只画前 N 行（v6.42）：全 A 四态清单 5000+ 行逐格建 item 会拖住 UI 线程；
# 截断必须**说实话**（脚注写明共多少行），绝不静默丢行。
MAX_TABLE_ROWS = 2000

# 三态 + 被剔除 的配色（E 节：命中主色实心 / 未命中灰 / 数据不足橙；跌与警示沿用现状色板）
STATUS_BG = {HIT: '#E8F5E9', MISS: '#F5F6F8', INSUFFICIENT: '#FFF3E0', FILTERED: '#F0F3F8'}
STATUS_FG = {HIT: '#2E7D32', MISS: '#8A94A6', INSUFFICIENT: '#E65100', FILTERED: '#B4BECB'}

# ---- 列索引（与 `scan_layout.TABLE_COLUMNS` 严格同序；★P6 新增行业列）----
(COL_NUM, COL_SYM, COL_NAME, COL_INDUSTRY, COL_CLOSE, COL_DAY, COL_MONTH, COL_YEAR,
 COL_AMOUNT, COL_VOL, COL_TURNOVER, COL_PE, COL_PB, COL_TOTAL_MKTCAP,
 COL_MKTCAP, COL_STATUS, COL_DETAIL) = range(17)
# 涨幅三列（用 _signed_pct 显带符号百分数）
_PCT_COLS = (COL_DAY, COL_MONTH, COL_YEAR)
# 表头点击 → 排序取值（'sym'/'name' 走文本，其余走 snapshot 原始键；排序按原始值，与显示同序）。
# 状态列 = 复位到"命中置顶"；`#` / 说明 不参与排序；★P5/P6 估值与行业列来自独立快照/缓存，暂不排序。
_SORT_KEY = {COL_SYM: 'sym', COL_NAME: 'name', COL_CLOSE: 'close',
             COL_DAY: 'day_pct', COL_MONTH: 'month_pct', COL_YEAR: 'year_pct',
             COL_AMOUNT: 'amount', COL_VOL: 'volume', COL_TURNOVER: 'turnover',
             COL_MKTCAP: 'float_mktcap'}

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


def _signed_pct(value) -> str:
    """涨幅小数 → 带符号百分数（+6.87 / -2.30）；None/NaN → '—'（诚实，不拿 0 冒充）。"""
    try:
        if value is None:
            return '—'
        number = float(value)
    except (TypeError, ValueError):
        return '—'
    if number != number:                      # NaN
        return '—'
    return f'{number * 100.0:+.2f}'


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

    def clear(self) -> None:
        """丢掉上一范围的结果痕迹（★v1.41 / §11.5-80：切换统计范围时调用）。

        【为什么必须有】范围变了以后，旧范围的 KPI（"命中 N · M 只" / "有效样本 x/M"）
        若继续挂在结果区上方，会和**新范围**的就绪度提示（"未下载 456/500"）同屏，
        两套数字打架、用户不知道该信哪个（用户实测截图复现）。
        只复位 KPI 与表格；空态由紧随其后的 `set_empty(...)` 接管，这里不碰。
        """
        p = self.page
        p._sort_col = None            # ★P1：换范围 ⇒ 排序复位到默认命中置顶
        p._sort_desc = False
        for pill in (p.kpi or {}).values():
            pill.setText('—')
            pill.setToolTip('还没有结果')
            pill.setStyleSheet(
                'font-size: 12px; font-weight: bold; color:#8A94A6;'
                'background:#F5F6F8; border-radius:8px; padding:5px 10px;')
        p.table.setRowCount(0)

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
    def toggle_sort(self, col: int) -> bool:
        """表头点击 → 切换排序态（写在页面 `_sort_col/_sort_desc`）。返回 True = 状态变了要重画。

        默认（`_sort_col is None`）= 命中置顶；点数值/文本列 = 全局按该列排（None 值恒排最后）；
        再点同列 = 升/降切换；点**状态列** = 复位到命中置顶（用户 2026-09-25 拍板，不加额外按钮）。
        """
        p = self.page
        if col == COL_STATUS:
            p._sort_col, p._sort_desc = None, False
            return True
        keyname = _SORT_KEY.get(col)
        if keyname is None:                       # `#` / 说明 列不排
            return False
        if p._sort_col == col:
            p._sort_desc = not p._sort_desc
        else:
            p._sort_col = col
            p._sort_desc = keyname not in ('sym', 'name')   # 文本列默认升序，数值列默认降序
        return True

    def _ordered_rows(self, status: dict, snapshot, names: dict) -> list:
        """行序：**永远命中置顶**（HIT→MISS→INSUFFICIENT→FILTERED 分组）。

        组内默认按代码；点了某列后**组内按该列排**（取不到值的行排到该组末尾）。
        —— 用户 2026-09-25 明确：要的是“命中永远置顶 + 组内排序”，不是把命中/未命中混排。
        """
        p = self.page
        snap = snapshot or {}
        keyname = _SORT_KEY.get(getattr(p, '_sort_col', None))
        desc = bool(getattr(p, '_sort_desc', False))

        def _val(sym):
            if keyname in (None, 'sym'):
                return sym
            if keyname == 'name':
                return str(names.get(sym) or '')
            raw = (snap.get(sym) or {}).get(keyname)
            try:
                return None if raw is None else float(raw)
            except (TypeError, ValueError):
                return None

        rows: list = []
        for key in (HIT, MISS, INSUFFICIENT, FILTERED):
            group = sorted(s for s in status if status[s] == key)
            if keyname:
                have = [s for s in group if _val(s) is not None]
                tail = [s for s in group if _val(s) is None]
                have.sort(key=_val, reverse=desc)
                group = have + tail
            rows.extend(group)
        return rows

    def _render_table(self, status: dict, detail, snapshot, names: dict,
                      valuation=None, industry=None, resize: bool = True) -> int:
        """填表并返回**总行数**（可能大于实际上屏行数 —— 截断由调用方说清）。

        ⚠ 性能铁律（v6.42，用户实测"点 ◀▶ 软件卡死"的根因）：
        列宽模式绝不许用 ResizeToContents —— 那是**动态**测宽，每 setItem 一格
        都触发全表重新测量，5000 行 × 7 列 = 平方级复杂度直接冻死 UI 线程。
        正确姿势：关更新 → 逐格填 → **一次性** resizeColumnsToContents → 开更新；
        tooltip 只给"说明"列（3.8 万个 tooltip 对象是另一笔白付的开销）。"""
        p = self.page
        table: QTableWidget = p.table
        rows = self._ordered_rows(status, snapshot, names)
        total = len(rows)
        shown = rows[:MAX_TABLE_ROWS]
        header = table.horizontalHeader()
        was_dynamic = any(
            header.sectionResizeMode(i) == QHeaderView.ResizeMode.ResizeToContents
            for i in range(table.columnCount()))
        if was_dynamic:                                   # 护栏：万一有人改回去，这里兜住
            for i in range(table.columnCount()):
                if header.sectionResizeMode(i) == QHeaderView.ResizeMode.ResizeToContents:
                    header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
        table.setUpdatesEnabled(False)
        try:
            table.setRowCount(len(shown))
            for row, sym in enumerate(shown):
                state = status[sym]
                values = (snapshot or {}).get(sym) or {}
                val = (valuation or {}).get(sym) or {}      # ★P5 估值（仅基准日==最新定稿日才传入）
                cells = (
                    row + 1,                              # 行号：随显示顺序（含排序后）重算，命中区一眼数得清
                    sym,
                    str(names.get(sym) or ''),
                    str((industry or {}).get(sym) or '') or '—',   # ★P6 细分行业（本地缓存，缺则 '—'）
                    _num(values.get('close')),
                    _signed_pct(values.get('day_pct')),
                    _signed_pct(values.get('month_pct')),
                    _signed_pct(values.get('year_pct')),
                    _num((values.get('amount') / 1e4) if values.get('amount') is not None else None),
                    _num((values.get('volume') / 1e6) if values.get('volume') is not None else None),
                    _num((values.get('turnover') * 100.0)
                         if values.get('turnover') is not None else None),
                    _num(val.get('pe')),                  # ★P5 估值（valuation=None 时自然全 '—'）
                    _num(val.get('pb')),
                    _num((val.get('total_mktcap') / 1e8) if val.get('total_mktcap') is not None else None),
                    _num((values.get('float_mktcap') / 1e8) if values.get('float_mktcap') is not None else None),
                    STATUS_LABELS.get(state, state),
                    (detail or {}).get(sym, ''),
                )
                for col, text in enumerate(cells):
                    item = QTableWidgetItem(str(text))
                    if col == COL_NUM:                    # 行号：居中 + 弱化色
                        item.setForeground(QColor('#B4BECB'))
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    elif col == COL_STATUS:               # 状态 pill
                        item.setForeground(QColor(STATUS_FG.get(state, '#1F2430')))
                        item.setBackground(QColor(STATUS_BG.get(state, '#FFFFFF')))
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    elif col == COL_DETAIL and text:      # 说明列才有 tooltip
                        item.setForeground(QColor('#8A94A6'))
                        item.setToolTip(str(text))
                    table.setItem(row, col, item)
            if resize:                                  # ★只在**新扫描**时测一次列宽；
                table.resizeColumnsToContents()         #   排序/切日期不重测（否则列宽随顶部行内容跳动）
        finally:
            table.setUpdatesEnabled(True)
        return total

    # ---------- 主入口 ----------
    def render(self, counts: dict, status: dict, detail, snapshot, names: dict,
               elapsed_ms: float, cached: bool, date_label: str, scope_label: str,
               valuation=None, industry=None, resize: bool = True) -> None:
        p = self.page
        self._render_kpis(counts, elapsed_ms, cached)
        total = self._render_table(status, detail, snapshot, names,
                                   valuation=valuation, industry=industry, resize=resize)
        p.empty_box.hide()
        p.table.show()
        # 口径印在标题上（E 节）
        p.lbl_title.setText(f'某一天的全市场筛选 · {date_label}')
        p.lbl_foot.setText(
            f'口径：{scope_label} · 前复权 · 粗筛后精算 · 数据不足不计入命中'
            + ('' if snapshot is not None
               else ' · 本日**只显示状态**（数值/明细以扫描基准日为准，见 D3 的缓存口径）')
            + (f' · 仅显示前 {MAX_TABLE_ROWS} 行（共 {total} 行，缩小范围可看更多）'
               if total > MAX_TABLE_ROWS else '')
            + ' · 双击任意一行 → 行情工作台打开该股')
