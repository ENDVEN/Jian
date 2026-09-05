# core/formula/program.py
"""
通达信式「整段函数」解析与执行 (多语句 + 绘制指令兼容)。

支持结构：
    NAME := 表达式 ;                       # 赋值中间变量
    NAME : 表达式 , 颜色/线型属性... ;      # 输出变量 (属性忽略, 仅取值)
    STICKLINE(...)/DRAWICON(...) ...;      # 绘制指令 —— 跳过不执行
    {注释} 与 // 行注释 会被整体剥离
    未定义的大写名称 (如用户自定义参数 N1) 按「函数参数」处理 (需在 params 提供)

执行结果 = 所有赋值变量 + 输出变量 的命名序列集合，
供上层 "函数检测 -> 条件配置" 工作流使用。
"""
from __future__ import annotations

import re

import pandas as pd

from core.formula.parser import parse, FormulaCompileError
from core.formula.runtime import EvalContext, FormulaEvalError

# 语句分类常量
ASSIGN = 'assign'   # NAME := expr
OUTPUT = 'output'   # NAME : expr, attrs...
SKIP = 'skip'       # 绘制/其它被忽略指令


class FormulaProgramError(ValueError):
    """函数程序错误 (语法/依赖/执行)，向 UI 展示友好信息"""


# 变量名片段 (允许中文字符)
_NAME_PART = r"[A-Za-z_\u4e00-\u9fff][\w\u4e00-\u9fff]*"


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


def _classify(statement: str) -> tuple[str, str, str]:
    """返回 (kind, name, expression)"""
    assign_match = re.match(rf"^({_NAME_PART})\s*:=\s*([\s\S]+)$", statement)
    if assign_match:
        return ASSIGN, assign_match.group(1).strip(), assign_match.group(2).strip()

    colon = _find_top_level(statement, ':')
    if colon != -1 and not statement[colon:colon + 2].startswith(':='):
        name = statement[:colon].strip()
        if re.fullmatch(rf"{_NAME_PART}", name):
            body = statement[colon + 1:].strip()
            comma = _find_top_level(body, ',')
            expression = body[:comma].strip() if comma != -1 else body
            return OUTPUT, name, expression
    return SKIP, "", statement


class CompiledProgram:
    """解析后的函数程序：语句列表 + 可重复执行"""

    def __init__(self, statements: list[tuple[str, str, object]]):
        self.statements = statements  # (kind, name, ast)

    @property
    def output_names(self) -> list[str]:
        """按声明顺序返回 赋值变量 + 输出变量 名称 (供 UI 条件选择)"""
        names = []
        for kind, name, _ in self.statements:
            if kind in (ASSIGN, OUTPUT) and name not in names:
                names.append(name)
        return names


def parse_program(text: str) -> CompiledProgram:
    """把整段函数编译成语句 AST；语法错误抛 FormulaProgramError"""
    statements = []
    for raw in _split_statements(text):
        kind, name, expression = _classify(raw)
        if kind == SKIP:
            # 绘制/指令行 (STICKLINE / DRAWICON / 属性) —— 本模块不执行，直接忽略
            continue
        try:
            ast = parse(expression)
        except FormulaCompileError as e:
            raise FormulaProgramError(f"语句 '{name}' 语法错误: {e}") from None
        statements.append((kind, name, ast))

    if not statements:
        raise FormulaProgramError("函数为空：没有可执行的有效语句。")
    return CompiledProgram(statements)


def missing_parameter_names(error: FormulaProgramError) -> list[str]:
    """从执行异常里提取缺失参数名 (供 UI 自动生成参数输入框)"""
    match = re.search(r"未定义的名称 '([^']+)'", str(error))
    return [match.group(1)] if match else []


def execute_program(program: CompiledProgram, df: pd.DataFrame,
                    params: dict) -> dict[str, pd.Series]:
    """按声明顺序执行整个函数，返回 {变量名: 序列}"""
    context = EvalContext(df, params)
    results: dict[str, pd.Series] = {}
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
    return results


def run_function(text: str, df: pd.DataFrame, params: dict = None) -> tuple[CompiledProgram, dict[str, pd.Series]]:
    """一站式入口：解析并执行整段函数。失败时抛 FormulaProgramError"""
    program = parse_program(text)
    return program, execute_program(program, df, params or {})
