# -*- coding: utf-8 -*-
"""文档契约自检（秒级、不依赖 Qt）：写完/搬完文档跑一次。

检查项：
  1. `docs/**/*.md`（除 `_TEMPLATE.md`）前 8 行必须有 `status:`；
  2. `docs/plans/README.md` 必须登记 `plans/active/` 下的每一份计划；
  3. 全仓 md 的**相对链接**必须都能打开；
  4. `docs/RULES.md` ≤ 100,000 字符（"能不能一次读完"的硬指标）；
  5. `docs/reference/MODULE_INDEX.md` 与当前代码一致（等价 `gen_codemap.py --check`）。

用法：`py scripts/check_docs.py`（退出码 0 = 全过）
"""
from __future__ import annotations

import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES_LIMIT = 100_000


def rel(p: str) -> str:
    return os.path.relpath(p, ROOT).replace(os.sep, '/')


def md_files():
    for base, dirs, files in os.walk(os.path.join(ROOT, 'docs')):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.'))
        for f in sorted(files):
            if f.endswith('.md'):
                yield os.path.join(base, f)


def check_front_matter():
    bad = []
    for p in md_files():
        if os.path.basename(p) == '_TEMPLATE.md':
            continue
        head = io.open(p, encoding='utf-8', errors='ignore').read().splitlines()[:8]
        if not any(l.strip().startswith('status:') for l in head):
            bad.append(rel(p))
    return bad


def check_plans_registry():
    idx = os.path.join(ROOT, 'docs', 'plans', 'README.md')
    text = io.open(idx, encoding='utf-8').read()
    missing = []
    active_dir = os.path.join(ROOT, 'docs', 'plans', 'active')
    for f in sorted(os.listdir(active_dir)) if os.path.isdir(active_dir) else []:
        if f.endswith('.md') and f not in text:
            missing.append('docs/plans/active/' + f)
    return missing


def check_links():
    bad = []
    for p in md_files():
        text = io.open(p, encoding='utf-8', errors='ignore').read()
        for m in re.finditer(r'\[[^\]]*\]\(([^)#]+)\)', text):
            tgt = m.group(1).strip()
            if tgt.startswith(('http://', 'https://', 'mailto:')):
                continue
            if not os.path.exists(os.path.normpath(os.path.join(os.path.dirname(p), tgt))):
                bad.append('%s -> %s' % (rel(p), tgt))
    return bad


def check_rules_size():
    p = os.path.join(ROOT, 'docs', 'RULES.md')
    n = len(io.open(p, encoding='utf-8').read())
    return n, n <= RULES_LIMIT


def check_module_index():
    sys.path.insert(0, os.path.join(ROOT, 'scripts'))
    try:
        import gen_codemap
    finally:
        sys.path.pop(0)
    out = os.path.join(ROOT, 'docs', 'reference', 'MODULE_INDEX.md')
    if not os.path.exists(out):
        return False, '缺失 docs/reference/MODULE_INDEX.md'
    if io.open(out, encoding='utf-8').read() != gen_codemap.build():
        return False, 'MODULE_INDEX 已过期（跑 py scripts/gen_codemap.py）'
    return True, '与代码一致'


def main() -> int:
    rows = []
    fm = check_front_matter()
    rows.append(('front-matter', not fm, '%d 个文件缺 status' % len(fm) if fm else 'OK'))
    plan = check_plans_registry()
    rows.append(('plans 登记', not plan, '未登记: %s' % plan if plan else 'OK'))
    lk = check_links()
    rows.append(('相对链接', not lk, '%d 处断链: %s' % (len(lk), lk[:3]) if lk else 'OK'))
    n, ok = check_rules_size()
    rows.append(('RULES 体积', ok, '%d 字符（上限 %d）' % (n, RULES_LIMIT)))
    mi, msg = check_module_index()
    rows.append(('MODULE_INDEX', mi, msg))

    width = max(len(k) for k, _, _ in rows)
    for k, ok, msg in rows:
        print('[%s] %-*s %s' % ('OK' if ok else 'FAIL', width, k, msg))
    return 0 if all(ok for _, ok, _ in rows) else 1


if __name__ == '__main__':
    raise SystemExit(main())
