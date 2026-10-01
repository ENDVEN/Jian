# ui/widgets/sweep_form.py
"""
参数稳健性研究（§7-B15）· 左栏研究设置面板（SW-5）。

视觉规格 = `design/1.58-param-sweep/`（**样板是验收标准不是示意图**，§11.5-85）：
- 固定 **306px** 白卡（`PANEL_CARD_QSS`：1px #E6EAF0 + 14px 圆角），头部「研究设置」+
  折叠钮；卡体垂直滚动（六步表单在矮窗口下也全部可达）。
- **折叠态 = 46px 竖条**（照样板 `.panel.collapsed .strip`）：展开钮**长在竖条上**、
  永不消失 —— ★v6.86 返工教训：旧版把展开钮放在被隐藏的卡体里 = 收起即死胡同。
- 六步（方案书 §3，顺序用户定）：标的 → 策略 → 参数网格 → 样本区间 → 门槛 → 运行。
  本件**只管输入与展示**；流程/统计/存档在 `ui/views/param_sweep.py` 编排。
- §10-9：数值控件一律 `custom_widgets` 工厂（最小宽 72px）；样式全部取自 `styles.py`。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                             QLineEdit, QProgressBar, QPushButton, QScrollArea,
                             QSizePolicy, QSlider, QVBoxLayout, QWidget)

from core.index_regimes import (DEFAULT_KIND, IntervalPreset, kind_entries,  # ★R2：预设组织
                                windows_of)
from core.sweep_plan import (MAX_COMBOS, MAX_DIMS, REF_BARS,
                             estimate_seconds, make_dimension)
from ui.widgets.custom_widgets import (NoWheelComboBox, NoWheelDateEdit,
                                       NoWheelDoubleSpinBox)
from ui.widgets.sweep_chart import TradesDistribution
from ui.widgets.styles import (FLAT_QSS, FLAT_QSS_DANGER, PANEL_CARD_QSS,
                               PANEL_HEAD_QSS, SEC_HINT_QSS, SEC_META_QSS,
                               SEC_TITLE_QSS, STEP_BADGE_QSS, SUMMARY_RUN_QSS,
                               WARN_HINT_QSS, apply_ui_font)

PANEL_WIDTH = 306      # 设计稿 .panel 的定宽
STRIP_WIDTH = 46       # 设计稿 .panel.collapsed 的竖条宽

_PARAM_KEYS_HINT = "（先选策略；带参数的配方才能扫）"


# ★R2 拆件：构件原语（提示行 / 节标题 / 步号徽标 / 分隔线 / 可收缩包装）已搬到
#   `ui.widgets.sweep_parts`，两边共用一份版式纪律 —— 这里**同名再导出**，
#   本文件既有的几十处 `_hint()/_sep()/_step_title()/_shrink()` 调用一行不改。
from ui.widgets.sweep_parts import (_hint, _sep, _shrink,  # noqa: F401
                                    _step_title, _title, _widen_popup)
from ui.widgets.sweep_run_form import SweepRunPanel


class SweepForm(QWidget):
    """左栏研究设置面板：输入 + 实时回执；对视图只暴露信号与 getter。"""

    # 运行信号（`run_is/oos/cancel_requested`）由 `SweepRunPanel` 提供，
    # 本类在 __init__ 里以**别名**转发 ⇒ 页面照旧 `form.run_is_requested.connect(…)`。
    changed = pyqtSignal()                     # 网格/区间变了（页面据此 gate 跑按钮）
    pick_requested = pyqtSignal()              # ★选标的（回车 / 「选择」按钮 —— M1 同款）
    preset_changed = pyqtSignal(str)           # 预设 key
    collapse_changed = pyqtSignal(bool)        # 折叠态变化（视图持久化偏好；连接只此一处）

    def __init__(self, parent=None):
        super().__init__(parent)
        apply_ui_font(self)
        self._presets: list[IntervalPreset] = []
        self._collapsed = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.panel = QFrame()
        self.panel.setObjectName("panelCard")
        self.panel.setStyleSheet(PANEL_CARD_QSS)
        self.panel.setFixedWidth(PANEL_WIDTH)
        root.addWidget(self.panel, 1)   # ★stretch 1：面板吃满高度（否则被自家 stretch 压成矮条）

        pl = QVBoxLayout(self.panel)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)

        # ---- 头部（常驻：折叠时它随卡体一起隐藏，由竖条接管）----
        self.head = QFrame()
        self.head.setObjectName("panelHead")
        self.head.setStyleSheet(PANEL_HEAD_QSS)
        hl = QHBoxLayout(self.head)
        hl.setContentsMargins(12, 9, 8, 9)
        hl.addWidget(_title("🧪 研究设置"))
        hl.addStretch(1)
        self.btn_collapse = QPushButton("«")
        self.btn_collapse.setStyleSheet(FLAT_QSS)
        self.btn_collapse.setFixedWidth(30)
        self.btn_collapse.setToolTip("收起左栏（跑完内/外后收起来看结果）")
        hl.addWidget(self.btn_collapse)
        pl.addWidget(self.head)

        # ---- 折叠竖条（46px；展开钮长在这里 —— 永不消失）----
        self.strip = QFrame()
        self.strip.setObjectName("panelCard")
        self.strip.setStyleSheet(PANEL_CARD_QSS)
        self.strip.setFixedWidth(STRIP_WIDTH)
        self.strip.setVisible(False)
        sl = QVBoxLayout(self.strip)
        sl.setContentsMargins(0, 8, 0, 8)
        sl.setSpacing(6)
        self.btn_expand = QPushButton("»")
        self.btn_expand.setStyleSheet(FLAT_QSS)
        self.btn_expand.setFixedWidth(30)
        sl.addWidget(self.btn_expand, 0, Qt.AlignmentFlag.AlignHCenter)
        self.strip_title = QLabel("\n".join("研究设置"))
        self.strip_title.setStyleSheet(SEC_HINT_QSS)
        self.strip_title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        sl.addWidget(self.strip_title, 0, Qt.AlignmentFlag.AlignHCenter)
        sl.addStretch(1)
        root.addWidget(self.strip, 1)   # 竖条态同样吃满高度

        # ---- 卡体：垂直滚动，六步永远可达；**横向不许滚**（306 定宽内收缩，★返工教训）----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setStyleSheet("QWidget { background: #FFFFFF; }")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(12, 10, 12, 12)
        bl.setSpacing(9)
        self._build_steps(bl)
        bl.addStretch(1)
        scroll.setWidget(body)
        pl.addWidget(scroll, 1)

        # ---- 信号 ----
        self.btn_collapse.clicked.connect(self.toggle_panel_collapsed)
        self.btn_expand.clicked.connect(self.toggle_panel_collapsed)
        self.cb_preset.currentIndexChanged.connect(self._on_preset)
        for d in self._dim_rows:
            for w in (d["start"], d["stop"], d["step"]):
                w.valueChanged.connect(self._refresh_combos)
            d["name"].currentIndexChanged.connect(self._refresh_combos)
        self._refresh_combos()

    # ================= 六步表单 =================
    def _build_steps(self, bl: QVBoxLayout) -> None:
        # ---- ① 标的 ----
        bl.addWidget(_step_title(1, "标的"))
        self.in_symbol = QLineEdit()
        # ★用户 2026-10-01 追加需求：标的行要**像 M1 一样** —— 手输（回车即选）+ 一颗「选择」按钮，
        #   选好后给 M1 同款的文字提示（`贵州茅台 (600519) · 已缓存`）。口径在
        #   `ui.widgets.symbol_pick`（M1 与本站共用一份，别各写一套提示文案）。
        self.in_symbol.setPlaceholderText("搜索 A股代码 / 名称，回车选择")
        self.in_symbol.returnPressed.connect(self.pick_requested)
        row_sym = QHBoxLayout()
        row_sym.setSpacing(4)
        row_sym.addWidget(_shrink(self.in_symbol), 1)
        self.btn_pick = QPushButton("选择")
        self.btn_pick.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pick.setStyleSheet(FLAT_QSS)
        self.btn_pick.setToolTip("按代码或名称在花名册里查一只 A 股（与「📈 单股回测」同一套口径）")
        self.btn_pick.clicked.connect(self.pick_requested)
        row_sym.addWidget(self.btn_pick)
        bl.addLayout(row_sym)
        self.lbl_symbol = _hint("未选择标的 —— 填代码后点「选择」，或从策略带入")
        bl.addWidget(self.lbl_symbol)
        self.lbl_data = _hint()
        bl.addWidget(self.lbl_data)

        # ---- ② 策略 ----
        bl.addWidget(_sep())
        bl.addWidget(_step_title(2, "策略（只列 M1 已保存的配方）"))
        self.cb_strategy = NoWheelComboBox()
        bl.addWidget(_shrink(self.cb_strategy))
        self.lbl_params = _hint()
        self.lbl_params.setText(_PARAM_KEYS_HINT)
        bl.addWidget(self.lbl_params)

        # ---- ③ 参数网格 ----
        bl.addWidget(_sep())
        bl.addWidget(_step_title(3, "参数网格"))
        self._dim_rows: list[dict] = []
        for i in range(MAX_DIMS):
            self._dim_rows.append(self._build_dim_row(bl, second=(i == 1)))
        self.set_dim2_visible(False)
        self.lbl_combos = _hint()
        bl.addWidget(self.lbl_combos)

        # ---- ④ 样本区间 ----
        bl.addWidget(_sep())
        bl.addWidget(_step_title(4, "样本区间（内调 → 外验）"))
        # ★R2：**三级**（口径 → 窗口 → 取近 N 组），不再平铺几十条（用户："太长太长"）。
        #   口径 = 单边上涨 / 单边下跌 / 震荡箱体 / 自定义；窗口 = 该口径下的窗口（近 N 组，
        #   标签带四日期）；`取近` = 3/5/10/全部（默认 5，用户 2026-10-01 拍板）。
        self.cb_interval_kind = _shrink(NoWheelComboBox())
        bl.addWidget(self.cb_interval_kind)
        _widen_popup(self.cb_interval_kind)     # ★弹层加宽（长标签后半截看不见）
        self.lbl_why = _hint()
        bl.addWidget(self.lbl_why)
        self.cb_preset = _shrink(NoWheelComboBox())    # 窗口（名字保留：既有断言与调用点不动）
        bl.addWidget(self.cb_preset)
        _widen_popup(self.cb_preset)                   # ★弹层加宽：长标签后半截看得见
        self._recent_row = QHBoxLayout()
        self.lbl_recent = QLabel("取近")
        self.lbl_recent.setStyleSheet(SEC_HINT_QSS)
        self.cb_recent_n = _shrink(NoWheelComboBox())
        for _lbl, _val in (("3 组", 3), ("5 组", 5), ("10 组", 10), ("全部", 0)):
            self.cb_recent_n.addItem(_lbl, _val)
        self.cb_recent_n.setCurrentIndex(1)            # 默认 5 组
        self._recent_row.addWidget(self.lbl_recent)
        self._recent_row.addWidget(self.cb_recent_n)
        self._recent_row.addStretch(1)
        bl.addLayout(self._recent_row)
        self.cb_interval_kind.currentIndexChanged.connect(self._on_kind_changed)
        self.cb_recent_n.currentIndexChanged.connect(self._on_recent_changed)
        # ★用户 2026-10-01：四日期改**两行两框 + 箭头**（内 / 外）。
        #   旧版 2×2 网格 + `Ignored` 收缩策略把 "2024-12-30" 挤成了 "201"（用户截图实锤
        #   "塞得看不完整"）；且 2×2 里"起/止"两个词各自还占一格，信息密度低。
        self.dt_is_start, self.dt_is_end = NoWheelDateEdit(), NoWheelDateEdit()
        self.dt_oos_start, self.dt_oos_end = NoWheelDateEdit(), NoWheelDateEdit()
        for _tag, _w0, _w1 in (("内", self.dt_is_start, self.dt_is_end),
                               ("外", self.dt_oos_start, self.dt_oos_end)):
            for _w in (_w0, _w1):
                _w.setCalendarPopup(True)
                _w.setDisplayFormat("yyyy-MM-dd")
                _w.setMinimumWidth(104)      # 够显示 yyyy-MM-dd（旧版被压到约 50px ⇒ 只见 "201"）
                _w.dateChanged.connect(lambda *_a: self._refresh_combos())
            _rr = QHBoxLayout()
            _rr.setSpacing(4)
            _tag_w = QLabel(_tag)
            _tag_w.setStyleSheet(SEC_META_QSS)
            _arrow = QLabel("→")
            _arrow.setStyleSheet(SEC_META_QSS)
            _rr.addWidget(_tag_w)
            _rr.addWidget(_w0, 1)
            _rr.addWidget(_arrow)
            _rr.addWidget(_w1, 1)
            bl.addLayout(_rr)
        self.lbl_interval = _hint()
        bl.addWidget(self.lbl_interval)

        # ---- ⑤ 门槛 + ⑥ 运行（★R2 拆件：整块搬进 `sweep_run_form.SweepRunPanel`）----
        self.run_panel = SweepRunPanel()
        bl.addWidget(self.run_panel)
        # 公共面**别名转发**：页面与既有断言照旧读/调这些名字（一行都不用改）。
        self.sl_gate = self.run_panel.sl_gate
        self.lbl_gate = self.run_panel.lbl_gate
        self.lbl_gate_hint = self.run_panel.lbl_gate_hint
        self.dist_chart = self.run_panel.dist_chart
        self.btn_run_is = self.run_panel.btn_run_is
        self.btn_run_oos = self.run_panel.btn_run_oos
        self.btn_cancel = self.run_panel.btn_cancel
        self.progress = self.run_panel.progress
        self.lbl_receipt = self.run_panel.lbl_receipt
        self.run_is_requested = self.run_panel.run_is_requested
        self.run_oos_requested = self.run_panel.run_oos_requested
        self.cancel_requested = self.run_panel.cancel_requested
        self.min_trades = self.run_panel.min_trades
        self.set_distribution = self.run_panel.set_distribution
        self.set_running = self.run_panel.set_running
        self.set_oos_enabled = self.run_panel.set_oos_enabled
        self.set_progress = self.run_panel.set_progress
        self.set_receipt = self.run_panel.set_receipt
        self.set_run_blocked = self.run_panel.set_blocked   # ★闸门要看得见
        self.blk_reason = self.run_panel.blk_reason

    # ================= getter（视图用）=================
    def symbol(self) -> str:
        return self.in_symbol.text().strip()

    def strategy_payload(self) -> dict | None:
        return self.cb_strategy.currentData()

    def preset_key(self) -> str:
        return str(self.cb_preset.currentData() or "custom")


    def _build_dim_row(self, bl: QVBoxLayout, second: bool) -> dict:
        """一维网格 = 参数名一行 + [起][止][步] 一行 + **本维档位提示**（★用户 2026-10-01 重设计）。

        旧版把"起/止/步"做成三个**独立灰字标签** + 三枚被 `Ignored` 收缩的框 ⇒ 306px 里
        「标签 + 框」×3 必然挤扁（用户截图："塞得看不完整"）。新版：**标签进框做前缀**
        （`起 5.0`），三框等分拉伸（每个 ≈88px，字看得全），且每维下面直说"共几档 / 超没超限"。
        """
        cb = _shrink(NoWheelComboBox())
        cb.addItem("（不用第 2 维）" if second else "（选参数）")
        cb.currentIndexChanged.connect(self._refresh_combos)
        bl.addWidget(cb)
        # ★用户 2026-10-01（第二版）：三框挤一行时每枚只剩 ~86px，而「起25.00 + 上下箭头」
        #   实测需要 96px ⇒ 末位仍被挤掉（用户截图「起 5.0C」）。改成**两行**：
        #   第 1 行 起 / 止（各 ≥120px），第 2 行 步 + 本维档位提示（同行，不额外占高度）。
        spins = {}
        widgets = [cb]
        row1 = QHBoxLayout()
        row1.setSpacing(4)
        for kind, lo, hi, val in (("起", 0.0, 1e6, 5.0), ("止", 0.0, 1e6, 25.0)):
            sp = self._make_dim_spin(kind, lo, hi, val)
            row1.addWidget(sp, 1)
            spins[kind] = sp
            widgets.append(sp)
        bl.addLayout(row1)
        row2 = QHBoxLayout()
        row2.setSpacing(4)
        sp_step = self._make_dim_spin("步", 0.01, 1e4, 5.0)
        row2.addWidget(sp_step, 1)
        spins["步"] = sp_step
        widgets.append(sp_step)
        dim_hint = _hint()
        row2.addWidget(dim_hint, 1)
        widgets.append(dim_hint)
        bl.addLayout(row2)
        return {"name": cb, "start": spins["起"], "stop": spins["止"], "step": spins["步"],
                "hint": dim_hint, "row_widgets": widgets}

    def _make_dim_spin(self, kind: str, lo: float, hi: float, val: float):
        """一枚网格数值框：**前缀进框**（标签不另占一列）+ 最小宽 96px。

        96 = 前缀「起」+ 值「25.00」+ 右侧上下箭头 18px + 内边距（实测值，见冒烟断言）——
        低于它末位字符就会被箭头挤掉（用户截图实锤）。
        """
        sp = NoWheelDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setDecimals(2)
        sp.setPrefix(kind)
        sp.setMinimumWidth(96)
        sp.setValue(val)
        sp.valueChanged.connect(lambda *_a: self._refresh_combos())
        return sp

    # ================= 折叠（§8-13；展开钮长在竖条上，永不消失）=================
    def set_panel_collapsed(self, collapsed: bool) -> None:
        self._collapsed = bool(collapsed)
        self.head.setVisible(not self._collapsed)
        self.panel.setVisible(not self._collapsed)
        self.strip.setVisible(self._collapsed)

    def is_panel_collapsed(self) -> bool:
        return self._collapsed

    def toggle_panel_collapsed(self) -> None:
        self.set_panel_collapsed(not self._collapsed)
        self.collapse_changed.emit(self._collapsed)

    # ================= 内部 =================
    def _refresh_combos(self) -> None:
        """网格即时反馈（逐维档位 + 组合数 + 预计耗时），并广播 `changed`。

        ★用户 2026-10-01：旧版只在**一行小灰字**里说"16 档超限"，按钮却照样能点 ⇒
        "我怎么点都没反应"。现在：**逐维**给档位（超限的维度自己变橙字），并广播 `changed`
        让页面把「▶ 跑样本内」禁用掉、把原因写在按钮旁边。
        """
        for i, d in enumerate(self._dim_rows):
            hint_w = d.get("hint")
            if hint_w is None:
                continue
            name = str(d["name"].currentText() or "").strip()
            if i == 1 and name in ("", "（不用第 2 维）"):
                hint_w.setVisible(False)
                continue
            if name in ("", "（选参数）", "（无可扫描参数）"):
                hint_w.setVisible(False)
                continue
            dim, msg = make_dimension(name, d["start"].value(), d["stop"].value(),
                                      d["step"].value())
            hint_w.setVisible(True)
            hint_w.setText(msg or f"共 {dim.n_levels} 档")
            hint_w.setStyleSheet(WARN_HINT_QSS if msg else SEC_HINT_QSS)
        dims, err = self.grid_dims()
        if err:
            self.lbl_combos.setText(err)
            self.changed.emit()
            return
        n = 1
        for d in dims:
            n *= d.n_levels
        est = estimate_seconds(n)
        self.lbl_combos.setText(
            f"组合数 {n} · 预计约 {est:.0f} 秒（每组 2 段 × {REF_BARS} 根 ≈55ms 口径）"
            + ("  ⚠ 网格超限，运行时会被拦" if n > MAX_COMBOS else ""))
        self.changed.emit()



    # ================= 供视图调用的 setter =================
    def set_data_receipt(self, text: str) -> None:
        self.lbl_data.setText(text)

    def set_symbol(self, text: str) -> None:
        """带入标的（页面从策略保存值取；只在用户没填时调，见 `_on_strategy_changed`）。"""
        self.in_symbol.setText(str(text or ""))

    def set_symbol_hint(self, text: str) -> None:
        """标的行的**文字提示**（M1 同款：`贵州茅台 (600519) · 已缓存`）。"""
        self.lbl_symbol.setText(str(text or ""))

    def set_strategies(self, payloads: list[dict]) -> None:
        self.cb_strategy.blockSignals(True)
        self.cb_strategy.clear()
        for p in payloads:
            label = str(p.get("name") or "未命名")
            if p.get("index"):
                label += "（指数门控 — 本页暂不支持）"
            self.cb_strategy.addItem(label, p)
        self.cb_strategy.blockSignals(False)

    def set_param_chips(self, text: str) -> None:
        self.lbl_params.setText(text or _PARAM_KEYS_HINT)

    def set_param_options(self, names: list[str]) -> None:
        for i, d in enumerate(self._dim_rows):
            cb = d["name"]
            cb.blockSignals(True)
            cb.clear()
            if i == 0:
                cb.addItems(names or ["（无可扫描参数）"])
            else:
                cb.addItem("（第 2 维不用）")
                cb.addItems(names or [])
                cb.setCurrentIndex(0)
            cb.blockSignals(False)
        self._refresh_combos()

    def set_dim2_visible(self, visible: bool) -> None:
        self._dim_rows[1]["name"].setVisible(visible)
        for w in self._dim_rows[1]["row_widgets"]:
            w.setVisible(visible)

    def set_regime_presets(self, presets: list[IntervalPreset],
                           entries: list[dict] | None = None) -> None:
        """装"口径 → 窗口 → 取近 N 组"三级（★R2；`entries` = `kind_entries(presets)`）。

        ⚠ **首次装配必须立刻把所选口径的那一对日期灌进四格** —— 否则"下拉显示一个窗口、
          四格还是控件初值" ⇒ 区间校验必报"重叠 / 早于本地数据" ⇒ 点运行**永远被拒**
          （§11.5-112 ③ 的真实事故）。下拉显示什么，四格就必须是什么。
        ⚠ 只在**首次**装配时套默认：之后切页回来保留用户自己选的口径与窗口。
        """
        first_time = not getattr(self, "_all_presets", None)
        self._all_presets = list(presets or [])
        self._entries = list(entries if entries is not None
                             else kind_entries(self._all_presets))
        if first_time:
            self.cb_interval_kind.blockSignals(True)
            self.cb_interval_kind.clear()
            for e in self._entries:
                self.cb_interval_kind.addItem(e["label"], e["kind"])
            self.cb_interval_kind.addItem("自定义（手工填四格日期）", "custom")
            idx = next((i for i, e in enumerate(self._entries) if e["kind"] == DEFAULT_KIND),
                       0 if self._entries else -1)
            if idx >= 0:
                self.cb_interval_kind.setCurrentIndex(idx)
            self.cb_interval_kind.blockSignals(False)
        self._apply_kind(apply_default=first_time)

    def _apply_kind(self, apply_default: bool = False) -> None:
        """按当前口径重建窗口下拉（受"取近 N 组"过滤）+ 刷新 why + 落日期。

        "自定义"口径 ⇒ 藏起窗口/取近两个控件（四格由用户或切块时间轴填）。
        """
        kind = str(self.cb_interval_kind.currentData() or "")
        custom = kind == "custom"
        entry = next((e for e in self._entries if e["kind"] == kind), None)
        self.lbl_why.setText("手工填下面四个日期（样本内起点/终点 · 样本外起点/终点）"
                             if custom else str((entry or {}).get("why") or ""))
        self.lbl_why.setVisible(bool(self.lbl_why.text()))
        for w in (self.cb_preset, self.lbl_recent, self.cb_recent_n):
            w.setVisible(not custom)
        if custom:
            self._presets = []
            return
        n = self.cb_recent_n.currentData() or 0
        self._presets = windows_of(self._all_presets, kind, None if int(n) == 0 else int(n))
        self.cb_preset.blockSignals(True)
        self.cb_preset.clear()
        for p in self._presets:
            self.cb_preset.addItem(("★ " if p.default else "") + self._window_label(p), p.key)
        if (apply_default or self.cb_preset.currentIndex() < 0) and self._presets:
            # 默认窗口 = 缓存标了 default 的那条（= 最近一段"震荡→震荡"）；没标 ⇒ 取最近一条
            self.cb_preset.setCurrentIndex(
                next((i for i, p in enumerate(self._presets) if p.default), 0))
        self.cb_preset.blockSignals(False)
        if self._presets:
            self._on_preset(self.cb_preset.currentIndex())
        else:
            self.lbl_interval.setText(
                "本机切块缓存里这个口径没有成对窗口 —— 换个口径，或到右栏「区间全景」里点一段选区间")

    @staticmethod
    def _window_label(p: IntervalPreset) -> str:
        """窗口项标签 = **只给四日期**。

        ⚠ 旧版把"…里调 · …里验"那句原样带上（几十条同文案，且太长）⇒ 下拉里**后半截看不见**
          （用户 2026-10-01 实测）。口径已在上面的下拉里选过了，这里只需回答"哪一段"。
        """
        return f"{p.is_start} → {p.is_end} ‖ {p.oos_start} → {p.oos_end}"

    def _on_kind_changed(self, *_a) -> None:
        """口径变了 ⇒ 重建窗口 + 落该口径的默认窗口日期（用户切口径就是一次完整选择）。"""
        self._apply_kind(apply_default=True)

    def _on_recent_changed(self, *_a) -> None:
        """"取近 N 组"变了 ⇒ 重建窗口，尽量保住当前那条（不在新列表里才回默认）。"""
        keep = self.cb_preset.currentData()
        self._apply_kind(apply_default=False)
        idx = self.cb_preset.findData(keep) if keep else -1
        if idx >= 0:
            self.cb_preset.setCurrentIndex(idx)
            self._on_preset(idx)

    def select_custom(self) -> None:
        """切到"自定义"口径（切块时间轴点段后调它，再落四格日期）。"""
        idx = self.cb_interval_kind.findData("custom")
        if idx >= 0:
            self.cb_interval_kind.setCurrentIndex(idx)      # 会触发 _on_kind_changed
        self._apply_kind(apply_default=False)

    def _on_preset(self, idx: int) -> None:
        """按下拉**索引**取窗口并落进四格日期（索引 = `self._presets` 的下标）。

        ⚠ 不能用 `key` 反查：key 在缓存里重复几十条（`sideways>sideways` × 40+），
          按 key 找永远命中第一条（2005 年那段）⇒ §11.5-112 ③ 的真实事故。
        """
        idx = int(idx)
        if 0 <= idx < len(self._presets):
            p = self._presets[idx]
            self.set_dates(p.is_start, p.is_end, p.oos_start, p.oos_end)
        self.preset_changed.emit(self.preset_key())

    def set_dates(self, is_start: str, is_end: str, oos_start: str, oos_end: str) -> None:
        from PyQt6.QtCore import QDate
        for w, s in ((self.dt_is_start, is_start), (self.dt_is_end, is_end),
                     (self.dt_oos_start, oos_start), (self.dt_oos_end, oos_end)):
            q = QDate.fromString(str(s), "yyyy-MM-dd")
            if q.isValid():
                w.setDate(q)

    def set_interval_receipt(self, text: str) -> None:
        self.lbl_interval.setText(text)


    def grid_dims(self):
        """(起,止,步) × 维 → (SweepDimension 元组, "") 或 ((), 拒绝原因)。"""
        from core.sweep_plan import make_dimension
        dims = []
        for i, d in enumerate(self._dim_rows):
            name = str(d["name"].currentText() or "").strip()
            if i == 1 and name in ("", "（第 2 维不用）"):
                continue
            if name in ("", "（选参数）", "（无可扫描参数）"):
                return (), f"第 {i + 1} 维还没选参数名"
            dim, msg = make_dimension(name, d["start"].value(), d["stop"].value(),
                                      d["step"].value())
            if dim is None:
                return (), msg
            dims.append(dim)
        return tuple(dims), ""

    def interval(self):
        from core.sweep_plan import StudyInterval
        fmt = "yyyy-MM-dd"
        return StudyInterval(
            self.dt_is_start.date().toString(fmt),
            self.dt_is_end.date().toString(fmt),
            self.dt_oos_start.date().toString(fmt),
            self.dt_oos_end.date().toString(fmt))

    def grid_signature(self, fingerprint: str) -> str:
        """同一网格身份（红线① OOS 只跑一次的判定键）。"""
        dims, _ = self.grid_dims()
        spec = "|".join(f"{d.name}:{','.join(f'{v:.6g}' for v in d.values)}" for d in dims)
        iv = self.interval()
        return f"{self.symbol()}|{fingerprint}|{spec}|{iv.is_start}~{iv.is_end}|{iv.oos_start}~{iv.oos_end}"
