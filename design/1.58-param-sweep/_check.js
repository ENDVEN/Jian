/* design/1.58-param-sweep/_check.js · 设计稿自检（2026-09-28 立）
   ─────────────────────────────────────────────────────────────
   为什么需要它：设计稿里塞的是**真 JS 图表**，而"一处抛异常"会让**整段脚本中断 ⇒ 后面所有图都不画**，
   肉眼看不出根因（本轮就因此丢了两轮图）。⇒ **改完设计稿必须真跑一遍**：

       node design/1.58-param-sweep/_check.js

   它做什么：① 用 `__dirname` 自动定位本目录（改目录名也不会失效）；
             ② 逐页抽出所有 id 建 DOM 桩 → 真跑页面内联 <script>（跳过带 src 的）；
             ③ 检查每个 `class="chart"` 容器是否真画出 `<svg>`；④ 兼容性检查 `PS`（v1 命名空间）仍可用。
   出口码：0 = 全绿；1 = 有图没画出来（会点名是哪一页、哪一张）。
   ⚠ 不要把它当"真浏览器"——它不校验视觉效果，只保证"脚本能跑、图真画出来了"。 */
const fs = require('fs');
const path = require('path');

const DIR = __dirname;
const CHART_JS = path.join(DIR, '_charts.js');
const PAGES = ['index.html', 'p2-双栏可折叠.html', 'a-单页研究台.html', 'b-向导分步.html', 'c-三栏分析台.html'];

function makeEl(id) {
  return {
    id, _html: '',
    set innerHTML(v) { this._html = String(v); },
    get innerHTML() { return this._html; }
  };
}

let failed = 0;
const chartSrc = fs.readFileSync(CHART_JS, 'utf8');

for (const page of PAGES) {
  const file = path.join(DIR, page);
  if (!fs.existsSync(file)) { console.log('⚠ 跳过（不存在）：' + page); continue; }
  const html = fs.readFileSync(file, 'utf8');

  const store = {};
  global.window = global;                      // 浏览器里 window 就是全局对象，node 里要显式对齐
  global.document = { getElementById: (id) => (store[id] || (store[id] = makeEl(id))) };

  const chartIds = [];
  const divRe = /<div([^>]*)>/g;
  let m;
  while ((m = divRe.exec(html))) {
    if (/class="chart/.test(m[1])) { const idm = /id="([^"]+)"/.exec(m[1]); if (idm) chartIds.push(idm[1]); }
  }

  try {
    (0, eval)(chartSrc);
    const inlineRe = /<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g;
    let s;
    while ((s = inlineRe.exec(html))) { (0, eval)(s[1]); }
  } catch (e) {
    failed++;
    console.log('❌ ' + page + ' 跑脚本抛异常：' + e.name + ': ' + e.message);
    continue;
  }

  const empty = chartIds.filter((id) => { const e = store[id]; return !(e && /^<svg/.test(e.innerHTML)); });
  if (chartIds.length > 0 && empty.length === 0) {
    console.log('✅ ' + page + '：' + chartIds.length + ' 张图全部画出 SVG（' + chartIds.join(', ') + '）');
  } else {
    failed++;
    console.log('❌ ' + page + '：共 ' + chartIds.length + ' 张图，空的有 ' + empty.length + ' 张 → ' + (empty.join(', ') || '（本页没有图容器）'));
  }
}

try {
  global.window = global;
  global.document = { getElementById: (id) => makeEl(id) };
  (0, eval)(chartSrc);
  global.PS.scatter(makeEl('ps-el'));          // v1 老页面的真实调用方式：传**元素**
  console.log('✅ PS（v1 命名空间）按"传元素"方式仍可用 —— a/b/c 三页不受影响');
} catch (e) { failed++; console.log('❌ PS 命名空间坏了：' + e.message); }

console.log(failed === 0 ? '\n全绿：本目录所有设计稿的图表都正常渲染' : '\n有 ' + failed + ' 处问题（见上）');
process.exit(failed === 0 ? 0 : 1);
