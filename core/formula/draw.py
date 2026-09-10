# core/formula/draw.py
"""
公式绘图的契约层（IR）—— 引擎侧唯一「绘图语义」定义处（§7-B3 B① · P1）。

职责（只出数据，**零 Qt、零绘图**）：
  1. 定义一期支持的绘图函数集合与元数；
  2. 定义通达信颜色名 → hex 的颜色表（含 COLORRRGGBB 直通）；
  3. 定义编译期规格 `DrawSpec` 与运行期数据 `DrawData`；
  4. 校验输出语句的绘图属性后缀（COLOR / LINETHICK / NODRAW / 线型）。

【纪律 · §7-B3 / §10-12】
  · 本模块**绝不画图** —— 渲染是 `ui/widgets/draw_overlay.py` 的 `OverlayPainter` 唯一职责。
  · **未知颜色 / 未知绘图函数 / 未知属性一律报错**，绝不静默跳过
    （历史 Bug 的根因正是 `program.py` 把绘图语句 SKIP 掉了，用户"算得出、没得画"）。
  · 已识别但一期未渲染的属性（如 VOLSTICK）**接受但不渲染**，不算未知 —— 避免误伤存量函数。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ==========================================
# 1) 绘图函数集合（一期）
# ==========================================
DRAW_FUNCTIONS = ('STICKLINE', 'DRAWICON')

# 已知的通达信绘图/指令函数：**本期不渲染，但绝不阻断函数运行**（v6.5 修订）。
# 演变史：旧行为 = 整行 SKIP 静默丢弃 → 用户"算得出、没得画"；
#        v6.0 一度改为"硬报错" → 却让**存量已保存的函数直接跑不起来**（真实回归，见 §9-Q）；
#        现取折中：登记为 kind='unsupported'，由 UI 汇总成"本期不渲染"的**非阻断提示** ——
#        既看得见问题，又不把能跑的函数掐死。
DEFERRED_DRAW_FUNCTIONS = (
    'DRAWTEXT', 'DRAWNUMBER', 'DRAWBAND', 'DRAWLINE', 'DRAWKLINE',
    'POLYLINE', 'PLOYLINE', 'PARTLINE', 'FILLRGN', 'DRAWGBK', 'DRAWBMP',
    'VERTLINE', 'HORLINE',
)

# 元数声明: 函数名 -> (最少参数, 最多参数)
DRAW_ARITY = {
    'STICKLINE': (5, 5),   # COND, PRICE1, PRICE2, WIDTH, EMPTY
    'DRAWICON': (3, 3),    # COND, PRICE, ICONID
}

# 函数名 -> DrawData.kind
DRAW_KIND = {
    'STICKLINE': 'stick',
    'DRAWICON': 'icon',
}


class FormulaDrawError(ValueError):
    """绘图语句的编译 / 属性校验错误（向 UI 展示友好信息）"""


# ==========================================
# 2) 颜色与线型
# ==========================================
COLOR_TABLE = {
    'WHITE': '#FFFFFF', 'BLACK': '#000000',
    'RED': '#FF0000', 'GREEN': '#00FF00', 'BLUE': '#0000FF',
    'YELLOW': '#FFFF00', 'CYAN': '#00FFFF', 'MAGENTA': '#FF00FF',
    'GRAY': '#808080', 'DARKGRAY': '#404040', 'LIGRAY': '#C0C0C0',
    'LIRED': '#FF8080', 'LIGREEN': '#80FF80', 'LIBLUE': '#8080FF',
    'LIYELLOW': '#FFFF80', 'LICYAN': '#80FFFF', 'LIMAGENTA': '#FF80FF',
    'BROWN': '#996633',
}

_LINE_STYLES = {
    'DOTLINE': 'dot', 'DASHLINE': 'dash',
    'CIRCLEDOT': 'dot', 'CROSSDOT': 'cross',
}

# 已识别、但一期不参与渲染的属性（接受，不算未知）—— 防误伤存量 TDX 函数
_ACCEPTED_UNRENDERED = {'VOLSTICK', 'LINESTICK'}

_HEX_DIGITS = set('0123456789ABCDEF')


def resolve_color(token: str) -> str:
    """把 COLORxxx / COLORRRGGBB 解析成 '#hex'；失败抛 FormulaDrawError"""
    word = (token or '').strip().upper()
    if not word.startswith('COLOR') or word == 'COLOR':
        raise FormulaDrawError(
            f"未知颜色属性 '{token}'，应形如 COLORRED 或 COLORFF0000。")
    body = word[len('COLOR'):]
    if body in COLOR_TABLE:
        return COLOR_TABLE[body]
    if len(body) == 6 and set(body) <= _HEX_DIGITS:
        return '#' + body
    raise FormulaDrawError(
        f"未知颜色 '{token}'。可用颜色名: {', '.join(sorted(COLOR_TABLE))}；"
        f"或直接写 COLORRRGGBB（如 COLORFF0000）。")


@dataclass
class DrawAttrs:
    """一条输出语句「属性后缀」的解析结果"""
    color: str | None = None
    thickness: int = 1
    style: str | None = None
    nodraw: bool = False


def parse_attrs(tokens) -> DrawAttrs:
    """把已按【顶层逗号】切好的属性 token 列表解析成 DrawAttrs（未知属性报错）。

    切分由 `program.py` 负责（它已有括号深度扫描 `_find_top_level`），
    本函数只做语义识别，避免两套文本扫描器（§11.5-12 教训）。
    """
    attrs = DrawAttrs()
    for raw in tokens or ():
        word = (raw or '').strip().upper()
        if not word:
            continue
        if word == 'NODRAW':
            attrs.nodraw = True
        elif word.startswith('COLOR'):
            attrs.color = resolve_color(word)
        elif word.startswith('LINETHICK'):
            tail = word[len('LINETHICK'):]
            if not tail.isdigit() or not (1 <= int(tail) <= 9):
                raise FormulaDrawError(
                    f"线宽属性 '{raw}' 非法，应形如 LINETHICK2（1~9）。")
            attrs.thickness = int(tail)
        elif word in _LINE_STYLES:
            attrs.style = _LINE_STYLES[word]
        elif word in _ACCEPTED_UNRENDERED:
            continue
        else:
            raise FormulaDrawError(
                f"无法识别的绘图属性 '{raw}'。可用: COLORxxx / LINETHICKn / NODRAW / "
                f"{' / '.join(sorted(_LINE_STYLES))}。")
    return attrs


# ==========================================
# 3) IR：编译期规格 / 运行期数据
# ==========================================
@dataclass
class DrawSpec:
    """编译期绘图规格（只描述结构，不求值）"""
    kind: str                       # 'line' | 'stick' | 'icon' | 'hidden' | 'unsupported'
    args: tuple = ()                # 各参数的 AST 节点（line 只含输出表达式）
    name: str = ''                  # line 的变量名；stick/icon 为绘图函数名
    color: str | None = None
    thickness: int = 1
    style: str | None = None
    source: str = ''                # 原始语句文本（报错 / 溯源）


@dataclass
class DrawData:
    """运行期绘图数据（各数组与宿主 df **等长、同序**，由宿主按窗口切片）"""
    kind: str
    source: str = ''
    name: str = ''
    color: str | None = None
    thickness: int = 1
    style: str | None = None
    x: Any = None                   # 日期轴（对齐用；渲染时由宿主切窗口）
    y: Any = None                   # line：取值数组
    cond: Any = None                # stick / icon：布尔数组
    lo: Any = None                  # stick
    hi: Any = None                  # stick
    width: Any = None               # stick
    hollow: bool = False            # stick：第 5 参（1=空心 / 0=实心）
    pos: Any = None                 # icon：位置价数组
    icon_id: int | None = None      # icon：图标号
