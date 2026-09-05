# core/formula/parser.py
"""
通达信(兼容类 Pine)公式方言的 语法分析器 (Parser)。

设计要点：
- 递归下降 + 优先级: NOT > 比较 > AND > OR
- 支持函数调用 / MACD.DIF 点字段引用 / 参数名 / 数字 / 括号
- AST 全部是“无状态描述”，求值由 runtime 通过 EvalContext 完成
- 关键词大小写不敏感；比较符 '=' '<>' 语义分别等于“约等于/不约等于”(数值容差比较)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from core.formula.tokens import Token, tokenize, FormulaSyntaxError, NUM, IDENT, SYM, KEYWORD

# 二元运算符
ARITH_OPS = {'+', '-', '*', '/'}
COMPARE_OPS = {'<', '>', '<=', '>=', '=', '<>'}
AND_KEY, OR_KEY, NOT_KEY = 'AND', 'OR', 'NOT'


class FormulaCompileError(ValueError):
    """公式编译(语法)错误，向用户展示友好信息"""


# ==========================================
# AST 节点
# ==========================================
class Node:
    """全部节点仅描述结构，真正的计算在 runtime.EvalContext 中完成"""


@dataclass
class NumberNode(Node):
    value: float


@dataclass
class VarNode(Node):
    """引用 数据列 / 用户参数 的名字"""
    name: str


@dataclass
class FieldNode(Node):
    """多输出指标字段引用，如 MACD.DIF / KDJ.K"""
    base: str
    field: str


@dataclass
class CallNode(Node):
    func: str
    args: List[Node]


@dataclass
class BinaryNode(Node):
    op: str
    left: Node
    right: Node


@dataclass
class UnaryNode(Node):
    op: str          # '-' 或 NOT
    operand: Node


# ==========================================
# Parser
# ==========================================
class _Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0

    # ---- token helpers ----
    def peek(self) -> Token | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def advance(self) -> Token:
        token = self.peek()
        if token is None:
            raise FormulaCompileError("公式意外结束 (缺少右括号或操作数?)")
        self.pos += 1
        return token

    def expect_symbol(self, sym: str) -> Token:
        token = self.peek()
        if token is None or token.kind != SYM or token.value != sym:
            raise FormulaCompileError(f"位置 {token.pos if token else '末尾'}: 期望 '{sym}'")
        return self.advance()

    def at_keyword(self, word: str) -> bool:
        t = self.peek()
        return t is not None and t.kind == KEYWORD and t.upper == word

    def _parse_expression(self) -> Node:
        return self._parse_or()

    def _parse_or(self) -> Node:
        node = self._parse_and()
        while self.at_keyword(OR_KEY):
            self.advance()
            node = BinaryNode('OR', node, self._parse_and())
        return node

    def _parse_and(self) -> Node:
        node = self._parse_not()
        while self.at_keyword(AND_KEY):
            self.advance()
            node = BinaryNode('AND', node, self._parse_not())
        return node

    def _parse_not(self) -> Node:
        if self.at_keyword(NOT_KEY):
            self.advance()
            return UnaryNode('NOT', self._parse_not())
        return self._parse_comparison()

    def _parse_comparison(self) -> Node:
        left = self._parse_additive()
        token = self.peek()
        if token is not None and token.kind == SYM and token.value in COMPARE_OPS:
            self.advance()
            right = self._parse_additive()
            return BinaryNode(token.value, left, right)
        return left

    def _parse_additive(self) -> Node:
        node = self._parse_multiplicative()
        while True:
            token = self.peek()
            if token is not None and token.kind == SYM and token.value in ('+', '-'):
                self.advance()
                node = BinaryNode(token.value, node, self._parse_multiplicative())
            else:
                return node

    def _parse_multiplicative(self) -> Node:
        node = self._parse_unary()
        while True:
            token = self.peek()
            if token is not None and token.kind == SYM and token.value in ('*', '/'):
                self.advance()
                node = BinaryNode(token.value, node, self._parse_unary())
            else:
                return node

    def _parse_unary(self) -> Node:
        token = self.peek()
        if token is not None and token.kind == SYM and token.value == '-':
            self.advance()
            return UnaryNode('-', self._parse_unary())
        return self._parse_primary()

    def _parse_primary(self) -> Node:
        token = self.peek()
        if token is None:
            raise FormulaCompileError("公式意外结束 (缺少操作数)")

        if token.kind == NUM:
            self.advance()
            try:
                return NumberNode(float(token.value))
            except ValueError:
                raise FormulaCompileError(f"非法数字 '{token.value}'") from None

        if token.kind == SYM and token.value == '(':
            self.advance()
            node = self._parse_expression()
            self.expect_symbol(')')
            return node

        if token.kind == IDENT:
            return self._parse_ident_chain()

        raise FormulaCompileError(f"位置 {token.pos}: 意外的语法元素 '{token.value}'")

    def _parse_ident_chain(self) -> Node:
        name = self.advance().value
        token = self.peek()

        # 字段引用: MACD.DIF / KDJ.K
        if token is not None and token.kind == SYM and token.value == '.':
            self.advance()
            field = self.advance()
            if field.kind != IDENT:
                raise FormulaCompileError(f"字段引用 '{name}.' 之后缺少字段名")
            return FieldNode(base=name.upper(), field=field.value.upper())

        # 函数调用: MA(C, 5)
        if token is not None and token.kind == SYM and token.value == '(':
            self.advance()
            args = []
            if not (self.peek() and self.peek().kind == SYM and self.peek().value == ')'):
                while True:
                    args.append(self._parse_expression())
                    if self.peek() and self.peek().kind == SYM and self.peek().value == ',':
                        self.advance()
                        continue
                    break
            self.expect_symbol(')')
            return CallNode(func=name.upper(), args=args)

        # 变量/参数引用: C / VOL / FAST
        return VarNode(name=name.upper())


def parse(text: str) -> Node:
    """把公式源码编译成 AST；语法错误抛 FormulaCompileError"""
    try:
        tokens = tokenize(text)
    except FormulaSyntaxError as e:
        raise FormulaCompileError(str(e)) from None
    parser = _Parser(tokens)
    node = parser._parse_expression()
    if parser.peek() is not None:
        raise FormulaCompileError(
            f"公式末尾存在无法解析的内容: '{parser.peek().value}' (位置 {parser.peek().pos})"
        )
    return node
