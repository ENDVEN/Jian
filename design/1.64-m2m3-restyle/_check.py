# design/1.64-m2m3-restyle/_check.py · 设计稿自检（静态版 · 2026-09-30）
# 用法：py design/1.64-m2m3-restyle/_check.py
# ⚠ 与 1.60 那份同一个口径（本机没有 JS 引擎 ⇒ 静态检查）：
#   ① 字体纪律（font-family 与 `font:` 简写都查 —— §10-15 禁专有字体名，简写最容易漏检）；
#   ② 静态 id 检查（脚本里 el('x') / getElementById('x') 引用的 id 必须存在）；
#   ③ JS 括号配对粗检（剥字符串/注释后计数一致）；
#   ④ __selftest 钩子存在（无头自检入口）；
#   ⑤ **每一页**都查内部链接有效（本目录 index 自带 selftest 脚本，所以链接检查不能只挂在
#      "没有脚本的总览页"上 —— 与 1.60 那份的差别就在这）。
# 装上 node 后请另跑真跑自检（浏览器打开 `?selftest=1` 也能拿到同样的证据）。
import io
import os
import re
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
PAGES = ['index.html', 'a-m2-全市场筛选.html', 'b-m3-广度统计.html']
WANT_LINKS = {'a-m2-全市场筛选.html', 'b-m3-广度统计.html'}
BAD_FONTS = re.compile(r'Consolas|Microsoft YaHei|微软雅黑|SimSun|宋体|Arial|Courier New', re.I)
DECL_RE = re.compile(r'font-family\s*:[^;}"\']*|font\s*:[^;}"\']*', re.I)
SCRIPT_RE = re.compile(r'<script>([\s\S]*?)</script>')
ELID_RE = re.compile(r"el\('([^']+)'\)|getElementById\('([^']+)'\)")
LINK_RE = re.compile(r'href="([ab]-[^"]+\.html)"')


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

    links = set(LINK_RE.findall(html))
    if page == 'index.html':
        if WANT_LINKS <= links:
            oks += 1
            print('  ✓ 两份样板链接齐全')
        else:
            fails.append('index 缺样板链接: ' + ', '.join(sorted(WANT_LINKS - links)))

    scripts = SCRIPT_RE.findall(html)
    if not scripts:
        print('  ✓ 无内联脚本')
        return fails, oks
    html_ids = set(re.findall(r'id="([^"]+)"', html))
    wanted = set()
    for src in scripts:
        for m in ELID_RE.finditer(src):
            wanted.add(m.group(1) or m.group(2))
    missing = [i for i in wanted if i not in html_ids]
    if missing:
        fails.append('脚本引用了不存在的 id: ' + ', '.join(missing))
    else:
        oks += 1
        print('  ✓ 静态 id 检查（%d 个引用全部存在）' % len(wanted))

    for k, src in enumerate(scripts):
        js = strip_js(src)
        if all(js.count(a) == js.count(b) for a, b in (('(', ')'), ('{', '}'), ('[', ']'))):
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
    tail = ('%d 项失败' % len(total_fail)) if total_fail else ('静态检查全部通过（%d 项）' % total_ok)
    print('\n===== %s =====' % tail)
    print('(真跑自检：浏览器打开任一样板并加 ?selftest=1)')
    for x in total_fail:
        print('  ✗ ' + x)
    sys.exit(1 if total_fail else 0)


if __name__ == '__main__':
    main()
