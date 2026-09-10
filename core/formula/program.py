# core/formula/program.py
"""
通达信式「整段函数」解析与执行 (多语句 + 绘图指令 → 绘图 IR)。

支持结构：
    NAME := 表达式 ;                          # 赋值中间变量
    NAME : 表达式 , 颜色/线型/属性... ;         # 输出变量（取值 + 一条线的绘图规格）
    STICKLINE(条件, 价1, 价2, 宽度, 0) ;        # 绘图指令
    DRAWICON(条件, 价, 图标号) ;                # 绘图指令
    {注释} 与 // 行注释 会被整体剥离
    未定义的大写名称 (如用户自定义参数 N1) 按「函数参数」处理 (需在 params 提供)

语句分类（v6.1 由 3 态扩为 **4 态**，见 §7-B3）：
    ASSIGN  赋值      -> 只产出变量
    OUTPUT  输出      -> 产出变量 + 一条绘图规格（带 NODRAW 时规格为 hidden）
    DRAW    绘图指令  -> 只产出绘图规格（不产出变量）
    （旧 SKIP 已移除：**无法识别的语句 / 绘图函数一律报错**，绝不静默跳过 ——
      历史 Bug 正是 STICKLINE 被静默吞掉，用户"算得出、没得画"。）

执行入口：
    execute_programs(...)                -> {变量名: 序列}      （行为与旧版完全一致）
    execute_programs_with_draws(...)     -> (变量, [DrawData])  （供 UI 渲染叠层）
"""
from __future__ import annotations

import re

import pandas as pd

from core.formula import draw
from core.formula.parser import parse, FormulaCompileError, CallNode
from core.formula.runtime import EvalContext, FormulaEvalError, FUNCTIONS, FUNC_ALIASES
from core.utils import synthetic_bars

# 语句分类常量
ASSIGN = 'assign'   # NAME := expr
OUTPUT = 'output'   # NAME : expr [, attrs...]
DRAW = 'draw'       # STICKLINE(...) / DRAWICON(...)


class FormulaProgramError(ValueError):
    """函数程序错误 (语法/依赖/执行)，向 UI 展示友好信息"""


# 变量名片段 (允许中文字符)
_NAME_PART = r"[A-Za-z_\u4e00-\u9fff][\w\u4e00-\u9fff]*"

_DRAW_HINT = "绘图语句应形如 STICKLINE(条件,价1,价2,宽度,0) 或 DRAWICON(条件,价,图标号)。"

# "调用式"语句：NAME(...) —— 用来在解析前先认出函数名（参数留给 parse 处理）
_DRAW_CALL_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*\(")


def strip_comments(text: str) -> str:
    """剥离 {大括号} 与 // 行注释"""
    if not text:
        return ""
    text = re.sub(r"\{[^}]*\}", "", text)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _split_statements(text: str) -> list[str]:
    parts = [p.strip() for p in strip_comments(text).split(';')]
    return [p for p in parts if p]


def _find_top_level(text: str, ch: str) -> int:
    """寻找字符 ch 在括号之外首次出现的位置；找不到返回 -1"""
    depth = 0
    for i, c in enumerate(text):
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
        elif c == ch and depth == 0:
            return i
    return -1


def _split_top_level(text: str, sep: str) -> list[str]:
    """按括号之外的 sep 切分（用于输出语句的属性后缀）"""
    parts: list[str] = []
    depth = 0
    start = 0
    for i, c in enumerate(text):
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
        elif c == sep and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return parts


def _classify(statement: str) -> tuple[str, str, str, draw.DrawAttrs | None]:
    """返回 (kind, name, payload, attrs)：
        ASSIGN -> payload = 表达式文本, attrs = None
        OUTPUT -> payload = 表达式文本, attrs = DrawAttrs
        DRAW   -> payload = 整条语句文本, attrs = None
    """
    assign_match = re.match(rf"^({_NAME_PART})\s*:=\s*([\s\S]+)$", statement)
    if assign_match:
        return ASSIGN, assign_match.group(1).strip(), assign_match.group(2).strip(), None

    colon = _find_top_level(statement, ':')
    if colon != -1 and not statement[colon:colon + 2].startswith(':='):
        name = statement[:colon].strip()
        if re.fullmatch(_NAME_PART, name):
            body = statement[colon + 1:].strip()
            comma = _find_top_level(body, ',')
            if comma != -1:
                expression = body[:comma].strip()
                attrs = draw.parse_attrs(_split_top_level(body[comma + 1:], ','))
            else:
                expression = body
                attrs = draw.DrawAttrs()
            return OUTPUT, name, expression, attrs
    return DRAW, "", statement, None


def _split_draw_attrs(statement: str) -> tuple[str, draw.DrawAttrs]:
    """把绘图语句**尾部的属性后缀**切出去（`, COLORFF0000` / `, LINETHICK2` …）。

    ⚠ 这是 v6.5 修掉的一个真实回归：通达信绘图语句允许**带颜色尾巴**——
        STICKLINE(状态, 值1, 值2, 3, 0), COLORFF0000;
    旧版把整条语句（含尾巴）丢给 `parse()`，解析器必在顶层逗号处炸
    （"公式末尾存在无法解析的内容: ','"），于是**存量已保存的函数直接跑不起来**。
    切分复用输出语句那套「括号深度扫描」，不引入第二套文本解析（§11.5-12）。
    """
    comma = _find_top_level(statement, ',')
    if comma == -1:
        return statement.strip(), draw.DrawAttrs()
    try:
        attrs = draw.parse_attrs(_split_top_level(statement[comma + 1:], ','))
    except draw.FormulaDrawError as e:
        raise FormulaProgramError(f"语句 '{statement}' 属性错误: {e}") from None
    return statement[:comma].strip(), attrs


def _compile_draw(statement: str) -> draw.DrawSpec:
    """把一条绘图语句编译成 DrawSpec。

    · 一期支持的绘图函数（STICKLINE / DRAWICON）→ 严格解析参数 + 元数校验；
    · 已知但本期未渲染的绘图函数、以及尚未收录的"调用式"语句 → 登记 `kind='unsupported'`
      （**不阻断运行**，由 UI 汇总成非阻断提示，见 §9-Q）；
    · 完全不像函数调用的垃圾语句 → 才报错（那才是真语法错误）。
    """
    call_text, attrs = _split_draw_attrs(statement)

    match = _DRAW_CALL_RE.match(call_text)
    if not match:
        raise FormulaProgramError(f"无法识别的语句 '{statement}'。{_DRAW_HINT}")
    func = match.group(1).upper()

    if func not in draw.DRAW_FUNCTIONS:
        if func in FUNCTIONS or func in FUNC_ALIASES:
            raise FormulaProgramError(
                f"语句 '{statement}' 是一个表达式，请改用「变量名 := 表达式」赋值"
                f"或「变量名: 表达式」输出。")
        return draw.DrawSpec(kind='unsupported', name=func, source=statement,
                             color=attrs.color, thickness=attrs.thickness, style=attrs.style)

    try:
        node = parse(call_text)
    except FormulaCompileError as e:
        raise FormulaProgramError(
            f"绘图语句 '{statement}' 语法错误：{e}。{_DRAW_HINT}") from None
    if not isinstance(node, CallNode):
        raise FormulaProgramError(f"无法识别的语句 '{statement}'。{_DRAW_HINT}")

    lo, hi = draw.DRAW_ARITY[func]
    if not (lo <= len(node.args) <= hi):
        raise FormulaProgramError(
            f"绘图函数 {func} 需要 {lo} 个参数，实际传入 {len(node.args)} 个。")

    return draw.DrawSpec(
        kind=draw.DRAW_KIND[func], args=tuple(node.args), name=func, source=statement,
        color=attrs.color, thickness=attrs.thickness, style=attrs.style)


class CompiledProgram:
    """解析后的函数程序：变量语句 + 绘图规格（可重复执行）"""

    def __init__(self, statements: list[tuple[str, str, object]],
                 line_specs: dict[str, draw.DrawSpec] | None = None,
                 draws: list[draw.DrawSpec] | None = None):
        self.statements = statements                 # [(kind, name, ast)]
        self.line_specs = dict(line_specs or {})     # name -> DrawSpec（OUTPUT 的线/隐藏）
        self.draws = list(draws or [])               # [DrawSpec]（DRAW 语句）

    @property
    def output_names(self) -> list[str]:
        """按声明顺序返回 赋值变量 + 输出变量 名称 (供 UI 条件选择)"""
        names = []
        for kind, name, _ in self.statements:
            if kind in (ASSIGN, OUTPUT) and name not in names:
                names.append(name)
        return names

    @property
    def unsupported(self) -> list[str]:
        """本期不渲染的绘图函数名（去重保序）——供 UI 给出**非阻断**提示（§9-Q）。"""
        names = []
        for spec in self.draws:
            if spec.kind == 'unsupported' and spec.name not in names:
                names.append(spec.name)
        return names

    @property
    def unsupported_count(self) -> int:
        """本期不渲染的绘图语句**条数**（同一函数出现多次会累加）。"""
        return sum(1 for spec in self.draws if spec.kind == 'unsupported')


def parse_program(text: str) -> CompiledProgram:
    """把整段函数编译成语句 AST + 绘图规格；语法/绘图错误抛 FormulaProgramError"""
    statements: list[tuple[str, str, object]] = []
    line_specs: dict[str, draw.DrawSpec] = {}
    draws: list[draw.DrawSpec] = []

    for raw in _split_statements(text):
        try:
            kind, name, payload, attrs = _classify(raw)
        except draw.FormulaDrawError as e:
            # 属性后缀错误也统一成 FormulaProgramError，UI 只需处理一种异常
            raise FormulaProgramError(f"语句 '{raw}' 属性错误: {e}") from None

        if kind == DRAW:
            draws.append(_compile_draw(raw))
            continue

        try:
            ast = parse(payload)
        except FormulaCompileError as e:
            raise FormulaProgramError(f"语句 '{name}' 语法错误: {e}") from None
        statements.append((kind, name, ast))

        if kind == OUTPUT:
            line_specs[name] = draw.DrawSpec(
                kind='hidden' if attrs.nodraw else 'line',
                args=(ast,), name=name,
                color=attrs.color, thickness=attrs.thickness,
                style=attrs.style, source=raw)

    if not statements and not draws:
        raise FormulaProgramError("函数为空：没有可执行的有效语句。")
    return CompiledProgram(statements, line_specs=line_specs, draws=draws)


def missing_parameter_names(error: FormulaProgramError) -> list[str]:
    """从执行异常里提取缺失参数名 (供 UI 自动生成参数输入框)"""
    match = re.search(r"未定义的名称 '([^']+)'", str(error))
    return [match.group(1)] if match else []


# ==========================================
# 执行
# ==========================================
def _axis(df: pd.DataFrame):
    """叠层对齐用的 x 轴：优先 date 列，否则 df 索引"""
    if 'date' in df.columns:
        return df['date'].to_numpy()
    return df.index.to_numpy()


def _const_int(ctx: EvalContext, node, what: str) -> int:
    """把一个 AST 求值成整数常量（用于 DRAWICON 的图标号）"""
    value = ctx.eval(node)
    if isinstance(value, pd.Series):
        uniq = value.dropna().unique()
        if len(uniq) != 1:
            raise FormulaProgramError(f"{what}必须是一个常数（不能是逐日变化的序列）。")
        value = uniq[0] if len(uniq) else 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise FormulaProgramError(f"{what}必须是整数。") from None
    if not number.is_integer():
        raise FormulaProgramError(f"{what}必须是整数，当前为 {number}。")
    return int(number)


def _eval_draw(spec: draw.DrawSpec, ctx: EvalContext, df: pd.DataFrame) -> draw.DrawData:
    """求值一条绘图规格 -> DrawData（与 df 等长）"""
    try:
        if spec.kind == 'stick':
            cond_n, lo_n, hi_n, width_n, empty_n = spec.args
            cond = ctx.truth_series(ctx.eval(cond_n))
            lo = ctx.ser(ctx.eval(lo_n))
            hi = ctx.ser(ctx.eval(hi_n))
            width = ctx.ser(ctx.eval(width_n))
            # 第 5 参 = 0 实心 / 1 空心（通达信惯例，通常为常量）
            hollow = bool(ctx.truth_series(ctx.eval(empty_n)).any())
            return draw.DrawData(
                kind='stick', source=spec.source, name=spec.name,
                color=spec.color, thickness=spec.thickness, style=spec.style,
                x=_axis(df), cond=cond.to_numpy(),
                lo=lo.to_numpy(), hi=hi.to_numpy(), width=width.to_numpy(),
                hollow=hollow)

        if spec.kind == 'icon':
            cond_n, price_n, id_n = spec.args
            cond = ctx.truth_series(ctx.eval(cond_n))
            pos = ctx.ser(ctx.eval(price_n))
            icon_id = _const_int(ctx, id_n, 'DRAWICON 的图标号')
            return draw.DrawData(
                kind='icon', source=spec.source, name=spec.name, color=spec.color,
                x=_axis(df), cond=cond.to_numpy(), pos=pos.to_numpy(), icon_id=icon_id)
    except FormulaEvalError as e:
        raise FormulaProgramError(
            f"绘图语句 '{spec.source}' 求值失败: {e}") from None

    raise FormulaProgramError(f"未知的绘图类型 '{spec.kind}'（语句 '{spec.source}'）。")


def _run_programs(programs: list[CompiledProgram], context: EvalContext,
                  df: pd.DataFrame) -> tuple[dict[str, pd.Series], list[list]]:
    """在给定的 EvalContext 上按顺序执行，返回 `(variables, [每段的 draws])`。

    **唯一**的执行循环 —— 三个公开入口都走它，保证"变量 / 绘图 / 分组"三种视角
    永远同源、不会各写一遍（§11.5-12）。
    """
    results: dict[str, pd.Series] = {}
    groups: list[list] = []

    for program in programs:
        segment: list = []
        for kind, name, ast in program.statements:
            if kind not in (ASSIGN, OUTPUT):
                continue
            try:
                value = context.eval(ast)
            except FormulaEvalError as e:
                raise FormulaProgramError(f"变量 '{name}' 计算失败: {e}") from None
            series = context.ser(value)
            context.add_variable(name, series)
            results[name] = series

            if kind == OUTPUT:
                spec = program.line_specs.get(name)
                if spec is not None and spec.kind == 'line':
                    segment.append(draw.DrawData(
                        kind='line', source=spec.source, name=name,
                        color=spec.color, thickness=spec.thickness, style=spec.style,
                        x=_axis(df), y=series.to_numpy()))

        for spec in program.draws:
            if spec.kind == 'unsupported':
                continue    # 本期不渲染；已登记在 program.unsupported 供 UI 做非阻断提示
            segment.append(_eval_draw(spec, context, df))
        groups.append(segment)

    return results, groups


def execute_programs(programs: list[CompiledProgram], df: pd.DataFrame,
                     params: dict) -> dict[str, pd.Series]:
    """把多段函数在【同一个 EvalContext】上按顺序执行，返回合并的 {变量名: 序列}。

    这是「多段粘贴 / 多指标合流」的地基：
    - 各段产出的变量进入共享变量池，任意后续语句或条件都可引用；
    - 后段可以引用前段产出的变量 (如同把各段按顺序拼成一大段执行)；
    - 同名变量的语义 = 后者覆盖前者，与单段内顺序赋值一致。

    **行为与旧版逐位一致**（绘图语句在此入口不产出任何东西）。
    """
    results, _groups = _run_programs(programs, EvalContext(df, params), df)
    return results


def execute_programs_with_draws(programs: list[CompiledProgram], df: pd.DataFrame,
                                params: dict) -> tuple[dict[str, pd.Series], list]:
    """在【同一个 EvalContext】上执行一遍，**同时**产出变量与绘图数据（不二次求值）。

    返回 `(variables, draws)`：
      · variables：与 `execute_programs` 的结果完全一致；
      · draws：OUTPUT 的可见线（NODRAW/hidden 不产出）+ STICKLINE / DRAWICON。
    """
    results, groups = _run_programs(programs, EvalContext(df, params), df)
    return results, [data for segment in groups for data in segment]


def execute_programs_with_draws_grouped(programs: list[CompiledProgram], df: pd.DataFrame,
                                        params: dict) -> tuple[dict[str, pd.Series], list[list]]:
    """同 `execute_programs_with_draws`，但 draws **按函数段分组**返回（v6.8 新增）。

    【为什么需要它】行情页允许**每个函数段各选一个目标窗格**（主图 / 副图 1/2/3）。
    但各段必须共用**同一个变量池**（后段引用前段变量，这是"多段共享池"的核心契约），
    所以不能"按目标分组各跑一遍" —— 只能**一次求值、再按段归位**。

    返回 `(variables, [第1段的 draws, 第2段的 draws, ...])`（与 programs 一一对应）。
    """
    return _run_programs(programs, EvalContext(df, params), df)


def probe_missing_parameters(programs: list[CompiledProgram], params: dict,
                             df: pd.DataFrame = None, *, placeholder: float = 5.0,
                             max_rounds: int = 60):
    """反复试运行，直到不再报"未定义的名称"；返回 `(缺失参数名, 补全后的参数副本)`。

    用途：多段函数里常引用用户自定义参数（如 `L1`、`L2`），但它们可能还没写在参数框里。
    逐轮试跑 → 收集缺失名 → 用 `placeholder` 顶过后重试（窗口类函数要求周期 ≥ 1，
    所以占位值不能是 0），最多 `max_rounds` 轮。

    :param df: 试跑用的行情；**传 None 时自动用 `core.utils.synthetic_bars()` 的哑行情**
               （只验证"能不能算出来"，与真实行情无关）。

    · **不修改传入的 `params`**；
    · **非缺参类**错误原样抛 `FormulaProgramError`，由调用方展示；
    · 返回的 `missing` 非空 ⇒ 调用方应提示用户补参数（占位值只用于探测，不能真跑）。

    v6.5 从回测页抽到引擎层：行情页的「公式叠加」需要**完全相同**的缺参探测行为，
    两处各写一遍必然漂移（§11.5-12）。
    """
    probe_df = synthetic_bars() if df is None else df
    missing: list[str] = []
    attempt = dict(params or {})
    for _ in range(max_rounds):
        try:
            execute_programs_with_draws(programs, probe_df, attempt)
            return missing, attempt
        except FormulaProgramError as e:
            names = missing_parameter_names(e)
            if names and names[0] not in missing:
                missing.append(names[0])
                attempt[names[0]] = placeholder
                continue
            raise
    return missing, attempt


def execute_program(program: CompiledProgram, df: pd.DataFrame,
                    params: dict) -> dict[str, pd.Series]:
    """单段执行 (兼容旧接口)：等价于只含一段的 execute_programs"""
    return execute_programs([program], df, params)


def run_function(text: str, df: pd.DataFrame,
                 params: dict = None) -> tuple[CompiledProgram, dict[str, pd.Series]]:
    """一站式入口：解析并执行整段函数。失败时抛 FormulaProgramError"""
    program = parse_program(text)
    return program, execute_program(program, df, params or {})
