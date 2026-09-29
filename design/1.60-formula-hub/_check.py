# design/1.60-formula-hub/_check.py · 设计稿自检（静态版 · 2026-09-29）
# 本机无 node 时用：py design/1.60-formula-hub/_check.py
# ⚠ 与 _check.js 的分工：node 能【真跑】内联 script + __selftest()；本机没有 JS 引擎
#   （quickjs 轮子编译失败，实测）⇒ 本版做静态检查：① 字体纪律（font-family 与 font: 简写都查）；
#   ② 静态 id 检查；③ JS 括号配对粗检（剥字符串/注释后 () {} [] 计数一致）；④ __selftest 钩子存在；
#   ⑤ index 的四条方案链接有效。装上 node 后请跑 `node _check.js` 拿"真跑"那份证据。
import io
import os
import re
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
PAGES = ['index.html', 'a-双栏管理台.html', 'b-全局浮窗.html', 'c-右侧抽屉.html', 'd-表格密集台.html']
BAD_FONTS = re.compile(r'Consolas|Microsoft YaHei|微软雅黑|SimSun|宋体|Arial|Courier New', re.I)
DECL_RE = re.compile(r'font-family\s*:[^;}"\']*|font\s*:[^;}"\']*', re.I)
SCRIPT_RE = re.compile(r'<script>([\s\S]*?)</script>')
ELID_RE = re.compile(r"el\('([^']+)'\)|getElementById\('([^']+)'\)")
LINK_RE = re.compile(r'href="([abcd]-[^"]+\.html)"')
WANT_LINKS = {'a-双栏管理台.html', 'b-全局浮窗.html', 'c-右侧抽屉.html', 'd-表格密集台.html'}


def strip_js(src):
    """剥掉字符串与注释，供括号配对粗检（够设计稿自检用，不当解析器）。"""
    out = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c in ('"', "'"):
            j = i + 1
            while j < n:
                if src[j] == '\\':
                    j += 2
                    continue
                if src[j] == c:
                    break
                j += 1
            i = j + 1
        elif src.startswith('//', i):
            j = src.find('\n', i)
            i = n if j < 0 else j
        elif src.startswith('/*', i):
            j = src.find('*/', i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def run_page(page):
    """返回 (fail_list, ok_count)。"""
    fails, oks = [], 0
    path = os.path.join(DIR, page)
    print('\n== %s ==' % page)
    if not os.path.exists(path):
        return ['文件不存在'], 0
    html = io.open(path, encoding='utf-8').read()

    hits = [d for d in DECL_RE.findall(html) if BAD_FONTS.search(d)]
    if hits:
        fails.append('专有字体名进样式: ' + hits[0].strip()[:60])
    else:
        oks += 1
        print('  ✓ 字体纪律（含 font: 简写）')

    scripts = SCRIPT_RE.findall(html)
    if not scripts:
        print('  ✓ 无内联脚本（总览页）')
        links = set(LINK_RE.findall(html))
        if WANT_LINKS <= links:
            oks += 1
            print('  ✓ 四条方案链接齐全')
        else:
            fails.append('index 缺方案链接: ' + ', '.join(sorted(WANT_LINKS - links)))
        return fails, oks + 1

    html_ids = set(re.findall(r'id="([^"]+)"', html))
    wanted = set()
    for src in scripts:
        for m in ELID_RE.finditer(src):
            wanted.add(m.group(1) or m.group(2))
    missing = [i for i in wanted if i not in html_ids]
    if missing:
        fails.append('getElementById 引用了不存在的 id: ' + ', '.join(missing))
    else:
        oks += 1
        print('  ✓ 静态 id 检查（%d 个引用全部存在）' % len(wanted))

    for k, src in enumerate(scripts):
        js = strip_js(src)
        balanced = all(js.count(a) == js.count(b) for a, b in (('(', ')'), ('{', '}'), ('[', ']')))
        if balanced:
            oks += 1
            print('  ✓ script#%d 括号配对粗检' % (k + 1))
        else:
            fails.append('script#%d 括号不配对' % (k + 1))
        if '__selftest' in src:
            oks += 1
        elif k == len(scripts) - 1:
            fails.append('缺 __selftest 钩子（无头自检的入口）')
    return fails, oks


def main():
    total_fail, total_ok = [], 0
    for page in PAGES:
        f, o = run_page(page)
        total_fail += ['%s: %s' % (page, x) for x in f]
        total_ok += o
    tail = '%d 项失败' % len(total_fail) if total_fail else '静态检查全部通过（%d 项）' % total_ok
    print('\n===== %s =====' % tail)
    print('(脚本真跑 + selftest 需要 node：node design/1.60-formula-hub/_check.js)')
    for x in total_fail:
        print('  ✗ ' + x)
    sys.exit(1 if total_fail else 0)


if __name__ == '__main__':
    main()
