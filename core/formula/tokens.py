# core/formula/tokens.py
"""
通达信(兼容类 Pine)公式方言的 词法分析器 (Lexer)。

规则：
- 标识符  : [A-Za-z_][A-Za-z0-9_]*   (如 MA, C, MACD)
- 数字    : 整数/小数 (12, 26.5)
- 运算符/标点 : + - * / % ( ) , . 与比较符 < > <= >= = <> 和 & | ! ^
- 逻辑关键字 AND / OR / XOR / NOT (大小写不敏感)
- '.' 作为“字段引用”分隔符 (如 MACD.DIF)，但与数字小数不冲突
"""

from dataclasses import dataclass

# Token 类型
NUM = 'NUM'
IDENT = 'IDENT'
SYM = 'SYM'          # 运算符/标点
KEYWORD = 'KEYWORD'  # AND OR NOT XOR

_SINGLE_SYMS = set('+-*/%(),.<>&|!^=')
_TWO_CHAR_SYMS = {'<=', '>=', '<>'}
_COMPARISON = {'<', '>', '<=', '>=', '=', '<>'}
_KEYWORDS = {'AND', 'OR', 'NOT', 'XOR'}


class FormulaSyntaxError(ValueError):
    """词法/语法错误统一异常 (带源码位置提示)"""


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    pos: int

    @property
    def upper(self) -> str:
        return self.value.upper()


def tokenize(text: str) -> list[Token]:
    src = text if text else ''
    tokens = []
    i, n = 0, len(src)
    while i < n:
        ch = src[i]
        if ch.isspace():
            i += 1
            continue

        # 数字
        if ch.isdigit():
            start = i
            while i < n and (src[i].isdigit() or src[i] == '.'):
                i += 1
            raw = src[start:i]
            if raw.count('.') > 1:
                raise FormulaSyntaxError(f"非法数字字面量 '{raw}' (位置 {start})")
            tokens.append(Token(NUM, raw, start))
            continue

        # 标识符 / 关键字
        if ch.isalpha() or ch == '_':
            start = i
            while i < n and (src[i].isalnum() or src[i] == '_'):
                i += 1
            word = src[start:i]
            kind = KEYWORD if word.upper() in _KEYWORDS else IDENT
            tokens.append(Token(kind, word, start))
            continue

        # 双字符比较符
        if i + 1 < n and src[i:i + 2] in _TWO_CHAR_SYMS:
            tokens.append(Token(SYM, src[i:i + 2], i))
            i += 2
            continue

        if ch in _SINGLE_SYMS:
            tokens.append(Token(SYM, ch, i))
            i += 1
            continue

        raise FormulaSyntaxError(f"无法识别的字符 '{ch}' (位置 {i})")

    return tokens
