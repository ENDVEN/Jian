# core/formula/__init__.py
"""
通达信(优先)/Pine 兼容 公式引擎。

对外稳定 API：
    FormulaEngine.validate(expr)                  # 语法自检, 抛 FormulaCompileError
    FormulaEngine.evaluate(expr, df, params=None) # 返回与 df 等长的信号序列
    available_functions() / available_columns()   # 供 UI 联想/提示
"""
import pandas as pd

from core.formula.parser import parse, FormulaCompileError
from core.formula.runtime import FUNCTIONS, FUNC_ALIASES, COLUMN_ALIASES, EvalContext, FormulaEvalError

__all__ = [
    'FormulaEngine', 'FormulaCompileError', 'FormulaEvalError',
    'available_functions', 'available_columns', 'FUNCTIONS',
]


def available_functions() -> list[str]:
    return sorted(set(FUNCTIONS) | set(FUNC_ALIASES))


def available_columns() -> list[str]:
    return sorted(set(COLUMN_ALIASES.values()))


class FormulaEngine:
    """公式引擎门面：解析 + 校验 + 求值"""

    @staticmethod
    def validate(expression: str) -> str:
        """语法自检：通过则返回归一化表达式，失败抛 FormulaCompileError"""
        expr = (expression or '').strip()
        parse(expr)
        return expr.upper()

    @staticmethod
    def parse(expression: str):
        return parse(expression)

    @staticmethod
    def evaluate(expression: str, df: pd.DataFrame, params: dict = None) -> pd.Series:
        """把表达式直接算成逐日信号序列 (非0为真)"""
        node = parse(expression)
        ctx = EvalContext(df, params)
        value = ctx.eval(node)
        return ctx.ser(value)

    @staticmethod
    def signal(expression: str, df: pd.DataFrame, params: dict = None) -> pd.Series:
        """返回布尔信号序列 (与 df 等长，index 对齐)"""
        return FormulaEngine.evaluate(expression, df, params) != 0
