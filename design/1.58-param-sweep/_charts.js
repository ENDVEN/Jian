/* design/1.58-param-sweep/_charts.js —— 图表生成器（无依赖、确定性伪随机 ⇒ 每次打开一模一样）
   版本：v1 = 四张分析图（scatter / heat / neighbors / rollIC）· v3 = 追加两张（regimeTimeline / tradeHist，含紧凑版）
        v4 = 修两个"整段脚本中断 ⇒ 图全不画"的 bug（`el(id)` 未定义；v1 四图收元素不收 id）
   自检：改完本文件请跑 `node design/1.58-param-sweep/_check.js`（别靠肉眼看）
   用法：<div class="chart" id="x"></div><script>PS.scatter('x')</script>
   这些都是"示意数据"，不是真实回测结果；真实实现里数据来自 core/param_sweep 的结果矩阵。 */
(function (w) {
  'use strict';

  const C = {axis: '#C9D3E0', grid: '#EEF2F7', text: '#616B7A', dim: '#8A94A6',
             pt: '#7C8AA0', hot: '#E65100', ok: '#2E7D32', danger: '#C62828', accent: '#1976D2'};

  function rnd(seed) {                 // 确定性伪随机（LCG）
    let s = seed || 20260927;
    return function () { s = (s * 1103515245 + 12345) % 2147483648; return s / 2147483648; };
  }
  function box(r, mu, sd) {            // 近似正态（12 均匀求和）
    let t = 0; for (let i = 0; i < 12; i++) t += r(); return mu + (t - 6) * sd;
  }
  function svg(W, H, inner) {
    return `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">${inner}</svg>`;
  }
  function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;'); }

  /* ============ ① 散点：样本内 × 样本外（含"冠军崩塌"标注） ============ */
  function scatter(el, opt) {
    const o = opt || {}, W = 620, H = 340, L = 56, R = 14, T = 22, B = 42;
    const x0 = -5, x1 = 10.5, y0 = -5.6, y1 = 3.2;
    const X = v => L + (v - x0) / (x1 - x0) * (W - L - R);
    const Y = v => T + (y1 - v) / (y1 - y0) * (H - T - B);
    const r = rnd(o.seed || 7);
    let s = '';

    // 网格与轴
    for (let v = -5; v <= 10; v += 2.5) {
      s += `<line x1="${X(v)}" y1="${T}" x2="${X(v)}" y2="${H - B}" stroke="${C.grid}"/>`;
      s += `<text x="${X(v)}" y="${H - B + 15}" fill="${C.dim}" font-size="10.5" text-anchor="middle">${v}</text>`;
    }
    for (let v = -5; v <= 3; v += 1) {
      s += `<line x1="${L}" y1="${Y(v)}" x2="${W - R}" y2="${Y(v)}" stroke="${C.grid}"/>`;
      s += `<text x="${L - 8}" y="${Y(v) + 3.5}" fill="${C.dim}" font-size="10.5" text-anchor="end">${v}</text>`;
    }
    s += `<line x1="${L}" y1="${Y(0)}" x2="${W - R}" y2="${Y(0)}" stroke="${C.axis}" stroke-width="1.2"/>`;
    s += `<line x1="${X(0)}" y1="${T}" x2="${X(0)}" y2="${H - B}" stroke="${C.axis}" stroke-width="1.2"/>`;

    // 稳健平台区（真正的推荐区：IS 中上 + OOS 不塌）
    s += `<rect x="${X(2.2)}" y="${Y(2.4)}" width="${X(6.2) - X(2.2)}" height="${Y(0) - Y(2.4)}"
            fill="#2E7D32" fill-opacity="0.07" stroke="${C.ok}" stroke-dasharray="5 4" rx="8"/>`;
    s += `<text x="${X(4.2)}" y="${Y(2.4) - 7}" fill="${C.ok}" font-size="11" text-anchor="middle"
            font-weight="600">稳健平台区：邻域高且不塌（选参看这里）</text>`;

    // 324 个参数组合（示意：弱正相关 + 厚噪声 = 你那张图的样子）
    const pts = [];
    for (let i = 0; i < 323; i++) {
      const is = Math.min(9.0, Math.max(-4.5, box(r, 4.2, 2.05)));
      const oos = 0.12 * is + box(r, 0.25, 1.15);
      pts.push([is, Math.min(2.9, Math.max(-5.2, oos))]);
    }
    pts.push([9.5, 0.4]);                                   // 样本内冠军（真实考场只剩 0.4%）
    pts.forEach(p => {
      s += `<circle cx="${X(p[0]).toFixed(1)}" cy="${Y(p[1]).toFixed(1)}" r="2.7"
              fill="${C.pt}" fill-opacity="0.55"/>`;
    });

    // 冠军 + 崩塌标注
    s += `<line x1="${X(9.5)}" y1="${Y(0.4)}" x2="${X(7.4)}" y2="${Y(2.55)}"
            stroke="${C.hot}" stroke-width="1.6" stroke-dasharray="4 3"/>`;
    s += `<circle cx="${X(9.5)}" cy="${Y(0.4)}" r="5.4" fill="${C.hot}"/>`;
    s += `<text x="${X(7.3)}" y="${Y(2.55) - 8}" fill="${C.hot}" font-size="11.5" font-weight="700"
            text-anchor="end">样本内冠军 MA(7/34)：9.5% → 样本外只剩 0.4%</text>`;
    s += `<text x="${X(7.3)}" y="${Y(2.55) + 6}" fill="${C.hot}" font-size="11" text-anchor="end">
            这不是策略坏了，是"324 次试验挑最高分"必然挑到运气最好的那个</text>`;

    // 中位线（看样本内排名是否有预测力）
    s += `<line x1="${L}" y1="${Y(0.85)}" x2="${W - R}" y2="${Y(0.85)}" stroke="${C.dim}"
            stroke-dasharray="3 4"/>`;
    s += `<line x1="${X(4.2)}" y1="${T}" x2="${X(4.2)}" y2="${H - B}" stroke="${C.dim}"
            stroke-dasharray="3 4"/>`;

    s += `<text x="${L + 8}" y="${T + 14}" fill="${C.danger}" font-size="12.5" font-weight="700">
            Rank IC = 0.12 —— 样本内排名对样本外几乎没有预测力</text>`;
    s += `<text x="${(W + L) / 2}" y="${H - 8}" fill="${C.text}" font-size="11.5" text-anchor="middle">
            样本内年化（%）</text>`;
    s += `<text x="14" y="${(H + T) / 2}" fill="${C.text}" font-size="11.5"
            transform="rotate(-90 14 ${(H + T) / 2})" text-anchor="middle">样本外年化（%）</text>`;

    el.innerHTML = svg(W, H, s);
  }

  /* ============ ② 参数热力图：找"平台"，别看"尖峰" ============ */
  function heat(el, opt) {
    const o = opt || {}, rows = o.rows || 8, cols = o.cols || 8;
    const cell = 40, L = 52, T = 26, W = L + cols * cell + 46, H = T + rows * cell + 44;
    const r = rnd(o.seed || 11);
    const val = [], maxV = 9.5;
    let s = '';
    const ns = [], ms = [];
    for (let c = 0; c < cols; c++) ns.push(3 + c * 4);       // 短窗 n：3,7,11…
    for (let i = 0; i < rows; i++) ms.push(12 + i * 5);      // 长窗 m：12,17…
    for (let i = 0; i < rows; i++) {
      val.push([]);
      for (let c = 0; c < cols; c++) {
        const inPlateau = (i >= 2 && i <= 5) && (c >= 1 && c <= 4);
        let v = inPlateau ? 1.1 + r() * 0.9 : 0.15 + r() * 0.6;
        if (r() < 0.12) v = -0.4 - r() * 0.7;
        val[i].push(v);
      }
    }
    val[6][6] = maxV;                                        // 尖峰（样本内冠军）
    // 色阶用**蓝色**（不用红/绿）：避开 A 股"红涨绿跌"的语义冲突，只表达"数值大小"
    // 灰 = 负年化（单独一档，让"亏钱的参数"一眼可辨）
    const col = v => {
      if (v < 0) return '#D8DEE8';
      const t = Math.min(1, v / maxV);
      return `rgb(${Math.round(232 - t * 206)},${Math.round(240 - t * 126)},${Math.round(250 - t * 14)})`;
    };
    for (let i = 0; i < rows; i++) for (let c = 0; c < cols; c++) {
      const x = L + c * cell, y = T + i * cell, v = val[i][c];
      s += `<rect x="${x}" y="${y}" width="${cell - 1}" height="${cell - 1}" rx="3" fill="${col(v)}">
              <title>n=${ns[c]}, m=${ms[i]} ⇒ 年化 ${v.toFixed(2)}%</title></rect>`;
    }
    // 平台圈 + 尖峰圈
    s += `<rect x="${L + 1 * cell - 4}" y="${T + 2 * cell - 4}" width="${4 * cell + 7}"
            height="${4 * cell + 7}" rx="10" fill="none" stroke="${C.ok}" stroke-width="2"
            stroke-dasharray="6 4"/>`;
    s += `<text x="${L + 1 * cell}" y="${T + 2 * cell - 8}" fill="${C.ok}" font-size="11"
            font-weight="700">平台：一整片都不错（选这里）</text>`;
    s += `<circle cx="${L + 6 * cell + cell / 2 - 0.5}" cy="${T + 6 * cell + cell / 2 - 0.5}" r="16"
            fill="none" stroke="${C.hot}" stroke-width="2.2"/>`;
    s += `<text x="${L + 6 * cell - 6}" y="${T + 6 * cell + cell + 14}" fill="${C.hot}"
            font-size="11" font-weight="700">尖峰 9.5%：邻居全塌 ⇒ 噪声</text>`;
    // 轴标
    for (let c = 0; c < cols; c++)
      s += `<text x="${L + c * cell + cell / 2}" y="${T - 8}" fill="${C.dim}" font-size="10.5"
              text-anchor="middle">${ns[c]}</text>`;
    for (let i = 0; i < rows; i++)
      s += `<text x="${L - 8}" y="${T + i * cell + cell / 2 + 3.5}" fill="${C.dim}" font-size="10.5"
              text-anchor="end">${ms[i]}</text>`;
    s += `<text x="${L + cols * cell / 2}" y="${H - 20}" fill="${C.text}" font-size="11.5"
            text-anchor="middle">参数 n（短窗）</text>`;
    s += `<text x="14" y="${T + rows * cell / 2}" fill="${C.text}" font-size="11.5"
            transform="rotate(-90 14 ${T + rows * cell / 2})" text-anchor="middle">参数 m（长窗）</text>`;
    // 色标
    for (let k = 0; k < 8; k++)
      s += `<rect x="${L + cols * cell + 12}" y="${T + k * 16}" width="12" height="16"
              fill="${col(maxV * (1 - k / 7.5))}"/>`;
    s += `<text x="${L + cols * cell + 12}" y="${T - 6}" fill="${C.dim}" font-size="10">年化%</text>`;
    s += `<text x="${L + cols * cell + 12}" y="${T + 8 * 16 + 12}" fill="${C.dim}" font-size="10">0</text>`;

    el.innerHTML = svg(W, H, s);
  }

  /* ============ ③ 邻域稳健条形：真正的排序键 ============ */
  function neighbors(el, opt) {
    const o = opt || {};
    const data = o.data || [
      {k: 'MA(11/41)', mean: 1.42, worst: 0.88}, {k: 'MA(15/45)', mean: 1.31, worst: 0.72},
      {k: 'MA(7/33)', mean: 1.18, worst: 0.64}, {k: 'MA(11/57)', mean: 1.05, worst: 0.41},
      {k: 'MA(15/33)', mean: 0.94, worst: 0.12}, {k: 'MA(19/41)', mean: 0.71, worst: -0.20},
      {k: 'MA(3/17)', mean: 0.63, worst: -0.55}, {k: 'MA(23/61)', mean: 0.38, worst: -0.31},
      {k: 'MA(7/34)', mean: 0.12, worst: -1.10, hot: true},
    ];
    const rowH = 26, L = 92, R = 62, W = 520, H = data.length * rowH + 40;
    const maxV = 1.5, minV = -0.6;
    const X = v => L + (v - minV) / (maxV - minV) * (W - L - R);
    let s = '';
    s += `<line x1="${X(0)}" y1="20" x2="${X(0)}" y2="${H - 18}" stroke="${C.axis}"/>`;
    data.forEach((d, i) => {
      const y = 22 + i * rowH, top3 = i < 3;
      s += `<text x="${L - 10}" y="${y + 14}" fill="${top3 ? C.text : C.text}" font-size="11.5"
              text-anchor="end" font-weight="${top3 ? 700 : 400}">${esc(d.k)}</text>`;
      s += `<rect x="${X(Math.min(0, d.mean))}" y="${y + 3}" width="${Math.abs(X(d.mean) - X(0))}"
              height="13" rx="3" fill="${d.hot ? '#FBE3D6' : (top3 ? '#D6E8FA' : '#EDF2F8')}"/>`;
      s += `<rect x="${X(Math.min(0, d.mean))}" y="${y + 3}" width="${Math.abs(X(d.mean) - X(0))}"
              height="13" rx="3" fill="none" stroke="${d.hot ? C.hot : (top3 ? C.accent : '#CBD6E4')}"/>`;
      s += `<line x1="${X(d.worst)}" y1="${y + 1}" x2="${X(d.worst)}" y2="${y + 18}"
              stroke="${d.worst < 0 ? C.danger : C.ok}" stroke-width="2"/>`;
      s += `<text x="${W - 6}" y="${y + 14}" fill="${d.hot ? C.hot : C.text2}" font-size="11"
              text-anchor="end">${d.mean.toFixed(2)} / ${d.worst.toFixed(2)}</text>`;
    });
    s += `<text x="${L}" y="12" fill="${C.dim}" font-size="11">条形=邻域均值（3×3）· 竖线=邻域最差
            　⇒ 排序按这个，**不看样本内冠军</text>`;
    el.innerHTML = svg(W, H, s);
  }

  /* ============ ④ 滚动（walk-forward）IC：不是"一个数"，而是一条分布 ============ */
  function rollIC(el, opt) {
    const o = opt || {}, W = 560, H = 210, L = 52, T = 18, B = 34, R = 14;
    const r = rnd(o.seed || 3);
    const vals = []; for (let i = 0; i < 12; i++) vals.push(box(r, 0.08, 0.19));
    const lo = -0.5, hi = 0.5;
    const X = i => L + i / 11 * (W - L - R);
    const Y = v => T + (hi - v) / (hi - lo) * (H - T - B);
    let s = '';
    s += `<rect x="${L}" y="${Y(0.15)}" width="${W - L - R}" height="${Y(-0.15) - Y(0.15)}"
            fill="#2E7D32" fill-opacity="0.07"/>`;
    s += `<line x1="${L}" y1="${Y(0.15)}" x2="${W - R}" y2="${Y(0.15)}" stroke="${C.ok}"
            stroke-dasharray="4 4"/>`;
    s += `<line x1="${L}" y1="${Y(-0.15)}" x2="${W - R}" y2="${Y(-0.15)}" stroke="${C.ok}"
            stroke-dasharray="4 4"/>`;
    s += `<text x="${L + 6}" y="${Y(0.15) - 5}" fill="${C.ok}" font-size="10.5">IC 0.15（弱可用门槛）</text>`;
    s += `<line x1="${L}" y1="${Y(0)}" x2="${W - R}" y2="${Y(0)}" stroke="${C.axis}"/>`;
    for (const v of [0.5, 0.25, 0, -0.25, -0.5]) {
      s += `<text x="${L - 8}" y="${Y(v) + 3.5}" fill="${C.dim}" font-size="10.5"
              text-anchor="end">${v}</text>`;
    }
    let path = '';
    vals.forEach((v, i) => { path += (i ? ' L' : 'M') + X(i).toFixed(1) + ' ' + Y(v).toFixed(1); });
    s += `<path d="${path}" fill="none" stroke="${C.accent}" stroke-width="2"/>`;
    vals.forEach((v, i) => {
      s += `<circle cx="${X(i).toFixed(1)}" cy="${Y(v).toFixed(1)}" r="3.4"
              fill="${Math.abs(v) < 0.15 ? C.danger : C.accent}"/>`;
      s += `<text x="${X(i).toFixed(1)}" y="${H - B + 15}" fill="${C.dim}" font-size="10"
              text-anchor="middle">${i + 1}</text>`;
    });
    s += `<text x="${L}" y="12" fill="${C.text2}" font-size="11.5">滚动 IC（12 折 walk-forward）
            —— 多数折低于门槛 ⇒ 该参数化不稳定（单个 Rank IC 会骗人）</text>`;
    el.innerHTML = svg(W, H, s);
  }

  /* ============================================================
     ▼ v3 增量（2026-09-28）：两张新图（**只增不改**上面的四张，a/b/c 三页不受影响）
        · regimeTimeline：上证指数切块 ⇒ 预设样本内/外成对区间（放**右栏顶部**，全宽）
        · tradeHist    ：交易次数分布 + 门槛（放**左栏第 5 步滑块下方**，紧凑版）
     ============================================================ */

  /* ⚠ v3 修正（2026-09-28）：本文件上半部分（v1 四张图）里的 `el` 是**参数名**、不是函数，
     所以这里**自带**一个取节点的小工具（既收 id 字符串、也收 DOM 元素），
     绝不依赖外部名字 —— 否则 `el(id)` 会抛 ReferenceError 并把后续所有图一起带崩。 */
  function _node(x) {
    if (x && x.nodeType) return x;
    return typeof x === 'string' ? document.getElementById(x) : x;
  }

  /* ============ ⑤ 上证指数切块 → 预设样本区间 ============ */
  function regimeTimeline(id, opt) {
    const o = opt || {}, W = 620, H = 176, L = 46, R = 14, T = 26, BH = 42, GAP = 30;
    const y0 = 2016, y1 = 2026.8, X = v => L + (v - y0) / (y1 - y0) * (W - L - R);
    // 【示例段】真实实现由 scripts/analyze_index_regimes.py 按上证指数现算并缓存（可重算、可复现）
    const segs = o.segs || [
      {a: 2016.0, b: 2018.0, t: 'up', label: '震荡上行'},
      {a: 2018.0, b: 2019.0, t: 'down', label: '单边下跌'},
      {a: 2019.0, b: 2021.9, t: 'up', label: '结构性上涨'},
      {a: 2021.9, b: 2024.0, t: 'flat', label: '震荡箱体'},
      {a: 2024.0, b: 2026.7, t: 'up', label: '修复上行'}];
    const bg = {up: '#FBE0DD', down: '#DDEEE1', flat: '#EDF0F4'};
    const fg = {up: C.danger, down: C.ok, flat: C.dim};
    let s = `<text x="${L}" y="14" fill="${C.text}" font-size="12" font-weight="700">上证指数切块（示例条目；本机点「重新切块」按数据现算）</text>`;
    segs.forEach(g => {
      const x = X(g.a), w = X(g.b) - X(g.a);
      s += `<rect x="${x}" y="${T}" width="${w}" height="${BH}" rx="6" fill="${bg[g.t]}" stroke="${fg[g.t]}" stroke-opacity="0.5"><title>${esc(g.label)} ${g.a.toFixed(1)}~${g.b.toFixed(1)}</title></rect>`
        + `<text x="${(x + w / 2).toFixed(1)}" y="${T + BH / 2 + 4}" fill="${fg[g.t]}" font-size="11.5" font-weight="600" text-anchor="middle">${g.label}</text>`;
    });
    for (let yr = 2016; yr <= 2026; yr += 2) {
      s += `<line x1="${X(yr)}" y1="${T + BH}" x2="${X(yr)}" y2="${T + BH + 6}" stroke="${C.axis}"/>`
        + `<text x="${X(yr)}" y="${T + BH + 19}" fill="${C.dim}" font-size="10.5" text-anchor="middle">${yr}</text>`;
    }
    const is = o.is || [2016.0, 2018.0], oos = o.oos || [2021.9, 2024.0];
    const name = o.name || '震荡 → 震荡（常态）';
    const y = T + BH + GAP;
    const br = (a, b, yy, color, label) => {
      const x = X(a), w = X(b) - X(a);
      return `<rect x="${x}" y="${yy}" width="${w}" height="20" rx="6" fill="${color}" fill-opacity="0.14" stroke="${color}"/>`
        + `<text x="${x + 6}" y="${yy + 14}" fill="${color}" font-size="11.5" font-weight="600">${label}</text>`;
    };
    s += `<text x="${L}" y="${y - 6}" fill="${C.text}" font-size="11.5">当前预设：<tspan font-weight="700">${esc(name)}</tspan>　点色块可换成别的配对</text>`
      + br(is[0], is[1], y, C.accent, `样本内 ${is[0]} ~ ${is[1]}`)
      + br(oos[0], oos[1], y + 24, C.hot, `样本外 ${oos[0]} ~ ${oos[1]}`)
      + `<text x="${L}" y="${H - 8}" fill="${C.dim}" font-size="11">切块口径：按上证指数分段识别「单边上涨 / 单边下跌 / 震荡箱体」⇒ 预设成对给出样本内与样本外，避免"随手切一刀"</text>`;
    _node(id).innerHTML = svg(W, H, s);
  }

  /* ============ ⑥ 交易次数分布 + 门槛（compact = 左栏 306px 宽的紧凑版） ============ */
  function tradeHist(id, opt) {
    const o = opt || {}, thr = o.thr || 30, compact = !!o.compact;
    const W = compact ? 300 : 560, H = compact ? 132 : 190;
    const L = compact ? 22 : 46, R = 12, T = compact ? 20 : 26, B = compact ? 34 : 46;
    const r = rnd(o.seed || 23), counts = [];
    for (let i = 0; i < 64; i++) counts.push(Math.max(4, Math.round(box(r, 46, 26))));
    const buckets = [[0, 10], [10, 20], [20, 30], [30, 40], [40, 50], [50, 60], [60, 80], [80, 140]];
    const hist = buckets.map(() => 0);
    counts.forEach(c => { for (let i = 0; i < buckets.length; i++) if (c >= buckets[i][0] && c < buckets[i][1]) { hist[i]++; break; } });
    const maxH = Math.max(1, ...hist), bw = (W - L - R) / buckets.length, Y = v => H - B - (v / maxH) * (H - B - T);
    let s = `<text x="${L}" y="13" fill="${C.text}" font-size="12" font-weight="700">`
      + (compact ? '交易次数分布（决定门槛用）' : '交易次数分布（帮你定门槛）—— 本次 64 组参数') + '</text>'
      + `<line x1="${L}" y1="${H - B}" x2="${W - R}" y2="${H - B}" stroke="${C.axis}"/>`;
    hist.forEach((v, i) => {
      const x = L + i * bw + (compact ? 1.5 : 3), w = bw - (compact ? 3 : 6), y = Y(v), keep = buckets[i][0] >= thr;
      s += `<rect x="${x}" y="${y}" width="${w}" height="${H - B - y}" rx="3" fill="${keep ? '#C9DEFA' : '#E7ECF3'}" stroke="${keep ? C.accent : '#CBD6E4'}"><title>${buckets[i][0]}~${buckets[i][1]} 次：${v} 组</title></rect>`;
      if (!compact) s += `<text x="${x + w / 2}" y="${y - 4}" fill="${keep ? C.accent : C.dim}" font-size="10.5" text-anchor="middle">${v}</text>`;
      if (!compact || i % 2 === 0) s += `<text x="${x + w / 2}" y="${H - B + 14}" fill="${C.dim}" font-size="10" text-anchor="middle">${buckets[i][0]}</text>`;
    });
    const ti = Math.max(0, buckets.findIndex(b => thr >= b[0] && thr < b[1])), tx = L + ti * bw;
    const sorted = counts.slice().sort((a, b) => a - b), kept = counts.filter(c => c >= thr).length;
    s += `<line x1="${tx}" y1="${T - 8}" x2="${tx}" y2="${H - B}" stroke="${C.danger}" stroke-width="2" stroke-dasharray="5 3"/>`
      + `<text x="${tx + 5}" y="${T - 10}" fill="${C.danger}" font-size="11.5" font-weight="700">门槛 ${thr} 次</text>`;
    if (compact) {
      s += `<text x="${L}" y="${H - 8}" fill="${C.text}" font-size="11">门槛 ${thr} ⇒ <tspan font-weight="700" fill="${C.accent}">${kept}/64 组</tspan> 通过 · 中位数 ${sorted[32]} 次</text>`;
    } else {
      s += `<text x="${L}" y="${H - 10}" fill="${C.text}" font-size="11.5">门槛 ${thr} ⇒ <tspan font-weight="700" fill="${C.accent}">${kept}/${counts.length} 组</tspan> 进入候选 · 网格中位数 <tspan font-weight="700">${sorted[32]}</tspan> 次 · 最少 ${Math.min(...counts)} · 最多 ${Math.max(...counts)}</text>`;
    }
    _node(id).innerHTML = svg(W, H, s);
  }

  w.PS = { scatter, heat, neighbors, rollIC };
  /* v3 增量：PS2 在主应用（p2 双栏版）里用；含四张旧图 + 两张新图。
     ⚠ v4 修正（2026-09-28 真跑校验抓出的第 2 个 bug）：
       v1 的四张图**收的是 DOM 元素**（内部直接 `el.innerHTML = …`），传 id 字符串会
       `TypeError: Cannot create property 'innerHTML' on string` ⇒ 脚本中断、**后面所有图都不画**。
       所以这里**只给 PS2 加一层 id 兼容包装**（收 id 或元素都行），`w.PS` 保持原样 ⇒ a/b/c 三页不受影响。 */
  w.PS2 = {
    scatter: (x, o) => scatter(_node(x), o),
    heat: (x, o) => heat(_node(x), o),
    neighbors: (x, o) => neighbors(_node(x), o),
    rollIC: (x, o) => rollIC(_node(x), o),
    regimeTimeline: (x, o) => regimeTimeline(x, o),
    tradeHist: (x, o) => tradeHist(x, o)
  };
})(window);
