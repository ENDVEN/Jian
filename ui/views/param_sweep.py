# ui/views/param_sweep.py
"""
🧪 参数研究 —— 页面装配（§7-B15 SW-5/6/7 · 薄壳 · ★v6.86 视觉返工版）。

版式照设计稿 `design/1.58-param-sweep/`（样板是验收标准不是示意图，§11.5-85）：
- **左栏** = `sweep_form.SweepForm`：固定 306px 白卡（折叠 = 46px 竖条，展开钮常驻），
  **不用 QSplitter** —— ★返工教训：分栏宽度交给 splitter 会在真实 DPI 下塌成 0，
  设计稿本就是"306px 定宽 + 右栏吃满"。
- **右栏** = 结果区（L0 吃满，§10-14）：切块时间轴卡（图① + 图例 chips）→
  结论条（红线③：同屏不可折叠，状态配色 bad/warn/ok）→ 散点 + 热力图卡
  （**空态隐藏**：没跑完样本外之前显示占位卡，不露裸坐标轴）→ 候选表卡。
- 研究流程的编排与闸门在本页（core 层无 Qt）：两段流程（红线①）、重跑样本外
  确认闸、§8-9 存快照、§8-19 候选表三件套。
"""
from __future__ import annotations

import logging

import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QLabel,
                             QPushButton, QScrollArea, QTableWidget,
                             QVBoxLayout, QWidget)

from core.conditions import gate_expression
from core.param_sweep import SweepOutcome, SweepSpec
from core.sweep_plan import StudyInterval, build_grid, validate_interval
from core.utils import synthetic_bars
from data.market_db import DataLakeManager
from data.strategy_store import StrategyStore, segments_of
from data.sweep_archive import SweepArchive, oos_key_of, strategy_fingerprint
from ui.widgets.custom_widgets import NoWheelComboBox  # noqa: F401 （表单内使用；此处锚引用）
from ui.widgets.styles import (EMPTY_STATE_QSS, SEC_META_QSS,
                               SUMMARY_GHOST_QSS, TABLE_HEAD_QSS,
                               VERDICT_IDLE_QSS, apply_ui_font)
from ui.widgets.sweep_chart import (ChartSwitcher,  # ★R4：四视图唯一渲染器
                                    HeatmapGrid, ScatterIso)  # noqa: F401 （公共面锚引用）
from ui.widgets.sweep_input import SweepInputMixin      # ★1.66 拆件：输入侧
from ui.widgets.sweep_regimes import (SweepRegimesMixin,  # ★R3 拆件：切块与区间
                                      build_timeline_card)
from ui.widgets.sweep_snap_card import (SweepSnapshotsMixin,  # ★R5b：研究快照卡
                                        build_snapshot_card)
from ui.widgets.sweep_form import SweepForm
from ui.widgets.sweep_results import SweepResultsMixin   # ★R0 拆件：结果装配与渲染
from ui.workers import JobGuard, ParamSweepWorker

logger = logging.getLogger(__name__)

_OUR_PREF_KEY = "sweep_ui"


# ★R1 统一件：卡 / 头条 / 标题 / 提示的构造**一律**走 `ui.widgets.sweep_parts`
#   （它与左栏共用一份版式纪律；本页不再自造 `_card()` 之类私有副本）。
from ui.widgets.kpi_card import make_kpi_label, set_kpi   # ★R1：KPI 小卡与 M2 结果区同一实现
from ui.widgets.sweep_parts import (_hint, _title,  # noqa: F401
                                    panel_card, panel_head)


class ParamSweepView(SweepInputMixin, SweepRegimesMixin, SweepSnapshotsMixin,
                     SweepResultsMixin, QWidget):
    """🧪 参数研究子页签（插在 单股回测 与 全市场筛选 之间，用户定，勿改）。"""

    def __init__(self, main_win, parent=None):
        super().__init__(parent)
        apply_ui_font(self)
        self.main_win = main_win
        self._lake = DataLakeManager()
        self._store = StrategyStore()
        self._archive = SweepArchive()
        self._guard = JobGuard()
        self._worker: ParamSweepWorker | None = None
        self._stage = ""                                  # "is" / "oos"
        self._spec: SweepSpec | None = None
        self._grid = None
        self._interval: StudyInterval | None = None
        self._preset_key = "custom"
        self._is_out: SweepOutcome | None = None          # 样本内结果（本会话）
        self._oos_out: SweepOutcome | None = None         # 样本外结果（红线①：只跑一次）
        self._oos_done: set[str] = set()                  # 已跑过样本外的网格身份
        self._stats: dict | None = None
        self._matrix = None
        self._items: list[tuple[str, dict]] = []
        self._nb_table = None           # ★R5：邻域表（候选表行悬停要报"邻居是谁"）
        self._replay_rid = None         # ★R5b：正在只读回放的快照 id（None = 不在回放）
        self._ran_sig = None            # ★1.66：上一轮结果对应的"实验身份"（网格 + 区间）

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        self.form = SweepForm()
        root.addWidget(self.form)   # ★不加 stretch —— 上一版它与结果区 1:1 平分剩余宽度（右栏半宽的根因）
        # ★R6 / §7-B16 H6：**函数总库入口**（第 5 个 —— 与 M1/M2/M3/行情页同名同义同脸）。
        #   单击只唤浮窗（页面内悬浮、宿主 = 本页，1.63 H7 口径 ⇒ **不新建第二套浮窗**）。
        self.btn_hub = self.form.btn_hub
        self.btn_hub.clicked.connect(self._open_formula_hub)

        # ---- 右栏：结果区（独立滚动；L0 吃满剩余高度，§10-14）----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 10, 8)
        rl.setSpacing(10)


        # ★R1：KPI 小卡行（与 M2 结果区**同一实现** `kpi_card`）—— 结论条的文字是给"读"的，
        #   这排卡是给"扫一眼"的；两处数字同源（`sweep_results._set_verdict` 一处填）。
        self.kpi = {"n": make_kpi_label("试验数", "—", "还没跑"),
                    "is": make_kpi_label("样本内", "—"),
                    "oos": make_kpi_label("样本外", "—"),
                    "ic": make_kpi_label("Rank IC", "—", "≥0.15 才有预测力"),
                    "pbo": make_kpi_label("PBO", "—", ">0.5 等于抛硬币")}
        kpi_row = QHBoxLayout()
        kpi_row.setContentsMargins(0, 0, 0, 0)
        kpi_row.setSpacing(8)
        for _w in self.kpi.values():
            kpi_row.addWidget(_w, 1)
        rl.addLayout(kpi_row)

        # ★R3 拆件：图①（切块全景 + 「⟳ 重新切块」）整块由 `sweep_regimes` 造
        rl.addWidget(build_timeline_card(self))

        # 结论条（红线③：同屏、不可折叠；状态配色照设计稿 .verdict.bad/warn/ok）
        self.lbl_verdict = QLabel(self._idle_verdict_text())
        self.lbl_verdict.setStyleSheet(VERDICT_IDLE_QSS)
        self.lbl_verdict.setWordWrap(True)
        self.lbl_verdict.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        rl.addWidget(self.lbl_verdict)

        # 图表卡（头条 + 空态隐藏 —— 不露裸坐标轴）
        self.chart_card = panel_card()
        ch_head = panel_head("结果图",
                             "散点 = IS×OOS（冠军崩塌） · 热力图 = 参数平面（平台 vs 尖峰）")
        cl = QVBoxLayout(self.chart_card)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(2)
        cl.addWidget(ch_head)
        # ★R4 ⑥：四个画布（散点 / 热力图 + 色标 / 邻域稳健 / 滚动 IC）+ 切换 chip
        #   收进 `sweep_chart.ChartSwitcher` —— 页面只负责"装配 + 喂数"（R0 拆件纪律）。
        #   ★1.66 口径保留：图体给**硬底线**（图卡是右栏唯一弹性项 ⇒ 亏空交给滚动条）。
        self.charts = ChartSwitcher()
        chart_body = self.charts
        chart_body.setMinimumHeight(300)
        chart_body.setMaximumHeight(460)     # ★R4-c：图只占 300~460px（不把候选表顶出窗口）
        cl.addWidget(chart_body, 1)
        # 公共面**不变**：散点 / 热力图仍是页面同名属性（`sweep_results` 与冒烟照旧用它们）
        self.scatter = self.charts.scatter
        self.heatmap = self.charts.heatmap
        self.chart_empty = QLabel("图表区 —— 跑完样本内 + 样本外后出图\n"
                                  "左 = 散点 IS×OOS（离对角线越远，冠军崩塌越狠） · "
                                  "右 = 参数平面热力图（一块亮的「平台」好过一根孤立的「尖峰」）")
        self.chart_empty.setStyleSheet(EMPTY_STATE_QSS)
        self.chart_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.chart_empty.setMinimumHeight(260)
        cl.addWidget(self.chart_empty, 1)
        self.scatter.hide()
        self.heatmap.hide()
        rl.addWidget(self.chart_card)        # ★R4-c：图不吃余量（自带 300~460 的上下限）

        # 候选表卡（头条 #FAFBFD + 表头样式与 M2 同族）
        self.table_card = panel_card()
        tb_head = panel_head("候选表", "按 邻域均值 ↓, OOS ↓, |Δ| ↑ 排序；门槛只筛不排")
        self.lbl_table_head = tb_head.title_label
        self.lbl_table_meta = tb_head.meta_label
        # 存快照 = **次级动作**（1.65 口径：一页只留一颗蓝底实心主按钮 = 左栏「▶ 跑样本内」）
        self.btn_save = QPushButton("💾 存快照")
        self.btn_save.setStyleSheet(SUMMARY_GHOST_QSS)
        self.btn_save.setEnabled(False)
        tb_head.layout().addWidget(self.btn_save)
        tb = QVBoxLayout(self.table_card)
        tb.setContentsMargins(0, 0, 0, 0)
        tb.setSpacing(2)
        tb.addWidget(tb_head)
        table_body = QWidget()
        table_body.setStyleSheet("QWidget { background: #FFFFFF; }")
        tb.addWidget(table_body, 1)
        tb2 = QVBoxLayout(table_body)
        tb2.setContentsMargins(8, 8, 8, 8)
        tb2.setSpacing(6)
        # ★R5：列数 7 → **9**（补「过门槛 ✓✗」与「平台/尖峰」—— 门槛只筛不排、判定与热力图同源）
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            ["#", "参数", "OOS 年化", "IS 年化", "|Δ|", "邻域均值", "交易数", "门槛", "判定"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        for w, col in ((40, 0), (150, 1), (90, 2), (90, 3), (80, 4), (90, 5),
                       (70, 6), (52, 7), (52, 8)):
            self.table.setColumnWidth(col, w)
        self.table.verticalHeader().setDefaultSectionSize(24)
        self.table.setMinimumHeight(180)
        self.table.horizontalHeader().setStyleSheet(TABLE_HEAD_QSS)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tb2.addWidget(self.table)
        rl.addWidget(self.table_card, 1)     # ★R4-c：竖向余量归候选表（图已封顶）
        rl.addWidget(build_snapshot_card(self))   # ★R5b ⑨ 研究快照卡（列表 + 回看/置顶/删除）

        scroll.setWidget(right)
        root.addWidget(scroll, 1)

        # ---- 信号 ----
        self.btn_save.clicked.connect(self._save_snapshot)
        self.form.run_is_requested.connect(self._run_is)
        self.form.run_oos_requested.connect(self._run_oos)
        self.form.cancel_requested.connect(self._cancel)
        self.form.cb_strategy.currentIndexChanged.connect(self._on_strategy_changed)
        self.form.pick_requested.connect(self._pick_symbol)   # ★「选择」/ 回车（M1 同款）
        # 折叠按钮的连接只在 SweepForm 内部（★返工教训：view 再连一次 = 双触发互相抵消）；
        # 视图只订阅"状态变化"持久化偏好。
        self.form.collapse_changed.connect(self._persist_collapse)
        # ★用户 2026-10-01：网格/区间一变就重算"能不能跑"（闸门要**看得见**，见 `_refresh_run_enabled`）
        self.form.changed.connect(self._refresh_run_enabled)

        self._load_regimes()
        self._refresh_strategies()
        self._restore_collapse()
        self._refresh_run_enabled()          # 首屏就按闸门显示"能不能跑"

    def _open_formula_hub(self) -> None:
        """★R6：唤「ƒ 函数库」浮窗（**转发给主窗口那一个** —— 与 M1/M2/M3/行情页同一套实现，
        绝不在这里新建第二套浮窗）。浮窗只做"看 / 管函数资产"：本页策略来源**仍是**
        `strategy_store`（M1 保存的配方），不含"把某函数变成策略"（那是 M1 的活）。"""
        win = getattr(self.main_win, "window", None)
        target = self.main_win.window() if callable(win) else self.main_win
        if hasattr(target, "show_formula_hub_panel"):
            target.show_formula_hub_panel()

    # ================= 闸门要看得见 =================
    def _refresh_run_enabled(self) -> None:
        """网格 / 区间不合规 ⇒ **禁用「▶ 跑样本内」+ 就地写原因**。

        ★用户 2026-10-01 实测根因：`L1 起5 止20 步1` = **16 档 > 上限 15** ⇒ 网格被闸门拒、
        `_build_study()` 直接返回 ⇒ 右边结果图当然不变；但运行按钮**照样能点**、原因只躲在
        一行小灰字里 ⇒ 用户判定"坏了 / 没重构完"。现在：拦住时按钮禁用 + 橙字一行说明 +
        tooltip 同句（一句话：**闸门的拒绝必须落在用户正在看的地方**）。
        """
        self._invalidate_if_changed()        # ★1.66：网格/区间变了 ⇒ 上一轮结果作废
        _dims, err = self.form.grid_dims()
        why = str(err or "")
        if not why:
            problems = validate_interval(self.form.interval())
            why = problems[0] if problems else ""
        self.form.set_run_blocked(why)

    # ================= 实验身份（★1.66）=================
    def _experiment_signature(self):
        """**这一次实验**的身份 = 网格（维名 + 档位）+ 区间四日期（网格不合法 ⇒ None）。"""
        dims, err = self.form.grid_dims()
        if err:
            return None
        iv = self.form.interval()
        return (tuple((d.name, tuple(d.values)) for d in dims),
                iv.is_start, iv.is_end, iv.oos_start, iv.oos_end,
                tuple(getattr(iv, "more", ()) or ()))      # ★R7：合并窗口也算实验身份

    def _invalidate_if_changed(self) -> None:
        """网格 / 区间一变 ⇒ 上一轮结果**作废**，并明确让用户重跑。

        ★1.66（用户实测「改参数、改区间后再跑，右边图表都不动」的真因）：两段结果会
        **跨轮次累积**，改了网格后交集里混进旧格子 ⇒ 邻域矩阵（按当前网格）与 values 长度
        不匹配 ⇒ `ValueError` 被 Qt 槽吞掉 ⇒ 图表**静默不动**。修法两层：
        ① 结果与"实验身份"绑定（这里作废 + `sweep_results` 只认当前网格的格子）；
        ② 统计装配异常一律**说出来**（不许静默）。
        """
        sig = self._experiment_signature()
        if sig is None or self._ran_sig is None or sig == self._ran_sig:
            return
        if self._worker is not None and self._worker.isRunning():
            return                          # 跑的过程中不动（结束时会刷新身份）
        self._is_out = None
        self._oos_out = None
        self._stats = None
        self._matrix = None
        self._items = []
        self._ran_sig = None
        self.btn_save.setEnabled(False)
        self.form.set_oos_enabled(False)
        self.chart_empty.show()
        self.scatter.hide()
        self.scatter.set_data([], [])       # 连图元一起清（不留上一轮的假现场）
        self.heatmap.hide()
        self.table.setRowCount(0)
        self.lbl_verdict.setStyleSheet(VERDICT_IDLE_QSS)
        self.lbl_verdict.setText(self._idle_verdict_text())
        for _key, _lab, _sub in (("n", "试验数", "还没跑"), ("is", "样本内", ""),
                                 ("oos", "样本外", ""),
                                 ("ic", "Rank IC", "≥0.15 才有预测力"),
                                 ("pbo", "PBO", ">0.5 等于抛硬币")):
            set_kpi(self.kpi[_key], _lab, "—", _sub)
        self.form.set_receipt("网格 / 样本区间已改 ⇒ 上一轮结果作废，"
                              "请重新 ▶ 跑样本内 → ▶ 跑样本外（样本外按新网格才作数）")

    def _build_study(self) -> tuple[SweepSpec, object, StudyInterval] | None:
        payload = self.form.strategy_payload()
        symbol = self.form.symbol()
        if not symbol:
            self.form.set_receipt("先填标的代码")
            return None
        if payload is None:
            self.form.set_receipt("先选一个 M1 已保存的策略（只列带条件的配方）")
            return None
        if payload.get("index"):
            self.form.set_receipt("该策略带指数门控，本页暂不支持（红线：不复刻阶段C 门控）")
            return None
        # ★1.66：条件在**运行前**就地判空 —— 配置 → DSL 是 `core.conditions` 的事，
        #   空条件到不了引擎（否则引擎会抛"不是表达式"的怪错，用户看不懂）。
        if not gate_expression(payload.get("condition_buy")) or \
                not gate_expression(payload.get("condition_sell")):
            self.form.set_receipt("该策略的买卖条件为空（或条件行没配好）⇒ 没有可回测的东西；"
                                  "先在 M1 配好买卖条件再存策略")
            return None
        dims, dim_err = self.form.grid_dims()
        if dim_err:
            self.form.set_receipt(f"参数网格：{dim_err}")
            return None
        grid = build_grid(dims)
        if not grid.ok:
            self.form.set_receipt(f"参数网格：{grid.rejection}")
            return None
        iv = self.form.interval()
        df = self._lake.load_data("kline_daily", symbol)
        data_start = data_end = ""
        if df is not None and not df.empty and "date" in df.columns:
            d = pd.to_datetime(df["date"])
            data_start, data_end = str(d.min().date()), str(d.max().date())
        problems = list(validate_interval(iv, data_start, data_end))
        if df is None or df.empty:
            problems.insert(0, f"本地没有 {symbol} 的前复权日线 —— 先去 🗄 数据管理 预下载")
        if problems:
            self.form.set_interval_receipt("；".join(problems))
            self.form.set_receipt("区间没过校验，先解决上面的问题")
            return None
        self.form.set_interval_receipt(f"区间 OK（本地数据 {data_start} → {data_end}）")
        spec = SweepSpec(
            symbol=symbol,
            segments=segments_of(payload),
            params_text=str(payload.get("params_text") or ""),
            # ★1.66：条件**原样**递过去（是**配置 dict**，不是字符串）—— 旧版在这里 `str(...)`，
            #   dict 被转成 repr 文本（"{'rule': 'rise', …}"）⇒ 引擎 `parse` 报
            #   "无法识别的字符 '{'" ⇒ **每一组都失败**（点运行只看到"完成 0 组，失败 N 组"）。
            #   配置 → DSL 的转换由 `core.conditions` 在求值前统一做（唯一真源）。
            condition_buy=payload.get("condition_buy") or "",
            condition_sell=payload.get("condition_sell") or "",
            risk=dict(payload.get("risk") or {}),
            fill_mode=(payload.get("fill") or {}).get("fill_mode"),
            trigger_tick=(payload.get("fill") or {}).get("trigger_tick"),
            has_index_gate=bool(payload.get("index")))
        self._spec, self._grid, self._interval = spec, grid, iv
        self._preset_key = self.form.preset_key()
        return spec, grid, iv

    def _start_worker(self, stage: str, done_keys: frozenset) -> None:
        spec, grid, iv = self._spec, self._grid, self._interval
        df = self._lake.load_data("kline_daily", spec.symbol)
        self._stage = stage
        self.form.set_running(True)
        job = self._guard.next()
        self._worker = ParamSweepWorker(job, df, spec, grid, iv, stage=stage,
                                        done_keys=done_keys)
        self._worker.progress.connect(self.form.set_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _run_is(self) -> None:
        if self._build_study() is None:
            return
        done = frozenset(self._is_out.completed) if self._is_out else frozenset()
        self._start_worker("is", done)

    def _run_oos(self) -> None:
        if self._build_study() is None:
            return
        if not self._is_out or not self._is_out.completed:
            self.form.set_receipt("先跑样本内（红线①：样本内选、样本外验一次）")
            return
        sig = self.form.grid_signature(strategy_fingerprint(self._spec))
        usage = self._archive.oos_usage(self._oos_key())
        if sig in self._oos_done or usage >= 1:
            if not self._confirm_pollution(usage):
                self.form.set_receipt("已取消 —— 样本外保持只跑一次（红线①）")
                return
        done = frozenset(self._oos_out.completed) if self._oos_out else frozenset()
        self._start_worker("oos", done)

    def _oos_key(self) -> str:
        if self._spec is None or self._interval is None:
            return ""
        return oos_key_of(self._spec.symbol, strategy_fingerprint(self._spec),
                          self._interval.oos_start, self._interval.oos_end)

    def _confirm_pollution(self, usage: int) -> bool:
        from PyQt6.QtWidgets import QMessageBox
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("重跑样本外 = 污染样本外")
        box.setText(f"这个网格身份的样本外已经跑过（本机已有 {max(usage, 1)} 项研究引用过"
                    f"同一 (标的, 策略, 样本外窗口)）。\n\n"
                    "再用它挑参数，样本外就变成了样本内 —— 研究结果失去意义。\n"
                    "确定要重跑吗？（默认：否）")
        box.setStandardButtons(QMessageBox.StandardButton.Yes
                               | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    def _cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.form.set_receipt("正在中断（当前组跑完就停，已完成的组保留可续）…")

    # ================= 回包 =================
    def _on_failed(self, job: int, reason: str) -> None:
        if not self._guard.accept(job):
            return
        self.form.set_running(False)
        self.form.set_receipt(f"参数扫描失败：{reason}")

    def _on_finished(self, job: int, outcome) -> None:
        if not self._guard.accept(job) or outcome is None:
            self.form.set_running(False)
            return
        self.form.set_running(False)
        merged_notes = list(outcome.notes)
        n_fail = len(outcome.failed)
        if outcome.failed:
            merged_notes.append(f"{n_fail} 组失败（详见回执）")
        if self._stage == "is":
            base = self._is_out or SweepOutcome()
            base.completed.update(outcome.completed)
            base.failed.update(outcome.failed)
            base.notes = merged_notes
            base.cancelled = outcome.cancelled
            self._is_out = base
            n_done = len(base.completed)
            self.form.set_distribution([co.trades for co in base.completed.values()],
                                       self.form.min_trades())
            self.form.set_oos_enabled(n_done > 0)
            tail = "（可中断续跑）" if outcome.cancelled else ""
            self.form.set_receipt(
                f"样本内完成 {n_done} 组{ '，失败 %d 组' % n_fail if n_fail else ''}{tail}。"
                "调好门槛后 → ▶ 跑样本外（只跑一次）")
        else:
            base = self._oos_out or SweepOutcome()
            base.completed.update(outcome.completed)
            base.failed.update(outcome.failed)
            base.notes = merged_notes
            base.cancelled = outcome.cancelled
            self._oos_out = base
            self._oos_done.add(self.form.grid_signature(
                strategy_fingerprint(self._spec or SweepSpec("", (), "", "", ""))))
            self._compute_and_show()
        self._ran_sig = self._experiment_signature()   # ★1.66：记住"这批结果属于哪个实验"
        if getattr(self, "_replay_rid", None):         # ★R5b：真跑 ⇒ 自动退出只读回放态
            self._replay_rid = None
            if getattr(self, "_chart_empty_backup", None):
                self.chart_empty.setText(self._chart_empty_backup)
        self._stage = ""

    # ================= 折叠（§8-13；展开钮长在竖条上，永不消失）=================
    def _restore_collapse(self) -> None:
        try:
            from core.preferences import preferences
            state = preferences.get(_OUR_PREF_KEY) or {}
            self.set_panel_collapsed(bool(state.get("panel_collapsed", False)))
        except Exception:  # noqa: BLE001 —— 偏好坏了不拖垮页面
            pass

    def set_panel_collapsed(self, collapsed: bool) -> None:
        self.form.set_panel_collapsed(collapsed)

    def is_panel_collapsed(self) -> bool:
        return self.form.is_panel_collapsed()

    def toggle_panel_collapsed(self) -> None:
        """供测试/外部调用；真按钮走 form 内部连接 + collapse_changed 持久化。"""
        self.form.toggle_panel_collapsed()

    def _persist_collapse(self, collapsed: bool) -> None:
        try:
            from core.preferences import preferences
            state = dict(preferences.get(_OUR_PREF_KEY) or {})
            state["panel_collapsed"] = bool(collapsed)
            preferences.set(_OUR_PREF_KEY, state)
        except Exception:  # noqa: BLE001
            pass
