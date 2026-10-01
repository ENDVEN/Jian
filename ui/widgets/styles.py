# ui/widgets/styles.py
"""全站**样式唯一定义处**（★1.59 / §7-B14 批3 自 `custom_widgets.py` 原样搬出）。

【为什么拆】§4 红榜长期第一名（1072 非空行）：样式族（QSS 常量 / QSS 生成器 / 字体栈）
与控件族（NoWheel 控件 / 工厂 / K线图元 / 手风琴卡片…）挤在同一文件。本文件只放
**QSS 与字体**；控件本体与控件工厂仍在 `ui/widgets/custom_widgets.py`。

【兼容契约】`custom_widgets.py` 对下面全部公开名做**同名再导出**（`import X as X` 显式
再导出，零 noqa）⇒ 既有 `from ui.widgets.custom_widgets import FLAT_QSS / UI_FONT_STACK
/ combo_qss …` 的调用方与断言**零改动**；**新增样式一律直接 import 本文件**。

【纪律不变】§10-9（完整 QSS、禁半截子控件、箭头成对）· §10-15（专有字体名禁入 QSS/QFont，
唯一出口 = 本文件的字体栈）——冒烟的源码级断言已改指本文件。
"""
from PyQt6.QtGui import QFont, QFontInfo


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
# 按钮家族：扁平（flat）与描边（outline）
# ==========================================
# ★v6.70 / §9-F③「`FLAT_QSS` 归属漂移」还账：原先定义住在 `backtest_panes.py`（名字带
# “回测”，实际被 M2/M3 版式、下载条、队列面板、回测页共 6 处引用），另有 **4 处私有副本**
# （`condition_gate` / `function_segments` / `data_manager` / `backtest_history_ui`）——
# 同一个名字四种写法，就是 §10-9「同类控件同一张脸」的长期回归点。
# 【本轮只统一结构，不改观感】它们**本来就不是同一种按钮**（内边距 / 圆角 / 字号 / 悬停色
# 各异），所以硬并成一个常量= 视觉上改东西。⇒ 用**一个生成器 + 命名变体**收编：
#   定义只在此处一份，想要哪种“脸”就引哪个名字；**新增按钮一律从这里取，不许再开私有副本**。
# 【为什么生成器能保持像素不变】CSS 的空白与分号不影响渲染（原副本里 `color:#1976D2` 与
#   `color: #1976D2` 混用）⇒ 统一排版 = 同一张脸；**颜色值 / 尺寸 / 字号 / 悬停态逐项照旧**。
FLAT_BLUE = "#1976D2"          # 主强调蓝（与 K 线主题、`RECIPE_BADGE_MAIN` 同源）
FLAT_MUTED = "#8A94A6"         # 弱化行内动作（删除段 / 附属小件）
FLAT_HOVER_BG = "#EEF4FD"      # flat 家族通用悬停底（浅蓝）
FLAT_DISABLED = "#B4BECB"      # flat 家族通用禁用字色


def flat_qss(*, color: str = FLAT_BLUE, padding: str = "0 8px", radius: int = 8,
             font_size: int = None, hover_bg: str = FLAT_HOVER_BG,
             hover_color: str = None, disabled_color: str = FLAT_DISABLED) -> str:
    """**文字型（无底无框）按钮**的完整 QSS —— 唯一生成处。

    只给 `QPushButton` 本体与 `:hover` / `:disabled` 状态（无子控件 ⇒ 不踩 §10-9“半截 QSS”）。
    :param hover_color: 悬停换字色（“删除”类按钮用红色告警）；None ⇒ 只换底色。
    :param disabled_color: None ⇒ 不写 disabled 态（紧凑行内按钮家族）。
    """
    qss = (f"QPushButton {{ color: {color}; background: transparent; border: none;"
           f" padding: {padding}; font-weight: bold; border-radius: {radius}px;")
    if font_size:
        qss += f" font-size: {font_size}px;"
    qss += f" }} QPushButton:hover {{ background: {hover_bg};"
    if hover_color:
        qss += f" color: {hover_color};"
    qss += " }"
    if disabled_color:
        qss += f" QPushButton:disabled {{ color: {disabled_color}; }}"
    return qss


FLAT_QSS = flat_qss()                                     # 标准行内动作（原 `backtest_panes` 值）
FLAT_QSS_WIDE = flat_qss(padding="0 10px", radius=6)       # 数据管理页：稍宽 + 小圆角
FLAT_QSS_SMALL = flat_qss(padding="0 6px", radius=6,       # 条件门控行：紧凑、无禁用态
                          font_size=12, disabled_color=None)
FLAT_QSS_DANGER = flat_qss(color=FLAT_MUTED,               # 删段小钮：静置灰字、悬停转红
                           padding="2px 6px", radius=6, font_size=11,
                           hover_bg="#FDECEA", hover_color="#F44336", disabled_color=None)
# 描边次级按钮（“实体但低调”）：旧副本叫 `_FLAT_QSS`，可它**有底有框**、不属 flat 家族
# ⇒ 收编时正名为 `OUTLINE_QSS`，**不要把两种形状当“配色漂移”强成一张脸**。
OUTLINE_QSS = ("QPushButton { border: 1px solid #E4E9F0; background: #fff; border-radius: 8px;"
               " padding: 6px 12px; font-size: 13px; color: #1F2430; }"
               "QPushButton:hover { background: #F3F8FE; border-color: #BBDEFB;"
               " color: #1976D2; }"
               "QPushButton:disabled { color: #B8C2D0; background: #F5F6F8;"
               " border-color: #EDF0F5; }")

# ==========================================
# 摘要条动作族（★1.64 · M2/M3 视觉重塑 STEP 2）
#   【为什么要收成一份】M1 的摘要条是「主操作 = 蓝底实心 + 次级 = 描边 ghost」，而 M2/M3 的主操作
#   写成 flat（**只有蓝字、没有底**）⇒ 三页并排看不出"哪个是主按钮"（用户报的"三套设计语言"之一）。
#   这里逐字搬 M1 已定稿的那两枚（**像素不变**），M1/M2/M3 一律引用。
# ==========================================
SUMMARY_RUN_QSS = ("QPushButton { background: #1976D2; color: white; font-weight: bold;"
                   " padding: 7px 20px; border: none; border-radius: 9px; font-size: 13.5px; }"
                   "QPushButton:hover { background: #1565C0; }"
                   "QPushButton:disabled { background: #B8C6D8; }")
SUMMARY_GHOST_QSS = ("QPushButton { color: #1976D2; background: transparent;"
                     " border: 1px solid #BBDEFB; border-radius: 9px; padding: 6px 13px;"
                     " font-weight: bold; font-size: 12.5px; }"
                     "QPushButton:hover { background: #E3F2FD; }")

# ==========================================
# 小号 KPI 卡（★1.64 · M2 结果区）
#   【为什么是"小号"】M2 这一页**主角是命中清单**（用户 2026-09-30 拍板）⇒ KPI 只当配角：
#   白底小卡 + 标签与值同行（值 17px，不是 M1 那排的 24px），把高度让给清单。
#   ⚠ 值的主色由各状态自己定（`scan_result._KPI_STYLE` 的 fg），这里只管**盒子**。
# ==========================================
KPI_CARD_QSS = ("QLabel { background: #FFFFFF; border: 1px solid #E7EAF0;"
                " border-radius: 10px; padding: 7px 11px; color: #20242C; }")

# —— 容器级白卡（★v6.86 / §7-B15 视觉返工 v2 · **与 M1/M2/M3 同族**）：
#   白底 + 1px #EDF0F5 + 8px 圆角 + #FAFBFD 头条（同 `backtest_history_ui._SECT_QSS` 的
#   SectionCard 语言）。页面级面板 / 图表外框 / 表格外框一律用它，
#   **不许**在页面里就地写第二份卡片 QSS（§10-9 同类控件同一张脸）。
PANEL_CARD_QSS = ("QFrame#panelCard { background: #FFFFFF; border: 1px solid #EDF0F5;"
                  " border-radius: 8px; }")
PANEL_HEAD_QSS = ("QFrame#panelHead { background: #FAFBFD; border: none;"
                  " border-top-left-radius: 8px; border-top-right-radius: 8px; }")
SEC_TITLE_QSS = ("QLabel { color: #3A4250; font-weight: bold; font-size: 12.5px;"
                 " background: transparent; border: none; }")
SEC_META_QSS = ("QLabel { color: #8A94A6; font-size: 11.5px; background: transparent;"
                " border: none; }")
SEC_HINT_QSS = "QLabel { color: #8A94A6; background: transparent; border: none; }"
# ★用户 2026-10-01：闸门"拦住了"必须有**看得见**的落点（灰字等于没说 ⇒ "点了没反应"）
WARN_HINT_QSS = ("QLabel { color: #E65100; background: #FFF8E1; border: 1px solid #FFE082;"
                 " border-radius: 6px; padding: 4px 6px; }")
#: 步号徽标（设计稿 .step-no：强调蓝底白字小圆块）
STEP_BADGE_QSS = ("QLabel { background: #1976D2; color: white; border-radius: 9px;"
                  " min-width: 18px; max-width: 18px; min-height: 18px; max-height: 18px;"
                  " font-size: 11px; font-weight: bold; }")
#: 空态占位卡（浅底 + 虚线边 —— 一眼看出"这里是占位，不是坏了"）
EMPTY_STATE_QSS = ("QLabel { background: #FAFBFD; border: 1px dashed #D9DEE8;"
                   " border-radius: 8px; color: #8A94A6; }")
TABLE_HEAD_QSS = ("QHeaderView::section { background: #F7F9FC; border: none;"
                  " border-bottom: 1px solid #EDF0F5; padding: 5px 6px;"
                  " color: #5B6472; font-weight: bold; }")
VERDICT_BAD_QSS = ("QLabel { background: #FDECEA; border: 1px solid #F5C6C0;"
                   " border-radius: 8px; padding: 10px 12px; color: #B71C1C; }")
VERDICT_WARN_QSS = ("QLabel { background: #FFF8E1; border: 1px solid #FFE082;"
                    " border-radius: 8px; padding: 10px 12px; color: #E65100; }")
VERDICT_OK_QSS = ("QLabel { background: #EDF7ED; border: 1px solid #C8E6C9;"
                  " border-radius: 8px; padding: 10px 12px; color: #1B5E20; }")
VERDICT_IDLE_QSS = ("QLabel { background: #FFFFFF; border: 1px solid #EDF0F5;"
                    " border-radius: 8px; padding: 10px 12px; color: #20242C; }")

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

# ==========================================
# 日期控件弹出的日历（★R4-b：用户实测「年月两栏透明，鼠标放上去才显示」）
# ==========================================
# 【为什么必须单独一份】`QCalendarWidget` 弹层是**独立的顶层窗口**，父控件的 QSS **管不到它**
#   （不是继承关系）；此前全仓库没有一处 `QCalendarWidget` 样式 ⇒ 它按系统调色板画，
#   在浅色主题下"月/年"那两栏（QToolButton + QSpinBox）就是**白底白字 = 看不见**
#   （悬停才被 hover 底色衬出来）—— 用户实测现象。这一份在 `NoWheelDateEdit.setCalendarPopup`
#   里挂到弹层上（一处修，全站日期控件一起好）。
CALENDAR_QSS = (
    "QCalendarWidget QWidget { background:#FFFFFF; color:#20242C; }"
    "QCalendarWidget QWidget#qt_calendar_navigationbar { background:#FFFFFF;"
    " border-bottom:1px solid #E6EAF0; }"
    "QCalendarWidget QToolButton { color:#20242C; background:transparent; border:0;"
    " padding:2px 6px; font-weight:600; }"
    "QCalendarWidget QToolButton:hover { background:#E8F1FB; border-radius:6px; }"
    "QCalendarWidget QToolButton::menu-indicator { image:none; }"
    "QCalendarWidget QSpinBox { background:#FFFFFF; color:#20242C; border:1px solid #E6EAF0;"
    " border-radius:6px; padding:1px 4px; selection-background-color:#1976D2;"
    " selection-color:#FFFFFF; }"
    "QCalendarWidget QSpinBox::up-button, QCalendarWidget QSpinBox::down-button"
    " { width:14px; background:#F2F5F9; border:0; }"
    "QCalendarWidget QAbstractItemView:enabled { background:#FFFFFF; color:#20242C;"
    " selection-background-color:#1976D2; selection-color:#FFFFFF; outline:0; }"
    "QCalendarWidget QAbstractItemView:disabled { color:#B4BECB; }"
    "QCalendarWidget QMenu { background:#FFFFFF; color:#20242C; }")

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
