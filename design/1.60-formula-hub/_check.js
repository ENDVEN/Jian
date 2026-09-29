/* design/1.60-formula-hub/_check.js · 设计稿自检（照 1.58 惯例 · 2026-09-29）
   ─────────────────────────────────────────────────────────────
   为什么需要它：设计稿页面里是真 JS（列表/详情/编辑/语法检测），"一处抛异常 ⇒ 后面全部不渲染"，
   肉眼看不出根因。⇒ **改完设计稿必须真跑一遍**：

       node design/1.60-formula-hub/_check.js     （本机无 node 时：py design/1.60-formula-hub/_check.py）

   它做什么：① 用 __dirname 定位本目录；② 逐页抽出内联 <script>（跳过带 src 的），
     在最小 DOM 桩上真跑（getElementById 按 id 建桩、innerHTML 为字符串）；
     ③ 调页面暴露的 window.__selftest()，逐项断言为真；
     ④ 静态 id 检查：脚本里 getElementById('x') 的 x 必须真实出现在 HTML 的 id="x" 里；
     ⑤ 字体纪律：font-family / font: 简写里都不许出现专有字体名（§10-15，堵 1.58 的简写漏检）。
   出口码：0 = 全绿；1 = 有失败（逐条点名）。 */
const fs = require('fs');
const path = require('path');

const DIR = __dirname;
const PAGES = ['index.html', 'a-双栏管理台.html', 'b-全局浮窗.html', 'c-右侧抽屉.html', 'd-表格密集台.html'];
const BAD_FONTS = /Consolas|Microsoft YaHei|微软雅黑|SimSun|宋体|Arial|Courier New/i;

function makeEl(id) {
  return {
    id, _html: '', value: '', checked: false, textContent: '', style: {}, dataset: {},
    set innerHTML(v) { this._html = String(v); },
    get innerHTML() { return this._html; },
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener() {}, removeEventListener() {},
    setAttribute() {}, getAttribute() { return ''; },
    querySelectorAll() { return []; }, querySelector() { return null; },
    focus() {}, click() {}, scrollIntoView() {},
  };
}

let failed = 0;
const bad = (msg) => { failed++; console.log('  ✗ ' + msg); };
const ok = (msg) => console.log('  ✓ ' + msg);

for (const page of PAGES) {
  const file = path.join(DIR, page);
  console.log('\n== ' + page + ' ==');
  if (!fs.existsSync(file)) { bad('文件不存在'); continue; }
  const html = fs.readFileSync(file, 'utf8');

  // ---- ⑤ 字体纪律（整页扫，font-family 与 font: 简写都查）----
  const decls = html.match(/font-family\s*:[^;}"']*|font\s*:[^;}"']*/gi) || [];
  const fontHits = decls.filter((d) => BAD_FONTS.test(d));
  if (fontHits.length) bad('专有字体名进样式：' + fontHits[0].trim().slice(0, 60));
  else ok('字体纪律（含 font: 简写）');

  // ---- ③④ 脚本真跑（index 无内联脚本则跳过）----
  const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
  if (!scripts.length) { ok('无内联脚本（总览页）'); continue; }

  const store = {};
  global.window = global;
  global.document = {
    getElementById: (id) => (store[id] || (store[id] = makeEl(id))),
    querySelectorAll: () => [], querySelector: () => null,
    addEventListener() {}, createElement: () => makeEl('_' + Math.random()),
  };
  global.setTimeout = global.setTimeout || ((fn) => 0);
  global.clearTimeout = global.clearTimeout || (() => 0);

  // ---- ④ 静态 id 检查 ----
  const htmlIds = new Set([...html.matchAll(/id="([^"]+)"/g)].map((m) => m[1]));
  const wanted = new Set();
  for (const src of scripts) {
    for (const m of src.matchAll(/el\('([^']+)'\)|getElementById\('([^']+)'\)/g))
      wanted.add(m[1] || m[2]);
  }
  const missing = [...wanted].filter((id) => !htmlIds.has(id));
  if (missing.length) bad('getElementById 引用了不存在的 id：' + missing.join(', '));
  else ok('静态 id 检查（' + wanted.size + ' 个引用全部存在）');

  // ---- ③ 真跑 + selftest ----
  try {
    for (const src of scripts) (0, eval)(src);
    if (typeof window.__selftest !== 'function') { ok('无 selftest 钩子（只验证脚本能跑）'); }
    else {
      const results = window.__selftest();
      for (const [name, pass] of results) pass ? ok('selftest · ' + name) : bad('selftest · ' + name);
    }
  } catch (e) {
    bad('脚本抛异常：' + e.constructor.name + ': ' + e.message);
  }
}

console.log('\n===== ' + (failed ? failed + ' 项失败' : '全部通过') + ' =====');
process.exit(failed ? 1 : 0);
