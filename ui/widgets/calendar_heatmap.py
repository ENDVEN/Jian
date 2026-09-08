"""
GitHub 风格「每日净额日历热力图」(Dashboard · C1)。

【与复盘页月历的区别 —— 勿混淆，见 JIAN_RULES.md §7-C1】
  · 复盘页月历 `ui/views/review.py`      : 单月 6×7，服务"某月哪天做了什么"，可点选交易；
  · 本控件 `ui/widgets/calendar_heatmap.py`: 整年 53×7，服务"这一年交易节奏与盈亏分布长什么样"。

【为什么手绘而不是用 pyqtgraph】
  ① 零图表库依赖：371 个格子用 QGraphicsItem 反而更重，paintEvent 一次画完最轻；
  ② 圆角 / 留白 / 抗锯齿可精确控制，满足 §10-1 的 Michael Pokorny 准则；
  ③ hover 命中检测就是一次 (col,row) 反查，比图形项的信号槽简单得多。

【口径纪律】
  颜色 = 当日**净额** (net_profit − commission)，绿盈红亏，深浅 = 绝对值分位 5 档；
  无交易 / 净额为 0 的日一律中性灰 —— 绝不用浅绿冒充"0 元"（§10-4 诚实原则）。
  本控件只做展示与 hover tooltip，不碰 SQL / 网络 / 落库。
"""
from __future__ import annotations

from datetime import date

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath
from PyQt6.QtWidgets import QSizePolicy, QToolTip, QWidget

# 周一为第一行（中文习惯）；仅标注 一/三/五 以免左侧拥挤（同 GitHub 做法）
_WEEKDAY_LABELS = ("一", "二", "三", "四", "五", "六", "日")
_LABEL_ROWS = (0, 2, 4)  # 一 / 三 / 五

_LEFT_W = 22      # 左侧星期标签宽度
_TOP_H = 16       # 顶部月份标签高度
_BOTTOM_H = 22    # 底部图例高度
_GAP = 2          # 格子间距
_PAD = 6          # 四周留白
_DEFAULT_CELL = 12


class CalendarHeatmap(QWidget):
    """整年 53×7 的 GitHub 风格日历热力图。

    对外 API:
        set_year_data(year, values, counts=None)
            year   : 年份 (int)
            values : {datetime.date: 当日净额(float)} —— 缺失的日期 = 无交易
            counts : {datetime.date: 当日成交笔数(int)}，仅用于 tooltip
        clear()

    只负责画，不持有任何业务对象；宿主 (Dashboard) 负责按年聚合与年份切换。
    """

    # 由浅到深 5 档；中间档刻意取 settings.COLOR_PROFIT / COLOR_LOSS，与全局配色同源
    PROFIT_SCALE = ("#C8E6C9", "#A5D6A7", "#81C784", "#4CAF50", "#2E7D32")
    LOSS_SCALE = ("#FFCDD2", "#EF9A9A", "#E57373", "#F44336", "#C62828")
    EMPTY_COLOR = "#EBEDF0"
    AXIS_TEXT = "#9AA3B2"
    GRID_TEXT = "#5B6472"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._year: int | None = None
        self._values: dict[date, float] = {}
        self._counts: dict[date, int] = {}
        self._thresholds: list[float] = []

        self._cols = 53
        self._boxes: dict[tuple[int, int], QRectF] = {}
        self._box_date: dict[tuple[int, int], date] = {}

        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(_TOP_H + _BOTTOM_H + _PAD * 2 + 7 * (_DEFAULT_CELL + _GAP))

    # ==========================================
    # 对外 API
    # ==========================================
    def set_year_data(self, year: int, values: dict, counts: dict | None = None):
        """载入某年份数据并重绘。values 的键必须是 datetime.date"""
        self._year = int(year)
        self._values = {d: float(v) for d, v in (values or {}).items()}
        self._counts = {d: int(c) for d, c in (counts or {}).items()}
        self._thresholds = self._calc_thresholds(self._values)
        # 不同年份占用的周列数不同（闰年且元旦在周日时可达 54 列），必须动态计算
        self._cols = self._week_count(self._year)
        self.updateGeometry()
        self.update()

    def clear(self):
        """清空（无数据态）"""
        self._year = None
        self._values = {}
        self._counts = {}
        self._thresholds = []
        self.update()

    # ==========================================
    # 尺寸
    # ==========================================
    def sizeHint(self) -> QSize:
        return QSize(
            self._cols * (_DEFAULT_CELL + _GAP) - _GAP + _LEFT_W + _PAD * 2,
            _TOP_H + _BOTTOM_H + _PAD * 2 + 7 * (_DEFAULT_CELL + _GAP) - _GAP,
        )

    # ==========================================
    # 数据派生
    # ==========================================
    @staticmethod
    def _calc_thresholds(values: dict) -> list[float]:
        """把净额绝对值切成 5 档的 4 个阈值。

        样本 >= 5 时用分位（避免单日暴利把其余日子全洗成浅色）；
        样本太少时退回线性等分（保证至少能分出层次）。
        """
        mags = sorted(abs(v) for v in values.values() if v)
        if not mags:
            return []
        if len(mags) >= 5:
            pick = lambda p: mags[min(len(mags) - 1, int(len(mags) * p))]
            return [pick(0.25), pick(0.50), pick(0.75), pick(0.90)]
        top = mags[-1]
        return [top * 0.2, top * 0.4, top * 0.6, top * 0.8]

    @staticmethod
    def _week_count(year: int) -> int:
        """该年在"周一起始"日历中占用的周列数（52 / 53 / 54）"""
        first = date(year, 1, 1)
        total = (date(year, 12, 31) - first).days + 1
        return (first.weekday() + total + 6) // 7

    def _level(self, value: float) -> int:
        """净额 -> 1..5 档（0 表示"无盈亏"，调用方会渲染成中性灰）"""
        if not value:
            return 0
        mag = abs(value)
        level = 1
        for t in self._thresholds:
            if mag > t:
                level += 1
        return min(level, 5)

    def _color_for(self, level: int, positive: bool) -> str:
        if level <= 0:
            return self.EMPTY_COLOR
        scale = self.PROFIT_SCALE if positive else self.LOSS_SCALE
        return scale[level - 1]

    # ==========================================
    # 网格几何
    # ==========================================
    def _grid(self):
        """计算本次绘制的格子尺寸与原点；返回 (cell, x0, y0, cols)"""
        cols = self._cols or 53
        avail_w = max(1.0, self.width() - _LEFT_W - _PAD * 2)
        avail_h = max(1.0, self.height() - _TOP_H - _BOTTOM_H - _PAD * 2)
        cell_w = (avail_w - (cols - 1) * _GAP) / cols
        cell_h = (avail_h - 6 * _GAP) / 7
        cell = max(4.0, min(cell_w, cell_h))  # 保持正方形，避免拉伸成条
        used_w = cols * (cell + _GAP) - _GAP
        x0 = _PAD + _LEFT_W + max(0.0, (avail_w - used_w) / 2)  # 水平居中
        return cell, x0, _PAD + _TOP_H, cols

    def _rebuild_boxes(self, cell: float, x0: float, y0: float):
        """重建 (col,row) -> 矩形 / 日期 的索引，供绘制与命中检测共用"""
        self._boxes.clear()
        self._box_date.clear()
        if self._year is None:
            return
        first = date(self._year, 1, 1)
        first_wd = first.weekday()  # 周一=0
        total = (date(self._year, 12, 31) - first).days + 1
        for offset in range(total):
            idx = first_wd + offset
            col, row = divmod(idx, 7)
            day = date.fromordinal(first.toordinal() + offset)
            rect = QRectF(x0 + col * (cell + _GAP), y0 + row * (cell + _GAP), cell, cell)
            self._boxes[(col, row)] = rect
            self._box_date[(col, row)] = day

    # ==========================================
    # 绘制
    # ==========================================
    def paintEvent(self, event):  # noqa: N802 (Qt 约定命名)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#FFFFFF"))

        if self._year is None:
            painter.setPen(QColor(self.AXIS_TEXT))
            painter.setFont(QFont("Microsoft YaHei", 10))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "暂无交易数据")
            return

        cell, x0, y0, cols = self._grid()
        self._rebuild_boxes(cell, x0, y0)

        self._draw_month_labels(painter, cell, x0, cols)
        self._draw_weekday_labels(painter, cell, y0)
        self._draw_cells(painter)
        self._draw_legend(painter, cell, y0)

    def _draw_month_labels(self, painter, cell, x0, cols):
        painter.setPen(QColor(self.AXIS_TEXT))
        painter.setFont(QFont("Microsoft YaHei", 9))
        last_month = None
        for col in range(cols):
            day = self._box_date.get((col, 0))
            if day is None or day.month == last_month:
                continue
            # 相邻月份标签至少隔 2 列，防止文字互相压叠
            if last_month is not None and col < getattr(self, "_last_label_col", -9) + 2:
                continue
            last_month = day.month
            self._last_label_col = col
            x = x0 + col * (cell + _GAP)
            painter.drawText(QRectF(x - 2, 0, cell + 28, _TOP_H),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             f"{day.month}月")

    def _draw_weekday_labels(self, painter, cell, y0):
        painter.setPen(QColor(self.AXIS_TEXT))
        painter.setFont(QFont("Microsoft YaHei", 9))
        for row in _LABEL_ROWS:
            painter.drawText(QRectF(0, y0 + row * (cell + _GAP), _LEFT_W - 4, cell),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             _WEEKDAY_LABELS[row])

    def _draw_cells(self, painter):
        for key, rect in self._boxes.items():
            day = self._box_date.get(key)
            if day is None:
                continue
            value = self._values.get(day)
            level = self._level(value) if value is not None else 0
            color = self._color_for(level, bool(value and value > 0)) if value is not None else self.EMPTY_COLOR
            path = QPainterPath()
            path.addRoundedRect(rect, 2.0, 2.0)
            painter.fillPath(path, QColor(color))
        # 【Pokorny 准则 2】去描边：格子之间靠 _GAP 的留白分隔，不再画黑色边框

    def _draw_legend(self, painter, cell, y0):
        """底部右侧图例：亏损(深→浅) · 中性 · 盈利(浅→深)"""
        leg = min(9.0, cell)
        cells = 11  # 5 档亏损 + 中性 + 5 档盈利
        width = cells * (leg + 2) - 2
        left_text, right_text = "亏损 ", " 盈利"
        font = QFont("Microsoft YaHei", 9)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        total_w = metrics.horizontalAdvance(left_text + right_text) + width + 8

        x_end = self.width() - _PAD
        if total_w > self.width() - _LEFT_W:
            return  # 空间不足时宁可不画，也不画到一半
        x = x_end - total_w
        y = y0 + 7 * (cell + _GAP) + 2

        painter.setPen(QColor(self.AXIS_TEXT))
        painter.drawText(QRectF(x, y, metrics.horizontalAdvance(left_text), leg + 2),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, left_text)
        x += metrics.horizontalAdvance(left_text)

        swatches = [self.LOSS_SCALE[i] for i in (4, 3, 2, 1, 0)]
        swatches += [self.EMPTY_COLOR]
        swatches += [self.PROFIT_SCALE[i] for i in (0, 1, 2, 3, 4)]
        for color in swatches:
            path = QPainterPath()
            path.addRoundedRect(QRectF(x, y + 1, leg, leg), 2.0, 2.0)
            painter.fillPath(path, QColor(color))
            x += leg + 2

        painter.drawText(QRectF(x + 4, y, metrics.horizontalAdvance(right_text), leg + 2),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, right_text)

    # ==========================================
    # 交互：hover tooltip
    # ==========================================
    def _hit(self, pos: QPointF) -> date | None:
        for key, rect in self._boxes.items():
            if rect.contains(pos):
                return self._box_date.get(key)
        return None

    def mouseMoveEvent(self, event):  # noqa: N802
        day = self._hit(event.position())
        if day is None:
            QToolTip.hideText()
            return
        value = self._values.get(day)
        if value is None:
            text = f"{day:%Y-%m-%d}\n当日无交易"
        else:
            text = (f"{day:%Y-%m-%d}\n"
                    f"净额 ￥{value:+,.2f}\n"
                    f"{self._counts.get(day, 0)} 笔交易")
        QToolTip.showText(event.globalPosition().toPoint(), text, self)

    def leaveEvent(self, event):  # noqa: N802
        QToolTip.hideText()
        super().leaveEvent(event)
