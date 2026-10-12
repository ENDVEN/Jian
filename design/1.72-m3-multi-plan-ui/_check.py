# -*- coding: utf-8 -*-
"""设计稿自检（`python design/1.72-m3-multi-plan-ui/_check.py`，零依赖、离线可跑）。

查四件事（都是"稿子会不会让人误读"的硬条件）：
  ① 五页都在；② 没有残留的 markdown 星号（HTML 里会原样显示 `**`）；
  ③ 每页都有「设计稿 · 未实现」标识 + 「示意数据」声明（**不许**让人以为是真实统计）；
  ④ 主图 SVG 的元素数在合理区间（既不是空图，也不是把整份数据塞进一个属性）。
"""
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))

PAGES = ["index.html", "a-多方案叠加.html", "b-多行小图.html",
         "c-事件对齐图.html", "d-K线色带与关系卡.html", "e-选图规则.html"]

fail = []


def check(name, ok, extra=""):
    print(f"  [{'OK' if ok else '!!'}] {name}{('  ' + extra) if extra else ''}")
    if not ok:
        fail.append(name)


print("== 设计稿自检 ==")
for page in PAGES:
    path = os.path.join(HERE, page)
    if not os.path.exists(path):
        check(f"{page} 存在", False)
        continue
    html = io.open(path, encoding="utf-8").read()
    check(f"{page} 存在且非空（{len(html)} 字符）", len(html) > 800)
    check(f"{page} 无残留 markdown 星号", "**" not in html)
    check(f"{page} 带「设计稿 · 未实现」标识", "设计稿 · 未实现" in html)
    if page != "index.html":
        check(f"{page} 有「示意数据」声明（不许被当成真实统计）", "示意数据" in html)
    svgs = re.findall(r"<svg[\s\S]*?</svg>", html)
    check(f"{page} 图形数量合理（{len(svgs)} 个 svg）",
          (1 <= len(svgs) <= 12) if page != "index.html" else len(svgs) == 0)
    for i, s in enumerate(svgs):
        n_poly = len(re.findall(r"<polyline|<polygon|<rect|<line", s))
        check(f"{page} svg#{i + 1} 图元数合理（{n_poly}）", 3 < n_poly < 8000)

for f in ("_style.css", "README.md"):
    check(f"{f} 存在", os.path.exists(os.path.join(HERE, f)))

print(f"\n===== 通过 {len(PAGES) + 8 + 4 - len(fail)} · 失败 {len(fail)} =====")
for f in fail:
    print("  FAIL:", f)
sys.exit(1 if fail else 0)
