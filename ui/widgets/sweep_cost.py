# ui/widgets/sweep_cost.py
"""🧪 参数研究 —— **成交成本与成本敏感性**（★1.79 / §7-B15 第二轮① · 用户 2026-10-17 重做）。

【为什么单独成件】① 用户实测："**窗口一小就完全看不见**" —— 入口原来塞在「候选表」头条行右侧，
  窗口一窄就被右边缘**裁掉**（截图实证）；② 它本该是一块**独立内容区**（口径 + 佣金档 + 进度 + 结果），
  挤在一条头条行里既看不见、也说不清；③ `sweep_results.py` 已越 400 行线 ⇒ 按 §4 纪律顺手分件。

【这块 UI 回答什么】"我这套参数，把佣金换个档还站得住吗？"
  （方案书原话：**"成本一调就崩 ⇒ 不是真本事"**，`docs/JIAN_SWEEP_PLAN.md` 第二轮①）
【它不是什么】不是"按成本挑最优"（红线②不许替用户选参）；候选顺序仍由既有排序键决定
  （红线①"样本外只看一次"、③"口径与排名同屏"都不动）。

【三条诚实边界 —— 全部写在界面上，不藏在 tooltip 里】
  1. **只含佣金**：本仓成交成本只有佣金一条（`core/backtest.DEFAULT_COMMISSION_RATE`），
     滑点 / 印花税**没有模型**；
  2. **回测本身目前固定按万3 计**：策略保存的成交成本**尚未接通**到参数研究链路
     （审计已记：`SweepSpec` 无 commission 字段）⇒ 下面三档只用于"看敏感性"，
     **不改变本次研究本身的成交口径**；
  3. **只重跑候选表前 N 名**（方案书：只跑 Top-N，不跑全网格）⇒ 其余行的「成本斜率」是
     "**没跑**"而不是"等于 0"（列头与行悬停都写明；跑完会自动滚到表顶，让你看见有数的那几行）。
"""
from __future__ import annotations

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                             QWidget)

from core.backtest import commission_rate_from_prefs, commission_text   # ★1.81 基准
from core.sweep_plan import GridPlan
from core.sweep_stats import DEFAULT_COST_LEVELS, annual_returns, cost_sensitivity
from core.sweep_stats import cost_tier_label
from ui.widgets.custom_widgets import NoWheelDoubleSpinBox
from ui.widgets.styles import SEC_HINT_QSS, SUMMARY_GHOST_QSS
from ui.widgets.sweep_parts import panel_card, panel_head

COST_TOP_N = 10          # 只对候选表**前 N 行**重跑（方案书：只跑 Top-N，不跑全网格）
TIER_UM_RANGE = (0.1, 100.0)     # 佣金档可调范围（万分之）—— 上限 100 万分之（千分之一）够用


def default_tiers_um() -> tuple:
    """三档默认 = **以全局回测佣金为基准**（基准万3 时正好 3 / 5 / 10）。"""
    base = max(commission_rate_from_prefs() * 10000.0, 0.1)
    return (round(base, 1), round(max(base * 5.0 / 3.0, base + 0.5), 1),
            round(max(base * 10.0 / 3.0, base + 1.0), 1))


def _um(rate: float) -> float:
    """小数比例 → 万分之（展示/输入的单位换算**只此一处**，别在 UI 各写一遍）。"""
    return float(rate) * 10000.0


class SweepCostMixin:
    """成交成本卡的行为（宿主 = `ui.views.param_sweep.ParamSweepView`）。"""

    COST_TOP_N = COST_TOP_N

    # ---------------- 佣金档（可调、记住） ----------------
    def cost_tiers_um(self) -> tuple:
        """当前三档（**万分之**，供界面显示/计算）—— 坏值一律回落默认三档。"""
        raw = None
        try:
            from core.preferences import preferences
            raw = (preferences.get("sweep_ui") or {}).get("commission_tiers")
        except Exception:               # noqa: BLE001 —— 偏好坏了不拖垮页面
            raw = None
        vals = []
        for i, dflt in enumerate(default_tiers_um()):
            try:
                v = float(raw[i])
            except (TypeError, ValueError, IndexError):
                v = dflt
            vals.append(min(max(v, TIER_UM_RANGE[0]), TIER_UM_RANGE[1]))
        return tuple(vals)

    def _persist_cost_tiers(self) -> None:
        """把三档写进 `sweep_ui.commission_tiers`（**只存配置、不存结果** —— 结果不落盘，D3 不变）。"""
        try:
            from core.preferences import preferences
            state = dict(preferences.get("sweep_ui") or {})
            state["commission_tiers"] = [float(v) for v in self.cost_tiers_um()]
            preferences.set("sweep_ui", state)
        except Exception:               # noqa: BLE001
            pass

    def _cost_levels(self) -> tuple:
        """三档 → `cost_sensitivity` 要的**小数比例/每边**（去重、升序；少于 2 档 ⇒ 界面会如实说）。"""
        rates = sorted({round(float(v) / 10000.0, 8) for v in self.cost_tiers_um()
                        if float(v) > 0})
        return tuple(rates)

    # ---------------- 取候选（按候选表顺序） ----------------
    def top_candidate_keys(self, n: int = COST_TOP_N) -> list:
        """候选表**当前顺序**的前 N 个组合键 —— 成本敏感性只准按这个顺序取候选。"""
        from core.param_sweep import combo_key
        rows = list(getattr(self, "_rows", None) or [])
        return [combo_key(r["combo"]) for r in rows[:max(1, int(n))]]

    # ---------------- 结果落屏 ----------------
    def set_cost_sensitivity(self, slopes: dict, levels=(), spans: dict = None,
                             annuals: dict = None) -> None:
        """把算好的斜率挂到表上 + 写卡上的结果区（**只换显示**：绝不重排候选）。"""
        self._cost_slopes = dict(slopes or {})
        self._cost_spans = dict(spans or {})
        self._cost_levels_used = tuple(levels or ())
        self._cost_annuals = dict(annuals or {})
        self._cost_topn = len(self._cost_slopes)
        self._fill_table(list(getattr(self, "_rows", None) or []))
        self._set_verdict((self._stats or {}).get("rank_ic"), (self._stats or {}).get("pbo"),
                          list(getattr(self, "_rows", None) or []))
        self._render_cost_result()

    def _render_cost_result(self) -> None:
        """卡上的结果区：最平 / 最陡 + 它们**逐档年化**（数字给全，判断留给人）。"""
        lbl = getattr(self, "lbl_cost_result", None)
        if lbl is None:
            return
        slopes = {k: v for k, v in (getattr(self, "_cost_slopes", None) or {}).items() if v == v}
        if not slopes:
            lbl.setText("")
            return
        levels = getattr(self, "_cost_levels_used", ()) or ()
        tiers = " / ".join(cost_tier_label(r) for r in levels)
        rows = []
        for tag, key in (("最平", min(slopes, key=lambda k: abs(slopes[k]))),
                         ("最陡", max(slopes, key=lambda k: abs(slopes[k])))):
            anns = (getattr(self, "_cost_annuals", None) or {}).get(key) or {}
            detail = " · ".join(
                f"{cost_tier_label(r)} {float(anns[r]):+.1%}" for r in levels if r in anns)
            rows.append(f"<b>{tag}</b> {key}：斜率 <b>{slopes[key] * 100:+.2f}</b>"
                        f" 个百分点/万分之（{detail}）")
        lbl.setText(f"佣金档：<b>{tiers}</b>（每边）· 对 <b>{len(slopes)}</b> 个候选各重跑了一遍样本外"
                    "<br>" + "<br>".join(rows)
                    + "<br><span style='color:#8A94A6'>只含佣金 · 斜率只给候选表<b>前 "
                      f"{int(getattr(self, 'COST_TOP_N', COST_TOP_N))} 名</b>"
                      "（其余行是「没跑」，不是 0）· 不参与选参（红线①②不动）</span>")

    def _cost_verdict_line(self) -> str:
        """结论条里的成本那一行（没有结果就不加 —— 不留空壳）。"""
        slopes = getattr(self, "_cost_slopes", None) or {}
        if not slopes:
            return ""
        return ("<br>成本敏感性（Top-N=" + str(getattr(self, "_cost_topn", 0)) + " × "
                + str(len(getattr(self, "_cost_levels_used", ()) or ())) + " 档 · 只含佣金）："
                + self._cost_summary(slopes) + " · <b>不参与选参</b>（红线①②不动）")

    @staticmethod
    def _cost_summary(slopes: dict) -> str:
        """人话小结：最平 / 最陡（**只报数** —— 方案书没给"够不够平"的门槛，本仓不发明判据）。"""
        ok = {k: v for k, v in (slopes or {}).items() if v == v}
        if not ok:
            return "有效档数不足 ⇒ 算不出斜率（缺档不插值）"
        flat = min(ok, key=lambda k: abs(ok[k]))
        steep = max(ok, key=lambda k: abs(ok[k]))
        return (f"最平 {flat}（{ok[flat] * 100:+.2f} 个百分点/万分之）· "
                f"最陡 {steep}（{ok[steep] * 100:+.2f}）")

    def _cost_status(self, text: str) -> None:
        lbl = getattr(self, "lbl_cost_status", None)
        if lbl is not None:
            lbl.setText(str(text))
        self.form.set_receipt(str(text))

    # ---------------- 跑（Top-N × 3 档，逐档串行，可中断） ----------------
    def _follow_cost_base(self) -> None:
        """把三档按**当前基准**重排（基准来自设置；只影响敏感性测算）。"""
        base = default_tiers_um()
        for sp, v in zip(getattr(self, "cost_spins", ()), base):
            sp.blockSignals(True)
            sp.setValue(float(v))
            sp.blockSignals(False)
        self._persist_cost_tiers()
        if getattr(self, "lbl_cost_base", None) is not None:
            self.lbl_cost_base.setText(
                "回测基准：<b>" + commission_text(commission_rate_from_prefs()) + "</b>（每边）—— "
                "改它去「⚙ 设置 → 回测与扫描默认」；下面三档只用于测算敏感性。")
        self._cost_status("三档已按基准重排：" + " / ".join(f"万{v:g}" for v in base)
                          + "（只影响敏感性测算，不改本次研究的成交口径）")

    def _run_cost(self) -> None:
        """「▶ 跑成本敏感性」入口。"""
        # ★1.79 QA：**回看态下点它 = 语境错位**（屏上是历史快照的行，却拿 live 候选重跑）
        if getattr(self, "_replay_rid", None):
            self._cost_status("现在在**回看历史快照** —— 成本敏感性只能对**当前这次研究**做："
                              "请先按快照参数重跑一次，或点「▶ 跑样本内」退出回看态。")
            return
        if not self._oos_out or not self._oos_out.completed:
            self._cost_status("先跑样本外 —— 成本敏感性是对**已选定的候选**换成本假设重跑 OOS"
                              "（两段都跑完后这个按钮才有意义）。")
            return
        if self._worker is not None and self._worker.isRunning():
            self._cost_status("正在跑别的任务 —— 等它结束再点「▶ 跑成本敏感性」。")
            return
        levels = self._cost_levels()
        if len(levels) < 2:
            self._cost_status("至少要两个**不同**的佣金档（现在三档里有重复或空值）—— 请先改档位。")
            return
        keys = self.top_candidate_keys(self.COST_TOP_N)
        by_key = {k: c for k, c in (self._items or [])}
        combos = tuple(by_key[k] for k in keys if k in by_key)
        if not combos:
            self._cost_status("候选表还是空的 —— 先 ▶ 跑样本内、再 ▶ 跑样本外。")
            return
        # 只含 Top-N 的**子网格**：`run_sweep` 只用 `combos`（不读 dims）⇒ 不必给内核加子集逻辑
        self._cost_grid = GridPlan(self._grid.dims, combos, len(combos),
                                   float(self._grid.est_seconds or 0.0) * len(combos)
                                   / max(1, self._grid.n_combos))
        self._cost_keys = [self.top_candidate_keys(self.COST_TOP_N)[i] for i in range(len(combos))]
        self._cost_levels_run = tuple(levels)
        self._cost_index = 0
        self._cost_annuals = {k: {} for k in self._cost_keys}
        if getattr(self, "btn_cost", None) is not None:
            self.btn_cost.setEnabled(False)      # ★1.79：跑起来要**看得见**（按钮灭 + 状态行报进度）
        self._run_cost_tier()

    def _run_cost_tier(self) -> None:
        """跑当前这一档佣金（串行：一档跑完在 `_on_finished` 里起下一档）。"""
        from ui.workers import ParamSweepWorker     # 局部 import：混入件不必与线程件互相引用

        rate = self._cost_levels_run[self._cost_index]
        df = self._lake.load_data("kline_daily", self._spec.symbol)
        self._stage = "cost"                        # ⚠ 独立阶段：绝不污染 `_oos_out`
        self.form.set_running(True)
        job = self._guard.next()
        self._worker = ParamSweepWorker(job, df, self._spec, self._cost_grid, self._interval,
                                        stage="oos", done_keys=frozenset(),
                                        commission_rate=rate)
        # ★1.81：进度**累进**（旧版直接连 `form.set_progress` ⇒ 每档从 0 开始，
        #   用户看到"倒退/重启" ⇒ 以为卡住或重跑）
        self._worker.progress.connect(self._on_cost_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        # ⚠ 状态写在 `start()` **之前**：回包可能同步到达，写在后面会盖掉它的话（QA 复核实测）
        self._cost_status(
            f"正在跑：第 {self._cost_index + 1}/{len(self._cost_levels_run)} 档"
            f"（佣金 {cost_tier_label(rate)}）· 只重跑 {self._cost_grid.n_combos} 个候选的样本外…")
        self._worker.start()

    def _on_cost_progress(self, done: int, total: int, note: str) -> None:
        """**累进**进度：已完成档 × 每档组数 + 本档进度（★1.81）。

        旧版把 worker 的 `(done,total)` 直接喂进度条 ⇒ 第 2 档又从 0 开始。
        """
        n = max(1, int(total or 0))
        self._cost_per_tier_n = n
        tiers = max(1, len(getattr(self, "_cost_levels_run", ()) or ()))
        tier = int(getattr(self, "_cost_index", 0))
        self.form.set_progress(tier * n + int(done), tiers * n,
                               f"第 {tier + 1}/{tiers} 档 · {note}")

    def _on_cost_finished(self, outcome) -> None:
        """累计本档 ⇒ 还有档就续跑；最后一档算斜率、上屏、写回执。"""
        rate = self._cost_levels_run[self._cost_index]
        for k, co in (outcome.completed or {}).items():
            if co.oos_returns is None:
                continue
            arr = np.asarray([co.oos_returns], dtype=float)
            self._cost_annuals.setdefault(k, {})[rate] = float(annual_returns(arr)[0])
        if outcome.cancelled:
            self._stage = ""
            if getattr(self, "btn_cost", None) is not None:
                self.btn_cost.setEnabled(True)
            self._cost_status("成本敏感性已中断（这一档没跑完）—— 已完成的档作废，"
                              "再点一次会从头跑这几档。")
            return
        if self._cost_index + 1 < len(self._cost_levels_run):
            self._cost_index += 1
            self._run_cost_tier()
            return
        keys = list(self._cost_keys)
        y = np.array([[self._cost_annuals.get(k, {}).get(r, np.nan) for k in keys]
                      for r in self._cost_levels_run], dtype=float)
        res = cost_sensitivity(y, self._cost_levels_run)
        slopes = {k: float(res['slope'][i]) for i, k in enumerate(keys)}
        spans = {k: float(res['span'][i]) for i, k in enumerate(keys)}
        self.set_cost_sensitivity(slopes, self._cost_levels_run, spans,
                                  {k: dict(v) for k, v in self._cost_annuals.items()})
        self._stage = ""
        if getattr(self, "btn_cost", None) is not None:
            self.btn_cost.setEnabled(True)
        # ★1.79：跑完**滚到表顶** —— 有数的就是前 N 行；不滚的话用户盯着下面的「—」会以为没反应
        try:
            self.table.scrollToTop()
        except Exception:               # noqa: BLE001
            pass
        self._cost_status("成本敏感性完成："
                          + f"{len(keys)} 个候选 × {len(self._cost_levels_run)} 档（"
                          + " / ".join(cost_tier_label(r) for r in self._cost_levels_run) + "）—— "
                          + self._cost_summary(slopes)
                          + "（**只含佣金**；成本结果不参与排序 ⇒ 红线①②不动）")


def build_cost_card(page) -> QWidget:
    """**成交成本卡**（★1.79）：口径说明 + 三档佣金 + 跑按钮 + 状态行 + 结果区。

    【为什么不做成头条行里的一颗按钮】用户实测："窗口小的时候会**完全看不见**" ——
      头条行的按钮会被窗口右边缘裁掉（截图实证）⇒ 这里用**独立卡片**（竖向排布、文本自动换行），
      窗口再窄也只会在**纵向**上被滚动，而不会横向消失。
    """
    card = panel_card()
    head = panel_head("成交成本", "只含佣金 · 回测本身固定按万3 计（策略保存值尚未接通）")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)
    lay.addWidget(head)
    body = QWidget()
    lay.addWidget(body)
    bl = QVBoxLayout(body)
    bl.setContentsMargins(8, 6, 8, 8)
    bl.setSpacing(5)

    intro = QLabel("把这套参数在**不同佣金档**下各重跑一遍**样本外**，看年化对佣金有多敏感"
                   "（斜率越接近 0 越稳）。<b>不参与选参</b>：候选顺序仍由既有排序键决定。")
    intro.setWordWrap(True)              # ★窗口窄时自动换行 —— 不再被裁掉
    intro.setStyleSheet(SEC_HINT_QSS)
    bl.addWidget(intro)
    page.lbl_cost_base = QLabel("")
    page.lbl_cost_base.setWordWrap(True)
    page.lbl_cost_base.setStyleSheet(SEC_HINT_QSS)
    bl.addWidget(page.lbl_cost_base)
    page.lbl_cost_base.setText(
        "回测基准：<b>" + commission_text(commission_rate_from_prefs()) + "</b>（每边）—— "
        "改它去「⚙ 设置 → 回测与扫描默认」；下面三档只用于测算敏感性。")

    row_tiers = QHBoxLayout()
    row_tiers.setSpacing(6)
    _lab = QLabel("佣金档（每边，万分之）：")
    _lab.setStyleSheet(SEC_HINT_QSS)
    row_tiers.addWidget(_lab)
    page.cost_spins = []
    _saved = tuple(page.cost_tiers_um())     # ★记住上次（`sweep_ui.commission_tiers`，改完立即落盘）
    for i, _um_val in enumerate(_saved):
        sp = NoWheelDoubleSpinBox()
        sp.setDecimals(1)
        sp.setRange(float(TIER_UM_RANGE[0]), float(TIER_UM_RANGE[1]))
        sp.setSingleStep(0.5)
        sp.setValue(float(_um_val))
        sp.valueChanged.connect(page._persist_cost_tiers)   # 只存**配置**，不存结果（D3 不变）
        sp.setFixedWidth(78)
        sp.setToolTip("第 %d 档佣金（每边、万分之）—— 万3 = 3.0\n"
                      "⚠ 只影响**成本敏感性**；本次研究本身的成交成本仍是万3（见下方说明）" % (i + 1))
        page.cost_spins.append(sp)
        row_tiers.addWidget(sp)
        if i < len(DEFAULT_COST_LEVELS) - 1:
            sep = QLabel("/")
            sep.setStyleSheet(SEC_HINT_QSS)
            row_tiers.addWidget(sep)
    page.btn_cost = QPushButton("▶ 跑成本敏感性")
    page.btn_cost.setStyleSheet(SUMMARY_GHOST_QSS)
    page.btn_cost.setEnabled(False)
    page.btn_cost.setCursor(Qt.CursorShape.PointingHandCursor)
    page.btn_cost.setToolTip("只对候选表**前 10 名**重跑样本外（不跑全网格）· 可随时中断\n"
                             "跑完：候选表第 9 列出现斜率 + 结论条多一行 + 本卡下方给逐档年化")
    page.btn_cost.clicked.connect(page._run_cost)
    page.btn_cost_follow = QPushButton("↺ 跟随基准")
    page.btn_cost_follow.setStyleSheet(SUMMARY_GHOST_QSS)
    page.btn_cost_follow.setCursor(Qt.CursorShape.PointingHandCursor)
    page.btn_cost_follow.setToolTip("把三档按**当前回测佣金**重排（万3 ⇒ 3 / 5 / 10）")
    page.btn_cost_follow.clicked.connect(page._follow_cost_base)
    row_tiers.addWidget(page.btn_cost_follow)
    row_tiers.addWidget(page.btn_cost)
    row_tiers.addStretch(1)
    bl.addLayout(row_tiers)

    page.lbl_cost_status = QLabel("")
    page.lbl_cost_status.setWordWrap(True)
    page.lbl_cost_status.setStyleSheet(SEC_HINT_QSS)
    bl.addWidget(page.lbl_cost_status)

    page.lbl_cost_result = QLabel("")
    page.lbl_cost_result.setWordWrap(True)
    page.lbl_cost_result.setTextFormat(Qt.TextFormat.RichText)
    bl.addWidget(page.lbl_cost_result)

    foot = QLabel("ⓘ 本仓成交成本只有**佣金**一条（滑点 / 印花税没有模型）；"
                  "回测本身目前**固定按万3** 计 —— 策略里保存的成交成本尚未接通到参数研究"
                  "（已知缺口，已登记待办）。斜率只给候选表**前 10 名**，其余行是「没跑」不是 0。")
    foot.setWordWrap(True)
    foot.setStyleSheet(SEC_HINT_QSS)
    bl.addWidget(foot)
    page.cost_card = card
    return card
