# ui/widgets/custom_widgets.py
import pyqtgraph as pg
from pyqtgraph import QtCore, QtGui
from PyQt6.QtWidgets import (QButtonGroup, QComboBox, QDateEdit, QDateTimeEdit,
                             QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QLayout,
                             QListWidget, QPushButton, QScrollArea, QSizePolicy,
                             QSpinBox, QVBoxLayout, QWidget)
from PyQt6.QtCore import QPoint, QRect, Qt, QSize, pyqtSignal
from PyQt6.QtGui import QFont, QFontInfo

from config import settings

# ★v1.41 / §7-B1/B2 补漏：「更新到最新」这个**动作按钮的文字 = 唯一出口**。
# 【为什么必须收成常量】同一个动作有三类引用方：①真正创建按钮的版式/流程；
#   ②各种**文案里指称该按钮**（"点「…」补齐数据"）。旧版把中文字面量在 6+ 处各写一遍，
#   结果 v6.47 把按钮改名成「⬆ 更新到最新交易日」后，**文案全部失联** ——
#   用户被指引去点一个**根本不存在的按钮**（实测截图复现，§11.5-80）。
#   ⇒ 按钮文字与"指称它的文案"必须同源，改名即全改。
# 【为什么放这里】本模块是全 app 的 UI 常量唯一出处（§10 控件样式纪律同源），
#   且**零依赖**（只 import pyqtgraph / settings）⇒ 版式、流程、结果区都能安全 import，
#   不会成环。⚠ `core/` 与 `data/` **不许** import UI 常量（分层），
#   所以它们的提示语里**不写按钮名**，只说"页面的下载入口"。
SYNC_ACTION_LABEL = '⬆ 更新到最新交易日'


# ==========================================
# 界面字体：**开源 / 免费商用优先**的字体栈（v1.46 · §10-9「字体只此一处」）
# ==========================================
# 【为什么必须有这一条】本项目**从来没设过全局字体** ⇒ 走 Qt 平台默认，Windows 上中文
#   会回落到宋体（笔画细、带衬线感），同一个页面在"装了黑体 / 没装"两台机器上观感完全不同
#   —— 用户 2026-09-25 实测点出"字体层面的设计没做到"。
#
# 【版权纪律（用户 2026-09-25 拍板 · 撤销"照抄样板字体名"的上一版方案）】
#   **一律只点名开源 / 免费商用字体**，并在注释里标明许可：
#   · 思源黑体 Source Han Sans（Adobe + Google，**SIL OFL 1.1**）＝ Noto Sans CJK
#   · Noto Sans SC / Noto Sans Mono（Google，**SIL OFL 1.1**）
#   · JetBrains Mono（**SIL OFL 1.1**）· Cascadia Code（**SIL OFL 1.1**）
#   · 更纱黑体 Sarasa Mono（**SIL OFL 1.1**）· 思源等宽 Source Han Mono（**SIL OFL 1.1**）
#   · HarmonyOS Sans（华为，**免费商用**）· MiSans（小米，**免费商用**）
#   · 阿里巴巴普惠体 Alibaba PuHuiTi（阿里，**免费商用**）
#   ⚠ **禁止**在 QSS / `QFont` 里点名微软雅黑、宋体、Consolas 等**系统专有字体** ——
#     即使用户本机装了也不写进代码：截图、分发、跨平台都可能构成风险（商业侵权）。
#
# 【为什么"只点菜、不捆绑"】本栈只**请求**列表里第一个**系统里已装好**的字体，
#   不随包分发任何字体文件（避免体积与再分发许可问题）；一款都没装 ⇒ Qt 自然回落
#   系统默认（行为与旧版一致，**不报错、不显方框**）。想让观感与设计样板一致，
#   装「思源黑体 / Noto Sans CJK SC」（免费、可商用、OFL）即可，页面无需改一行。
#   本机实测结果见启动日志（`ui_font_status()`）。
UI_FONT_STACK = (
    "Source Han Sans SC", "Noto Sans CJK SC", "Noto Sans SC", "思源黑体",
    "Source Han Sans CN", "HarmonyOS Sans SC", "MiSans", "Alibaba PuHuiTi 3.0",
)
# 等宽栈（代码块 / 公式块）：全 OFL，末尾 "Monospace" 是 Qt 的**通用族**（非某款字体）
UI_MONO_STACK = (
    "JetBrains Mono", "Cascadia Code", "Sarasa Mono SC", "Source Han Mono SC",
    "Noto Sans Mono", "Monospace",
)
UI_FONT_SIZE_PX = 13          # 界面基准字号（与 §7-B12 P8 样板 body 同值）


def mono_font_css() -> str:
    """等宽字体栈的 **QSS 片段**（`font-family:…;`）—— 代码块一律用它，不写字面字体名。"""
    return 'font-family:' + ', '.join(f'"{f}"' for f in UI_MONO_STACK) + ';'


def ui_font(size_px: int = UI_FONT_SIZE_PX, bold: bool = False) -> QFont:
    """造一个**开源字体栈**优先的 `QFont`（需要单独设字体的地方一律用它）。"""
    font = QFont()
    font.setFamilies(list(UI_FONT_STACK))
    font.setPixelSize(int(size_px))
    font.setBold(bool(bold))
    return font


def ui_painter_font(point_size: int, bold: bool = False, italic: bool = False) -> QFont:
    """手绘 / 表格项用的开源字体栈 `QFont`（**按磅值**）。

    ⚠ 为什么单独留一个"磅值版"：老代码里散着「微软雅黑 9pt」「Arial 10pt Bold」这类
      **专有字体名**的 `QFont` 构造（§10-15 禁止）。本函数**只换字体族**，
      磅值 / 粗体 / 斜体语义逐条保持不变 ⇒ 替换是"除 family 外逐像素等价"的，
      **不会引起版式漂移**（比强行换成 px 字号安全得多）。
    """
    font = QFont()
    font.setFamilies(list(UI_FONT_STACK))
    font.setPointSize(int(point_size))
    font.setBold(bool(bold))
    font.setItalic(bool(italic))
    return font


def apply_ui_font(widget, size_px: int = UI_FONT_SIZE_PX) -> None:
    """把开源字体栈**钉到整棵控件树**（Qt 字体向下继承 ⇒ 在页面根调一次即可）。

    ⚠ 为什么不能只写 QSS：页面里多处 QSS 只覆盖了 `font-size`，**字体族靠继承** ——
      在页面根 `setFont` 一次，它们就一起跟着走；反过来若只写 QSS，会漏掉所有
      "没写 QSS 的原生控件"（表格单元格 / 下拉弹层 / 复选框 / 滚动条）。
    """
    font = QFont(widget.font())
    font.setFamilies(list(UI_FONT_STACK))
    font.setPixelSize(int(size_px))
    widget.setFont(font)


def ui_font_status() -> str:
    """**实测**当前真正用上的字体族 —— 诚实报告"命中了开源栈 / 回落了系统默认"。

    给启动日志用：用户反馈"字体不对"时，第一眼就能确认本机到底装没装开源中文字体。
    """
    fam = str(QFontInfo(ui_font()).family() or "")
    low = fam.lower()
    if any(name.lower() in low or low in name.lower() for name in UI_FONT_STACK):
        return f"界面字体：{fam}（开源字体 · 与设计样板一致）"
    return (f"界面字体：{fam}（本机未装开源中文字体 ⇒ 回落系统默认；"
            "装「思源黑体 / Noto Sans CJK SC」（免费可商用）即可还原设计观感）")


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
# 数值控件工厂 (v1.42 · §10-9「最小宽度 72px / 同类控件同一张脸」)
# ==========================================
# 【为什么收成工厂 · 由用户实测倒逼】批量预下载弹窗的「间隔(秒)」预设是 0.6，
# 但控件被 `setFixedWidth` 钉死在 **64px** —— 原生 QDoubleSpinBox 右侧要留约 18~22px 放
# 上下箭头，64px 扣掉箭头与内边距后文本区只剩约 30px ⇒ **"0.6" 被截成 "0"**，
# 用户以为预设值是 0（与真实值不符，且他无法确认自己设了多少）。
# 对照：数据管理页同一个"同步间隔"用的是 82px —— 同一件事两个尺寸，
# 正是 §10-9「同类控件必须同一张脸 + 数值控件最小宽度不得小于 72px」被破。
# 【纪律】宽度只给 **minimumWidth**、**绝不 `setFixedWidth`**：让布局按内容自然给位，
# 换字体/换数值长度都不会再截字。要美化必须写全四个子控件并收敛到本文件（见上方说明）。
SPIN_MIN_WIDTH = 72


def _spin_step(decimals: int) -> float:
    """步长跟着**小数位**自适应（判据与 `backtest_panes.number_spin` v6.18 同源，勿各写一遍）。

    0 位 -> 1；1 位 -> 0.5；>=2 位 -> 10^-decimals。
    """
    return 1.0 if decimals == 0 else (0.5 if decimals == 1 else 10.0 ** -decimals)


def double_spin(*, value: float = 0.0, lo: float = 0.0, hi: float = 100.0,
                decimals: int = 1, tooltip: str = "",
                step: float | None = None) -> NoWheelDoubleSpinBox:
    """全站通用的小数输入框（防滚轮误触 + 宽度不截字 + 样式原生）。"""
    spin = NoWheelDoubleSpinBox()
    spin.setRange(lo, hi)
    spin.setDecimals(decimals)
    spin.setValue(value)
    spin.setSingleStep(step if step is not None else _spin_step(decimals))
    spin.setMinimumWidth(SPIN_MIN_WIDTH)   # ★ 只给下限，不钉死宽度
    spin.setFixedHeight(28)
    if tooltip:
        spin.setToolTip(tooltip)
    spin.setStyleSheet(SPINBOX_QSS)
    return spin


def int_spin(*, value: int = 0, lo: int = 0, hi: int = 999,
             tooltip: str = "", step: int = 1) -> NoWheelSpinBox:
    """全站通用的整数输入框（与 `double_spin` 同一张脸，§10-9）。"""
    spin = NoWheelSpinBox()
    spin.setRange(lo, hi)
    spin.setValue(value)
    spin.setSingleStep(step)
    spin.setMinimumWidth(SPIN_MIN_WIDTH)
    spin.setFixedHeight(28)
    if tooltip:
        spin.setToolTip(tooltip)
    spin.setStyleSheet(SPINBOX_QSS)
    return spin


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


class OhlcBarItem(pg.GraphicsObject):
    """美国线（OHLC bar）：竖线 = 高低，左横 tick = 开，右横 tick = 收。

    ★ 与 `CandlestickItem` **同一数据格式** `(t, open, close, min, max)`、同一套涨绿跌红
    色板（settings.COLOR_PROFIT/LOSS）—— 两者只是"实体柱 vs 四价横线"的画法差异，
    调用方可直接互换（M3 指数副图的可选视觉之一）。同样遵守 Pokorny 三原则：
    抗锯齿、无额外描边、单色高对比；画笔循环外一次创建（同 K 线的性能教训）。
    """

    def __init__(self, data):
        pg.GraphicsObject.__init__(self)
        self.data = data
        self.generatePicture()

    def generatePicture(self):
        self.picture = QtGui.QPicture()
        p = QtGui.QPainter(self.picture)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        w = 0.3
        if len(self.data) > 1:
            w = (self.data[1][0] - self.data[0][0]) * 0.3
        pens = {True: pg.mkPen(settings.COLOR_PROFIT, width=1.2),
                False: pg.mkPen(settings.COLOR_LOSS, width=1.2)}
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        for (t, open_p, close_p, min_p, max_p) in self.data:
            pen = pens[close_p >= open_p]
            p.setPen(pen)
            p.drawLine(QtCore.QPointF(t, min_p), QtCore.QPointF(t, max_p))     # 高低竖线
            p.drawLine(QtCore.QPointF(t - w, open_p), QtCore.QPointF(t, open_p))   # 左=开
            p.drawLine(QtCore.QPointF(t, close_p), QtCore.QPointF(t + w, close_p))  # 右=收
        p.end()

    def paint(self, p, *args):
        p.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        return QtCore.QRectF(self.picture.boundingRect())


# ==========================================
# 自动换行布局（§7-B8 · 分组胶囊数量不定，必须能换行）
# ==========================================
class FlowLayout(QLayout):
    """按可用宽度自动换行（Qt 官方 FlowLayout 示例的紧凑版）。

    【为什么需要它】`QHBoxLayout` 会把超出宽度的胶囊**压扁**（而不是换行），
    在 338px 的侧栏里"4 个分组"就会挤成看不清；`QGridLayout` 则要求预先知道列数，
    而胶囊宽度取决于组名长度（"高股息" vs "科技成长"），列数算不准。
    """

    def __init__(self, parent=None, margin: int = 0, spacing: int = 5):
        super().__init__(parent)
        self._items: list = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def addItem(self, item):                    # noqa: N802 (Qt 约定)
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index):                    # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):                    # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):              # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:        # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:    # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):                # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):                         # noqa: N802
        return self.minimumSize()

    def minimumSize(self):                      # noqa: N802
        size = QSize()
        for item in self._items:
            if item.isEmpty():                  # ★v1.46：隐藏的子件不占位（见 _do_layout）
                continue
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(),
                            margins.top() + margins.bottom())

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, line_height = area.x(), area.y(), 0
        for item in self._items:
            # ★v1.46：**隐藏的子件必须跳过** —— 标准 `QBoxLayout` 靠 `isEmpty()` 自动跳过
            #   隐藏控件，本自定义布局早期漏了这一步 ⇒ `setVisible(False)` 的按钮照样
            #   占一格、把动作行撑出空档（"运行历史"的按 kind 显隐动作按钮时立刻显形）。
            if item.isEmpty():
                continue
            hint = item.sizeHint()
            next_x = x + hint.width() + self.spacing()
            if next_x - self.spacing() > area.right() and line_height > 0:
                x = area.x()
                y = y + line_height + self.spacing()
                next_x = x + hint.width() + self.spacing()
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()


class FlowHost(QWidget):
    """承载 `FlowLayout` 的宿主：把"换行后需要多高"钉进自己的 `minimumHeight`。

    【这个坑的实录】`QWidget` 默认 `hasHeightForWidth() = False` ⇒ 父布局按
    `sizeHint()` 给固定高度 ⇒ **换行后的第二行被裁掉**（渲染探针里实测：
    "分组胶囊只剩上半截"）。只覆写 `heightForWidth()` **不够** —— 它要沿着
    "胶囊宿主 → 卡片 → 页面 → 堆叠页 → 面板"一层层往上传，
    链条上任何一环不转发就**静默失效**（不报错、只是少一行）。
    ⇒ 所以这里同时做两件事：
      ① `heightForWidth()` 透出去（父链配合时走这条优雅路径）；
      ② `sync_height()` 按**当前宽度**算出所需高度直接设 `minimumHeight`
         —— 这条**不依赖父链配合**，是真正兜底的。
    """

    def __init__(self, parent=None, spacing: int = 5):
        super().__init__(parent)
        self.flow = FlowLayout(self, spacing=spacing)
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def hasHeightForWidth(self) -> bool:        # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:    # noqa: N802
        return self.flow.heightForWidth(width)

    def sync_height(self, width: int = None) -> int:
        """按给定（或当前）宽度算出行数所需高度并设为 `minimumHeight`。

        调用时机：**每次重建子控件之后**（此时才知道有几个、各自多宽），
        以及自身被 resize 时（宽度变了 ⇒ 换行数可能变）。
        """
        width = int(width or self.width() or 0)
        if width <= 1:
            width = 300     # 还没被布局分配过宽度 ⇒ 先按侧栏最小可用宽估一次，resize 时会纠正
        needed = self.flow.heightForWidth(width)
        if needed != self.minimumHeight():
            self.setMinimumHeight(needed)
        return needed

    def resizeEvent(self, event):               # noqa: N802
        super().resizeEvent(event)
        self.sync_height()


# ==========================================
# 页面内容区（§7-B8 第 5 批）：内容放不下就滚 + 底部主操作钉住
# ==========================================
SCROLL_REGION_QSS = (
    "QScrollArea { background:transparent; border:none; }"
    "QScrollArea > QWidget > QWidget { background:transparent; }"
    "QScrollBar:vertical { width:6px; background:transparent; margin:0; }"
    "QScrollBar::handle:vertical { background:#D5DDE8; border-radius:3px; min-height:24px; }"
    "QScrollBar::handle:vertical:hover { background:#BFC9D8; }"
    "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }"
    "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }")


class ScrollRegion(QScrollArea):
    """页面**内容区**：卡片按内容高度堆叠、超出就滚；底部主操作留在外面（永远够得着）。

    【为什么页面需要它（v6.24 · 第 5 批）】之前页面用 `lay.addWidget(card, 1)` 把卡片拉满，
    两头都坏：① 内容少的卡片变成**巨大空框**（标题被垂直居中、内容飘在中段）——
    正是用户说的"展开还是不展开都要占据大量页面内容，又完全不为交互考虑"；
    ② 内容一多就**把底部按钮顶出可视区**（主操作够不着）。
    现在分工明确：内容区负责"放不下就滚"，外层 `lay` 只放**钉底**的主操作。

    `content` = 往里面 `addWidget(卡片)` 的布局。⚠ **卡片一律不要贪心拉伸**，
    除非它本来是"越长越好"的东西（自选清单、画线工具目录）。
    """

    def __init__(self, parent=None, spacing: int = 8):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(SCROLL_REGION_QSS)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        self.content = QVBoxLayout(holder)
        self.content.setContentsMargins(0, 0, 0, 0)
        self.content.setSpacing(spacing)
        self.setWidget(holder)


# ==========================================
# 手风琴卡片（§7-B8 · A 方案的核心交互）
# ==========================================
ACCORD_QSS = (
    "QFrame#AccordionCard { background:#FFFFFF; border:1px solid #E4E9F0; border-radius:10px; }"
    "QFrame#AccordionCard[open=\"0\"] { background:#FBFCFE; border-color:#EAEFF6; }"
    "QFrame#AccordionHead { background:transparent; border:none;"
    " border-top-left-radius:9px; border-top-right-radius:9px; }"
    "QFrame#AccordionHead:hover { background:#F4F9FF; }"
    "QLabel#AccordionIcon { font-size:13px; border:none; background:transparent; }"
    "QLabel#AccordionTitle { font-size:12.6px; font-weight:800; color:#3A4250;"
    " border:none; background:transparent; }"
    "QLabel#AccordionArrow { font-size:11px; color:#B6BEC9; border:none; background:transparent; }")
_ACCORD_STATE_QSS = ("font-size:11.3px; font-weight:700; color:%s;"
                     " border:none; background:transparent;")
# 状态色（四档，与 §7-B8 样板一致；"bad" 只给"会影响数据"的动作）
ACCORD_STATE_COLOR = {"": "#8A94A6", "ok": "#2E7D32", "warn": "#E65100", "bad": "#C62828"}


class ClickFrame(QFrame):
    """整行可点的容器（Qt 没有现成的"可点卡片头"，别让人去点 12px 的小箭头）。

    ⚠ 公开件（不是 `_ClickFrame`）：配方 chip / 分组胶囊 / 画线类型 tile 都要用它，
    跨模块导入私有名是坏味道（改个名字就会静默断在各种地方）。
    """

    sigClicked = pyqtSignal()

    def mouseReleaseEvent(self, event):        # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            self.sigClicked.emit()
        super().mouseReleaseEvent(event)


class AccordionCard(QFrame):
    """手风琴卡片：**卡头即状态行**（§7-B8 · 用户 2026-09-17 采纳的 A 方案）。

    为什么不是"标题栏 + 折叠三角"：
      · 收起后**卡头仍然在**，并带着状态文字（"4 组 · 6 只" / "组合 +0.82%"）
        ⇒ 用户不必展开就知道里面配了什么（治 §7-B6 记的"状态看不见"这条病灶）；
      · **整行可点**（不是只有小箭头）—— 只有 12px 的箭头可点是常见的手感坑；
      · 状态文字走 `set_state()` 单一入口 ⇒ 各页不各自拼样式（§10-9）。
    """

    sigToggled = pyqtSignal(bool)

    def __init__(self, title: str, icon: str = "", parent=None, open: bool = True):
        super().__init__(parent)
        self.setObjectName("AccordionCard")
        self.setStyleSheet(ACCORD_QSS)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        # 卡头永远**贴顶**：收起后内容区隐藏、卡片若仍被外力撑高，多余高度留在底部，
        # 而不是把卡头垂直居中（第 5 批实测：不设它，收起后卡头被顶到卡片正中间）
        box.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._head = ClickFrame()
        self._head.setObjectName("AccordionHead")
        self._head.setCursor(Qt.CursorShape.PointingHandCursor)
        head = QHBoxLayout(self._head)
        head.setContentsMargins(11, 9, 11, 9)
        head.setSpacing(8)

        self.icon = QLabel(icon)
        self.icon.setObjectName("AccordionIcon")
        self.icon.setFixedWidth(20)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.addWidget(self.icon)

        self.title = QLabel(title)
        self.title.setObjectName("AccordionTitle")
        head.addWidget(self.title)
        head.addStretch()

        self._state = QLabel("")
        head.addWidget(self._state)

        self._arrow = QLabel("▾")
        self._arrow.setObjectName("AccordionArrow")
        head.addWidget(self._arrow)

        # ⚠⚠ 卡头**必须钉成固定高**（v6.24 · 第 5 批修的真 bug）：
        #   卡头与内容区默认都是 `Preferred` ⇒ 父布局把整张卡拉高时，多出来的高度会被
        #   **两者平分** ⇒ 卡头变成一个大框、标题被垂直居中，而内容区的内容贴在自己顶端
        #   ⇒ 页面上就是"标题悬在半空、内容离它老远"；**卡片收起时更糟**：内容一隐藏，
        #   全部多余高度压到卡头身上（一整个空框里就一行小字）。
        #   正确做法 = 卡头 Fixed（永远 = 自己文字的高度），多余高度**全部给内容区**。
        head_policy = self._head.sizePolicy()
        head_policy.setVerticalPolicy(QSizePolicy.Policy.Fixed)
        self._head.setSizePolicy(head_policy)
        box.addWidget(self._head)

        # 内容放进**独立容器**：收起时只需隐藏这一个 widget
        # （若直接往布局里加控件，逐个 setVisible 会漏掉嵌套布局里的控件）
        self._host = QWidget()
        self.body = QVBoxLayout(self._host)
        self.body.setContentsMargins(11, 0, 11, 11)
        self.body.setSpacing(7)
        # 拉伸因子给**内容区**：卡片被拉高时，长高的是内容区，不是卡头（见上面那段说明）
        box.addWidget(self._host, 1)

        self._head.sigClicked.connect(self._toggle)
        self._open = True
        self.set_open(open)

    # ---- 标题 / 状态 ----
    def set_title(self, text: str) -> None:
        self.title.setText(text)

    def title_text(self) -> str:
        return self.title.text()

    def state_text(self) -> str:
        return self._state.text()

    def set_state(self, text: str, kind: str = "", tooltip: str = "") -> None:
        """右上角状态。`kind`："" 灰 / ok 绿 / warn 橙 / bad 红。"""
        self._state.setText(text)
        self._state_kind = kind or ""
        self._state.setStyleSheet(_ACCORD_STATE_QSS % ACCORD_STATE_COLOR.get(kind, "#8A94A6"))
        self._state.setToolTip(tooltip or text)

    def state_kind(self) -> str:
        """状态档位（测试用：验证"有缺数据时要转成警示色"这类口径）。"""
        return getattr(self, "_state_kind", "")

    # ---- 折叠 ----
    def is_open(self) -> bool:
        return self._open

    def set_open(self, value: bool) -> None:
        self._open = bool(value)
        self._host.setVisible(self._open)
        self._arrow.setText("▾" if self._open else "▸")
        self.setProperty("open", "1" if self._open else "0")
        self.style().unpolish(self)
        self.style().polish(self)
        # ★ 收起/展开会改变卡片的高度需求（内容区显示/隐藏）⇒ 让卡片高度**立即**跟上：
        #   `updateGeometry()` 通知父布局、`adjustSize()` 直接把自己收到 sizeHint ——
        #   第 5 批实测：只靠 updateGeometry / 父布局 invalidate+activate **都不够**，
        #   收起后卡片高度纹丝不动（Qt 在 QScrollArea 里不重排这条链）；adjustSize 才真能缩。
        self.updateGeometry()
        self.adjustSize()

    def _toggle(self) -> None:
        self.set_open(not self._open)
        self.sigToggled.emit(self._open)


# ==========================================
# 分组胶囊（§7-B8 R1）：组名 + **组合当日涨跌**
# ==========================================
GROUP_CHIP_QSS_ON = (
    "QFrame#GroupChip { background:#E8F2FE; border:1px solid #BBDEFB; border-radius:999px; }"
    "QFrame#GroupChip QLabel { border:none; background:transparent; }"
    "QLabel#GroupChipName { font-size:12px; font-weight:800; color:#1565C0; }"
    "QLabel#GroupChipCount { font-size:10.8px; color:#8A94A6; }")
GROUP_CHIP_QSS_OFF = (
    "QFrame#GroupChip { background:#FFFFFF; border:1px solid #E4E9F0; border-radius:999px; }"
    "QFrame#GroupChip:hover { background:#F7FBFF; border-color:#A9C7EA; }"
    "QFrame#GroupChip QLabel { border:none; background:transparent; }"
    "QLabel#GroupChipName { font-size:12px; font-weight:700; color:#3A4250; }"
    "QLabel#GroupChipCount { font-size:10.8px; color:#8A94A6; }")
GROUP_CHIP_QSS_ADD = (
    "QFrame#GroupChip { background:#F7FBFF; border:1px dashed #BBDEFB; border-radius:999px; }"
    "QFrame#GroupChip:hover { background:#EAF3FE; border-color:#A9C7EA; }"
    "QFrame#GroupChip QLabel { border:none; background:transparent; }"
    "QLabel#GroupChipName { font-size:12px; font-weight:700; color:#1976D2; }")
_CHIP_TEXT_QSS = ("font-size:11.2px; font-weight:700; color:%s;"
                  " border:none; background:transparent;")
CHIP_VALUE_UP = "#4CAF50"       # 与 K 线涨色同源（涨=绿）
CHIP_VALUE_DOWN = "#F44336"     # 与 K 线跌色同源（跌=红）
CHIP_VALUE_NEUTRAL = "#5B6472"  # 平盘（0.00%）用中性灰 —— 「平」既不是涨也不是跌
CHIP_WARN_COLOR = "#E65100"


class GroupChip(ClickFrame):
    """分组胶囊：`组名 ＋ 组合当日涨跌`（一个分组 ≈ 一只"自建基金"，§7-B8 R1）。

    · `key is None` = "全部"（**聚合视图，不是真实分组** —— 别把它写进存储）；
    · 涨跌留空 = 还没算 / 算不出来 ⇒ **只显示组名**，不留 "0.00%" 这种假数；
    · `set_warn()` = 组里**有票今天没数据**（不算它，但要在标签上打 ⚠。
      绝不拿 0% 混进去把数字冲淡 —— 那是看不见的假口径）。
    """

    sigPicked = pyqtSignal(object)      # 参数 = 分组键（None = 全部）

    def __init__(self, key, name: str, count: int = 0, parent=None):
        super().__init__(parent)
        self.setObjectName("GroupChip")
        self.key = key
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 5, 10, 5)
        row.setSpacing(6)

        self._name = QLabel(name)
        self._name.setObjectName("GroupChipName")
        row.addWidget(self._name)

        self._count = QLabel("")
        self._count.setObjectName("GroupChipCount")
        row.addWidget(self._count)

        self._value = QLabel("")
        row.addWidget(self._value)

        self._warn = QLabel("")
        row.addWidget(self._warn)

        # 空标签**必须隐藏**：留下的空 QLabel 会白占一个 spacing（每个胶囊 ~12px），
        # 结果是"胶囊虚胖、一行只放得下一个"（渲染探针实测过）
        self._value.setVisible(False)
        self._warn.setVisible(False)

        self._selected = False
        self.set_count(count)
        self.set_selected(False)
        self.sigClicked.connect(lambda: self.sigPicked.emit(self.key))

    def set_count(self, count) -> None:
        text = "" if count is None else f"{count} 只"
        self._count.setText(text)
        self._count.setVisible(bool(text))

    def count_text(self) -> str:
        return self._count.text()

    def value_text(self) -> str:
        return self._value.text()

    def value_color(self) -> str:
        """当前涨跌值的颜色（测试用：钉住"平盘不是绿"这条口径）。"""
        return getattr(self, "_value_color", "")

    def warn_text(self) -> str:
        return self._warn.text()

    def warn_tooltip(self) -> str:
        return self._warn.toolTip()

    def set_value(self, text: str = "", up=None) -> None:
        """右侧涨跌值：`up=True` 绿 / `False` 红 / **`None` 中性灰**（平盘）。

        `text=""`（还没算出来 / 算不出来）⇒ **整段隐藏**，不留 "0.00%" 这种假数。
        """
        text = text or ""
        self._value.setText(text)
        self._value.setVisible(bool(text))
        if text:
            color = (CHIP_VALUE_UP if up is True
                     else CHIP_VALUE_DOWN if up is False else CHIP_VALUE_NEUTRAL)
            self._value_color = color
            self._value.setStyleSheet(_CHIP_TEXT_QSS % color)

    def set_warn(self, tooltip: str = "") -> None:
        self._warn.setText("⚠" if tooltip else "")
        self._warn.setVisible(bool(tooltip))
        self._warn.setStyleSheet(_CHIP_TEXT_QSS % CHIP_WARN_COLOR)
        self._warn.setToolTip(tooltip)

    def set_selected(self, on: bool) -> None:
        self._selected = bool(on)
        self.setStyleSheet(GROUP_CHIP_QSS_ON if self._selected else GROUP_CHIP_QSS_OFF)

    def is_selected(self) -> bool:
        return self._selected


RECIPE_BADGE_MAIN = "#1976D2"       # 主图 = 蓝（与样板一致）
RECIPE_BADGE_SUB = "#7E57C2"        # 副图 = 紫
RECIPE_CHIP_QSS_OFF = (
    "QFrame#RecipeChip { background:#FFFFFF; border:1px solid #E4E9F0; border-radius:9px; }"
    "QFrame#RecipeChip:hover { background:#F7FBFF; border-color:#A9C7EA; }"
    "QFrame#RecipeChip QLabel { border:none; background:transparent; }"
    "QLabel#RecipeChipName { font-size:12px; color:#3A4250; }")
RECIPE_CHIP_QSS_ON = (
    "QFrame#RecipeChip { background:#EAF7EE; border:1px solid #BFE3C8; border-radius:9px; }"
    "QFrame#RecipeChip QLabel { border:none; background:transparent; }"
    "QLabel#RecipeChipName { font-size:12px; font-weight:800; color:#2E7D32; }")
RECIPE_BADGE_QSS = ("color:%s; font-size:%s; font-weight:%s; border-radius:%s;"
                    " padding:%s; background:%s; border:%s;")
RECIPE_OPS_BTN_QSS = ("QPushButton { border:none; background:transparent; color:#8A94A6;"
                      " font-size:11px; padding:0 3px; }"
                      "QPushButton:hover { color:#1976D2; }")


class RecipeChip(ClickFrame):
    """配方库里的一个条目（§7-B8 R6）：**徽标 + 名称 +（管理模式下的）操作**。

    【为什么徽标是必需的】用户原话："保存的时候选了主图还是副图，但**从配方库载入时
    完全看不出**这个配方到底是主图的还是副图的" ⇒ 徽标不是装饰，是在治一个真实痛点。
    ★三轮定稿之后它更强了：**去处只有两类且互不串门** ⇒ "徽标 = 去处"语义上唯一正确。

    · **内置项**：徽标写「内置」、**只能开关不能删改**（连管理模式也不给 ✏/🗑）；
    · 点击 = 开/关（点的是行本体；点 ✏/🗑 不会误触发开关，因为按钮会吃掉那个点击）；
    · `⚙` 参数入口**不在这里加** —— 它跟 R16 的窗口一起做（有就是有、没有就是没有，
      绝不放一个点了没反应的按钮）。
    """

    sigToggled = pyqtSignal(str)
    sigRename = pyqtSignal(str)
    sigDelete = pyqtSignal(str)
    sigParams = pyqtSignal(str)

    def __init__(self, key: str, name: str, target: str, builtin: bool = False,
                 has_params: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("RecipeChip")
        self.key = str(key)
        self.builtin = bool(builtin)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(7, 5, 7, 5)
        row.setSpacing(6)

        badge = QLabel("内置" if builtin else ("主图" if target == "main" else "副图"))
        badge.setObjectName("RecipeChipBadge")
        if builtin:
            badge.setStyleSheet(RECIPE_BADGE_QSS % ("#5B6472", "9.6px", "800", "4px",
                                                    "0 4px", "#FFFFFF", "1px solid #DCE3EC"))
        else:
            color = RECIPE_BADGE_MAIN if target == "main" else RECIPE_BADGE_SUB
            badge.setStyleSheet(RECIPE_BADGE_QSS % ("#FFFFFF", "10.4px", "800", "5px",
                                                    "1px 5px", color, "none"))
        self.badge = badge
        row.addWidget(badge)

        self.name = QLabel(str(name))
        self.name.setObjectName("RecipeChipName")
        row.addWidget(self.name)

        # ★v6.24（§7-B8 R16）：**有参数才有 ⚙** —— `成交量` 那种没有参数的就不给，
        #   "有就是有、没有就是没有"，绝不放一个点了没反应的入口。
        self.btn_params = None
        if has_params:
            self.btn_params = QPushButton("⚙")
            self.btn_params.setStyleSheet(RECIPE_OPS_BTN_QSS)
            self.btn_params.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_params.setToolTip("参数设置（改了要「应用」才生效；内置参数有范围校验）")
            self.btn_params.clicked.connect(lambda: self.sigParams.emit(self.key))
            row.addWidget(self.btn_params)

        # 操作（✏ / 🗑）—— 默认隐藏，进「管理模式」才出现（§10-10：危险动作不与高频操作同排）
        self._ops = QWidget()
        ops = QHBoxLayout(self._ops)
        ops.setContentsMargins(0, 0, 0, 0)
        ops.setSpacing(0)
        self.btn_rename = QPushButton("✏")
        self.btn_delete = QPushButton("🗑")
        for button in (self.btn_rename, self.btn_delete):
            button.setStyleSheet(RECIPE_OPS_BTN_QSS)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_rename.setToolTip("改名（内置项不可改名）")
        self.btn_delete.setToolTip("删除这条配方（会同时从图上移除）")
        ops.addWidget(self.btn_rename)
        ops.addWidget(self.btn_delete)
        self._ops.setVisible(False)
        row.addWidget(self._ops)

        self._on = False
        self.set_on(False)
        self._sync_ops()
        self.sigClicked.connect(lambda: self.sigToggled.emit(self.key))
        self.btn_rename.clicked.connect(lambda: self.sigRename.emit(self.key))
        self.btn_delete.clicked.connect(lambda: self.sigDelete.emit(self.key))

    # ---- 状态 ----
    def set_on(self, value: bool) -> None:
        self._on = bool(value)
        self.setStyleSheet(RECIPE_CHIP_QSS_ON if self._on else RECIPE_CHIP_QSS_OFF)

    def is_on(self) -> bool:
        return self._on

    def has_param_button(self) -> bool:
        """这个条目有没有 `⚙`（测试用：钉住"没参数就不给假入口"）。"""
        return self.btn_params is not None

    def set_manage(self, value: bool) -> None:
        """管理模式开关。**内置项永远不显示操作** —— 那是刻意的（怕用户改回不来）。"""
        self._manage = bool(value)
        self._sync_ops()

    def ops_visible(self) -> bool:
        """操作区是否显示。

        ⚠ 用 `isVisibleTo(self)` 而不是 `isVisible()`：后者要求**整条祖先链都可见**，
        页面没 `show()` 时永远返回 False —— 那样断言会"因为窗口没显示"而假绿/假红。
        """
        return self._ops.isVisibleTo(self)

    def _sync_ops(self) -> None:
        self._ops.setVisible(getattr(self, "_manage", False) and not self.builtin)


class AddChip(ClickFrame):
    """「＋ 新建分组」胶囊（**虚线边** = "这里能造新的"，与真实分组一眼区分）。"""

    def __init__(self, text: str = "＋ 新建分组", parent=None):
        super().__init__(parent)
        self.setObjectName("GroupChip")
        self.setStyleSheet(GROUP_CHIP_QSS_ADD)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 5, 10, 5)
        row.setSpacing(6)
        self.label = QLabel(text)
        self.label.setObjectName("GroupChipName")
        row.addWidget(self.label)