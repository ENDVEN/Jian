# ui/widgets/custom_widgets.py
import pyqtgraph as pg
from pyqtgraph import QtCore, QtGui
from PyQt6.QtWidgets import (QListWidget, QPushButton, QComboBox, QDateEdit,
                             QDoubleSpinBox, QSpinBox)
from PyQt6.QtCore import Qt, QSize

from config import settings


# ==========================================
# 防滚轮误触控件族 (高信息密度页面防手滑)
# ==========================================
class _NoWheelMixin:
    """让滚轮事件不再改变控件值。

    适用场景：策略编辑页里“参数下拉/数值/日期”本身是高危误操作区——
    用户本想滚动页面/列表，悬停在控件上就会悄悄改掉关键参数。
    覆写 wheelEvent 直接忽略，把滚动权交还给父级滚动容器。
    若确需键盘微调：点中控件后用上下方向键 (Combo/Spin/Date 原生支持)。
    """

    def wheelEvent(self, event):
        event.ignore()


class NoWheelComboBox(_NoWheelMixin, QComboBox):
    pass


class NoWheelDoubleSpinBox(_NoWheelMixin, QDoubleSpinBox):
    pass


class NoWheelSpinBox(_NoWheelMixin, QSpinBox):
    pass


class NoWheelDateEdit(_NoWheelMixin, QDateEdit):
    pass

class HoverDeleteListWidget(QListWidget):
    def __init__(self, delete_callback, parent=None):
        super().__init__(parent)
        self.delete_callback = delete_callback
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setIconSize(QSize(100, 100))
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setFixedHeight(130)
        self.setStyleSheet("QListWidget { border: 2px dashed #E0E0E0; border-radius: 6px; background: #FAFAFA; padding: 5px;} QListWidget::item:selected { border: 2px solid #1976D2; background: transparent; border-radius: 4px;}")
        self.setMouseTracking(True)
        self.btn_delete = QPushButton("🗑️", self)
        self.btn_delete.setStyleSheet("QPushButton { background-color: rgba(244, 67, 54, 0.85); color: white; border: none; border-radius: 12px; font-size: 12px; font-weight: bold;} QPushButton:hover { background-color: rgba(211, 47, 47, 1); }")
        self.btn_delete.resize(24, 24)
        self.btn_delete.hide()
        self.btn_delete.clicked.connect(self._on_delete_clicked)
        self.hovered_item = None

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        item = self.itemAt(event.pos())
        if item: 
            self.hovered_item = item
            rect = self.visualItemRect(item)
            self.btn_delete.move(rect.right() - 26, rect.top() + 2)
            self.btn_delete.show()
        else: 
            self.hovered_item = None
            self.btn_delete.hide()

    def leaveEvent(self, event): 
        super().leaveEvent(event)
        self.btn_delete.hide()

    def _on_delete_clicked(self):
        if self.hovered_item: 
            filepath = self.hovered_item.data(Qt.ItemDataRole.UserRole)
            self.btn_delete.hide()
            self.delete_callback(self.hovered_item, filepath)

class CandlestickItem(pg.GraphicsObject):
    def __init__(self, data):
        pg.GraphicsObject.__init__(self)
        self.data = data
        self.generatePicture()

    def generatePicture(self):
        self.picture = QtGui.QPicture()
        p = QtGui.QPainter(self.picture)
        
        # 【Pokorny 原则 1】开启抗锯齿渲染，让图表像丝绸一样平滑
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        
        w = 0.3
        if len(self.data) > 1:
            w = (self.data[1][0] - self.data[0][0]) * 0.35 

        # 【性能要点】画笔/画刷仅有“涨/跌”两种状态，必须在循环外一次性创建；
        # 否则每根 K 线都会新造 3 个 Qt 图形对象，千根 K 线即产生数千次内存分配。
        # 【Pokorny 原则 2】抛弃刺眼的黑色描边，影线和实体采用纯净的扁平单色。
        styles = {
            True:  (pg.mkPen(settings.COLOR_PROFIT, width=1.5),
                    pg.mkPen(settings.COLOR_PROFIT, width=1),
                    pg.mkBrush(settings.COLOR_PROFIT)),
            False: (pg.mkPen(settings.COLOR_LOSS, width=1.5),
                    pg.mkPen(settings.COLOR_LOSS, width=1),
                    pg.mkBrush(settings.COLOR_LOSS)),
        }

        for (t, open_p, close_p, min_p, max_p) in self.data:
            wick_pen, body_pen, body_brush = styles[close_p >= open_p]
            
            # 画影线 (Wick)
            p.setPen(wick_pen)
            p.drawLine(QtCore.QPointF(t, min_p), QtCore.QPointF(t, max_p))
            
            # 画实体 (Body)：边框和填充色完全一致，彻底消除描边感
            p.setBrush(body_brush)
            p.setPen(body_pen)
            p.drawRect(QtCore.QRectF(t - w, open_p, w * 2, close_p - open_p))
            
        p.end()

    def paint(self, p, *args): 
        p.drawPicture(0, 0, self.picture)

    def boundingRect(self): 
        return QtCore.QRectF(self.picture.boundingRect())