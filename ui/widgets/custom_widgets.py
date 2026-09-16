# ui/widgets/custom_widgets.py
import pyqtgraph as pg
from pyqtgraph import QtCore, QtGui
from PyQt6.QtWidgets import (QButtonGroup, QComboBox, QDateEdit, QDateTimeEdit,
                             QDoubleSpinBox, QFrame, QHBoxLayout, QLabel,
                             QListWidget, QPushButton, QSpinBox)
from PyQt6.QtCore import Qt, QSize, pyqtSignal

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

# ==========================================
# 表单小构件（v6.21 · §7-B6 STEP 1 上收：原先住在 `backtest_panes.py`）
# ==========================================
# 【为什么上收】行情工作台收口（§7-B6）也要用这两个构件；而"同一手法"在
# `ui/views/dashboard.py` 里已被**复制过一份**（§9-O7 那类重复的老毛病）。
# 现在定义只此一处：回测页 / 行情页 / Dashboard 一律 import 本文件。
# （`backtest_panes` 保留同名再导出 ⇒ 既有 `from ui.widgets.backtest_panes import mini_label`
#   调用方与断言零改动。）
def mini_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("font-size: 12px; font-weight: bold; color: #5B6472;")
    return lbl


def hint_icon(tooltip: str) -> QLabel:
    """灰字说明弱化：用一个小 ? 角标承载 tooltip，代替占据版面的长灰字"""
    icon = QLabel("?")
    icon.setFixedSize(15, 15)
    icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
    icon.setStyleSheet("QLabel { background:#E3E7EF; color:#7A8392; border-radius:7px;"
                       " font-size:10px; font-weight:bold; }")
    icon.setToolTip(tooltip)
    return icon


# 页签（pill）样式：编辑抽屉顶部页签等（v6.21 从 `backtest_panes` 上收）
TAB_QSS_OFF = ("QPushButton { background:#F7F9FC; border:1px solid #E7EAF0; border-radius:8px;"
               " padding:5px 12px; font-size:12.5px; font-weight:bold; color:#5B6472; }"
               "QPushButton:hover { border-color:#A9C7EA; color:#1976D2; }")
TAB_QSS_ON = ("QPushButton { background:#E8F2FE; border:1px solid #A9C7EA; border-radius:8px;"
              " padding:5px 12px; font-size:12.5px; font-weight:bold; color:#1257A8; }")

# 胶囊 chip（行情工作台工具行的"最近使用"开关，v6.21 · §7-B6 STEP 3c）：
# 开 = 绿底实心（当前生效）／关 = 灰底空心（**曾用过但已关**，留着让用户能一键点回来）
CHIP_QSS_ON = ("QPushButton { background:#EAF7EE; border:1px solid #BFE3C8; border-radius:12px;"
               " padding:4px 11px; font-size:12.2px; font-weight:bold; color:#2E7D32; }"
               "QPushButton:hover { background:#DFF3E5; }")
CHIP_QSS_OFF = ("QPushButton { background:#FBFCFE; border:1px solid #E4E9F0; border-radius:12px;"
                " padding:4px 11px; font-size:12.2px; color:#8A94A6; }"
                "QPushButton:hover { border-color:#A9C7EA; color:#1976D2; }")
CHIP_MORE_QSS = ("QPushButton { background:#FBFCFE; border:1px solid #E4E9F0; border-radius:12px;"
                 " padding:4px 9px; font-size:12.5px; color:#5B6472; font-weight:bold; }"
                 "QPushButton:hover { border-color:#A9C7EA; color:#1976D2; }")


# ==========================================
# 分段控件（Segmented Control · v6.21 · §7-B6 STEP 1）
# ==========================================
# 【为什么自建】Qt 没有原生 segmented control；而用 `QComboBox` 表达"周期 / 复权"这种
# **高频**切换是两次点击（展开 + 选择）。分段控件一次点击直接生效（§7-B6-C 的 L2 层）。
# 【为什么必须有生成器】它同样是"复合外观"控件：`QPushButton:checked` 在 Windows 原生样式
# 下会被吃掉（必须 `setFlat(True)` + 自写 QSS）；且首/尾按钮的圆角与中段的分隔线必须**成套**
# 出现，否则会出现"半个圆角 + 双边框"——这就是 §10-9 要求"完整 QSS、单一来源"的原因。
# 【纪律】业务页面**不许**自己拼 `QPushButton` 做分段切换，一律用 `SegmentedControl`。
def segment_qss(*, background: str = "white", border: str = "#D9DEE8", radius: int = 8) -> str:
    """分段控件**容器**的完整样式（按钮样式见 `segment_button_qss`，按位置生成）。"""
    return (f"QFrame#SegmentedControl {{ background: {background};"
            f" border: 1px solid {border}; border-radius: {radius}px; }}")


def segment_button_qss(position: str = "middle", *, radius: int = 8,
                       padding: str = "5px 13px", font_size: float = 12.5,
                       color: str = "#5B6472", checked_bg: str = "#E8F2FE",
                       checked_color: str = "#1257A8", checked_border: str = "#A9C7EA",
                       hover_bg: str = "#F5F8FD", separator: str = "#E9EDF3") -> str:
    """分段控件内**单个按钮**的完整样式（按位置决定圆角与分隔线）。

    :param position: ``first`` / ``middle`` / ``last`` / ``only``（首尾圆角 + 中段左分隔线）
    """
    if position not in ("first", "middle", "last", "only"):
        raise ValueError(f"未知位置: {position}")
    shape = ""
    if position in ("first", "only"):
        shape += f" border-top-left-radius: {radius}px; border-bottom-left-radius: {radius}px;"
    if position in ("last", "only"):
        shape += f" border-top-right-radius: {radius}px; border-bottom-right-radius: {radius}px;"
    separator_rule = "" if position in ("first", "only") else f" border-left: 1px solid {separator};"
    return (f"QPushButton {{ background: transparent; border: none;{separator_rule}{shape}"
            f" padding: {padding}; font-size: {font_size}px; color: {color}; }}"
            f"QPushButton:hover {{ background: {hover_bg}; }}"
            f"QPushButton:checked {{ background: {checked_bg}; color: {checked_color};"
            f" border: 1px solid {checked_border};{shape} font-weight: bold; }}")


class SegmentedControl(QFrame):
    """一行互斥按钮 = 分段控件（周期 / 复权 / 视图切换）。

    【单一状态源】真实状态只有 `current_key()` 一处，按钮的 checked 只是它的**投影**
    —— 禁止"从控件外观反推业务状态"（§7-B6-D-6 / §11.5-11 的教训）。
    【幂等】重复点同一段不发信号；`set_current()` 已是该段时也不发（除非显式 `emit=True`）。
    """

    sigChanged = pyqtSignal(str)

    def __init__(self, options, parent=None, *, current: str = None, radius: int = 8,
                 padding: str = "5px 13px"):
        """:param options: ``[(key, label), ...]`` —— 顺序即显示顺序（key 是业务值，label 是中文）"""
        super().__init__(parent)
        self.setObjectName("SegmentedControl")
        self.setStyleSheet(segment_qss(radius=radius))
        pairs = [(str(key), str(label)) for key, label in options]
        self._keys: list[str] = [key for key, _ in pairs]
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        for index, (key, label) in enumerate(pairs):
            if len(pairs) == 1:
                position = "only"
            elif index == 0:
                position = "first"
            elif index == len(pairs) - 1:
                position = "last"
            else:
                position = "middle"
            button = QPushButton(label)
            button.setCheckable(True)
            button.setFlat(True)          # 不给 Windows 原生样式插手（§10-9）
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setProperty("segment_key", key)
            button.setStyleSheet(segment_button_qss(position, radius=radius, padding=padding))
            self._group.addButton(button, index)
            lay.addWidget(button)
        self._current = self._keys[0] if self._keys else ""
        self._group.idClicked.connect(self._on_clicked)
        if current is not None:
            self.set_current(current)
        else:
            self._sync_visual()

    # ---------- 对外 ----------
    def set_current(self, key: str, *, emit: bool = False) -> bool:
        """切到某一段（**幂等**：已是该段则原样返回 True 且不发信号）。key 非法返回 False。"""
        key = str(key)
        if key not in self._keys:
            return False
        changed = (key != self._current)
        self._current = key
        self._sync_visual()
        if changed and emit:
            self.sigChanged.emit(key)
        return True

    def current_key(self) -> str:
        return self._current

    def current_index(self) -> int:
        return self._keys.index(self._current) if self._current in self._keys else -1

    def key_at(self, index: int) -> str:
        return self._keys[index] if 0 <= index < len(self._keys) else ""

    def count(self) -> int:
        return len(self._keys)

    def labels(self) -> list:
        return [self._group.button(i).text() for i in range(len(self._keys))]

    def buttons(self) -> list:
        """按顺序返回按钮（供测试/程序化点击；业务代码请用 `set_current`）。"""
        return [self._group.button(i) for i in range(len(self._keys))]

    # ---------- 内部 ----------
    def _on_clicked(self, index: int) -> None:
        key = self.key_at(index)
        if not key or key == self._current:
            return
        self._current = key
        self._sync_visual()
        self.sigChanged.emit(key)

    def _sync_visual(self) -> None:
        for index, key in enumerate(self._keys):
            button = self._group.button(index)
            if button is not None:
                button.setChecked(key == self._current)


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
    # 【v6.23 · 一字板可读性】开=收 的 bar（一字板 / T 字板）**实体高度为 0**，
    #   按老画法只剩一条 1px 细横线 —— 缩小时几乎看不见，一串一字板就看成一串"虚点/断口"，
    #   像"K 线画丢了"（用户 2026-09-17 两次反馈的"一字板显示问题"；数据已用独立源逐根核对
    #   确认为真连板）。
    #   ⇒ 这类 bar 改用**加粗横档**画：视觉上仍是"一字"，但在任何缩放下都看得见。
    #   ⚠ **只改画法，不动任何数据**；其它 bar 的画法（影线 + 实体）一个字都没改。
    FLAT_BAR_PEN_WIDTH = 2.5

    def __init__(self, data):
        pg.GraphicsObject.__init__(self)
        self.data = data
        self.generatePicture()

    @staticmethod
    def is_flat_bar(open_p, close_p) -> bool:
        """实体高度是否为 0（一字板：开=高=低=收；T 字板：开=收=高）。"""
        return float(open_p) == float(close_p)

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
        # 每组 = (影线笔, 实体描边笔, 实体填充刷, **零高度实体的横档笔**)。
        styles = {
            True:  (pg.mkPen(settings.COLOR_PROFIT, width=1.5),
                    pg.mkPen(settings.COLOR_PROFIT, width=1),
                    pg.mkBrush(settings.COLOR_PROFIT),
                    pg.mkPen(settings.COLOR_PROFIT, width=self.FLAT_BAR_PEN_WIDTH)),
            False: (pg.mkPen(settings.COLOR_LOSS, width=1.5),
                    pg.mkPen(settings.COLOR_LOSS, width=1),
                    pg.mkBrush(settings.COLOR_LOSS),
                    pg.mkPen(settings.COLOR_LOSS, width=self.FLAT_BAR_PEN_WIDTH)),
        }

        for (t, open_p, close_p, min_p, max_p) in self.data:
            wick_pen, body_pen, body_brush, flat_pen = styles[close_p >= open_p]
            p.setBrush(body_brush)

            # 影线 (Wick)：一字板没有影线（高=低），画了也只是个点，跳过
            if max_p != min_p:
                p.setPen(wick_pen)
                p.drawLine(QtCore.QPointF(t, min_p), QtCore.QPointF(t, max_p))

            if self.is_flat_bar(open_p, close_p):
                # 一字板 / T 字板：实体没高度 ⇒ 用**加粗横档**表达（否则只有头发丝细一条）
                p.setPen(flat_pen)
                p.drawLine(QtCore.QPointF(t - w, close_p), QtCore.QPointF(t + w, close_p))
                continue

            # 画实体 (Body)：边框和填充色完全一致，彻底消除描边感
            p.setPen(body_pen)
            p.drawRect(QtCore.QRectF(t - w, open_p, w * 2, close_p - open_p))
            
        p.end()

    def paint(self, p, *args): 
        p.drawPicture(0, 0, self.picture)

    def boundingRect(self): 
        return QtCore.QRectF(self.picture.boundingRect())