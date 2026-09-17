# ui/widgets/annotation_icons.py
"""画线类型的**图标绘制**（v6.24 · §7-B8 R10）—— 纯矢量、**不引入任何图片资源**。

【为什么要图标】用户原话："纯粹的表格方格展示用户有些不知道是啥，有个图标或者其他的
表现形式就会高很多，**用户的再教育难度也会小一些**。"
⇒ 图标是**语义化的线型示意**（斜线 = 趋势、几条横线 = 斐波回调、扇形 = 斐波扇形…），
**不是装饰** —— 目标是"看一眼就知道画出来长什么样"。

【为什么程序化画、而不是用 SVG/PNG 文件】① 分类色相要跟着**分类**变
（同一形状换个颜色就能复用，32 个图标不必画 32 份）；② 矢量绘制在任何 DPI 下都清晰；
③ 不引入资源文件 ⇒ 打包与路径问题一律不碰（§10-12 同族：能少一个依赖就少一个）。
"""
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap

ICON_W, ICON_H = 26, 18


def _pen(color: str, width: float = 1.5) -> QPen:
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def paint_icon(painter: QPainter, shape: str, rect: QRectF, color: str) -> None:
    """在 `rect` 内画出 `shape` 的示意图形（`shape` 取值见 `annotation_catalog` 的 `icon`）。"""
    painter.setPen(_pen(color))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()

    def pt(fx: float, fy: float) -> QPointF:
        """按 0~1 的相对坐标取点（这样每种形状只写比例，不写像素）。"""
        return QPointF(x + w * fx, y + h * fy)

    if shape in ("trend", "ray"):
        painter.drawLine(pt(0.10, 0.88), pt(0.90, 0.12))
        if shape == "ray":
            painter.setBrush(QColor(color))
            painter.drawEllipse(pt(0.10, 0.88), 1.8, 1.8)
    elif shape in ("channel",):
        painter.drawLine(pt(0.08, 0.55), pt(0.92, 0.05))
        painter.drawLine(pt(0.08, 0.95), pt(0.92, 0.45))
    elif shape == "fan":
        for end in (0.12, 0.50, 0.88):
            painter.drawLine(pt(0.08, 0.90), pt(0.92, end))
    elif shape == "hline":
        painter.drawLine(pt(0.05, 0.50), pt(0.95, 0.50))
    elif shape == "ray_h":
        painter.drawLine(pt(0.14, 0.50), pt(0.95, 0.50))
        painter.setBrush(QColor(color))
        painter.drawEllipse(pt(0.14, 0.50), 1.8, 1.8)
    elif shape == "vline":
        painter.drawLine(pt(0.50, 0.08), pt(0.50, 0.92))
    elif shape == "cross":
        painter.drawLine(pt(0.08, 0.50), pt(0.92, 0.50))
        painter.drawLine(pt(0.50, 0.08), pt(0.50, 0.92))
    elif shape == "band":
        painter.drawLine(pt(0.06, 0.34), pt(0.94, 0.34))
        painter.drawLine(pt(0.06, 0.68), pt(0.94, 0.68))
    elif shape == "vbands":
        for fx in (0.28, 0.50, 0.72):
            painter.drawLine(pt(fx, 0.10), pt(fx, 0.90))
    elif shape == "rect":
        painter.drawRect(QRectF(pt(0.12, 0.20), pt(0.88, 0.80)))
    elif shape == "triangle":
        painter.drawPolygon(pt(0.10, 0.86), pt(0.50, 0.14), pt(0.90, 0.86))
    elif shape == "ellipse":
        painter.drawEllipse(QRectF(pt(0.08, 0.20), pt(0.92, 0.80)))
    elif shape == "arrow":
        painter.drawLine(pt(0.12, 0.80), pt(0.84, 0.22))
        painter.drawLine(pt(0.84, 0.22), pt(0.62, 0.26))
        painter.drawLine(pt(0.84, 0.22), pt(0.80, 0.46))
    elif shape == "wave":
        path = (pt(0.06, 0.62), pt(0.26, 0.24), pt(0.46, 0.62), pt(0.66, 0.24), pt(0.90, 0.56))
        for start, end in zip(path, path[1:]):
            painter.drawLine(start, end)
    elif shape == "fib":
        for fy in (0.16, 0.38, 0.62, 0.84):
            painter.drawLine(pt(0.06, fy), pt(0.94, fy))
    elif shape == "fib_ext":
        for fy in (0.16, 0.38, 0.62):
            painter.drawLine(pt(0.06, fy), pt(0.66, fy))
        dashed = _pen(color, 1.2)
        dashed.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(dashed)
        painter.drawLine(pt(0.66, 0.16), pt(0.94, 0.16))
        painter.drawLine(pt(0.66, 0.62), pt(0.94, 0.62))
    elif shape == "arc":
        for inset in (0.02, 0.16, 0.30):
            painter.drawArc(QRectF(pt(0.06 + inset, -0.30 + inset),
                                   pt(0.60 + inset, 0.90)), 0, 90 * 16)
    elif shape == "pct":
        for fy in (0.24, 0.50, 0.76):
            painter.drawLine(pt(0.06, fy), pt(0.72, fy))
        painter.setBrush(QColor(color))
        for fy in (0.24, 0.50, 0.76):
            painter.drawEllipse(pt(0.82, fy), 1.6, 1.6)
    elif shape == "ruler":
        painter.drawLine(pt(0.06, 0.52), pt(0.94, 0.52))
        for fx, half in ((0.18, 0.22), (0.38, 0.30), (0.58, 0.22), (0.78, 0.30)):
            painter.drawLine(pt(fx, 0.52 - half), pt(fx, 0.52 + half))
    elif shape == "measure":
        painter.drawLine(pt(0.12, 0.50), pt(0.88, 0.50))
        painter.drawLine(pt(0.12, 0.30), pt(0.12, 0.70))
        painter.drawLine(pt(0.88, 0.30), pt(0.88, 0.70))
    elif shape == "measure_v":
        painter.drawLine(pt(0.50, 0.12), pt(0.50, 0.88))
        painter.drawLine(pt(0.30, 0.12), pt(0.70, 0.12))
        painter.drawLine(pt(0.30, 0.88), pt(0.70, 0.88))
    elif shape == "text":
        painter.drawLine(pt(0.24, 0.86), pt(0.50, 0.14))
        painter.drawLine(pt(0.76, 0.86), pt(0.50, 0.14))
        painter.drawLine(pt(0.34, 0.60), pt(0.66, 0.60))
    elif shape == "tag":
        painter.drawRect(QRectF(pt(0.08, 0.24), pt(0.72, 0.76)))
        painter.drawLine(pt(0.72, 0.24), pt(0.92, 0.50))
        painter.drawLine(pt(0.72, 0.76), pt(0.92, 0.50))
    elif shape == "marker":
        painter.drawPolygon(pt(0.50, 0.16), pt(0.80, 0.66), pt(0.20, 0.66))
        painter.drawLine(pt(0.50, 0.66), pt(0.50, 0.90))
    elif shape == "comment":
        painter.drawRoundedRect(QRectF(pt(0.06, 0.16), pt(0.94, 0.62)), 4, 4)
        painter.drawLine(pt(0.26, 0.62), pt(0.22, 0.86))
        painter.drawLine(pt(0.22, 0.86), pt(0.46, 0.62))
    elif shape == "dots":
        painter.setBrush(QColor(color))
        for fx in (0.22, 0.50, 0.78):
            painter.drawEllipse(pt(fx, 0.50), 2.0, 2.0)
    else:
        # 未知形状：画一条横线（**宁可画个通用符号，也绝不崩**）
        painter.drawLine(pt(0.06, 0.50), pt(0.94, 0.50))


def make_icon(shape: str, color: str, width: int = ICON_W, height: int = ICON_H) -> QPixmap:
    """把示意图形渲染成 pixmap（高 DPI 由 Qt 的设备像素比统一处理）。"""
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    paint_icon(painter, shape, QRectF(0, 0, width, height), color)
    painter.end()
    return pixmap
