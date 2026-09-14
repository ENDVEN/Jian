# ui/widgets/custom_widgets.py
import pyqtgraph as pg
from pyqtgraph import QtCore, QtGui
from PyQt6.QtWidgets import (QListWidget, QPushButton, QComboBox, QDateEdit,
                             QDateTimeEdit, QDoubleSpinBox, QSpinBox)
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


class NoWheelDateTimeEdit(_NoWheelMixin, QDateTimeEdit):
    """带时分的时间输入（用于手工录入的交易/开仓时间）。

    v6.9 补：此前手工录入弹窗用的是裸 QDateTimeEdit，悬停时滚轮会误改时间 ——
    属于 §6.6-U2「防滚轮误触」遗漏项。
    """
    pass


# ==========================================
# 数值控件统一视觉契约 (v5.6 · 详见 JIAN_RULES.md §10-9)
# ==========================================
# 【为什么是空串 = 沿用原生】QSpinBox / QDoubleSpinBox 属于 Qt「复合控件」：
# 一旦只给控件本体写 QSS（例：`QDoubleSpinBox { padding…; border-radius… }`）
# 而没把 ::up-button / ::down-button / ::up-arrow / ::down-arrow 四个子控件写全，
# Qt 就会退回「默认度量」重绘箭头，后果是：
#   ① 箭头图标与其它位置的原生箭头不一致（历史 Bug：风控行 vs 买卖条件组）；
#   ② 点击热区与视觉图标错位（历史 Bug：风控行「上箭头只有右半边能点」）。
#
# 【纪律】全 app 数值控件一律使用 NoWheelSpinBox / NoWheelDoubleSpinBox + 本常量，
# 业务页面**禁止就地 setStyleSheet 半截样式**；确需改外观，必须写全四个子控件
# 并把完整 QSS 收敛到本文件统一导出。
SPINBOX_QSS = ""

# ==========================================
# 复合控件「完整 QSS」契约 (v6.9 · §10-9)
# ==========================================
# 【为什么必须成对写】QComboBox / QDateEdit / QDateTimeEdit 都是 Qt「复合控件」：
# 一旦用 QSS 触碰它们的子控件（例如 ::drop-down），Qt 就切到"样式化绘制"路径 ——
# 此时若**没有**同时给出 ::down-arrow，下拉箭头会**整个消失**。
# （v6.9 离屏实测：只写本体 → 箭头可见；加上 ::drop-down 而不给箭头 → 箭头区域
#   零像素。复盘页时间选择器、手工录入弹窗此前就处在这种"没有箭头"的状态，
#   用户难以察觉但下拉控件的可发现性已被破坏。）
# 因此这里用**生成器**保证 ::drop-down 与 ::down-arrow 永远成对出现，
# 箭头用 border 三角绘制（纯 QSS，**无需任何图片资源 / 不引入二进制文件**）。
#
# 【纪律】本文件是全 app 复合控件样式的**唯一来源**；业务页面只准引用下面的具名常量，
# 禁止就地 setStyleSheet 写半截规则（§10-9）。
_ARROW_TRIANGLE = ("width: 0; height: 0; margin-right: 8px;"
                   " border-left: 5px solid transparent; border-right: 5px solid transparent;"
                   " border-top: 6px solid {color};")


def _combo_subcontrols(drop_width: int = 22, arrow: str = "#6B7280") -> str:
    """QComboBox 子控件：下拉热区 + 箭头三角（成对出现，防"半截 QSS"丢箭头）。"""
    return (f"QComboBox::drop-down {{ border: none; width: {drop_width}px; }}"
            "QComboBox::down-arrow { " + _ARROW_TRIANGLE.format(color=arrow) + " }")


def combo_qss(*, border: str = "#E0E4EC", border_width: int = 1, radius: int = 8,
              padding: str = "0 10px", font_size: int | None = None,
              font_weight: str | None = None, color: str = "#1F2430",
              background: str = "white", focus_border: str | None = None,
              hover_background: str | None = None, drop_width: int = 22,
              arrow: str = "#6B7280") -> str:
    """生成 QComboBox 的**完整**样式（本体 + 状态 + 成对子控件）。"""
    body = (f"QComboBox {{ padding: {padding}; border: {border_width}px solid {border};"
            f" border-radius: {radius}px; background: {background}; color: {color};")
    if font_size is not None:
        body += f" font-size: {font_size}px;"
    if font_weight:
        body += f" font-weight: {font_weight};"
    body += " }"

    state = ""
    if focus_border:
        state += f"QComboBox:focus {{ border: {border_width}px solid {focus_border}; }}"
    if hover_background:
        state += f"QComboBox:hover {{ background: {hover_background}; }}"
    return body + state + _combo_subcontrols(drop_width, arrow)


def date_edit_qss(*, widget: str = "QDateEdit", border: str = "#E0E4EC",
                  border_width: int = 1, radius: int = 4, padding: str = "3px",
                  font_size: int | None = None, color: str = "#212121",
                  background: str = "white", arrow: str = "#6B7280",
                  drop_width: int = 22) -> str:
    """生成 QDateEdit / QDateTimeEdit 的**完整**样式（本体 + 成对子控件）。"""
    body = (f"{widget} {{ padding: {padding}; border: {border_width}px solid {border};"
            f" border-radius: {radius}px; background: {background}; color: {color};")
    if font_size is not None:
        body += f" font-size: {font_size}px;"
    body += " }"
    subs = (f"{widget}::drop-down {{ border: none; width: {drop_width}px; }}"
            f"{widget}::down-arrow {{ " + _ARROW_TRIANGLE.format(color=arrow) + " }")
    return body + subs


# ---- 具名变体：各页面只引用这些常量（新增变体请走上面的生成器，勿手写字符串）----
COMBO_QSS = combo_qss(focus_border="#1976D2")                     # 通用（回测页 / 指数 / 行情页）
COMBO_QSS_SMALL = combo_qss(padding="0 8px", font_size=12,
                            focus_border="#1976D2")               # 紧凑（条件组行 / Dashboard 年份）
COMBO_QSS_ACCENT = combo_qss(padding="5px 15px", font_size=16, radius=6, border="#E0E0E0",
                             color="#1976D2", font_weight="bold", drop_width=20,
                             hover_background="#F5F5F5")          # 强调（复盘页时间选择器）
COMBO_QSS_EDIT = combo_qss(padding="4px", radius=4, border="#D1D9E6",
                           color="#212121")                       # 复盘页策略编辑框
COMBO_QSS_EDIT_OK = combo_qss(padding="4px", radius=4, border_width=2, border="#4CAF50",
                              color="#2E7D32", background="#E8F5E9",
                              font_weight="bold")                 # 保存成功的瞬时反馈
LINE_COMBO_QSS = (                                                # 工具栏：输入框与下拉同一个脸
    "QLineEdit, QComboBox { padding: 0 12px; border: 1px solid #D9DEE8; border-radius: 8px;"
    " background: white; font-size: 13px; color: #1F2430; }"
    "QLineEdit:focus, QComboBox:focus { border: 1px solid #1976D2; }"
    + _combo_subcontrols()
)
DATEEDIT_QSS_WARN = date_edit_qss(border="#FFCC80", radius=4, padding="3px",
                                  arrow="#E65100")                # 复盘页孤儿补录日期
DIALOG_INPUT_QSS = (                                              # 手工录入等表单弹窗
    "QDialog { background-color: #FAFAFA; font-family: -apple-system, sans-serif; }"
    "QLabel { font-weight: bold; color: #424242; }"
    "QLineEdit, QComboBox, QDateTimeEdit { border: 1px solid #E0E0E0; border-radius: 6px;"
    " padding: 6px; background: white; font-size: 14px; }"
    + _combo_subcontrols(drop_width=26)
    + "QDateTimeEdit::drop-down { border: none; border-left: 1px solid #E0E0E0; width: 26px; }"
    + "QDateTimeEdit::down-arrow { " + _ARROW_TRIANGLE.format(color="#6B7280") + " }"
)

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