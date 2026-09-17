/* ============================================================
   design/1.24-desk-sidebar-ui/shell.js
   四套样板共用的外壳脚本：
     ① 用**固定种子**生成一段示意行情 → 画成 K 线 / 量 / MACD（四套样板图形完全一致，
        这样对照侧边栏时不会因为图表不同而分心）；
     ② 图标轨切页（点图标 → 显示对应的 [data-page]，并高亮）；
     ③ 折起 / 展开面板（与 App 的真实行为一致：面板消失、宽度还给图表）；
     ④ 开关、分段控件的通用点击行为。
   ⚠ 这里的数据只用于"画个形状给眼睛看"，**不是真实行情**，也不进 App 任何逻辑。
   ============================================================ */
(function () {
  'use strict';

  /* ---------- ① 示意行情（固定种子 ⇒ 每次打开形状一致） ---------- */
  function lcg(seed) {
    let s = seed >>> 0;
    return function () { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
  }

  function genSeries(seed, base, n) {
    const r = lcg(seed);
    const out = [];
    let price = base;
    for (let i = 0; i < n; i++) {
      const drift = Math.sin(i / 16) * 0.011 + Math.sin(i / 5.1) * 0.0055;
      const shock = (r() - 0.5) * 0.018;
      const open = price;
      const close = open * (1 + drift + shock);
      const high = Math.max(open, close) * (1 + r() * 0.007);
      const low = Math.min(open, close) * (1 - r() * 0.007);
      out.push({ open, high, low, close, vol: (0.45 + r()) * 1e6 });
    }
    return out;
  }

  function svg(tag, attrs) {
    const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const k in attrs) el.setAttribute(k, attrs[k]);
    return el;
  }

  function ext(arr, key) {
    let lo = Infinity, hi = -Infinity;
    arr.forEach(d => { lo = Math.min(lo, d[key]); hi = Math.max(hi, d[key]); });
    return [lo, hi];
  }

  const GREEN = '#4CAF50', RED = '#F44336', GRID = '#EEF1F6', AXIS = '#B4BECB';

  /* ★ 纵轴"固定左槽" —— 四张窗格共用同一个 PAD_L，刻度文字一律**右对齐**贴在同一位置。
     这就是"副图变多以后左边坐标轴缩进不一致"的修法示意：
     长标签（成交量 3,120,400）与短标签（MACD -0.05）都从同一条右边线往左排，
     所以每张窗格的绘图区左边缘完全一致（App 侧对应 AxisItem 固定宽度）。 */
  const PAD_L = 64;

  function drawMain(el, data, opts) {
    opts = opts || {};
    const W = el.clientWidth || 900, H = el.clientHeight || 320, padL = PAD_L, padR = 8, padT = 8, padB = 4;
    const iw = W - padL - padR, ih = H - padT - padB;
    const lo = Math.min.apply(null, data.map(d => d.low));
    const hi = Math.max.apply(null, data.map(d => d.high));
    const span = (hi - lo) || 1;
    const x = i => padL + (i + 0.5) * iw / data.length;
    const y = v => padT + ih - (v - lo) / span * ih;
    const g = svg('g', {});

    // 网格 + 价格刻度
    for (let k = 0; k <= 4; k++) {
      const v = lo + span * k / 4, yy = y(v);
      g.appendChild(svg('line', { x1: padL, x2: W - padR, y1: yy, y2: yy, stroke: GRID }));
      const t = svg('text', { x: padL - 6, y: yy + 3.5, fill: AXIS, 'font-size': 10, 'text-anchor': 'end' });
      t.textContent = v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      g.appendChild(t);
    }
    // K 线（App 口径：收 >= 开 = 绿）
    const bw = Math.max(1.6, iw / data.length * 0.62);
    data.forEach((d, i) => {
      const up = d.close >= d.open;
      const c = up ? GREEN : RED;
      const cx = x(i);
      g.appendChild(svg('line', { x1: cx, x2: cx, y1: y(d.high), y2: y(d.low), stroke: c, 'stroke-width': Math.min(1.4, bw / 2) }));
      const y1 = y(Math.max(d.open, d.close)), y2 = y(Math.min(d.open, d.close));
      g.appendChild(svg('rect', { x: cx - bw / 2, y: y1, width: bw, height: Math.max(1.1, y2 - y1), fill: c }));
    });
    // MA5 / MA20
    if (opts.ma) {
      [[5, '#1976D2'], [20, '#E65100']].forEach(function (pair) {
        const n = pair[0], color = pair[1], pts = [];
        for (let i = 0; i < data.length; i++) {
          if (i < n - 1) continue;
          let s = 0; for (let j = i - n + 1; j <= i; j++) s += data[j].close;
          pts.push(x(i) + ',' + y(s / n));
        }
        g.appendChild(svg('polyline', { points: pts.join(' '), fill: 'none', stroke: color, 'stroke-width': 1.3, opacity: .85 }));
      });
    }
    // 布林带（上下轨 + 浅填充）
    if (opts.boll) {
      const upper = [], lower = [];
      for (let i = 0; i < data.length; i++) {
        if (i < 19) continue;
        const win = data.slice(i - 19, i + 1).map(d => d.close);
        const m = win.reduce((a, b) => a + b, 0) / win.length;
        const sd = Math.sqrt(win.reduce((a, b) => a + (b - m) * (b - m), 0) / win.length);
        upper.push(x(i) + ',' + y(m + 2 * sd));
        lower.push(x(i) + ',' + y(m - 2 * sd));
      }
      if (upper.length) {
        const poly = upper.concat(lower.slice().reverse()).join(' ');
        g.appendChild(svg('polygon', { points: poly, fill: '#1976D2', opacity: .06 }));
        g.appendChild(svg('polyline', { points: upper.join(' '), fill: 'none', stroke: '#7E9BC4', 'stroke-width': 1, 'stroke-dasharray': '4 3' }));
        g.appendChild(svg('polyline', { points: lower.join(' '), fill: 'none', stroke: '#7E9BC4', 'stroke-width': 1, 'stroke-dasharray': '4 3' }));
      }
    }
    el.appendChild(g);
  }

  function drawVol(el, data) {
    const W = el.clientWidth || 900, H = el.clientHeight || 70, padL = PAD_L, padR = 8, padT = 6, padB = 2;
    const iw = W - padL - padR, ih = H - padT - padB;
    const hi = ext(data, 'vol')[1] || 1;
    const bw = Math.max(1.6, iw / data.length * 0.62);
    const g = svg('g', {});
    // 刻度：长数字（3,120,400）—— 用来对照"最长的标签也不影响左边缘"
    [hi, hi / 2].forEach(function (v) {
      const yy = padT + ih - v / hi * ih;
      g.appendChild(svg('line', { x1: padL, x2: W - padR, y1: yy, y2: yy, stroke: GRID }));
      const t = svg('text', { x: padL - 6, y: yy + 3.5, fill: AXIS, 'font-size': 10, 'text-anchor': 'end' });
      t.textContent = Math.round(v).toLocaleString('en-US');
      g.appendChild(t);
    });
    data.forEach((d, i) => {
      const up = d.close >= d.open, c = up ? GREEN : RED;
      const h = d.vol / hi * ih;
      g.appendChild(svg('rect', { x: padL + (i + 0.5) * iw / data.length - bw / 2, y: padT + ih - h, width: bw, height: Math.max(1, h), fill: c, opacity: .8 }));
    });
    const t = svg('text', { x: padL - 6, y: padT + 9, fill: AXIS, 'font-size': 10, 'text-anchor': 'end' });
    t.textContent = '量';
    g.appendChild(t);
    el.appendChild(g);
  }

  function drawMacd(el, data) {
    const W = el.clientWidth || 900, H = el.clientHeight || 80, padL = PAD_L, padR = 8, padT = 6, padB = 2;
    const iw = W - padL - padR, ih = H - padT - padB;
    const ema = (n) => {
      const k = 2 / (n + 1), out = [data[0].close];
      for (let i = 1; i < data.length; i++) out.push(data[i].close * k + out[i - 1] * (1 - k));
      return out;
    };
    const e12 = ema(12), e26 = ema(26);
    const dif = e12.map((v, i) => v - e26[i]);
    const dea = (function () { const k = 2 / 10, o = [dif[0]]; for (let i = 1; i < dif.length; i++) o.push(dif[i] * k + o[i - 1] * (1 - k)); return o; })();
    const macd = dif.map((v, i) => (v - dea[i]) * 2);
    let lo = 0, hi = 0;
    dif.concat(dea, macd).forEach(v => { lo = Math.min(lo, v); hi = Math.max(hi, v); });
    const span = (hi - lo) || 1;
    const y = v => padT + ih - (v - lo) / span * ih;
    const g = svg('g', {});
    g.appendChild(svg('line', { x1: padL, x2: W - padR, y1: y(0), y2: y(0), stroke: GRID }));
    // 刻度：短数字（-0.05 / 0.00 / 0.05）—— 与量柱那张的 9 位长数字共用同一个右对齐左槽
    [hi, 0, lo].forEach(function (v) {
      const yy = y(v);
      const t = svg('text', { x: padL - 6, y: yy + 3.5, fill: AXIS, 'font-size': 10, 'text-anchor': 'end' });
      t.textContent = v.toFixed(2);
      g.appendChild(t);
    });
    const bw = Math.max(1.4, iw / data.length * 0.5);
    macd.forEach((v, i) => {
      const cx = padL + (i + 0.5) * iw / data.length;
      const yy = y(v);
      g.appendChild(svg('rect', { x: cx - bw / 2, y: Math.min(yy, y(0)), width: bw, height: Math.max(1, Math.abs(yy - y(0))), fill: v >= 0 ? GREEN : RED, opacity: .7 }));
    });
    [[dif, '#1976D2'], [dea, '#E65100']].forEach(function (pair) {
      g.appendChild(svg('polyline', { points: pair[0].map((v, i) => (padL + (i + 0.5) * iw / data.length) + ',' + y(v)).join(' '), fill: 'none', stroke: pair[1], 'stroke-width': 1.2 }));
    });
    const t = svg('text', { x: padL - 6, y: padT + 9, fill: AXIS, 'font-size': 10, 'text-anchor': 'end' });
    t.textContent = 'MACD';
    g.appendChild(t);
    el.appendChild(g);
  }

  function paintChart() {
    const main = document.getElementById('chartMain');
    if (!main) return;
    const data = genSeries(20260917, 1480, 120);
    [['chartMain', drawMain], ['chartVol', drawVol], ['chartMacd', drawMacd]].forEach(function (pair) {
      const el = document.getElementById(pair[0]);
      if (!el) return;
      el.innerHTML = '';
      pair[1](el, data, pair[0] === 'chartMain' ? { ma: true } : {});
    });
  }

  /* ---------- ② 图标轨切页 ----------
     ⚠ 这里同时登记 v1 的键（formula / layer）与 A v2 的键（lib）——
        A v2 把「公式与配方 + 主副图叠加」整合成了「配方库(lib)」并删掉了图层页，
        但 b/c/d 三套样板仍是 v1 的 5 页，共用本文件 ⇒ 两套键都要认识。 */
  const PAGE_TITLES = {
    watch: '自选股', formula: '公式与配方', layer: '主图叠加 / 附图',
    lib: '配方库', anno: '标注工具', data: '数据与口径'
  };
  const PAGE_SUB = {
    watch: '双击即切换当前标的', formula: '函数内容的编辑与资产化', layer: '显示开关（真源 = 这些复选框）',
    lib: '公式都在这：按主图 / 副图分类，点一下即应用',
    anno: '画线都在这（按标的 + 周期保存）', data: '现在看的是哪一份数据'
  };

  function showPage(key) {
    document.querySelectorAll('.rail button[data-key]').forEach(b => b.classList.toggle('on', b.dataset.key === key));
    document.querySelectorAll('[data-page]').forEach(p => p.classList.toggle('on', p.dataset.page === key));
    const t = document.getElementById('pageTitle'), s = document.getElementById('pageSub');
    if (t) t.textContent = PAGE_TITLES[key] || '';
    if (s) s.textContent = PAGE_SUB[key] || '';
    const panel = document.getElementById('panel');
    if (panel) panel.dataset.cur = key;
    // 各样板可选钩子：例如"下钻返回列表页首"
    if (typeof window.__onRail === 'function') window.__onRail(key);
  }

  /* ---------- ③ 折起 / 展开 ---------- */
  function toggleFold() {
    const side = document.getElementById('side');
    if (!side) return;
    side.classList.toggle('collapsed');
    const b = document.getElementById('foldBtn');
    if (b) b.textContent = side.classList.contains('collapsed') ? '⇥' : '⇤';
  }

  /* ---------- ④ 通用交互 ---------- */
  function bindGeneric() {
    // 分段控件（周期 / 复权 / 分钟 / 画线工具）
    document.querySelectorAll('.seg').forEach(function (seg) {
      seg.addEventListener('click', function (e) {
        const b = e.target.closest('button');
        if (!b) return;
        if (seg.dataset.multi !== '1') seg.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
        else b.classList.toggle('on');
        if (seg.dataset.onclick === 'minute' && seg.querySelector('button.on')) {
          const mg = document.getElementById('segMinute');
          if (mg) mg.classList.add('show');
        }
        const anchor = seg.dataset.anchor;
        if (anchor) {
          const t = document.getElementById(anchor);
          if (t) { t.classList.add('flash'); setTimeout(() => t.classList.remove('flash'), 900); }
        }
      });
    });
    // 开关
    document.querySelectorAll('.sw').forEach(function (s) {
      s.addEventListener('click', function () { s.classList.toggle('on'); });
    });
    // 折起
    const f = document.getElementById('foldBtn');
    if (f) f.addEventListener('click', toggleFold);
    // 列表选中
    document.querySelectorAll('.pickable li').forEach(function (li) {
      li.addEventListener('click', function () {
        li.parentElement.querySelectorAll('li').forEach(x => x.classList.toggle('on', x === li));
      });
    });
    // 页面级切换按钮（下钻等，用 data-goto）
    document.querySelectorAll('[data-goto]').forEach(function (el) {
      el.addEventListener('click', function (e) {
        e.stopPropagation();
        if (typeof window.__goto === 'function') window.__goto(el.dataset.goto, el);
      });
    });
  }

  window.DeskShell = { showPage: showPage, toggleFold: toggleFold, paintChart: paintChart };

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.rail button[data-key]').forEach(function (b) {
      b.addEventListener('click', function () { showPage(b.dataset.key); });
    });
    bindGeneric();
    paintChart();
    const first = document.querySelector('.rail button[data-key]');
    if (first) showPage(first.dataset.key);
  });
  window.addEventListener('resize', function () { paintChart(); });
})();
