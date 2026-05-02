# ui/widgets/custom_widgets.py
import pyqtgraph as pg
from pyqtgraph import QtCore, QtGui
from PyQt6.QtWidgets import QListWidget, QPushButton
from PyQt6.QtCore import Qt, QSize

from config import settings

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
            
        for (t, open_p, close_p, min_p, max_p) in self.data:
            is_profit = close_p >= open_p
            
            # 【Pokorny 原则 2】抛弃刺眼的黑色描边，影线和实体采用纯净的扁平单色
            color_hex = settings.COLOR_PROFIT if is_profit else settings.COLOR_LOSS
            color = QtGui.QColor(color_hex)
            
            # 画影线 (Wick)
            p.setPen(pg.mkPen(color, width=1.5))
            p.drawLine(QtCore.QPointF(t, min_p), QtCore.QPointF(t, max_p))
            
            # 画实体 (Body)：边框和填充色完全一致，彻底消除描边感
            p.setBrush(pg.mkBrush(color))
            p.setPen(pg.mkPen(color, width=1)) 
            p.drawRect(QtCore.QRectF(t - w, open_p, w * 2, close_p - open_p))
            
        p.end()

    def paint(self, p, *args): 
        p.drawPicture(0, 0, self.picture)

    def boundingRect(self): 
        return QtCore.QRectF(self.picture.boundingRect())