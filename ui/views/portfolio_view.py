# ui/views/portfolio_view.py
"""🧺 组合页（★1.85 / §7-B17 · **P0 已交付 + P1 净值/持仓**）。

【P0（已交付）】组合列表（新建/删除）· 空态 · **从自选股组导入**（等权）· 保存/重载。
【P1（本期）】**净值曲线**（组合 vs 基准，基期 1.0000 + 总收益/年化/最大回撤）· **持仓表**
（代码/名称/权重/成本/最新/盈亏）。
【P2–P4】市场·行业分布 → 组合回测（含佣金与换手）→ 接 B15 池化。

【成分唯一来源】`main_win.page_market.watchlist`（`data/watchlist_store.WatchlistStore`），**只读**；
组合里只存**组名**（不存名单快照）⇒ 组改名/移组自动跟随；组被删 ⇒ 如实标「来源组已不存在」，**不静默清空**。

【诚实边界（写在卡面上，不藏）】
  · 净值 = **价格收益**（日线收盘 · 前复权）· **未含佣金**（组合回测在 P3 计入换手成本）；
  · 某只票整只没数据 ⇒ 持仓表写「数据不足」，**不当 0 收益**；
  · 图上标"日线（收盘）"，**不做实时**。
"""
from __future__ import annotations

import numpy as np
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (QDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog,
                             QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                             QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout,
                             QWidget)

from PyQt6.QtGui import QColor, QPainter

from core.backtest import commission_rate_from_prefs
from core.portfolio_stats import (annualized, build_returns, holdings_rows, industry_mix,
                                  market_mix, market_of, max_drawdown, nav_series,
                                  nav_with_costs,
                                  period_return)
from core.preferences import preferences
from data.market_db import DataLakeManager
from ui.dialogs.portfolio_edit import PortfolioEditDialog
from data.portfolio_store import (DEFAULT_BASE, REBALANCE_LABELS, WEIGHT_LABELS,
                                  PortfolioStore, members_from_entries, new_portfolio)
from ui.widgets.chart_host import ChartHost
from ui.widgets.styles import (EMPTY_STATE_QSS, SEC_HINT_QSS, SEC_TITLE_QSS,
                               SUMMARY_GHOST_QSS, SUMMARY_RUN_QSS, TABLE_HEAD_QSS,
                               WARN_HINT_QSS)
from ui.widgets.sweep_parts import panel_card, panel_head

UI_PREF_KEY = "portfolios_ui"
# ★1.87：三条线必须**一眼分得清**（用户实测：两条线颜色几乎一样、完全不可辨别）
#   含成本 = 深蓝实线 · 不含成本 = 青绿虚线 · 基准 = 中性灰点线（三种色相 + 三种线型）
BASE_COLORS = {"nav": "#1565C0", "gross": "#00A38B", "base": "#9E9E9E"}


def _dot(title: str, color: str) -> str:
    """卡头标题前加彩色圆点（样板做法；只影响本页，不动全局 QSS）。"""
    return f'<span style="color:{color}">●</span> {title}'


class _PfCard(QFrame):
    """左栏的一张组合卡（样板样式）：名称 + 累计/日/净值 + 来源组。

    ⚠ 与列表项的关系：卡是**显示层**，`QListWidgetItem` 仍保留文本（断言与 tooltip 用）。
    """

    QSS = (
        "QFrame#pfCard { background:#FFFFFF; border:1px solid #E7ECF3; border-radius:10px; }"
        "QFrame#pfCard[sel=\"true\"] { background:#EAF3FE; border:1px solid #B6D4F7; }"
        "QLabel { background: transparent; }")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pfCard")
        self.setStyleSheet(self.QSS)
        self._sel = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.lbl_name = QLabel("")
        self.lbl_name.setStyleSheet("font-size:13px;font-weight:700;color:#1F2A37;")
        top.addWidget(self.lbl_name, 1)
        self.lbl_group = QLabel("")
        self.lbl_group.setStyleSheet("font-size:11px;color:#8A94A6;")
        top.addWidget(self.lbl_group, 0)
        lay.addLayout(top)

        self.lbl_metrics = QLabel("")
        self.lbl_metrics.setStyleSheet("font-size:11.5px;")
        lay.addWidget(self.lbl_metrics)

        self.lbl_sub = QLabel("")
        self.lbl_sub.setStyleSheet("font-size:11px;color:#9AA6B8;")
        lay.addWidget(self.lbl_sub)

    def fill(self, name: str, group: str, ret, day) -> None:
        self.lbl_name.setText(name)
        self.lbl_group.setText(f"自选组：{group}" if group else "自选组：未指定")
        parts = []
        if ret is None:
            parts.append('<span style="color:#9AA6B8">累计 —</span>')
        else:
            _c = "#2E7D32" if ret >= 0 else "#C62828"
            parts.append(f'<span style="color:{_c}">累计 {ret:+.2f}%</span>')
        if day is not None:
            _c = "#2E7D32" if day >= 0 else "#C62828"
            parts.append(f'<span style="color:{_c}">日 {day:+.2f}%</span>')
        if ret is not None:
            parts.append(f'<span style="color:#5A6577">净值 {1 + ret / 100.0:.4f}</span>')
        self.lbl_metrics.setText("　".join(parts))

    def set_selected(self, sel: bool) -> None:
        self._sel = bool(sel)
        self.setProperty("sel", "true" if sel else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class _Ring(QWidget):
    """极简环形图（QPainter 自绘，不引第三方）。

    ⚠ 只画"占比"；**没有数据就不画**（空列表 ⇒ 只留灰底），绝不画一个假的 100% 圆。
    """

    COLORS = ("#1976D2", "#26A69A", "#7E57C2", "#FB8C00", "#8D6E63", "#78909C")

    def __init__(self, parent=None, palette_offset: int = 0):
        super().__init__(parent)
        self._offset = int(palette_offset or 0)   # ★1.87：单段时两环不要撞色
        self._data = []
        self.setMinimumSize(118, 118)
        self.setMaximumSize(150, 150)

    def set_data(self, data) -> None:
        self._data = [(str(k), float(v)) for k, v in (data or []) if float(v) > 1e-9]
        self.update()

    def paintEvent(self, _event) -> None:      # noqa: N802 —— Qt 命名
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(8, 8, -8, -8)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#EDF1F7"))           # 底色（无数据时就是它）
        p.drawEllipse(rect)
        total = sum(v for _k, v in self._data)
        if total > 0:
            start = 90 * 16
            for i, (_k, v) in enumerate(self._data):
                span = int(-360 * 16 * v / total)
                p.setBrush(QColor(self.COLORS[(i + self._offset) % len(self.COLORS)]))
                p.drawPie(rect, start, span)
                start += span
        # 挖个白心 ⇒ 环
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(rect.adjusted(26, 26, -26, -26))


class PortfolioView(QWidget):
    """组合页（P0 + P1）。宿主 = `JianMainWindow`。"""

    def __init__(self, main_win, parent=None):
        super().__init__(parent)
        self.main_win = main_win
        self._store = PortfolioStore()
        self._lake = DataLakeManager()
        self._current = ""
        self._cache = {}          # symbols 元组 → {symbol: DataFrame}
        # ★1.87：列表的「累计/日」只显示**算过的**（key=组合 id）；没算过写「—」，不编数
        self._metrics = {}
        self._window = 0          # 0=全部 / 12=近1年 / 3=近3月（★1.87）
        self._pf_cur = None       # 当前渲染的组合（切窗口时重画用）
        self._names_cache = None  # 花名册（代码→名称），懒加载
        self._nav = None          # 最近一次算出的净值（Series）—— 断言与调试都读它
        self._build()
        self._load_ui()
        self.refresh()

    # ================= 版式 =================
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("🧺 组合")
        title.setStyleSheet(SEC_TITLE_QSS + "font-size:15px;")
        head.addWidget(title)
        hint = QLabel("把「自选股组」变成可回测的组合 —— 成分只引用组，不复制名单")
        hint.setStyleSheet(SEC_HINT_QSS)
        head.addWidget(hint, 1)
        self.btn_new = QPushButton("＋ 新建组合")
        self.btn_new.setStyleSheet(SUMMARY_GHOST_QSS)
        self.btn_new.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_new.setToolTip("先建一个空组合，之后再导入成分")
        self.btn_new.clicked.connect(self._on_new)
        head.addWidget(self.btn_new)
        self.btn_import = QPushButton("↻ 从自选股组导入")
        self.btn_import.setStyleSheet(SUMMARY_RUN_QSS)
        self.btn_import.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_import.setToolTip("读行情页「自选股 → 组」的成分，按**等权**生成组合（只读，不改自选）")
        self.btn_import.clicked.connect(self._on_import)
        head.addWidget(self.btn_import)
        # ★1.87：**手工增删改成分**（P0 只有"整组导入"，空组合根本没法加票）
        self.btn_edit = QPushButton("✏ 编辑成分")
        self.btn_edit.setStyleSheet(SUMMARY_GHOST_QSS)
        self.btn_edit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_edit.setToolTip("逐只加/删、改权重、设现金（合计必须 100.00%）")
        self.btn_edit.setEnabled(False)
        self.btn_edit.clicked.connect(self._on_edit)
        head.addWidget(self.btn_edit)
        self.btn_del = QPushButton("删除")
        self.btn_del.setStyleSheet(SUMMARY_GHOST_QSS)
        self.btn_del.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_del.setEnabled(False)
        self.btn_del.clicked.connect(self._on_delete)
        head.addWidget(self.btn_del)
        root.addLayout(head)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)

        # ---- 左：组合列表 ----
        left = panel_card()
        bl = QVBoxLayout(left)
        bl.setContentsMargins(10, 8, 10, 10)
        bl.setSpacing(6)
        self.list_head = panel_head(_dot("我的组合", "#1976D2"), "新 → 旧")
        bl.addWidget(self.list_head)
        self.lst = QListWidget()
        # ★1.87：卡片化（样板样式）——列表只做容器，卡片自带白底圆角与选中态
        self.lst.setStyleSheet("QListWidget { background: transparent; border: none; }"
                               " QListWidget::item { margin: 3px 1px; }"
                               " QListWidget::item:selected { background: transparent; }")
        self.lst.setSpacing(2)
        self.lst.currentItemChanged.connect(self._on_select)
        self.lst.itemDoubleClicked.connect(lambda _it: self._on_rename())
        self.lst.setToolTip("双击可重命名组合")
        bl.addWidget(self.lst, 1)
        left.setMinimumWidth(200)   # ★1.85：240→200（1000 窗不出横条）
        left.setMaximumWidth(300)
        grid.addWidget(left, 0, 0)

        # ---- 右：空态 / 详情 ----
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(10)

        self.empty = QFrame(right)
        el = QVBoxLayout(self.empty)
        el.setContentsMargins(0, 0, 0, 0)
        el.setSpacing(10)
        self.lbl_empty = QLabel(
            "还没有组合。\n\n"
            "「组合」= 一组标的 + 权重 + 基准 + 再平衡规则。\n"
            "成分来源只有一处：<b>行情页 → 自选股 → 组</b>（这里只引用，不复制名单）。")
        self.lbl_empty.setWordWrap(True)
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty.setStyleSheet(EMPTY_STATE_QSS)
        el.addWidget(self.lbl_empty, 1)
        self.btn_empty_import = QPushButton("↻ 从自选股组导入")
        self.btn_empty_import.setStyleSheet(SUMMARY_RUN_QSS)
        self.btn_empty_import.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_empty_import.clicked.connect(self._on_import)
        el.addWidget(self.btn_empty_import, 0, Qt.AlignmentFlag.AlignCenter)
        rl.addWidget(self.empty, 1)

        self.detail = QFrame(right)
        dl = QVBoxLayout(self.detail)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(10)

        # ① 设置摘要
        self.card_sum = panel_card()
        sl = QVBoxLayout(self.card_sum)
        sl.setContentsMargins(10, 8, 10, 10)
        sl.setSpacing(6)
        self.sum_head = panel_head(_dot("组合设置", "#78909C"), "")
        sl.addWidget(self.sum_head)
        self.lbl_sum = QLabel("")
        self.lbl_sum.setWordWrap(True)
        self.lbl_sum.setStyleSheet(SEC_HINT_QSS)
        sl.addWidget(self.lbl_sum)
        self.lbl_warn = QLabel("")
        self.lbl_warn.setWordWrap(True)
        self.lbl_warn.setStyleSheet(WARN_HINT_QSS)
        self.lbl_warn.hide()
        sl.addWidget(self.lbl_warn)
        dl.addWidget(self.card_sum)

        # ①.5 概览（★1.87：样板是 **4 张独立卡**，不再合并成一张）
        self.ov_cards = []
        self.lbl_ov = {}
        for _k, _t in (("ret", "总收益"), ("nav", "净值"),
                       ("day", "最近一日"), ("excess", "超额（vs 基准）")):
            _card = panel_card()
            _l = QVBoxLayout(_card)
            _l.setContentsMargins(10, 7, 10, 8)
            _l.setSpacing(1)
            _cap = QLabel(_t)
            _cap.setStyleSheet(SEC_HINT_QSS)
            _l.addWidget(_cap)
            _val = QLabel("—")
            _val.setStyleSheet("font-size:16px;font-weight:700;color:#1F2A37;background:transparent;")
            _card.setMinimumHeight(54)
            _l.addWidget(_val)
            self.lbl_ov[_k] = _val
            self.ov_cards.append(_card)
        # 2×2 四宫格（样板：四块并列，各自独立边框）
        self.ov_box = QWidget()
        _ovg = QGridLayout(self.ov_box)
        _ovg.setContentsMargins(0, 0, 0, 0)
        _ovg.setHorizontalSpacing(8)
        _ovg.setVerticalSpacing(8)
        for _idx, _card in enumerate(self.ov_cards):
            _ovg.addWidget(_card, _idx // 2, _idx % 2)
        dl.addWidget(self.ov_box)


        # ② 净值曲线（P1）
        self.card_nav = panel_card()
        nl = QVBoxLayout(self.card_nav)
        nl.setContentsMargins(10, 8, 10, 10)
        nl.setSpacing(6)
        self.nav_head = panel_head(_dot("净值曲线", "#00A38B"), "日线（收盘）· 基期 1.0000")
        nl.addWidget(self.nav_head)
        # ★1.87：区间档（只影响**显示窗口**与窗口内 KPI，不改任何口径）
        _wrow = QHBoxLayout()
        _wrow.setSpacing(4)
        self._win_btns = {}
        for _k, _t in ((3, "近 3 月"), (12, "近 1 年"), (0, "全部")):
            _b = QPushButton(_t)
            _b.setCheckable(True)
            _b.setChecked(_k == 0)
            _b.setCursor(Qt.CursorShape.PointingHandCursor)
            _b.setStyleSheet(SUMMARY_GHOST_QSS + " QPushButton:checked { background:#1976D2;"  " color:#FFFFFF; border-color:#1976D2; }")
            _b.clicked.connect(lambda _c=False, k=_k: self._set_window(k))
            _wrow.addWidget(_b)
            self._win_btns[_k] = _b
        _wrow.addStretch(1)
        nl.addLayout(_wrow)
        self.lbl_nav_meta = QLabel("")
        self.lbl_nav_meta.setWordWrap(True)
        self.lbl_nav_meta.setStyleSheet(SEC_HINT_QSS)
        nl.addWidget(self.lbl_nav_meta)
        self.chart = ChartHost(self)
        self.chart.setMinimumHeight(220)
        self.chart.setMaximumHeight(300)
        nl.addWidget(self.chart, 1)
        self.lbl_legend = QLabel("")
        self.lbl_legend.setStyleSheet(SEC_HINT_QSS)
        nl.addWidget(self.lbl_legend)
        self.lbl_nav_note = QLabel("")
        self.lbl_nav_note.setWordWrap(True)
        self.lbl_nav_note.setStyleSheet(SEC_HINT_QSS)
        nl.addWidget(self.lbl_nav_note)
        dl.addWidget(self.card_nav, 1)

        # ③ 持仓表（P1）
        self.card_hold = panel_card()
        hl = QVBoxLayout(self.card_hold)
        hl.setContentsMargins(10, 8, 10, 10)
        hl.setSpacing(6)
        self.hold_head = panel_head(_dot("持仓", "#7E57C2"), "")
        # ★1.87：与样板一致 —— 按标的 / 按行业 / 按市场
        _hseg = QHBoxLayout()
        _hseg.setSpacing(4)
        self._hold_mode = "symbol"
        self._hold_btns = {}
        for _mk, _mt in (("symbol", "按标的"), ("industry", "按行业"), ("market", "按市场")):
            _b = QPushButton(_mt)
            _b.setCheckable(True)
            _b.setChecked(_mk == "symbol")
            _b.setCursor(Qt.CursorShape.PointingHandCursor)
            _b.setStyleSheet(SUMMARY_GHOST_QSS + " QPushButton:checked { background:#1976D2;"  " color:#FFFFFF; border-color:#1976D2; }")
            _b.clicked.connect(lambda _c=False, k=_mk: self._set_hold_mode(k))
            _hseg.addWidget(_b)
            self._hold_btns[_mk] = _b
        _hseg.addStretch(1)
        hl.addLayout(_hseg)
        hl.addWidget(self.hold_head)
        # ★1.87：与样板对齐 —— 序号 / 代码 / 名称 / 仓位 / 成本 / 最新 / 盈亏（7 列）
        self.tbl_hold = QTableWidget(0, 7)
        self.tbl_hold.setHorizontalHeaderLabels(
            ["序号", "代码", "名称", "仓位 %", "成本", "最新", "盈亏 %"])
        self.tbl_hold.verticalHeader().setVisible(False)
        self.tbl_hold.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl_hold.setStyleSheet(TABLE_HEAD_QSS)
        self.tbl_hold.setMinimumHeight(140)
        _h = self.tbl_hold.horizontalHeader()
        for _c in (0, 1, 3, 4, 5, 6):
            _h.setSectionResizeMode(_c, QHeaderView.ResizeMode.ResizeToContents)
        _h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hl.addWidget(self.tbl_hold, 1)
        # ★1.87：口径走**页脚一行**（样板做法；不留"设置卡"）
        self.lbl_hold_foot = QLabel("")
        self.lbl_hold_foot.setWordWrap(True)
        self.lbl_hold_foot.setStyleSheet(SEC_HINT_QSS)
        hl.addWidget(self.lbl_hold_foot)
        dl.addWidget(self.card_hold, 1)

        # ④ 分布（P2）：样板是 **两张独立卡**（市场 / 行业），不合并
        self.card_mkt = panel_card()
        _ml = QVBoxLayout(self.card_mkt)
        _ml.setContentsMargins(10, 8, 10, 10)
        _ml.setSpacing(4)
        _ml.addWidget(panel_head(_dot("市场分布", "#FB8C00"), "按权重 · 现金单列"))
        _rowm = QHBoxLayout()
        _rowm.setSpacing(10)
        self.ring_mkt = _Ring(self, palette_offset=0)
        _rowm.addWidget(self.ring_mkt, 0, Qt.AlignmentFlag.AlignLeft)
        self.leg_mkt = QLabel("")
        self.leg_mkt.setWordWrap(True)
        self.leg_mkt.setStyleSheet(SEC_HINT_QSS)
        _rowm.addWidget(self.leg_mkt, 1)
        _ml.addLayout(_rowm)

        self.card_ind = panel_card()
        _il = QVBoxLayout(self.card_ind)
        _il.setContentsMargins(10, 8, 10, 10)
        _il.setSpacing(4)
        _head_ind = panel_head(_dot("行业分布", "#7E57C2"), "按权重 · 未分类单列")
        _il.addWidget(_head_ind)
        _rowi = QHBoxLayout()
        _rowi.setSpacing(10)
        self.ring_ind = _Ring(self, palette_offset=2)
        _rowi.addWidget(self.ring_ind, 0, Qt.AlignmentFlag.AlignLeft)
        self.leg_ind = QLabel("")
        self.leg_ind.setWordWrap(True)
        self.leg_ind.setStyleSheet(SEC_HINT_QSS)
        _rowi.addWidget(self.leg_ind, 1)
        _il.addLayout(_rowi)
        # 行业映射是"外部拉取"来的 ⇒ 卡上给一个**同步入口**（没有映射时它就是唯一出路）
        _irow = QHBoxLayout()
        self.lbl_ind_note = QLabel("")
        self.lbl_ind_note.setWordWrap(True)
        self.lbl_ind_note.setStyleSheet(SEC_HINT_QSS)
        _irow.addWidget(self.lbl_ind_note, 1)
        self.btn_ind_sync = QPushButton("↻ 同步行业")
        self.btn_ind_sync.setStyleSheet(SUMMARY_GHOST_QSS)
        self.btn_ind_sync.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ind_sync.setToolTip("从东财分批拉「代码→行业」（每批几页，可重复点直到覆盖）")
        self.btn_ind_sync.clicked.connect(self._on_sync_industry)
        _irow.addWidget(self.btn_ind_sync, 0)
        _il.addLayout(_irow)



        # ④ 再平衡记录（P3）：只记**软件内**发生过的再平衡（时间 / 换手 / 成本）
        self.card_reb = panel_card()
        rl2 = QVBoxLayout(self.card_reb)
        rl2.setContentsMargins(10, 8, 10, 10)
        rl2.setSpacing(6)
        self.reb_head = panel_head(_dot("再平衡记录", "#8D6E63"), "只记软件内 · 按月末")
        rl2.addWidget(self.reb_head)
        self.lbl_reb = QLabel("")
        self.lbl_reb.setWordWrap(True)
        self.lbl_reb.setStyleSheet(SEC_HINT_QSS)
        rl2.addWidget(self.lbl_reb)
        dl.addWidget(self.card_reb, 0)

        # ⑤ 成分卡已删除（★1.87 用户定：与「持仓」重复 —— 持仓已含代码/名称/仓位，
        #   且能看盈亏；留两份只会让人问"这两块有什么区别"）
        # 旧代码保留注释说明：
        # ★1.85 P2：分布卡放到**净值之后**（小卡先看，长表后看）


        # ★1.85 P1：卡片变多了（设置/净值/持仓/成分）⇒ 详情列**必须能纵向滚**。
        #   本项目踩过"容器关掉滚动条 ⇒ 内容够不到"的坑（§11.5-137）：宁可出现滚动条，也不许看不见。
        _sa = QScrollArea(right)
        _sa.setWidgetResizable(True)
        _sa.setFrameShape(QFrame.Shape.NoFrame)
        _sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        _sa.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        _sa.setWidget(self.detail)
        self._detail_scroll = _sa
        rl.addWidget(_sa, 1)
        grid.addWidget(right, 0, 1)

        # ★1.87：**右栏**（概览 / 分布 / 再平衡记录）—— 宽窗独立一列，窄窗整体下沉到主区下方
        self.rail = QWidget()
        self.rail.setMinimumWidth(260)
        self.rail.setMaximumWidth(300)
        self._rail_lay = QVBoxLayout(self.rail)
        self._rail_lay.setContentsMargins(0, 0, 0, 0)
        self._rail_lay.setSpacing(10)
        for _c in (self.ov_box, self.card_mkt, self.card_ind, self.card_reb):
            self._rail_lay.addWidget(_c)
        self._rail_lay.addStretch(1)
        grid.addWidget(self.rail, 0, 2)
        self._rail_in_grid = True
        self._rail_narrow = False          # ★独立记录"当前是不是窄态"（别拿 in_grid 当状态）
        self._grid = grid
        self._detail_lay = dl
        root.addLayout(grid, 1)

        self.detail.hide()

    # 常见指数的"前缀"（index_daily 里文件名是 sh000001 / sz399001 这种）
    KNOWN_INDEX = {"000300": "sh", "000905": "sh", "000001": "sh",
                   "399001": "sz", "399006": "sz"}

    def _available_indices(self) -> str:
        """本机已有指数的文件名（给用户一句实话，而不是干巴巴"无数据"）。"""
        try:
            import os

            from config import settings as _st
            d = os.path.join(_st.USER_DATA_DIR, "data_lake", "macro", "index")
            names = [n[:-8] for n in os.listdir(d) if n.endswith(".parquet")]
            return "、".join(sorted(names)[:4]) if names else "无"
        except Exception:                  # noqa: BLE001
            return "无"

    def _load_base_df(self, base: dict):
        """基准日线：**指数在 `index_daily`（文件名带 sh/sz 前缀）**，个股在 `kline_daily`。

        ★1.87 修：旧版只查 `kline_daily` ⇒ 指数基准永远"本机无数据"（用户已下载也看不到）。
        返回 `(df, 人话原因)`。
        """
        code = str((base or {}).get("code") or "").strip()
        if not code:
            return None, "未设基准"
        kind = str((base or {}).get("kind") or "index")
        tries = []
        if kind == "index":
            pre = self.KNOWN_INDEX.get(code) or ("sh" if code[0] in "056" else "sz")
            tries.append(("index_daily", f"{pre}{code}"))
        tries.append(("kline_daily", code))        # 个股当基准
        tries.append(("index_daily", code))
        for zone, fn in tries:
            try:
                df = self._lake.load_data(zone, fn)
            except Exception:                  # noqa: BLE001
                df = None
            if df is not None and len(df):
                return df, ""
        return None, (f"本机没有 {code} 的日线；指数要先去「🗄 数据管理」下载"
                      f"（当前已有指数：{self._available_indices()}）")

    def _set_hold_mode(self, mode: str) -> None:
        """持仓三种视角（按标的/行业/市场）。只重排显示，不动成分。"""
        self._hold_mode = str(mode or "symbol")
        for k, b in self._hold_btns.items():
            b.setChecked(k == self._hold_mode)
        if self._pf_cur is not None:
            self._render(self._pf_cur)

    @staticmethod
    def _group_rows(rows, key_of, label: str) -> list:
        """按 key 聚合（行业/市场）：权重相加；盈亏按权重加权（缺数据的票不进加权）。"""
        agg = {}
        for r in rows:
            k = str(key_of(r) or label)
            it = agg.setdefault(k, {"symbol": "—", "name": k, "weight": 0.0,
                                    "_pnl_w": 0.0, "_w_ok": 0.0, "data_ok": True,
                                    "cost": None, "last": None, "pnl": None})
            w = float(r.get("weight") or 0.0)
            it["weight"] += w
            if r.get("data_ok") and r.get("pnl") is not None:
                it["_pnl_w"] += w * float(r["pnl"])
                it["_w_ok"] += w
            elif not r.get("data_ok"):
                it["data_ok"] = False
        out = []
        for it in agg.values():
            if it["_w_ok"] > 0:
                it["pnl"] = it["_pnl_w"] / it["_w_ok"]
            it["weight"] = round(it["weight"], 2)
            it.pop("_pnl_w", None)
            it.pop("_w_ok", None)
            out.append(it)
        out.sort(key=lambda r: -float(r.get("weight") or 0.0))
        return out

    def _clear_curve(self) -> None:
        """**彻底**清曲线。

        ⚠ 用户实测：删掉一个组合、新建空组合后，**上一份曲线还挂在那里**
          —— `ChartHost.clear()` 只清窗格，不清主图里的数据项。
        """
        try:
            self.chart.clear()
        except Exception:                  # noqa: BLE001
            pass
        try:
            self.chart.main_pane.plot_item.clear()
        except Exception:                  # noqa: BLE001
            pass

    def _on_sync_industry(self) -> None:
        """从东财**分批**拉「代码→行业」并合并进 `industry_store`（可重复点，断点续抓）。"""
        w0 = getattr(self, "_ind_worker", None)
        if w0 is not None and w0.isRunning():
            return
        from data.industry_store import get_industry_store
        from ui.workers import IndustryMapWorker
        page = int(getattr(self, "_ind_page", 1) or 1)
        w = IndustryMapWorker(page_start=page, pages=3, parent=self)
        self._ind_worker = w
        self.btn_ind_sync.setEnabled(False)
        self.lbl_ind_note.setText(f"正在拉行业（第 {page} 页起，共 3 页）…")

        def _done(res) -> None:
            self.btn_ind_sync.setEnabled(True)
            store = get_industry_store()
            if not res:
                self.lbl_ind_note.setText("行业同步失败（网络/频控）—— 稍后再点一次；已有映射不会丢。")
                return
            mp = res.get("map") or {}
            try:
                store.merge(mp)
            except Exception:              # noqa: BLE001
                pass
            done = bool(res.get("done"))
            self._ind_page = 1 if done else page + int(res.get("pages_done") or 0)
            self.lbl_ind_note.setText(
                f"本次 {len(mp)} 条 · 库内合计 {store.coverage()} 条"
                + ("（已到最后一页，再点从头扫）" if done else "（再点继续下一页）"))
            if self._pf_cur is not None:
                self._render(self._pf_cur)

        w.finished.connect(_done)
        w.start()

    def _set_window(self, months: int) -> None:
        """切净值显示窗口（0=全部）。只重画，不重算成本、不动存储。"""
        self._window = int(months or 0)
        for k, b in self._win_btns.items():
            b.setChecked(k == self._window)
        if self._pf_cur is not None:
            self._render(self._pf_cur)

    # ================= 自适应（★1.87：≤1180 右栏下沉，绝不出横向滚动）=================
    RAIL_BREAK = 940      # 页面宽（不是窗口宽）：再窄就把右栏下沉

    def resizeEvent(self, event) -> None:      # noqa: N802 —— Qt 命名
        super().resizeEvent(event)
        self._relayout_rail(self.width() < self.RAIL_BREAK)

    def _relayout_rail(self, narrow: bool) -> None:
        """窄窗 ⇒ 右栏搬到主区下方（单列）；宽窗 ⇒ 回到第 3 列。

        ⚠ 只搬**同一批控件**，不重建、不隐藏内容（§11.5-111：宁可下沉也不给横向条）。
        """
        rail = getattr(self, "rail", None)
        if rail is None or getattr(self, "_rail_in_grid", None) is None:
            return
        # ⚠ 状态必须是**独立的窄/宽标记**：旧版拿 `_rail_in_grid` 比 ⇒ 首次就短路，永远不重排
        if narrow == self._rail_narrow:
            return
        if narrow:
            self._grid.removeWidget(rail)
            self._detail_lay.addWidget(rail)
        else:
            self._detail_lay.removeWidget(rail)
            self._grid.addWidget(rail, 0, 2)
        self._rail_narrow = narrow
        self._rail_in_grid = not narrow

    # ================= 数据 =================
    def _watchlist(self):
        """成分来源（只读门面）—— 从行情页拿，**不自己建第二份**。"""
        page = getattr(self.main_win, "page_market", None)
        return getattr(page, "watchlist", None) if page is not None else None

    def refresh(self) -> None:
        """重读存储 + 重建列表（选中项尽量保持）。"""
        items = self._store.list()
        keep = self._current
        self.lst.blockSignals(True)
        self.lst.clear()
        self._cards = {}                 # ★刷新时清掉旧卡片引用（否则点已删的组合会报错）
        for p in items:
            group = str(p.get("source_group") or "")
            missing = bool(group) and not self._group_exists(group)
            text = self._item_text(p)
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, str(p.get("id")))
            it.setSizeHint(QSize(0, 74))
            _card = _PfCard(self.lst)
            _m = self._metrics.get(str(p.get("id"))) or {}
            _card.fill(str(p.get("name") or "组合"), group, _m.get("ret"), _m.get("day"))
            _card.set_selected(str(p.get("id")) == str(keep))
            _card.mousePressEvent = lambda _e, _i=self.lst.count(): \
                self.lst.setCurrentRow(_i)
            _card.mouseDoubleClickEvent = lambda _e: self._on_rename()
            self._cards = getattr(self, "_cards", {})
            self._cards[str(p.get("id"))] = _card
            if missing:
                it.setToolTip("行情页里找不到这个自选股组了 —— 成分不再自动更新（点开看说明）")
            self.lst.addItem(it)
            self.lst.setItemWidget(it, _card)
        self.lst.blockSignals(False)
        try:
            self.list_head.meta_label.setText(f"共 {len(items)} 个 · 点击切换")
        except Exception:                  # noqa: BLE001
            pass
        if not items:
            self._current = ""
            self.detail.hide()
            self.empty.show()
            self.btn_del.setEnabled(False)
            self.btn_edit.setEnabled(False)
            return
        row = 0
        for i in range(self.lst.count()):
            if self.lst.item(i).data(Qt.ItemDataRole.UserRole) == keep:
                row = i
                break
        self.lst.setCurrentRow(row)
        self._on_select(self.lst.currentItem(), None)

    def _roster_names(self) -> dict:
        """花名册（代码→名称）—— 走 `engine.roster_names()` 门面（UI 不碰 DB）。

        ★1.87：名称不能只靠"导入时的快照"——手工加的票没有名字，
        列表/持仓/成分三处都会空着（用户实测）。
        """
        if self._names_cache is None:
            try:
                eng = getattr(self.main_win, "engine", None)
                self._names_cache = dict(eng.roster_names() or {}) if eng is not None else {}
            except Exception:              # noqa: BLE001 —— 读不到就按"没名字"显示
                self._names_cache = {}
        return self._names_cache

    def name_of(self, symbol: str, current: str = "") -> str:
        """名称优先用存量值，其次花名册，最后留空（不编）。"""
        return str(current or "").strip() or str(self._roster_names().get(str(symbol)) or "")

    def _item_text(self, p: dict) -> str:
        """列表一行的文案：名称 / 累计·日 / 来源组（**没算过就写「—」**）。"""
        group = str(p.get("source_group") or "")
        missing = bool(group) and not self._group_exists(group)
        _m = self._metrics.get(str(p.get("id"))) or {}
        _ret, _day = _m.get("ret"), _m.get("day")
        _ret_txt = f"累计 {_ret:+.2f}%" if _ret is not None else "累计 —"
        _day_txt = f" · 日 {_day:+.2f}%" if _day is not None else ""
        tip = f"{p.get('name')}\n{_ret_txt}{_day_txt}\n来源组：{group or '（未指定）'}"
        return tip + ("（已不存在）" if missing else "")

    def _group_exists(self, group: str) -> bool:
        wl = self._watchlist()
        try:
            return bool(wl is not None and group and group in (wl.groups() or []))
        except Exception:                      # noqa: BLE001
            return False

    def _frames(self, symbols) -> dict:
        """按需读日线（缓存：同一批标的只读一次）。缺失的票**不进** dict（由界面写"数据不足"）。"""
        key = tuple(str(s) for s in symbols)
        if key in self._cache:
            return self._cache[key]
        out = {}
        for s in key:
            try:
                df = self._lake.load_data("kline_daily", s)
            except Exception:                  # noqa: BLE001 —— 读失败按"没有数据"处理，如实显示
                df = None
            if df is not None and len(df):
                out[s] = df
        self._cache[key] = out
        return out

    def _on_select(self, cur, _prev) -> None:
        if cur is None:
            return
        pid = str(cur.data(Qt.ItemDataRole.UserRole) or "")
        p = self._store.load_one(pid) if pid else None
        if not p:
            return
        self._current = pid
        for _pid, _card in getattr(self, "_cards", {}).items():
            try:
                _card.set_selected(_pid == pid)
            except Exception:              # noqa: BLE001
                pass
        self.btn_del.setEnabled(True)
        self.btn_edit.setEnabled(True)
        self.empty.hide()
        self.detail.show()
        self._render(p)
        self._save_ui()

    def _render(self, p: dict) -> None:
        group = str(p.get("source_group") or "")
        members = p.get("members") or []
        base = p.get("base") or DEFAULT_BASE
        self.sum_head.title_label.setText(str(p.get("name") or "组合"))
        self.sum_head.meta_label.setText(f"共 {len(members)} 只 · {WEIGHT_LABELS.get(p.get('weight_mode'), '等权')}")
        # ★1.87：与样板对齐 —— 摘要**压成一行**（样板没有"设置卡"，口径走在页脚）
        self.lbl_sum.setText(
            f"来源组：<b>{group or '（未指定）'}</b>　·　"
            f"权重：<b>{WEIGHT_LABELS.get(p.get('weight_mode'), '等权')}</b>　·　"
            f"现金：<b>{float(p.get('cash') or 0):.2f}%</b>　·　"
            f"基准：<b>{base.get('name') or base.get('code')}</b>　·　"
            f"再平衡：<b>{REBALANCE_LABELS.get(p.get('rebalance'), '买入持有')}</b>")
        missing = bool(group) and not self._group_exists(group)
        if missing:
            self.lbl_warn.setText("⚠ 来源组「" + group + "」在行情页已不存在（被删或改名）—— "
                                 "成分不会自动更新；请重新「从自选股组导入」，或先在行情页恢复该组。")
            self.lbl_warn.show()
        else:
            self.lbl_warn.hide()

        # P2：市场 / 行业分布（删"成分卡"时被连带删过 ⇒ 这是补回）
        try:
            from data.industry_store import get_industry_store as _gis
            _imap = _gis().as_map() or {}
        except Exception:                  # noqa: BLE001 —— 读不到就全「未分类」
            _imap = {}
        _cash = float(p.get("cash") or 0.0)
        self._fill_mix(self.ring_mkt, self.leg_mkt, market_mix(members, _cash), "合计")
        self._fill_mix(self.ring_ind, self.leg_ind, industry_mix(members, _imap, _cash), "合计")
        try:
            _n_ind = len(_imap)
            if _n_ind == 0:
                self.lbl_ind_note.setText("行业映射是空的 ⇒ 点「↻ 同步行业」分批拉取（可重复点）。")
            else:
                _miss = [m for m in members if not _imap.get(str(m.get("symbol")))]
                self.lbl_ind_note.setText(
                    f"库内行业 {_n_ind} 条" + (f" · 本组合缺 {len(_miss)} 只的行业" if _miss else ""))
        except Exception:                  # noqa: BLE001
            pass

        self._render_p1(p)

    # ---------------- P1：净值 + 持仓 ----------------
    def _render_p1(self, p: dict) -> None:
        members = p.get("members") or []
        symbols = [str(m.get("symbol")) for m in members]
        names = {str(m.get("symbol")): self.name_of(m.get("symbol"), m.get("name"))
                 for m in members}
        weights = {str(m.get("symbol")): float(m.get("weight") or 0.0) for m in members}
        frames = self._frames(symbols) if symbols else {}
        self._nav = None
        self._clear_curve()
        if not symbols:
            self.nav_head.meta_label.setText("还没有成分")
            self.lbl_nav_meta.setText("先「↻ 从自选股组导入」—— 没有成分时**不画线**。")
            self.lbl_nav_note.setText("")
            self.hold_head.meta_label.setText("0 只")
            self.tbl_hold.setRowCount(0)
            self.reb_head.meta_label.setText("—")
            self.lbl_reb.setText("没有成分 ⇒ 没有换手。")
            self._set_ov()
            return

        days, rets = build_returns(frames)
        missing = [s for s in symbols if s not in frames]
        if not days:
            self.nav_head.meta_label.setText("数据不足")
            self.lbl_nav_meta.setText(
                f"本机日线里没有这 {len(symbols)} 只的数据 —— 先去 🗄 数据管理 预下载（**不拿假数据凑图**）。")
            self.lbl_nav_note.setText("")
            self.hold_head.meta_label.setText(f"{len(symbols)} 只 · 全部缺数据")
            self._fill_holdings(holdings_rows(symbols, names, weights, {}, {}),
                                float(p.get("cash") or 0.0))
            self._set_ov()
            return

        # ★1.85 · **诚实规则**：只要有成员**整只**没有数据 ⇒ **不画组合线**。
        #   `nav_series` 只会拿"有数据的"归一成 100% ⇒ 等于用剩余权重冒充整个组合（假净值）。
        if missing:
            self.nav_head.meta_label.setText(f"缺 {len(missing)} 只 · 不画")
            _miss_txt = "、".join(missing[:4]) + ("…" if len(missing) > 4 else "")
            self.lbl_nav_meta.setText(
                f"有 {len(missing)} 只在本机没有日线（{_miss_txt}）⇒ <b>不画组合线</b>："
                "用剩下的权重归一去画，等于把整个组合换成了另一只组合。"
                "先去 🗄 数据管理 补齐，再回来看。")
            self.lbl_nav_note.setText("")
            _fc, _lc = {}, {}
            for _s in symbols:
                _df = frames.get(_s)
                if _df is not None and len(_df):
                    try:
                        _fc[_s] = float(_df["close"].iloc[0])
                        _lc[_s] = float(_df["close"].iloc[-1])
                    except Exception:      # noqa: BLE001
                        pass
            self._fill_holdings(holdings_rows(symbols, names, weights, _fc, _lc),
                                float(p.get("cash") or 0.0))
            self.hold_head.meta_label.setText(
                f"{len(symbols)} 只 · 有数据 {len(_fc)} 只 · 合计 "
                f"{sum(float(w) for w in weights.values()):.2f}%")
            self._set_ov()
            return

        # ★1.85 P3：**含换手成本**（用户口径：月末再平衡、双边、按全局「回测佣金」）
        _fee = commission_rate_from_prefs()
        _res = nav_with_costs(days, rets, weights, float(p.get("cash") or 0.0),
                              str(p.get("rebalance") or "monthly"), _fee)
        nav = _res["nav_net"]
        _gross = _res["nav_gross"]
        self._pf_cur = dict(p)
        # ★1.87：按窗口裁剪（只裁显示；成本已在全区间算过，**不会因换窗口而变**）
        _cut = ""
        if self._window and len(days):
            _y, _m, _d = (int(x) for x in str(days[-1]).split("-"))
            _m2 = _m - int(self._window)
            _y2 = _y + (_m2 - 1) // 12
            _m2 = (_m2 - 1) % 12 + 1
            _cut = f"{_y2:04d}-{_m2:02d}-{_d:02d}"
            _keep = [i for i, d in enumerate(days) if d >= _cut]
            if len(_keep) >= 2:
                days = [days[i] for i in _keep]
                nav = nav.iloc[_keep]
                _gross = _gross.iloc[_keep]
                rets = {k: v.iloc[_keep] for k, v in rets.items()}
        self._nav = nav
        tot, ann, dd = period_return(nav), annualized(nav), max_drawdown(nav)
        _day = (float(nav.iloc[-1]) / float(nav.iloc[-2]) - 1.0) if len(nav) >= 2 else None
        self._set_ov(ret=tot, nav=float(nav.iloc[-1]), day=_day)
        try:
            self._metrics[str(p.get("id") or "")] = {
                "ret": float(tot) * 100.0 if tot == tot else None,
                "day": float(_day) * 100.0 if _day is not None else None}
        except Exception:                  # noqa: BLE001
            pass
        _base_name0 = str((p.get("base") or {}).get("name") or (p.get("base") or {}).get("code") or "")
        self.nav_head.meta_label.setText(
            f"基准：{_base_name0 or '—'}　·　{len(days)} 个交易日 · {days[0]} → {days[-1]}"
            + (f"　·　缺 {len(missing)} 只" if missing else ""))

        # 画线：组合 + 基准（基准有数据才画，**没有就不画**）
        # ⚠ `main_pane` / `plot_item` 都是 **property**（不是方法）—— 写成 `()` 会 TypeError
        pi = self.chart.main_pane.plot_item
        x = np.arange(len(nav), dtype=float)
        import pyqtgraph as _pg
        # ★1.87：**先画"不含成本"、再画"含成本"** —— 成本很小时两条线几乎重合，
        #   旧顺序让细线盖住主线 ⇒ 用户看到"只有一条线、颜色还都差不多"。
        #   现在：细虚线在下、粗实线在上；虚线半透明，重合时也能透出主线颜色。
        import pyqtgraph as _pg
        _gpen = _pg.mkPen(color=(0, 163, 139, 150), width=1.4,
                          style=_pg.QtCore.Qt.PenStyle.DashLine)
        pi.plot(x, _gross.to_numpy(dtype=float), pen=_gpen, name="不含成本")
        pi.plot(x, nav.to_numpy(dtype=float),
                pen={"color": BASE_COLORS["nav"], "width": 2.4}, name="组合（含成本）")
        base_name = ""
        bdf, base_why = self._load_base_df(p.get("base") or {})
        if bdf is not None and len(bdf):
            bdays, brets = build_returns({"base": bdf})
            if bdays:
                _fill = {d: 0.0 for d in nav.index}
                _fill.update(brets["base"].to_dict())
                bnav = (1.0 + np.array([_fill.get(d, 0.0) for d in nav.index])).cumprod()
                pi.plot(x, bnav,
                        pen=_pg.mkPen(color=BASE_COLORS["base"], width=1.3,
                                      style=_pg.QtCore.Qt.PenStyle.DotLine), name="基准")
                base_name = str((p.get("base") or {}).get("name") or "")
                try:
                    self._set_ov(ret=tot, nav=float(nav.iloc[-1]), day=_day,
                                 excess=float(tot) - (float(bnav[-1]) - 1.0))
                except Exception:          # noqa: BLE001 —— 基准形状异常就不给超额
                    pass
        if bdf is None or not len(bdf):
            # ★1.87：基准缺数据要**说清原因**（不是只在图例里写四个字）
            _m0 = self.nav_head.meta_label.text()
            if "⚠" not in _m0:
                self.nav_head.meta_label.setText(f"{_m0}　·　⚠ {base_why or '基准无数据'}")
        # 稀疏日期刻度（最多 6 个）
        step = max(1, len(nav) // 6)
        ticks = [(float(i), str(nav.index[i])[5:]) for i in range(0, len(nav), step)]
        pi.getAxis("bottom").setTicks([ticks])
        pi.showGrid(x=False, y=True, alpha=0.15)
        pi.setLabel("left", "净值（基期 1.0000）")
        self.lbl_nav_meta.setText(
            f"总收益 <b>{self._pct(tot)}</b>（含成本）　·　年化 <b>{self._pct(ann)}</b>　·　"
            f"最大回撤 <b>{self._pct(-dd if dd == dd else float('nan'))}</b>　·　"
            f"换手 <b>{_res['turnover_total']:.1f}%</b>　·　"
            f"成本拖累 <b>{_res['cost_pct']:.2f}%</b>　·　"
            f"基准 <b>{base_name or '（本机无数据）'}</b>")
        self.lbl_legend.setText(
            f"<span style='color:{BASE_COLORS['nav']}'>━━ 含成本</span>　"
            f"<span style='color:{BASE_COLORS['gross']}'>┅┅ 不含成本</span>"
            + (f"　<span style='color:{BASE_COLORS['base']}'>··· 基准（{base_name}）</span>"
               if base_name else "　<span style='color:#9E9E9E'>基准：本机无数据</span>"))
        self.lbl_nav_note.setText(
            "口径：日线收盘（前复权）· 权重 = " + WEIGHT_LABELS.get(p.get("weight_mode"), "等权")
            + " · 再平衡 = " + REBALANCE_LABELS.get(p.get("rebalance"), "买入持有")
            + f" · 现金 {float(p.get('cash') or 0):.2f}%　·　<b>已含换手成本</b>"
              f"（每边 {commission_rate_from_prefs() * 10000:.2f} 万分之一 · 月末再平衡 · 买卖各收一次）"
            + (f"　·　⚠ {len(missing)} 只没有数据（已从曲线与持仓中如实标注）" if missing else ""))

        # 持仓：成本 = 基期收盘、最新 = 最后收盘
        first_close, last_close = {}, {}
        for s in symbols:
            df = frames.get(s)
            if df is None or not len(df):
                continue
            try:
                first_close[s] = float(df["close"].iloc[0])
                last_close[s] = float(df["close"].iloc[-1])
            except Exception:                  # noqa: BLE001
                continue
        rows = holdings_rows(symbols, names, weights, first_close, last_close)
        # ★1.87：持仓三视角（按标的/按行业/按市场）
        if self._hold_mode == "market":
            rows = self._group_rows(rows, lambda r: {"sh": "沪市", "sz": "深市",
                                                       "bj": "北交所"}.get(market_of(r["symbol"]), "其他"),
                                    "其他")
        elif self._hold_mode == "industry":
            _imap = {}
            try:
                from data.industry_store import get_industry_store as _gis2
                _imap = _gis2().as_map() or {}
            except Exception:              # noqa: BLE001
                _imap = {}
            rows = self._group_rows(rows, lambda r: _imap.get(str(r["symbol"])) or "未分类",
                                    "未分类")
        self._fill_holdings(rows, float(p.get("cash") or 0.0))
        # ★1.87：指标算完**立刻回写列表那一行**（否则要再点一次才看到收益）
        _cur = str(p.get("id") or "")
        for _i in range(self.lst.count()):
            _it = self.lst.item(_i)
            if str(_it.data(Qt.ItemDataRole.UserRole)) == _cur:
                _p2 = dict(p)
                _it.setText(self._item_text(_p2))
                _card = getattr(self, "_cards", {}).get(_cur)
                if _card is not None:
                    _mm = self._metrics.get(_cur) or {}
                    _card.fill(str(p.get("name") or "组合"),
                               str(p.get("source_group") or ""),
                               _mm.get("ret"), _mm.get("day"))
                break
        _ev = _res["events"]
        self.reb_head.meta_label.setText(f"{len(_ev)} 次 · 换手合计 {_res['turnover_total']:.1f}% · "
                                         f"成本拖累 {_res['cost_pct']:.2f}%")
        if _ev:
            _lines = [f"{e['date']}　换手 <b>{e['turnover_pct']:.2f}%</b>　"
                      f"成本 <b>{e['cost'] * 10000:.2f}‱</b>（占净值 {e['cost_pct']:.4f}%）"
                      for e in _ev[-5:]]
            self.lbl_reb.setText("<br>".join(_lines)
                                 + ("<br><span style='color:#8A94A6'>只显示最近 5 次</span>"
                                    if len(_ev) > 5 else ""))
        else:
            self.lbl_reb.setText("还没有再平衡（买入持有 · 或本月还没到月末）—— 没有换手就没有成本，这是对的。")
        ok = sum(1 for r in rows if r.get("data_ok"))
        _wsum = sum(float(r.get("weight") or 0) for r in rows)
        _cash = float(p.get("cash") or 0.0)
        self.hold_head.meta_label.setText(
            f"合计 {_wsum + _cash:.2f}% · {len(rows)} 只 + 现金 {_cash:.2f}%"
            + (f" · 有数据 {ok} 只" if ok != len(rows) else ""))
        self.lbl_hold_foot.setText(
            "权重：" + WEIGHT_LABELS.get(p.get("weight_mode"), "等权")
            + "（可改 等权 / 市值 / 自定义）　·　成本价 = 组合基期收盘　·　"
              "现金可调（默认 0%，不参与再平衡）　·　盈亏 = 最新 / 成本 − 1（区间涨跌）")

    def _fill_holdings(self, rows, cash: float = 0.0) -> None:
        """填持仓表；**现金单独一行**（样板如此，且用户强调"现金也能跑赢"）。"""
        rows = list(rows or [])
        self.tbl_hold.setRowCount(len(rows) + 1)
        for r, row in enumerate(rows):
            _has_price = row.get("cost") is not None
            ok = bool(row.get("data_ok")) and _has_price
            # 聚合行（按行业/按市场）本身没有单一成本价 ⇒ 显示「—」
            _cost_txt = "数据不足" if not row.get("data_ok") else (
                f"{row['cost']:.3f}" if _has_price else "—")
            _last_txt = "数据不足" if not row.get("data_ok") else (
                f"{row['last']:.3f}" if _has_price else "—")
            vals = [str(r + 1), row.get("symbol") or "", row.get("name") or "",
                    f"{float(row.get('weight') or 0):.2f}",
                    _cost_txt, _last_txt,
                    self._pct(row.get("pnl")) if row.get("pnl") is not None else "—"]
            for c, txt in enumerate(vals):
                it = QTableWidgetItem(txt)
                if c >= 3:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if not ok and c >= 4:
                    it.setToolTip("这只票在本机数据湖里没有日线 —— 不拿 0 冒充（§10-4）")
                self.tbl_hold.setItem(r, c, it)
        # 现金行（永远在最后一行；0% 也显示，避免"看不见现金"）
        _cash = float(cash or 0.0)
        _cr = len(rows)
        for c, txt in enumerate(["—", "现金", "现金",
                                 f"{_cash:.2f}", "—", "—", "—"]):
            _it = QTableWidgetItem(txt)
            if c >= 3:
                _it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            _it.setToolTip("现金（可调，默认 0%）：不参与再平衡、收益按 0 计"
                           "（用户口径：有时持有现金跑赢所有组合）")
            self.tbl_hold.setItem(_cr, c, _it)

    def _set_ov(self, ret=None, nav=None, day=None, excess=None) -> None:
        """概览四个数（含成本口径）；拿不到就给「—」，**不编 0**。"""
        vals = {"ret": ret, "nav": nav, "day": day, "excess": excess}
        for k, v in vals.items():
            w = (self.lbl_ov or {}).get(k)
            if w is None:
                continue
            if v is None:
                w.setText("—")
                continue
            w.setText(f"{float(v):.4f}" if k == "nav" else self._pct(v))

    @staticmethod
    def _fill_mix(ring, legend, data, tail: str) -> None:
        """把 `[(label, pct)]` 灌进环形 + 图例；**0 项也保留**（现金要看得见）。"""
        ring.set_data(data)
        rows = [f"{lab} <b>{float(v):.2f}%</b>" for lab, v in data]
        total = sum(float(v) for _lab, v in data)
        legend.setText("<br>".join(rows) + f"<br><span style='color:#8A94A6'>{tail} {total:.2f}%</span>")

    @staticmethod
    def _pct(v) -> str:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return "—"
        return "—" if f != f else f"{f * 100:+.2f}%"

    # ================= 动作 =================
    def _on_new(self) -> None:
        name, ok = QInputDialog.getText(self, "新建组合", "组合名称：", text="新组合")
        if not ok or not str(name).strip():
            return
        pf = new_portfolio(str(name).strip(), "", [])
        if self._store.save(pf):
            self._current = pf["id"]
            self.refresh()

    def _on_import(self) -> None:
        wl = self._watchlist()
        if wl is None:
            QMessageBox.information(self, "暂时读不到自选股",
                                    "行情页还没准备好自选股存储 —— 切到「市场行情」再回来。")
            return
        try:
            groups = list(wl.groups() or [])
        except Exception as e:                 # noqa: BLE001
            QMessageBox.warning(self, "读自选股组失败", str(e))
            return
        if not groups:
            QMessageBox.information(self, "还没有自选股组",
                                    "先去「市场行情 → 自选股」建一个组并加几只票，再回来导入。")
            return
        group, ok = QInputDialog.getItem(self, "从自选股组导入", "选择自选股组：", groups, 0, False)
        if not ok or not group:
            return
        try:
            entries = wl.entries_in(str(group)) or []
        except Exception as e:                 # noqa: BLE001
            QMessageBox.warning(self, "读组成分失败", str(e))
            return
        members = members_from_entries(entries)
        if not members:
            QMessageBox.information(self, "这个组还没有成分",
                                    f"「{group}」里没有股票 —— 先在行情页把票加进这个组。")
            return
        name, ok2 = QInputDialog.getText(self, "命名组合", "组合名称：", text=str(group))
        if not ok2 or not str(name).strip():
            return
        pf = new_portfolio(str(name).strip(), str(group), members)
        if self._store.save(pf):
            self._current = pf["id"]
            self.refresh()
        else:
            QMessageBox.warning(self, "保存失败", "组合没能写入磁盘（详见日志）。")

    def _on_edit(self) -> None:
        """手工编辑成分：加/删/改权重/现金（取消零副作用）。"""
        p = self._store.load_one(self._current) if self._current else None
        if not p:
            QMessageBox.information(self, "先选一个组合", "在左侧点一个组合，再编辑它的成分。")
            return
        dlg = PortfolioEditDialog(p, self, name_lookup=self.name_of)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dlg.result_portfolio()
        try:
            if not self._store.save(updated):
                QMessageBox.warning(self, "保存失败", "组合没能写入磁盘（详见日志）。")
                return
        except ValueError as exc:            # 权重合计不 100 ⇒ 人话拦下（对话框已校验，兜底）
            QMessageBox.warning(self, "权重不合法", str(exc))
            return
        self._current = str(updated.get("id") or self._current)
        self.refresh()

    def _on_rename(self) -> None:
        """双击列表项 ⇒ 改名（只改名字，不动成分/权重/口径）。"""
        p = self._store.load_one(self._current) if self._current else None
        if not p:
            return
        name, ok = QInputDialog.getText(self, "重命名组合", "组合名称：",
                                        text=str(p.get("name") or ""))
        name = str(name or "").strip()
        if not ok or not name or name == str(p.get("name") or ""):
            return
        p["name"] = name
        if not self._store.save(p):
            QMessageBox.warning(self, "保存失败", "改名没能写入磁盘（详见日志）。")
            return
        self.refresh()

    def _on_delete(self) -> None:
        if not self._current:
            return
        p = self._store.load_one(self._current)
        if not p:
            return
        if QMessageBox.question(self, "删除组合",
                                f"确定删除「{p.get('name')}」？\n（只删组合本身，**不动自选股组**）") \
                != QMessageBox.StandardButton.Yes:
            return
        if self._store.delete(self._current):
            self._current = ""
            self.refresh()

    # ================= 偏好 =================
    def _load_ui(self) -> None:
        try:
            data = preferences.get(UI_PREF_KEY) or {}
            self._current = str(data.get("last") or "")
        except Exception:                     # noqa: BLE001
            self._current = ""

    def _save_ui(self) -> None:
        try:
            preferences.set(UI_PREF_KEY, {"last": str(self._current or "")})
        except Exception:                     # noqa: BLE001
            pass


__all__ = ["PortfolioView", "UI_PREF_KEY"]
