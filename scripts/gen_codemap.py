# -*- coding: utf-8 -*-
"""生成 `docs/reference/MODULE_INDEX.md`：**每个 .py 一行**（路径 · 一句话 · 公共符号 · 行数）。

【为什么要有它】手工维护的 `CODEMAP.md` 会漂移；这份是**自动生成**的"文件清单"，
只回答"哪个文件干什么"，不写设计理由（理由在 CODEMAP / RULES）。

用法：
    py scripts/gen_codemap.py            # 写入文件
    py scripts/gen_codemap.py --check    # 只校验：文件是否与当前代码一致（CI/自检用）
"""
from __future__ import annotations

import ast
import io
import os
import sys

def _force_utf8_stdout() -> None:
    """★2.02：**不依赖环境**地把 stdout 钉成 UTF-8。

    为什么：CI（windows-latest）控制台默认 cp1252，脚本里一句中文 print 就会
    `UnicodeEncodeError` ⇒ 退出码 1，看起来像"检查没通过"，其实是编码事故。
    这里用 `reconfigure` 兜底；老解释器没有该方法就跳过（不抛）。
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                      # noqa: BLE001 —— 兜底失败不影响主流程
        pass


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'docs', 'reference', 'MODULE_INDEX.md')
SKIP_DIRS = {'.git', '__pycache__', '.idea', '.vscode', 'design', 'samples', 'build', 'dist'}


def describe(path: str) -> tuple:
    src = io.open(path, encoding='utf-8', errors='ignore').read()
    lines = sum(1 for l in src.splitlines() if l.strip())
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return ('(语法错误，无法解析)', 0, lines)
    doc = (ast.get_docstring(tree) or '').strip().splitlines()
    first = doc[0].strip() if doc else ''
    pub = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            pub += 1
    return (first or '—', pub, lines)


def build() -> str:
    rows = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith('.'))
        for f in sorted(files):
            if not f.endswith('.py'):
                continue
            full = os.path.join(base, f)
            rel = os.path.relpath(full, ROOT).replace(os.sep, '/')
            desc, pub, lines = describe(full)
            desc = desc.replace('|', '/')[:88]
            rows.append((rel, desc, pub, lines))
    rows.sort()
    head = ('---\nstatus: reference\ntopic: 逐文件清单（自动生成，勿手改）\n'
            'read_when: 想知道"哪个文件干什么"（先看这里，再看 CODEMAP）\n'
            'skip_if: 已知文件位置\nverified: auto\n---\n\n'
            '# 模块清单（自动生成）\n\n'
            '> 由 `scripts/gen_codemap.py` 生成；**只写"文件干什么"**，设计理由在 `CODEMAP.md` / `docs/RULES.md`。\n'
            '> 改了文件就重跑：`py scripts/gen_codemap.py`；校验：`py scripts/gen_codemap.py --check`。\n\n'
            '| 文件 | 一句话 | 顶层符号 | 行数 |\n|---|---|---|---|\n')
    body = ''.join('| `%s` | %s | %d | %d |\n' % r for r in rows)
    return head + body + '\n> 共 %d 个 .py 文件。\n' % len(rows)


def main() -> int:
    _force_utf8_stdout()
    text = build()
    if '--check' in sys.argv:
        if not os.path.exists(OUT):
            print('缺失', OUT)
            return 1
        cur = io.open(OUT, encoding='utf-8').read()
        if cur != text:
            print('MODULE_INDEX 已过期 —— 运行 `py scripts/gen_codemap.py` 重新生成')
            return 1
        print('MODULE_INDEX 与代码一致')
        return 0
    io.open(OUT, 'w', encoding='utf-8', newline='').write(text)
    print('已写入', os.path.relpath(OUT, ROOT), len(text), '字符')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
