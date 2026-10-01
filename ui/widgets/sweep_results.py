# ui/widgets/sweep_results.py
"""
🧪 参数研究 —— **结果装配与渲染**（★R0 拆件；原 `ui/views/param_sweep.py` 的"统计装配 + 展示 + 存快照"）。

【为什么搬出来】`ui/views/param_sweep.py` 一度 **615 行**（§4 越线登记），其中近 1/4 是
"结果怎么算、怎么画、怎么存"，与"页面编排 + 红线闸门"（选策略 / 网格 / 区间 / 两段流程 / 污染闸）混住。
拆开后：视图回到**编排与闸门**（它该干的活），结果侧的后续改动（R4 四视图 / R5 候选表与快照卡）
只动本件，页面不用再跟着长。

【形态：混入类，不是第二套页面】R0 的纪律是**纯搬迁 · 零行为变化** —— 公共面一字不改 ⇒
既有断言与页面代码不许改一行。所以用 `ParamSweepView(SweepResultsMixin, QWidget)`：
方法体**逐字**搬来，`self.*` 语义完全不变（宿主仍是那个页面对象）。
R4/R5 若要把它长成"自带卡片与四视图的右栏渲染件"，在**本件内**演进即可。

【纪律】排序键 / 门槛"只筛不排" / 红线③"同屏不可折叠"的**口径全在**
`core.sweep_stats` 与 `data.sweep_archive`；本件只做"取数 → 喂控件 → 写回执"，
**不许在这里重算统计**（§10-11）。
"""
from __future__ import annotations

import logging

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QTableWidgetItem

from core.backtest import risk_summary
from core.param_sweep import (ComboOutcome, SweepOutcome, build_matrix,
                              combo_key, split_indices)
from core.sweep_plan import neighborhood_indices
from core.sweep_stats import (pbo_cscv, platform_spike_flags,  # ★R4
                              rank_ic, rolling_ic, study_key_stats)
from data.sweep_archive import TOP_N_DAILY, build_snapshot, top_candidate_rows
from ui.widgets.kpi_card import set_kpi   # ★R1：KPI 小卡与 M2 结果区同一实现
from ui.widgets.styles import (ACCORD_STATE_COLOR, VERDICT_BAD_QSS,
                               VERDICT_OK_QSS, VERDICT_WARN_QSS)

CANDIDATE_SHOW_MAX = 100     # 候选表最多显示行数（诚实截断）

logger = logging.getLogger(__name__)

#: 成交口径的人话（结论条要印 —— 红线③：口径同屏；与 M1 的三档命名同源）
_FILL_LABELS = {"next_open": "次日开盘", "close": "当日收盘", "trigger": "触发式条件单"}


class SweepResultsMixin:
    """结果侧方法集（宿主 = `ui.views.param_sweep.ParamSweepView`）。

    这里的方法只读宿主的既有属性：`_is_out` / `_oos_out` / `_grid` / `_items` / `_stats` /
    `_matrix` / `_interval` / `_spec` / `_preset_key` / `form` / `timeline` / `scatter` /
    `heatmap` / `chart_empty` / `lbl_verdict` / `table` / `lbl_table_meta` / `btn_save` /
    `_archive` / `_oos_key()`。
    """

    # ================= 统计装配与展示 =================
    def _compute_and_show(self) -> None:
        is_c = self._is_out.completed if self._is_out else {}
        oos_c = self._oos_out.completed if self._oos_out else {}
        keys = [k for k in is_c if k in oos_c]
        if not keys:
            self.form.set_receipt("样本内/样本外没有交集（两段要同一批组合都跑完才有统计）")
            return
        # ★1.66（用户实测「改了参数/区间再跑，图表依然不动」的真因）：
        #   两段结果会**跨轮次累积**（`_on_finished` 把新一轮 merge 进旧 outcome）⇒ 改了网格后
        #   旧组合键仍在，交集里就混进"**当前网格里不存在**的格子"；而邻域矩阵是按当前网格算的
        #   （`neighborhood_indices(self._grid.dims)`）⇒ `M @ values` 维度不匹配 ⇒
        #   `ValueError: matmul ...`。异常发生在 Qt 槽里（无人接）⇒ **图表静默不动、回执也不更新**。
        #   ⇒ 口径钉死：**图与表永远只讲"当前这一次的网格"**，旧格子一律不参与。
        valid = {combo_key(c) for c in self._grid.combos}
        keys = [k for k in keys if k in valid]
        if not keys:
            self.form.set_receipt(
                "当前网格里还没有两段都跑完的组合 —— 请 ▶ 跑样本内、再 ▶ 跑样本外"
                "（换过网格后，上一轮的结果不再参与统计）")
            return
        merged = SweepOutcome()
        for k in keys:
            a, b = is_c[k], oos_c[k]
            merged.completed[k] = ComboOutcome(
                key=k, combo=dict(a.combo), is_returns=a.is_returns,
                oos_returns=b.oos_returns, is_dates=a.is_dates, oos_dates=b.oos_dates,
                is_trades=a.is_trades, oos_trades=b.oos_trades)
        try:
            matrix = build_matrix(merged, keys)
            i_idx, o_idx = split_indices(merged)
            table = neighborhood_indices(self._grid.dims)
            metrics = study_key_stats(matrix, i_idx, o_idx, table)
            self._nb_table = table          # ★R5：候选表行悬停要报"邻居是谁"
        except ValueError as e:
            # ★1.66：统计装配**不许静默失败** —— 异常一旦被 Qt 槽吞掉，用户看到的就是
            #   "点了没反应"。这里兜住并说人话（同时记日志，便于定位）。
            logger.warning("统计装配失败：%s", e)
            self.form.set_receipt(f"统计装配失败（这是缺陷，已记日志）：{e}")
            return
        ic = rank_ic(metrics.is_annual, metrics.oos_annual)
        pbo = pbo_cscv(matrix, table, s_blocks=12)
        self._items = [(k, merged.completed[k].combo) for k in keys]
        trades = [merged.completed[k].trades for k in keys]
        self._stats = {"rank_ic": ic, "pbo": pbo, "metrics": metrics,
                       "n_done": len(keys), "n_failed": len(is_c) - len(keys)}
        self._matrix = matrix
        # ---- 展示 ----
        gate = self.form.min_trades()
        rows = self._candidate_rows(metrics, trades, gate)
        self.chart_empty.hide()
        self.scatter.show()
        # ★R4 ①：两个**十字标注** ——「样本内冠军」（IS 年化最大 = 最容易骗人的那个）与
        #   「最终候选」（候选表第 1 名，即排序键的赢家）。两者**常常不是同一个点**，
        #   图上把这两处标出来，就是"冠军崩塌"最直观的一张图。
        champ = (int(np.nanargmax(metrics.is_annual))
                 if np.isfinite(metrics.is_annual).any() else None)
        cand = None
        if rows:
            _ck = combo_key(rows[0]["combo"])
            cand = next((i for i, (k, _c) in enumerate(self._items) if k == _ck), None)
        # ★R4-b：平台/尖峰**只判一次** —— 散点的"稳健平台区"框与热力图的绿框/橙圈共用同一份
        plat, spike = platform_spike_flags(metrics.oos_annual, metrics.nb_mean,
                                           metrics.nb_worst)
        labels = [self._combo_text(c) for _k, c in self._items]
        self.scatter.set_data(metrics.is_annual, metrics.oos_annual, highlight=set(),
                              champion=champ, candidate=cand,
                              combos=[c for _k, c in self._items],
                              nb_mean=metrics.nb_mean, rank_ic=ic, platform=plat)
        self._show_heatmap(metrics, plat, spike)
        self._show_other_views(metrics, labels, champ)
        self._set_verdict(ic, pbo, rows)
        self._fill_table(rows)
        self.btn_save.setEnabled(True)
        usage = self._archive.oos_usage(self._oos_key())
        msg = (f"样本外完成 {len(oos_c)} 组。⚠ 该样本外窗口已被 {usage} 项研究引用"
               "（含本次）—— 引用越多，它越像样本内（红线①）")
        if not any(r.get("kept") for r in rows):
            # ★1.66 / ★R4：门槛把组合筛空时**说清到底卡在哪**。门槛是**三条同时成立**
            #   （交易数 ≥ 门槛 且 IS 年化 > 0 且 OOS 年化 > 0，口径唯一出口
            #   `core.sweep_stats.apply_gate`）；只说"把门槛调低"会让人白忙
            #   —— 本次实测：区间整体负收益时，门槛调到 1 也依然 0 组。
            n_trades_ok = sum(1 for t in trades if float(t) >= float(gate))
            n_pos = sum(1 for i in range(len(trades))
                        if metrics.is_annual[i] > 0 and metrics.oos_annual[i] > 0)
            mx = max(trades) if trades else 0
            if n_trades_ok == 0:
                msg += (f"\n门槛 {gate} 笔把所有组合都筛掉了（本次最多的一组只有 {mx} 笔）"
                        "⇒ 把门槛滑块调低再看（门槛只筛不排）")
            elif n_pos == 0:
                msg += (f"\n门槛里还有一条「IS 与 OOS 年化**都**为正」—— 本次 {len(trades)} 组"
                        "没有一组两者都为正 ⇒ **光调低门槛解决不了**，先看参数区间是否整体亏钱")
            else:
                msg += (f"\n交易数够的有 {n_trades_ok} 组，但同时满足「IS 与 OOS 年化都为正」"
                        f"的只有 {n_pos} 组 ⇒ 门槛的三条要**同时**成立")
        self.form.set_receipt(msg)
        # ★R3：时间轴现在**分得清内外**（样本内蓝框 / 样本外橙框）⇒ 四个日期都要给它
        self.timeline.set_marks(self._interval.is_start, self._interval.is_end,
                                self._interval.oos_start, self._interval.oos_end)

    def _set_verdict(self, ic, pbo, rows) -> None:
        iv = self._interval
        fill = _FILL_LABELS.get(self._spec.fill_mode or "next_open",
                                str(self._spec.fill_mode))
        risk_txt = risk_summary(self._spec.risk) or "无"
        ic_txt = "—" if ic is None or ic != ic else f"{ic:.2f}"
        pbo_txt = "—" if pbo is None or pbo != pbo else f"{pbo:.0%}"
        bad = pbo is not None and pbo == pbo and pbo > 0.5
        weak = (not bad) and ic is not None and ic == ic and ic < 0.15
        if bad:
            self.lbl_verdict.setStyleSheet(VERDICT_BAD_QSS)
            warn = "  ⚠ <b>PBO&gt;0.5：这套选参流程等于抛硬币</b>"
        elif weak:
            self.lbl_verdict.setStyleSheet(VERDICT_WARN_QSS)
            warn = "  ⚠ <b>Rank IC&lt;0.15：该参数化没有预测力，别按样本内冠军选参</b>"
        else:
            self.lbl_verdict.setStyleSheet(VERDICT_OK_QSS)
            warn = ""
        # 红线③：全部统计前提同屏直排 —— 不进 tooltip、不可折叠
        self.lbl_verdict.setText(
            f"<b>结论（同屏不可折叠）</b>：试验数 <b>{self._grid.n_combos}</b>"
            f"（完成 {len(self._items)} / 失败 {self._stats['n_failed']}）· "
            f"Rank IC <b>{ic_txt}</b>（&lt;0.15 ⇒ 无预测力）· PBO <b>{pbo_txt}</b>{warn}<br>"
            f"区间 <b>{iv.is_start} ~ {iv.is_end}</b>（样本内）→ "
            f"<b>{iv.oos_start} ~ {iv.oos_end}</b>（样本外）· 成交：<b>{fill}</b> · "
            f"风控：<b>{risk_txt}</b> · 过门槛 <b>"
            f"{sum(1 for r in rows if r.get('kept'))}</b> 组")
        # ★R1：KPI 小卡行（与 M2 结果区**同一个** `kpi_card`）—— 数字与结论条**同源同一批变量**；
        #   结论条文字是给"读"的，这排卡是给"扫一眼"的（红线③：两者都在屏上、都不许折叠）。
        kpi = getattr(self, "kpi", None) or {}
        if kpi:
            set_kpi(kpi["n"], "试验数", str(self._grid.n_combos),
                    f"完成 {len(self._items)} / 失败 {self._stats['n_failed']}")
            set_kpi(kpi["is"], "样本内", f"{iv.is_start[:7]} ~ {iv.is_end[:7]}", "调参区间",
                    ACCORD_STATE_COLOR["ok"])
            set_kpi(kpi["oos"], "样本外", f"{iv.oos_start[:7]} ~ {iv.oos_end[:7]}", "只验一次",
                    ACCORD_STATE_COLOR["ok"])
            set_kpi(kpi["ic"], "Rank IC", ic_txt, "≥0.15 才有预测力",
                    ACCORD_STATE_COLOR[""] if (ic is None or ic != ic)
                    else ACCORD_STATE_COLOR["bad" if weak else "ok"])
            set_kpi(kpi["pbo"], "PBO", pbo_txt, ">0.5 等于抛硬币",
                    ACCORD_STATE_COLOR["bad"] if bad
                    else (ACCORD_STATE_COLOR["warn"] if weak else ACCORD_STATE_COLOR["ok"]))

    def _candidate_rows(self, metrics, trades, gate):
        """★R5：**门槛只筛不排** ⇒ 表里把没过的也列出来（灰显 + ✗），让人看见"被筛掉了什么"。"""
        return top_candidate_rows(metrics, self._items, trades, gate,
                                  top=CANDIDATE_SHOW_MAX, include_gated=True)

    @staticmethod
    def _combo_text(combo: dict) -> str:
        """组合的参数文本（图上一行要写得下：`L1=9 L2=33`）—— 与候选表同一种写法，不另造格式。"""
        return " ".join(f"{k}={float(v):.6g}" for k, v in sorted((combo or {}).items()))

    def _show_other_views(self, metrics, labels, champion) -> None:
        """★R4 ③④：邻域稳健 + 滚动 IC。

        纪律：**只重排不重跑** —— 数据全部来自已经算好的 `metrics` 与 `self._matrix`
        （`matrix` 就是 PBO 吃的那份 IS+OOS 拼接逐日收益），这里一个新回测都不发起。
        """
        charts = getattr(self, "charts", None)
        if charts is None:
            return
        charts.set_neighborhood(metrics.nb_mean, metrics.nb_worst, labels, champion)
        charts.set_rolling_ic(rolling_ic(self._matrix))

    def _show_heatmap(self, metrics, plat, spike) -> None:
        dims = self._grid.dims
        charts = getattr(self, "charts", None)
        if len(dims) != 2:
            # ★R4-e：单维时**不许把热力图藏起来**（藏了就是"点开一片空白"，用户实测的正是这个），
            #   改成页内明确空态 + chip 置灰（`show_notice` 一处收口）。
            if charts is not None:
                charts.show_notice("heatmap")
            return
        self.heatmap.show()     # 有数据就正常画（chip 高亮由 `show_view` 管，这里不插手）
        xv, yv = list(dims[0].values), list(dims[1].values)
        xi = {v: i for i, v in enumerate(xv)}
        yi = {v: i for i, v in enumerate(yv)}
        grid_vals = np.full((len(yv), len(xv)), np.nan)
        # 平台/尖峰格子坐标（判据来自 `core.sweep_stats.platform_spike_flags`，与候选表同一函数）
        p_cells, s_cells = [], []
        for idx, (k, combo) in enumerate(self._items):
            a = metrics.oos_annual[idx]
            px = next((v for v in xv
                       if abs(float(combo.get(dims[0].name, np.nan)) - v) < 1e-9), None)
            py = next((v for v in yv
                       if abs(float(combo.get(dims[1].name, np.nan)) - v) < 1e-9), None)
            if px is not None and py is not None:
                grid_vals[yi[py], xi[px]] = a
                if idx < plat.size and bool(plat[idx]):
                    p_cells.append((xi[px], yi[py]))
                elif idx < spike.size and bool(spike[idx]):
                    s_cells.append((xi[px], yi[py]))
        self.heatmap.set_grid(dims[0].name, xv, dims[1].name, yv, grid_vals,
                              platform_cells=p_cells, spike_cells=s_cells)

    def _fill_table(self, rows) -> None:
        """候选表（★R5：9 列 —— 补「过门槛 ✓✗」与「平台/尖峰」两列 + 行悬停）。"""
        n_kept = sum(1 for r in rows if r.get("kept"))
        self.table.setRowCount(len(rows))
        self.table.setUpdatesEnabled(False)
        for r, row in enumerate(rows):
            combo_txt = "  ".join(f"{k}={v:.6g}" for k, v in row["combo"].items())
            # ★R5：行悬停 = IS/OOS/邻域三值 + **邻居是谁**（"为什么说它是平台/尖峰"要有依据）
            nbr = ""
            try:
                _nbt = getattr(self, "_nb_table", None) or []
                nb_idx = (_nbt[row["idx"]]
                          if row.get("idx") is not None and row["idx"] < len(_nbt) else ())
                who = [self._combo_text(self._items[j][1]) for j in nb_idx
                       if 0 <= j < len(self._items) and j != row.get("idx")]
                if who:
                    nbr = "；邻居：" + "、".join(who[:6]) + ("…" if len(who) > 6 else "")
            except (IndexError, KeyError, TypeError):
                nbr = ""
            tip = (f"{combo_txt} ⇒ IS {row['is_annual']:.2%} · OOS {row['oos_annual']:.2%} · "
                   f"邻域均值 {row['nb_mean']:.2%}（最差 {row['nb_worst']:.2%}）· "
                   f"交易 {row['trades']} 次"
                   + ("· ✅ 过门槛" if row.get("kept") else "· ❌ 未过门槛（门槛只筛不排，仍列出）")
                   + (f"· 判定：{'平台' if row['flag'] == '平' else '尖峰'}" if row.get("flag") else "")
                   + nbr)
            vals = [str(row["rank"]), combo_txt, f"{row['oos_annual']:.1%}",
                    f"{row['is_annual']:.1%}", f"{row['delta']:+.1%}",
                    f"{row['nb_mean']:.1%}", str(row["trades"]),
                    "✓" if row.get("kept") else "✗",
                    {"平": "平", "尖": "尖"}.get(row.get("flag"), "—")]
            for c, txt in enumerate(vals):
                item = QTableWidgetItem(txt)
                if c in (2, 3, 4, 5):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                          | Qt.AlignmentFlag.AlignVCenter)
                elif c in (7, 8):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setToolTip(tip)
                if not row.get("kept"):          # ★R5：没过的**灰显保留**（不是删掉）
                    item.setForeground(QColor("#B4BECB"))
                self.table.setItem(r, c, item)
        self.table.setUpdatesEnabled(True)
        self.lbl_table_meta.setText(
            "按 邻域均值 ↓, OOS ↓, |Δ| ↑ 排序；门槛只筛不排（✗ = 未过门槛，灰显保留）"
            f" · 过门槛 {n_kept} / 列出 {len(rows)} 组"
            + (f"（只显示前 {CANDIDATE_SHOW_MAX} 行）" if len(rows) >= CANDIDATE_SHOW_MAX else ""))

    @staticmethod
    def _idle_verdict_text() -> str:
        return ("还没有研究结果 —— 先在左栏选标的与策略，<b>▶ 跑样本内</b>，再 <b>▶ 跑样本外</b>"
                "（只跑一次）。结论条会常驻在这里：试验数 · Rank IC · PBO · 区间 · 成交与风控口径。")

    # ================= 存快照 =================
    def _save_snapshot(self) -> None:
        if self._stats is None or self._spec is None:
            self.form.set_receipt("还没有可存的研究结果")
            return
        payload = self.form.strategy_payload() or {}
        keys = [k for k, _ in self._items]
        is_c = self._is_out.completed
        oos_c = self._oos_out.completed
        daily_keys = keys[:TOP_N_DAILY]
        daily = {"keys": daily_keys,
                 "is_dates": list(next(iter(is_c.values())).is_dates or ()),
                 "oos_dates": list(next(iter(oos_c.values())).oos_dates or ()),
                 "is_returns": {k: [float(x) for x in is_c[k].is_returns] for k in daily_keys},
                 "oos_returns": {k: [float(x) for x in oos_c[k].oos_returns] for k in daily_keys}}
        trades = [is_c[k].trades for k in keys]
        snap = build_snapshot(
            spec=self._spec, strategy_name=str(payload.get("name") or ""),
            asset_id=str(payload.get("asset_id") or ""),
            grid=self._grid, interval=self._interval, preset_key=self._preset_key,
            min_trades=self.form.min_trades(),
            stats={**self._stats, "items": self._items, "trades": trades},
            matrix=self._matrix, daily=daily)
        rid = self._archive.save(snap)
        if rid is None:
            self.form.set_receipt("快照超体积上限，没写入（诚实拒绝）")
            return
        usage = self._archive.oos_usage(self._oos_key())
        self.form.set_receipt(f"快照已存（{rid}）。⚠ 该样本外窗口累计被 {usage} 项研究引用")
        self._refresh_snapshots()          # ★R5b：存完立刻在 ⑨ 卡里看得见
