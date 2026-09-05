# core/formula/runtime.py
"""
通达信公式方言的 运行时函数库 与 求值上下文 (EvalContext)。

约定：
- 求值永远返回「序列」(pd.Series) 或「标量」(float/bool)。
  参与逐日信号计算的节点都是序列；数值常量在运算中自动广播。
- 窗口类函数的 N / M 必须传标量 (直接写数字或用户参数)。
- 逻辑/比较结果以 bool 语义处理 (非 0 即真)。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.formula.parser import (
    Node, NumberNode, VarNode, FieldNode, CallNode, BinaryNode, UnaryNode,
)

# A股数据列 与 通达信/惯例变量名 的映射 (大小写不敏感)
COLUMN_ALIASES = {
    'C': 'close', 'CLOSE': 'close',
    'O': 'open', 'OPEN': 'open',
    'H': 'high', 'HIGH': 'high',
    'L': 'low', 'LOW': 'low',
    'V': 'volume', 'VOL': 'volume', 'VOLUME': 'volume',
}

# 函数同义别名归一 (把类 Pine/其它写法折到通达信惯用函数)
FUNC_ALIASES = {
    'XUP': 'CROSS', 'CROSSOVER': 'CROSS',
    'AVG': 'MA',
}


class FormulaEvalError(ValueError):
    """公式求值(语义)错误"""


def _num(value, ctx) -> float:
    """把节点值解释成标量 (用于窗口长度等参数)"""
    if isinstance(value, pd.Series):
        if not np.allclose(value.dropna().to_numpy(), value.dropna().iloc[0] if len(value.dropna()) else np.nan):
            raise FormulaEvalError("该参数需要是一个数字常量，不能是逐日序列")
        value = value.dropna().iloc[0] if len(value.dropna()) else 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        raise FormulaEvalError(f"参数 '{value}' 不是有效数字") from None


def _period(ctx, value, func: str) -> int:
    """窗口/周期类参数：必须是 ≥ 1 的整数标量。

    把非法周期转成友好的 FormulaEvalError，避免 pandas
    (如 ewm span / rolling window) 抛出原始 ValueError 穿透到 UI 层。
    """
    raw = _num(value, ctx)
    if pd.isna(raw) or not np.isfinite(raw) or raw < 1:
        raise FormulaEvalError(f"函数 {func} 的周期参数必须 ≥ 1，当前为 {raw!r}")
    return int(raw)


def _truthy(v) -> bool:
    """标量真值判定 (非0即真, 空值当假)"""
    try:
        if pd.isna(v):
            return False
    except (TypeError, ValueError):
        pass
    return bool(v)


class EvalContext:
    """一次公式求值的运行环境：持有行情 df、用户参数、中间变量与指标缓存"""

    def __init__(self, df: pd.DataFrame, params: dict = None, variables: dict = None):
        self.df = df
        self.params = {}
        for key, value in (params or {}).items():
            self.params[str(key).upper()] = value
        # 中间变量 (赋值语句 NAME := ... 的结果)，供后续语句与买卖条件引用
        self.variables = {str(k).upper(): v for k, v in (variables or {}).items()}
        # 多输出指标 (MACD / KDJ) 只算一次，缓存为 {指标名: {字段: Series}}
        self._indicator_cache: dict[str, dict[str, pd.Series]] = {}

    def add_variable(self, name: str, series):
        """登记一个由赋值语句产出的中间变量 (可被后续语句与条件引用)"""
        self.variables[str(name).upper()] = self.ser(series)

    # ---------------- 基础工具 ----------------
    def ser(self, value) -> pd.Series:
        if isinstance(value, pd.Series):
            return value
        if isinstance(value, bool):
            value = float(value)
        if isinstance(value, (int, float, np.number)):
            return pd.Series(float(value), index=self.df.index)
        raise FormulaEvalError(f"无法把 {type(value).__name__} 转成行情序列")

    def truth_series(self, value) -> pd.Series:
        s = self.ser(value)
        return (s != 0).fillna(False)

    # ---------------- 指标计算 ----------------
    def _macd(self, fast=12, slow=26, signal=9) -> dict[str, pd.Series]:
        close = self.df['close'].astype(float)
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=signal, adjust=False).mean()
        macd = (dif - dea) * 2  # 国内惯例放大 2 倍，与 TAEngine 一致
        return {'DIF': dif, 'DEA': dea, 'MACD': macd, 'HIST': macd}

    def _sma_rec(self, x: pd.Series, n: float, m: float) -> pd.Series:
        """通达信 SMA(X,N,M) 递归定义 ≈ alpha=M/N 的指数加权"""
        n = max(1.0, n)
        return x.ewm(alpha=m / n, adjust=False).mean()

    def _kdj(self, n=9) -> dict[str, pd.Series]:
        low = self.df['low'].astype(float)
        high = self.df['high'].astype(float)
        close = self.df['close'].astype(float)
        llv = low.rolling(int(n), min_periods=1).min()
        hhv = high.rolling(int(n), min_periods=1).max()
        rsv = ((close - llv) / (hhv - llv).replace(0, np.nan) * 100).fillna(50.0)
        k = self._sma_rec(rsv, n=3, m=1)
        d = self._sma_rec(k, n=3, m=1)
        j = 3 * k - 2 * d
        return {'K': k, 'D': d, 'J': j}

    def field(self, base: str, field: str) -> pd.Series:
        base, field = base.upper(), field.upper()
        if base not in self._indicator_cache:
            if base == 'MACD':
                self._indicator_cache[base] = self._macd()
            elif base == 'KDJ':
                self._indicator_cache[base] = self._kdj()
            else:
                raise FormulaEvalError(
                    f"未知的字段式指标 '{base}'，当前支持: MACD / KDJ (形如 MACD.DIF)"
                )
        if field not in self._indicator_cache[base]:
            raise FormulaEvalError(
                f"指标 {base} 没有字段 '{field}'，可用: {sorted(self._indicator_cache[base])}"
            )
        return self._indicator_cache[base][field]

    def resolve_column(self, name: str) -> pd.Series:
        alias = COLUMN_ALIASES.get(name, name)
        # 大小写不敏感查找 (兼容函数输出的用户自定义变量列)
        target = None
        if alias in self.df.columns:
            target = alias
        else:
            lower = alias.lower()
            for col in self.df.columns:
                if str(col).lower() == lower:
                    target = col
                    break
        if target is not None:
            return self.df[target].astype(float)
        raise FormulaEvalError(
            f"行情数据缺少列 '{alias}' (公式引用了 {name})"
        )

    # ---------------- 表达式求值 ----------------
    def eval(self, node: Node):
        if isinstance(node, NumberNode):
            return node.value

        if isinstance(node, VarNode):
            name = node.name
            # 1) 数据列/行情变量别名 (C/O/H/L/V...) —— 列名大小写不敏感
            lower = name.lower()
            if (COLUMN_ALIASES.get(name) in self.df.columns
                    or any(str(c).lower() == lower for c in self.df.columns)):
                return self.resolve_column(name)
            # 2) 函数内赋值产出的中间变量 (NAME := ...)
            if name in self.variables:
                return self.variables[name]
            # 3) 用户参数
            if name in self.params:
                return float(self.params[name])
            raise FormulaEvalError(
                f"未定义的名称 '{name}'：不是行情列/中间变量，也不是用户参数。"
                f"可用行情变量: C/O/H/L/V(VOL)；参数需在运行参数中提供。"
            )

        if isinstance(node, FieldNode):
            return self.field(node.base, node.field)

        if isinstance(node, CallNode):
            func = FUNC_ALIASES.get(node.func, node.func)
            fn = FUNCTIONS.get(func)
            if fn is None:
                raise FormulaEvalError(
                    f"不支持的函数 '{node.func}'，当前可用: {sorted(FUNCTIONS)}"
                )
            args = [self.eval(arg) for arg in node.args]
            lo, hi = ARITY.get(func, (1, 99))
            if not (lo <= len(args) <= hi):
                raise FormulaEvalError(
                    f"函数 {func} 需要 {lo if lo == hi else f'{lo}-{hi}'} 个参数，实际传入 {len(args)} 个"
                )
            return fn(self, *args)

        if isinstance(node, UnaryNode):
            if node.op == '-':
                val = self.eval(node.operand)
                return -val
            if node.op == 'NOT':
                return ~self.truth_series(self.eval(node.operand))
            raise FormulaEvalError(f"未知一元运算符 {node.op}")

        if isinstance(node, BinaryNode):
            if node.op in ('AND', 'OR'):
                left = self.truth_series(self.eval(node.left))
                right = self.truth_series(self.eval(node.right))
                return left & right if node.op == 'AND' else left | right
            # 数值/比较运算
            left = self.eval(node.left)
            right = self.eval(node.right)
            return self._apply_binary(node.op, left, right)

        raise FormulaEvalError(f"无法求值的节点: {type(node).__name__}")

    def _apply_binary(self, op: str, left, right):
        # 浮点近似相等：避免由浮点误差导致的 “=” 永不成立
        if op in ('=', '<>'):
            l, r = self.ser(left), self.ser(right)
            tol = (l.abs() + r.abs()) * 1e-9 + 1e-12
            eq = (l - r).abs() <= tol
            return eq if op == '=' else ~eq

        if op == '>':
            return self.ser(left) > self.ser(right)
        if op == '<':
            return self.ser(left) < self.ser(right)
        if op == '>=':
            return self.ser(left) >= self.ser(right)
        if op == '<=':
            return self.ser(left) <= self.ser(right)

        # 纯算术：标量-标量保持标量，序列参与则升维
        if isinstance(left, pd.Series) or isinstance(right, pd.Series):
            l, r = self.ser(left), self.ser(right)
            if op == '+':
                return l + r
            if op == '-':
                return l - r
            if op == '*':
                return l * r
            if op == '/':
                return l / r
        else:
            if op == '+':
                return left + right
            if op == '-':
                return left - right
            if op == '*':
                return left * right
            if op == '/':
                return left / right if right != 0 else float('nan')
        raise FormulaEvalError(f"未知二元运算符 {op}")


# ==========================================
# 通达信风格函数注册表
# 签名统一: fn(ctx, *args)，args 可为标量或 Series
# ==========================================
def _cross_above(ctx, a, b) -> pd.Series:
    """CROSS(A,B)：A 上穿 B (前值 A<=B 且当前 A>B)"""
    a, b = ctx.ser(a), ctx.ser(b)
    prev_a, prev_b = a.shift(1), b.shift(1)
    up = (a > b) & (prev_a <= prev_b)
    return up.fillna(False)


def _barslast(ctx, cond) -> pd.Series:
    """BARSLAST(COND)：距最近一次条件成立的天数 (无记录时为 NaN)"""
    cond = ctx.truth_series(cond)
    idx = np.arange(len(cond))
    positions = pd.Series(np.where(cond.to_numpy(), idx, np.nan), index=cond.index)
    last = positions.ffill()
    distance = pd.Series(idx, index=cond.index) - last
    return distance


def _if3(ctx, cond, a, b):
    """通达信 IF(COND,A,B)：COND 为真取 A，否则取 B"""
    cond_bool = ctx.truth_series(cond).to_numpy()
    a_series = ctx.ser(a).to_numpy()
    b_series = ctx.ser(b).to_numpy()
    return pd.Series(np.where(cond_bool, a_series, b_series), index=ctx.df.index)


def _max_ab(ctx, a, b):
    if isinstance(a, pd.Series) or isinstance(b, pd.Series):
        return ctx.ser(a).combine(ctx.ser(b), np.fmax)
    return max(a, b)


def _min_ab(ctx, a, b):
    if isinstance(a, pd.Series) or isinstance(b, pd.Series):
        return ctx.ser(a).combine(ctx.ser(b), np.fmin)
    return min(a, b)


FUNCTIONS = {
    # 技术指标一律“满窗才算有效”：窗口前导区为 NaN，避免把“未满窗平均值”误当信号
    'MA': lambda ctx, x, n: ctx.ser(x).rolling(_period(ctx, n, 'MA'), min_periods=_period(ctx, n, 'MA')).mean(),
    'EMA': lambda ctx, x, n: ctx.ser(x).ewm(span=_period(ctx, n, 'EMA'), adjust=False).mean(),
    'SMA': lambda ctx, x, n, m: ctx._sma_rec(ctx.ser(x), _num(n, ctx), _num(m, ctx)),
    'REF': lambda ctx, x, n: ctx.ser(x).shift(int(_num(n, ctx))),
    'HHV': lambda ctx, x, n: ctx.ser(x).rolling(_period(ctx, n, 'HHV'), min_periods=_period(ctx, n, 'HHV')).max(),
    'LLV': lambda ctx, x, n: ctx.ser(x).rolling(_period(ctx, n, 'LLV'), min_periods=_period(ctx, n, 'LLV')).min(),
    'COUNT': lambda ctx, cond, n: ctx.truth_series(cond).rolling(_period(ctx, n, 'COUNT'), min_periods=_period(ctx, n, 'COUNT')).sum(),
    'SUM': lambda ctx, x, n: ctx.ser(x).rolling(_period(ctx, n, 'SUM'), min_periods=_period(ctx, n, 'SUM')).sum(),
    'IF': _if3,
    'EVERY': lambda ctx, cond, n: ctx.truth_series(cond).rolling(_period(ctx, n, 'EVERY'), min_periods=_period(ctx, n, 'EVERY')).min().fillna(0) == 1,
    'CROSS': _cross_above,
    'BARSLAST': _barslast,
    'ABS': lambda ctx, x: ctx.ser(x).abs(),
    'MAX': _max_ab,
    'MIN': _min_ab,
}

# 元数声明: 函数名 -> (最少参数, 最多参数) —— 在求值前做统一参数个数校验
ARITY = {
    'MA': (2, 2), 'EMA': (2, 2), 'SMA': (3, 3), 'REF': (2, 2),
    'HHV': (2, 2), 'LLV': (2, 2), 'COUNT': (2, 2), 'SUM': (2, 2),
    'IF': (3, 3), 'EVERY': (2, 2),
    'CROSS': (2, 2), 'BARSLAST': (1, 1), 'ABS': (1, 1),
    'MAX': (2, 2), 'MIN': (2, 2),
}


def evaluate(df: pd.DataFrame, node: Node, params: dict = None) -> pd.Series:
    """便捷入口：按 AST 求值并保证返回与 df 等长的序列"""
    ctx = EvalContext(df, params)
    return ctx.ser(ctx.eval(node))
