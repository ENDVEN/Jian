# ui/views/portfolio_view.py
"""🧺 组合页（★1.85 / §7-B17 · **P0 已交付 + P1 净值/持仓**）。

【P0（已交付）】组合列表（新建/删除）· 空态 · **从自选股组导入**（等权）· 保存/重载。
【P1（本期）】**净值曲线**（组合 vs 基准，基期 1.0000 + 总收益/年化/最大回撤）· **持仓表**
（代码/名称/权重/成本/最新/盈亏）。
【P2–P4】市场·行业分布 → 组合回测（含佣金与换手）→ 接 B15 池化。

【成分唯一来源】`main_win.page_market.watchlist`（`data/watchlist_store.WatchlistStore`），**只读**。
⚠★1.90 口径纠正：导入/编辑时把**当时的成分存成快照**（`members`），`source_group` 只记名字用来溯源
  ⇒ 组改了**不会自动改组合**（自定义权重不许被静默覆盖）；渲染时若来源组成分与快照不一致会**提示**，
  要重新对齐请点「↻ 从自选股组导入」（会按等权重算）；组被删 ⇒ 如实标「来源组已不存在」，**不静默清空**。

【诚实边界（写在卡面上，不藏）】
  · 净值 = **价格收益**（日线收盘 · 前复权）· **已含换手成本**（每边按全局「回测佣金」，月末再平衡双边收）；
  · 基准**只允许指数/行业指数**（名称来自 `akshare_feed.INDEX_PRESETS`）；基准缺的交易日**不画线、也不当 0 收益**；
  · 某只票整只没数据 ⇒ 持仓表写「数据不足」，**不当 0 收益**；
  · 图上标"日线（收盘）"，**不做实时**。
"""
from __future__ import annotations

import os
import time as _time

import numpy as np
from PyQt6.QtCore import QSize, Qt
from ui.widgets.custom_widgets import COMBO_QSS_SMALL, NoWheelComboBox
from PyQt6.QtWidgets import (QDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
                             QInputDialog,
                             QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                             QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout,
                             QWidget)

from config import settings
from core.backtest import commission_rate_from_prefs
from core.portfolio_stats import (annualized, build_returns, holdings_rows, industry_mix,
                                  market_caps as _market_caps,
                                  market_mix, market_of, max_drawdown, nav_series,
                                  nav_with_costs,
                                  period_return)
from core.preferences import preferences
from data.market_db import DataLakeManager
from ui.dialogs.portfolio_edit import PortfolioEditDialog
from data.portfolio_store import (DEFAULT_BASE, REBALANCE_LABELS, WEIGHT_LABELS,
                                  PortfolioStore, append_change, diff_members,
                                  members_from_entries, new_portfolio)
from ui.widgets.chart_host import ChartHost
from ui.widgets.portfolio_changes import ChangeList, build_records
from ui.widgets.portfolio_parts import PfCard, RingChart, dot_title, overview_qss
from ui.widgets.styles import (EMPTY_STATE_QSS, SEC_HINT_QSS, SEC_TITLE_QSS,
                               SUMMARY_GHOST_QSS, SUMMARY_RUN_QSS, TABLE_HEAD_QSS,
                               WARN_HINT_QSS)
from ui.widgets.sweep_parts import panel_card, panel_head

UI_PREF_KEY = "portfolios_ui"
# ★1.87：三条线必须**一眼分得清**（用户实测：两条线颜色几乎一样、完全不可辨别）
#   含成本 = 深蓝实线 · 不含成本 = 青绿虚线 · 基准 = 中性灰点线（三种色相 + 三种线型）
BASE_COLORS = {"nav": "#1565C0", "gross": "#00A38B", "base": "#9E9E9E"}


def _weight_label(mode) -> str:
    """权重模式的**显示名**（★1.90：`cap` 已真接 = 最新收盘 × 最新流通股本）。"""
    m = str(mode or "equal")
    if m == "cap":
        return "流通市值（编辑时快照）"
    return WEIGHT_LABELS.get(m, "等权")


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
        # ★1.90：区间档改成"可读的键"（用户加了「今年以来」与「自组合建立」）
        self._range = "all"       # 3m / 1y / ytd / all / since
        self._pf_cur = None       # 当前渲染的组合（切窗口时重画用）
        self._names_cache = None  # 花名册（代码→名称），懒加载
        self._nav = None          # 最近一次算出的净值（Series）—— 断言与调试都读它
        self._build()
        self._load_ui()
        self.refresh()

    # ================= 版式 =================
    def _build(self) -> None:
        # ★1.88：本页卡片统一（圆角 12 / 细边框 #E7ECF3 / 字号体系统一）—— 只作用于组合页，
        #   不动物流/行情等其它页面（那些走全局 QSS，改动需整站回归）。
        self.setStyleSheet(
            "QFrame#panelCard { background:#FFFFFF; border:1px solid #E7ECF3; border-radius:12px; }"
            "QFrame#panelHead { background:transparent; border:none; }"
            "QLabel { font-size:12.5px; color:#3A4250; }")
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
        self.btn_import.setToolTip("读行情页「自选股 → 组」的成分，按等权生成组合（只读，不改自选）")
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
        # ★1.89：组合 ⇄ 自选股组 的桥（用户实测："组合建了，行情工作台看不到"）
        self.btn_pub = QPushButton("⇄ 生成自选股组")
        self.btn_pub.setStyleSheet(SUMMARY_GHOST_QSS)
        self.btn_pub.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pub.setToolTip("把当前组合的成分写进行情页的一个自选股组（同名），"
                                "组合随即引用该组 —— 两边从此是同一批票")
        self.btn_pub.setEnabled(False)
        self.btn_pub.clicked.connect(self._on_publish_group)
        head.addWidget(self.btn_pub)
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
        self.list_head = panel_head(dot_title("我的组合", "#1976D2"), "新 → 旧")
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
        self.sum_head = panel_head(dot_title("组合设置", "#78909C"), "")
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
            _val.setStyleSheet(overview_qss("neutral"))
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
        self.nav_head = panel_head(dot_title("净值曲线", "#00A38B"), "日线（收盘）· 基期 1.0000")
        nl.addWidget(self.nav_head)
        # ★1.87：区间档（只影响**显示窗口**与窗口内 KPI，不改任何口径）
        _wrow = QHBoxLayout()
        _wrow.setSpacing(4)
        self._win_btns = {}
        # ★1.88："全部"是伪命题（各票上市日不同）⇒ 改为"成立以来"，
        #   起点 = **所有成分都有数据的第一天**（build_returns 已改交集）
        # ★1.90：加「今年以来」（1 月 1 日至今）与「自组合建立」（`created_at` 起）——
        #   后者才是"我自己真正持有这段"的口径；创建日早于本机数据起点时按数据起点画并说明。
        for _k, _t in (("3m", "近 3 月"), ("1y", "近 1 年"), ("ytd", "今年以来"),
                       ("all", "成立以来"), ("since", "自组合建立")):
            _b = QPushButton(_t)
            _b.setCheckable(True)
            _b.setChecked(_k == self._range)
            _b.setCursor(Qt.CursorShape.PointingHandCursor)
            _b.setStyleSheet(SUMMARY_GHOST_QSS + " QPushButton:checked { background:#1976D2;"  " color:#FFFFFF; border-color:#1976D2; }")
            _b.clicked.connect(lambda _c=False, k=_k: self._set_window(k))
            _wrow.addWidget(_b)
            self._win_btns[_k] = _b
        _wrow.addStretch(1)
        # ★1.89：基准**与区间同一行**（用户：放下面不好看），并给足宽度
        _wrow.addWidget(QLabel("基准"))
        self.cmb_base = NoWheelComboBox()
        self.cmb_base.setStyleSheet(COMBO_QSS_SMALL)
        self.cmb_base.setMinimumWidth(150)
        self.cmb_base.setMaximumWidth(240)
        self.cmb_base.setToolTip("换基准只换对照线，不改组合成分") 
        self.cmb_base.currentIndexChanged.connect(self._on_base_changed)
        _wrow.addWidget(self.cmb_base, 1)
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
        self.hold_head = panel_head(dot_title("持仓", "#7E57C2"), "")
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
        _ml.addWidget(panel_head(dot_title("市场分布", "#FB8C00"), "按权重 · 现金单列"))
        _rowm = QHBoxLayout()
        _rowm.setSpacing(10)
        self.ring_mkt = RingChart(self, palette_offset=0)
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
        _head_ind = panel_head(dot_title("行业分布", "#7E57C2"), "按权重 · 未分类单列")
        _il.addWidget(_head_ind)
        _rowi = QHBoxLayout()
        _rowi.setSpacing(10)
        self.ring_ind = RingChart(self, palette_offset=2)
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
        self.btn_ind_sync.setToolTip(
            "按当前组合的成分补行业：按标的批量取（100 只/请求）⇒ 通常 1~3 个请求补满；"
            "东财没给的票会点名，不会瞎猜")
        self.btn_ind_sync.clicked.connect(self._on_sync_industry)
        _irow.addWidget(self.btn_ind_sync, 0)
        _il.addLayout(_irow)



        # ④ 再平衡记录（P3）：只记**软件内**发生过的再平衡（时间 / 换手 / 成本）
        self.card_reb = panel_card()
        rl2 = QVBoxLayout(self.card_reb)
        rl2.setContentsMargins(10, 8, 10, 10)
        rl2.setSpacing(6)
        self.reb_head = panel_head(dot_title("调仓记录", "#8D6E63"), "手动改成分 + 月末再平衡")
        rl2.addWidget(self.reb_head)
        # ★1.90：富文本一坨 ⇒ 换成控件列表（日期一行 + 每笔一行 + 左标签右数值，参考富途）
        self.reb_list = ChangeList(self.card_reb)
        rl2.addWidget(self.reb_list, 1)
        # 说明/空态文案（"为什么没有记录"必须能讲清，不能只是空白）
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
        for _c in (self.ov_box, self.card_mkt, self.card_ind):
            self._rail_lay.addWidget(_c, 0)
        # ★1.90（用户 2026-10-28）：记录卡**吃满右栏剩余高度** —— 旧版在末尾 `addStretch(1)`，
        #   多出来的高度全给了空白，记录框被压成一条（他实测"文本框太小"）。
        self._rail_lay.addWidget(self.card_reb, 1)
        grid.addWidget(self.rail, 0, 2)
        self._rail_in_grid = True
        self._rail_narrow = False          # ★独立记录"当前是不是窄态"（别拿 in_grid 当状态）
        self._grid = grid
        self._detail_lay = dl
        root.addLayout(grid, 1)

        self.detail.hide()

    # ★1.90：基准**只允许指数 / 行业指数**（用户 2026-10-28："下拉里一堆代码严重影响使用体验"）。
    #   名称与前缀的**唯一真源** = `data.akshare_feed.INDEX_PRESETS`（30 个大盘/行业指数，键带 sh/sz/bj）。
    #   ⚠ 旧版拿"数据湖里有哪几个文件"当下拉项 ⇒ 899050 / 000688 这类**裸代码**直接怼到用户脸上
    #     （那 5 个不在旧 `INDEX_NAMES` 里的指数就只能显示文件名）。现在：名字不认识的不列、个股不进基准。
    @staticmethod
    def _index_catalog() -> dict:
        """`{'000300': ('sh000300', '沪深300')}`（6 位代码 → 带市场前缀的文件名 / 中文名）。"""
        from data.akshare_feed import INDEX_PRESETS
        return {str(_s)[2:]: (str(_s), str(_n)) for _s, _n in INDEX_PRESETS.items()}

    @staticmethod
    def _local_index_codes() -> set:
        """本机 `index_daily` 里已下载的指数代码（6 位）—— 只用来标「已下载/未下载」。"""
        try:
            d = os.path.join(settings.USER_DATA_DIR, "data_lake", "macro", "index")
            out = set()
            for n in os.listdir(d):
                if n.endswith(".parquet"):
                    code = n[:-8][-6:]
                    if code.isdigit():
                        out.add(code)
            return out
        except Exception:                  # noqa: BLE001
            return set()

    def _available_indices(self) -> str:
        """本机已有指数**的名字**（给用户一句实话，而不是一串文件名）。"""
        cat = self._index_catalog()
        have = [cat[c][1] for c in cat if c in self._local_index_codes()]
        return "、".join(have[:4]) + ("…" if len(have) > 4 else "") if have else "无"

    def _load_base_df(self, base: dict):
        """基准日线：指数在 `index_daily`（文件名 = 市场前缀 + 代码，如 `sh000300`）。

        ★1.87 修：旧版只查 `kline_daily` ⇒ 指数基准永远"本机无数据"（用户已下载也看不到）。
        ★1.90：文件名由 `INDEX_PRESETS` 精确给出（旧版对 899050 这类会猜成 `sh899050` ⇒ 永远读不到）；
               个股档只为**历史数据**保留（界面已不再提供"个股当基准"）。
        返回 `(df, 人话原因)`。
        """
        code = str((base or {}).get("code") or "").strip()
        if not code:
            return None, "未设基准"
        kind = str((base or {}).get("kind") or "index")
        tries = []
        if kind == "index":
            fn = self._index_catalog().get(code, ("", ""))[0] or f"sh{code}"
            tries.append(("index_daily", fn))
        else:                                       # 旧数据：曾把个股当基准（界面已不再提供）
            tries.append(("kline_daily", code))
        tries.append(("index_daily", code))
        for zone, fn in tries:
            try:
                df = self._lake.load_data(zone, fn)
            except Exception:                  # noqa: BLE001
                df = None
            if df is not None and len(df):
                return df, ""
        _nm = self._index_catalog().get(code, ("", ""))[1] or code
        return None, (f"本机没有「{_nm}」的日线；去「🗄 数据管理 → 批量预下载 → 指数预设」补"
                      f"（当前已有：{self._available_indices()}）")

    def _set_hold_mode(self, mode: str) -> None:
        """持仓三种视角（按标的/行业/市场）。只重排显示，不动成分。

        ★1.90：**必须真的重画**。旧版 `if self._pf_cur is not None` 才重画，而 `_pf_cur`
        在"空成分/缺数据"的早退路径上还是 None（旧版只在算成功那一步赋值）⇒ 出现
        "按钮跳到「按标的」、表格却还是按行业聚合的『未分类 90%』"这种自相矛盾的画面。
        现在：没有现成快照就**从存储里捞当前组合**再渲染。
        """
        self._hold_mode = str(mode or "symbol")
        for k, b in self._hold_btns.items():
            b.setChecked(k == self._hold_mode)
        p = self._pf_cur
        if p is None and self._current:
            p = self._store.load_one(self._current)
        if p is not None:
            self._render(p)

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

    @staticmethod
    def _em_logged_in() -> bool:
        """东财是否已登录（只读凭据状态，不发请求）。判据坏了按"未登录"处理。"""
        try:
            from data import em_auth
            return bool(em_auth.is_logged_in())
        except Exception:                  # noqa: BLE001
            return False

    def _goto_em_login(self) -> None:
        """跳去设置页的「账号」组（东财登录的唯一入口）。失败不打扰。"""
        try:
            self.main_win.switch_to("settings")
            self.main_win.page_settings.open_group("account")
        except Exception:                  # noqa: BLE001
            pass

    def _current_members(self) -> list:
        """当前显示的组合的成分（优先渲染态，其次存储）。"""
        p = self._pf_cur or (self._store.load_one(self._current) if self._current else None)
        return [str(m.get("symbol")) for m in ((p or {}).get("members") or []) if str(m.get("symbol") or "")]

    def _on_sync_industry(self) -> None:
        """**按当前组合的成分**补行业（★1.91）。

        【为什么改】旧版走全市场分页（每批 3 页 ≈300 只、**按代码升序**）⇒ 一个 300 只的组合
        要十几轮才轮到它关心的票（§11.5-106 的真实教训），用户体感就是"永远补不满"。
        现在按标的批量取（`fetch_enrich_map`，100 只/请求）⇒ **1~3 个请求**把本组合一次补满；
        库里其它标的照旧保留（`merge` 只增不减）。全市场分页那条路仍留给 M2/M3（它们要全市场）。
        """
        w0 = getattr(self, "_ind_worker", None)
        if w0 is not None and w0.isRunning():
            return
        members = self._current_members()
        if not members:
            QMessageBox.information(
                self, "先选一个组合",
                "行业是按当前组合的成分补的 —— 先在左侧点一个组合（或先给它加几只票）。\n"
                "（全市场补行业在「市场回测 → 全市场筛选」里，那边才是整市场扫。）")
            return
        # 未登录东财 ⇒ 匿名档**常被整段 RST**（§11.5-99）⇒ 先说清楚并给一条出路，
        #   别让用户点完只看到"没取到"（他修不好，也不该由他猜）。
        if not self._em_logged_in():
            _box = QMessageBox(self)
            _box.setWindowTitle("东财未登录")
            _box.setText("现在<b>没有登录东财</b>，匿名访问经常被整段拒绝（行业/估值都取不到）。")
            _box.setInformativeText("登录只需粘贴一次浏览器 Cookie（不用账号密码），之后一直有效。")
            _b_go = _box.addButton("去设置登录", QMessageBox.ButtonRole.AcceptRole)
            _box.addButton("先试一次", QMessageBox.ButtonRole.RejectRole)
            _box.exec()
            if _box.clickedButton() is _b_go:
                self._goto_em_login()
                return
        from data.industry_store import get_industry_store
        from ui.workers import IndustryPoolWorker
        w = IndustryPoolWorker(members, parent=self)
        self._ind_worker = w
        self.btn_ind_sync.setEnabled(False)
        self.lbl_ind_note.setText(f"正在补行业（{len(members)} 只 · 按标的批量取）…")

        def _done(res) -> None:
            self.btn_ind_sync.setEnabled(True)
            res = res or {}
            mp = res.get("map") or {}
            store = get_industry_store()
            _saved, _why = True, "详见日志。"
            try:
                _saved = bool(store.merge(mp)) if mp else True
            except Exception as exc:       # noqa: BLE001
                _saved, _why = False, f"{type(exc).__name__}: {exc}"
            if not _saved:
                self.lbl_ind_note.setText(
                    f"抓到 {len(mp)} 条但没写进磁盘（{_why}）—— 已有映射不会丢，稍后再点一次。")
                return
            _err = str(res.get("error") or "").strip()
            # 匿名访问东财常被整段 RST（§11.5-99）⇒ 必须给一条**用户能执行**的出路，不只报错
            _hint = ("—— 东财对匿名访问常直接拒连：去「⚙ 设置 → 东财账号」登录后再点一次"
                     if any(k in _err for k in ("RemoteDisconnected", "Proxy", "RST",
                                                "Connection", "timed out")) else
                     "—— 稍后再点一次")
            miss = list(res.get("missed") or [])
            if not mp and _err:
                self.lbl_ind_note.setText(f"这次没取到（{_err}）{_hint}；已有映射不会丢。")
            elif miss:
                _nm = "、".join(miss[:4]) + ("…" if len(miss) > 4 else "")
                self.lbl_ind_note.setText(
                    f"本组合 {len(mp)}/{len(members)} 只有行业 · 缺 {len(miss)} 只（{_nm}）"
                    " —— 东财没给这几只（停牌/退市/非 A 股），**不瞎猜**")
            else:
                self.lbl_ind_note.setText(
                    f"本组合 {len(mp)}/{len(members)} 只都有行业了 · 库内共 {store.coverage()} 条")
            if self._pf_cur is not None:
                self._render(self._pf_cur)

        w.finished.connect(_done)
        w.start()

    def _base_options(self) -> list:
        """基准可选项：`[(显示名, {kind, code, name})]` —— **只有指数/行业指数**，先已下载再未下载。

        ★1.90（用户 2026-10-28 实测）：旧版把"数据湖里有哪几个文件"当列表项，名字不认识就显示文件名
          ⇒ 下拉里出现 `899050 / 000009 / 000688` 这类裸代码，"严重影响使用体验"。
          ⇒ 现在显示名一律取 `INDEX_PRESETS` 的中文名；**认不出的本地指数不列**（宁可少一项，也不摆代码）；
             个股不再作为基准（`kind` 恒为 `index`）。
        """
        cat = self._index_catalog()
        have = self._local_index_codes()
        out = []
        for want_local in (True, False):           # ① 已下载 ② 未下载（都按预设顺序，不按文件名排序）
            for code, (_fn, nm) in cat.items():
                if (code in have) is not want_local:
                    continue
                out.append((nm if want_local else f"{nm}（未下载）",
                            {"kind": "index", "code": code, "name": nm}))
        return out

    def _refresh_base_combo(self, base: dict) -> None:
        """按当前组合的基准回填下拉（无匹配时**如实追加一项**，不清空、不假装）。"""
        opts = self._base_options()
        cur = dict(base or {})
        cur_code = str(cur.get("code") or "")
        self.cmb_base.blockSignals(True)
        self.cmb_base.clear()
        for label, val in opts:
            self.cmb_base.addItem(label, val)
        idx = next((i for i in range(self.cmb_base.count())
                    if str((self.cmb_base.itemData(i) or {}).get("code")) == cur_code), -1)
        if idx < 0 and cur_code:
            # 旧数据：基准是个股 / 已下架指数 / 不认识的名字 ⇒ 原样列出来（不静默换成沪深300）
            _nm = str(cur.get("name") or cur_code)
            self.cmb_base.addItem(f"{_nm}（当前 · 不在指数预设内）",
                                  {"kind": str(cur.get("kind") or "index"),
                                   "code": cur_code, "name": _nm})
            idx = self.cmb_base.count() - 1
        if idx >= 0:
            self.cmb_base.setCurrentIndex(idx)
        self.cmb_base.blockSignals(False)
        _unknown = len(self._local_index_codes() - set(self._index_catalog()))
        self.cmb_base.setToolTip(
            "换基准只换对照线，不改组合成分（只列指数 / 行业指数）"
            + (f"\n本机另有 {_unknown} 个未收录名称的指数未列出（可在 🗄 数据管理 里查看/删除）"
               if _unknown else ""))

    def _on_base_changed(self, _idx: int) -> None:
        """换基准：只改对照线，不动成分/权重；写回存储（**失败必须出声**，否则界面与磁盘不一致）。"""
        val = self.cmb_base.currentData()
        p = self._store.load_one(self._current) if self._current else None
        if not val or not p:
            return
        _old = dict(p.get("base") or {})
        p["base"] = dict(val)
        _why = "详见日志。"
        try:
            ok = self._store.save(p)
        except Exception as exc:              # noqa: BLE001
            ok = False
            _why = f"{type(exc).__name__}: {exc}"
        if not ok:
            p["base"] = _old
            self._render(p)                   # 回到磁盘上的那一份
            QMessageBox.warning(self, "基准没保存成功",
                                f"「{val.get('name') or val.get('code')}」没能写入磁盘，"
                                "界面已退回原基准。\n" + _why)
            return
        self._render(p)

    def _set_window(self, key) -> None:
        """切净值显示区间（`3m/1y/ytd/all/since`）。只重画，不重算成本、不动存储。

        ★1.90：键从"月数"改成可读字符串（多两档语义不同：今年以来 / 自组合建立）。
        """
        self._range = str(key or "all")
        for k, b in self._win_btns.items():
            b.setChecked(k == self._range)
        if self._pf_cur is not None:
            self._render(self._pf_cur)

    def _range_cut(self, p: dict, days) -> tuple:
        """当前区间档 → `(cut_date, 说明)`；`cut_date == ""` ⇒ 不裁。

        说明只在"画不出/被改口径"时给（例如自组合建立那天之后只有 1 个交易日）。
        """
        key = str(self._range or "all")
        if key == "all" or not days:
            return "", ""
        last = str(days[-1])
        if key in ("3m", "1y"):
            months = 3 if key == "3m" else 12
            try:
                _y, _m, _d = (int(x) for x in last.split("-"))
            except ValueError:
                return "", ""
            _m2 = _m - months
            _y2 = _y + (_m2 - 1) // 12
            _m2 = (_m2 - 1) % 12 + 1
            return f"{_y2:04d}-{_m2:02d}-{_d:02d}", ""
        if key == "ytd":
            return f"{last[:4]}-01-01", ""
        if key == "since":
            _c = str((p or {}).get("created_at") or "")[:10]
            if not _c:
                return "", "组合没有创建时间"
            if _c < str(days[0]):
                return "", f"组合创建于 {_c}（早于本机数据起点 {days[0]}，按数据起点画）"
            return _c, ""
        return "", ""

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
            _card = PfCard(self.lst)
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
            self.btn_pub.setEnabled(False)
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
        """按需读日线（缓存键 = 标的 + 各文件 mtime）。

        ★1.90：缓存键里带 **文件修改时间** —— 旧版只按标的缓存且永不失效 ⇒ 补下载完日线回来看
          还是旧曲线（用户会以为下载没生效）。缺失的票**不进** dict（由界面写"数据不足"）。
        """
        syms = [str(s) for s in symbols]
        _mtime = getattr(self._lake, "file_mtime", None)      # 打桩的假湖可能没有它 ⇒ 退化为 0.0
        key = tuple((s, float(_mtime("kline_daily", s)) if callable(_mtime) else 0.0)
                    for s in syms)
        if key in self._cache:
            return self._cache[key]
        out = {}
        for s in syms:
            try:
                df = self._lake.load_data("kline_daily", s)
            except Exception:                  # noqa: BLE001 —— 读失败按"没有数据"处理，如实显示
                df = None
            if df is not None and len(df):
                out[s] = df
        if len(self._cache) > 8:               # mtime 作键后每批都不同 ⇒ 留最近几批，防无限长
            self._cache.clear()
        self._cache[key] = out
        return out

    def caps_of(self, symbols) -> tuple:
        """`({symbol: 流通市值(元)}, [缺市值的 symbol])` —— 编辑框「市值」档的取数口（只读日线）。

        ★1.90：市值 = **最新收盘 × 最新流通股本**（`outstanding_share`）。本机日线实测
        5168/5169 个文件都有这一列（东财兜底源没有 ⇒ 那几只进 `missing`，界面点名、权重记 0）。
        """
        return _market_caps(self._frames(symbols))

    def _on_select(self, cur, _prev) -> None:
        if cur is None:
            return
        pid = str(cur.data(Qt.ItemDataRole.UserRole) or "")
        p = self._store.load_one(pid) if pid else None
        if not p:
            return
        self._current = pid
        self.btn_pub.setEnabled(True)
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
        self.sum_head.meta_label.setText(f"共 {len(members)} 只 · {_weight_label(p.get('weight_mode'))}")
        # ★1.87：与样板对齐 —— 摘要**压成一行**（样板没有"设置卡"，口径走在页脚）
        self.lbl_sum.setText(
            f"来源组：<b>{group or '（未指定）'}</b>　·　"
            f"权重：<b>{_weight_label(p.get('weight_mode'))}</b>　·　"
            f"现金：<b>{float(p.get('cash') or 0):.2f}%</b>　·　"
            f"基准：<b>{base.get('name') or base.get('code')}</b>　·　"
            f"再平衡：<b>{REBALANCE_LABELS.get(p.get('rebalance'), '买入持有')}</b>")
        missing = bool(group) and not self._group_exists(group)
        if missing:
            self.lbl_warn.setText("⚠ 来源组「" + group + "」在行情页已不存在（被删或改名）—— "
                                 "成分不会自动更新；请重新「从自选股组导入」，或先在行情页恢复该组。")
            self.lbl_warn.show()
        elif group:
            # ★1.90：组还在、但成分与组合快照不一致 ⇒ **说出来**（不静默跟随、也不静默忽略）。
            #   为什么不自动跟随：组里加一只就自动改组合，会把用户手调的权重静默冲掉。
            _warn = ""
            try:
                _wl = self._watchlist()
                _syms = {str(s) for s in (_wl.symbols_in(group) or [])} if _wl is not None else set()
                _mine = {str(m.get("symbol")) for m in members}
                if _syms and _syms != _mine:
                    _warn = (f"⚠ 来源组「{group}」现在有 {len(_syms)} 只，组合存的是 {len(_mine)} 只 —— "
                             "组变了不会自动改组合（手调的权重不会被静默覆盖）。"
                             "要对齐请点「↻ 从自选股组导入」重新生成（会按等权计算）。")
            except Exception:              # noqa: BLE001 —— 读不到就不提示，不打扰
                _warn = ""
            if _warn:
                self.lbl_warn.setText(_warn)
                self.lbl_warn.show()
            else:
                self.lbl_warn.hide()
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
            # ★1.91：讲**本组合的覆盖率**（旧版只报"库内 N 条"，用户看不出自己缺几只）
            _miss = [str(m.get("symbol")) for m in members if not _imap.get(str(m.get("symbol")))]
            _have = len(members) - len(_miss)
            if not _imap:
                self.lbl_ind_note.setText(
                    f"本组合 0/{len(members)} 只有行业 ⇒ 点「↻ 同步行业」（按本组合补，1~3 个请求）")
            elif _miss:
                _nm = "、".join(_miss[:3]) + ("…" if len(_miss) > 3 else "")
                self.lbl_ind_note.setText(
                    f"本组合 {_have}/{len(members)} 只有行业 · 缺 {len(_miss)} 只（{_nm}）"
                    + ("" if self._em_logged_in() else " · 未登录东财（匿名档常被拒）"))
            else:
                self.lbl_ind_note.setText(
                    f"本组合 {_have}/{len(members)} 只有行业 · 库内共 {len(_imap)} 条")
        except Exception:                  # noqa: BLE001
            pass

        try:
            self._refresh_base_combo(base)
        except Exception:                  # noqa: BLE001
            pass
        self._render_p1(p)

    # ---------------- P1：净值 + 持仓 ----------------
    def _render_p1(self, p: dict) -> None:
        # ★1.90：**先记当前组合再干别的** —— 旧版只在"算成功了"那一步赋值，空成分/缺数据的早退
        #   会让 `_pf_cur` 停在上一个组合 ⇒ 此时点「按行业」「近 3 月」会把**上一只组合**重新渲染一遍。
        self._pf_cur = dict(p)
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
            self.lbl_nav_meta.setText("先「↻ 从自选股组导入」或「✏ 编辑成分」—— 没有成分时不画线。")
            self.lbl_nav_note.setText("")
            self.hold_head.meta_label.setText("0 只")
            self.tbl_hold.setRowCount(0)
            # ★1.90：成分被清空时**历史仍要看得到**（旧版直接写"没有调仓"，等于把账本也删了）
            self._render_changes_only(p)
            self._set_ov()
            return

        days, rets = build_returns(frames)
        missing = [s for s in symbols if s not in frames]
        if not days:
            self.nav_head.meta_label.setText("数据不足")
            self.lbl_nav_meta.setText(
                f"本机日线里没有这 {len(symbols)} 只的数据 —— 先去 🗄 数据管理 预下载（不拿假数据凑图）。")
            self.lbl_nav_note.setText("")
            self.hold_head.meta_label.setText(f"{len(symbols)} 只 · 全部缺数据")
            self._fill_holdings(holdings_rows(symbols, names, weights, {}, {}),
                                float(p.get("cash") or 0.0))
            self._render_changes_only(p)
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
            self._render_changes_only(p)
            self._set_ov()
            return

        # ★1.85 P3：**含换手成本**（用户口径：月末再平衡、双边、按全局「回测佣金」）
        _fee = commission_rate_from_prefs()
        _res = nav_with_costs(days, rets, weights, float(p.get("cash") or 0.0),
                              str(p.get("rebalance") or "monthly"), _fee)
        nav = _res["nav_net"]
        _gross = _res["nav_gross"]
        # ★1.87：按区间裁剪（只裁显示；成本已在全区间算过，**不会因切档而变**）
        # ★1.90：区间档扩到 5 个（多「今年以来」「自组合建立」）；裁不出曲线时**出声**，不悄悄画全段。
        _cut, _range_note = self._range_cut(p, days) if len(days) else ("", "")
        if _cut and len(days):
            _keep = [i for i, d in enumerate(days) if d >= _cut]
            if len(_keep) >= 2:
                days = [days[i] for i in _keep]
                nav = nav.iloc[_keep]
                _gross = _gross.iloc[_keep]
                rets = {k: v.iloc[_keep] for k, v in rets.items()}
                # ★1.88：**区间内重新定基 1.0000**（用户实测：点"近1年"起点是 1.6，
                #   因为旧版只是截取了全区间净值的一段）
                try:
                    nav = nav / float(nav.iloc[0])
                    _gross = _gross / float(_gross.iloc[0])
                except Exception:          # noqa: BLE001
                    pass
            else:
                _lb = str(self._win_btns[self._range].text()) if self._range in self._win_btns else self._range
                _range_note = (f"「{_lb}」区间内只有 {len(_keep)} 个交易日，画不出曲线"
                               if _keep else
                               f"「{_lb}」区间内没有交易日（数据最新到 {days[-1]}）")
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
            + (f"　·　缺 {len(missing)} 只" if missing else "")
            + (f"　·　⚠ {_range_note}" if _range_note else ""))

        # 画线：组合 + 基准（基准有数据才画，**没有就不画**）
        # ⚠ `main_pane` / `plot_item` 都是 **property**（不是方法）—— 写成 `()` 会 TypeError
        pi = self.chart.main_pane.plot_item
        x = np.arange(len(nav), dtype=float)
        import pyqtgraph as _pg
        # ★1.87：**先画"不含成本"、再画"含成本"** —— 成本很小时两条线几乎重合，
        #   旧顺序让细线盖住主线 ⇒ 用户看到"只有一条线、颜色还都差不多"。
        #   现在：细虚线在下、粗实线在上；虚线半透明，重合时也能透出主线颜色。
        _gpen = _pg.mkPen(color=(0, 163, 139, 150), width=1.4,
                          style=_pg.QtCore.Qt.PenStyle.DashLine)
        pi.plot(x, _gross.to_numpy(dtype=float), pen=_gpen, name="不含成本")
        pi.plot(x, nav.to_numpy(dtype=float),
                pen={"color": BASE_COLORS["nav"], "width": 2.4}, name="组合（含成本）")
        base_name = ""
        _drew_base = False
        bdf, base_why = self._load_base_df(p.get("base") or {})
        if bdf is not None and len(bdf):
            bdays, brets = build_returns({"base": bdf})
            if bdays:
                _base_nm = str((p.get("base") or {}).get("name") or (p.get("base") or {}).get("code") or "")
                # ★1.90（用户 2026-10-28 前实测口径问题）：**缺的交易日不许当 0 收益**。
                #   旧版把 nav.index 每天先塞一个 0 收益再覆盖 ⇒ "基准那时还没数据"被画成一条
                #   **一动不动的假平线**（组合 2010 起、指数 2015 起时最明显），超额收益也跟着假。
                #   现在：缺就留 NaN ⇒ 图上是**断线**，并在卡头写明基准从哪天起才有数据。
                _bs = brets["base"].reindex(nav.index)
                _mask = np.asarray(_bs.notna().to_numpy(), dtype=bool)
                if _mask.any():
                    _arr = _bs.to_numpy(dtype=float)
                    bnav = np.full(len(nav), np.nan, dtype=float)
                    bnav[_mask] = np.cumprod(1.0 + np.nan_to_num(_arr[_mask], nan=0.0))
                    pi.plot(x[_mask], bnav[_mask],
                            pen=_pg.mkPen(color=BASE_COLORS["base"], width=1.3,
                                          style=_pg.QtCore.Qt.PenStyle.DotLine), name="基准")
                    base_name = _base_nm
                    _drew_base = True
                    if not bool(_mask.all()):
                        # 起点不同必须说出来（否则用户以为基准"横盘"了半年）
                        self.nav_head.meta_label.setText(
                            self.nav_head.meta_label.text()
                            + f"　·　⚠ 基准自 {str(nav.index[_mask][0])} 起才有数据（之前不画线）")
                    try:
                        # 超额 = **同一段共同区间**上的收益差（区间不同不能相减）
                        _nv = nav.to_numpy(dtype=float)[_mask]
                        _ex = (float(_nv[-1]) / float(_nv[0]) - 1.0) - (float(bnav[_mask][-1]) - 1.0)
                        self._set_ov(ret=tot, nav=float(nav.iloc[-1]), day=_day, excess=_ex)
                    except Exception:          # noqa: BLE001 —— 基准形状异常就不给超额
                        pass
        if not _drew_base:
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
            "口径：日线收盘（前复权）· 权重 = " + _weight_label(p.get("weight_mode"))
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
        self._fill_records(p, _res["events"], cost_pct=_res["cost_pct"])

        ok = sum(1 for r in rows if r.get("data_ok"))
        _wsum = sum(float(r.get("weight") or 0) for r in rows)
        _cash = float(p.get("cash") or 0.0)
        self.hold_head.meta_label.setText(
            f"合计 {_wsum + _cash:.2f}% · {len(rows)} 只 + 现金 {_cash:.2f}%"
            + (f" · 有数据 {ok} 只" if ok != len(rows) else ""))
        self.lbl_hold_foot.setText(
            "权重：" + _weight_label(p.get("weight_mode"))
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
        """概览四个数（含成本口径）；拿不到就给「—」，**不编 0**。

        ★1.89：**按数值上色**（用户要求）——正=绿、负=红、等于 0=灰；
        净值以 1.0000 为基准色（>1 绿 / <1 红）。
        """
        vals = {"ret": ret, "nav": nav, "day": day, "excess": excess}
        for k, v in vals.items():
            w = (self.lbl_ov or {}).get(k)
            if w is None:
                continue
            if v is None:
                w.setText("—")
                w.setStyleSheet(overview_qss("neutral"))
                continue
            _num = float(v)
            if k == "nav":
                w.setText(f"{_num:.4f}")
                _tone = "up" if _num > 1.0 else ("down" if _num < 1.0 else "neutral")
            else:
                w.setText(self._pct(_num))
                _tone = "up" if _num > 0 else ("down" if _num < 0 else "neutral")
            w.setStyleSheet(overview_qss(_tone))

    @staticmethod
    def _change_line(c: dict) -> str:
        """一条「手动改成分」记录 → 一行富文本（日期 + 具体哪只票从多少改到多少）。"""
        _bits = []
        for x in (c.get("moved") or [])[:3]:
            _d = float(x.get("delta") or 0.0)
            _col = "#2E7D32" if _d > 0 else "#C62828"
            _bits.append(f"<span style='color:{_col}'>{x.get('name') or x.get('symbol')} "
                         f"{float(x.get('before') or 0):.2f}→{float(x.get('after') or 0):.2f}%"
                         f"（{_d:+.2f}）</span>")
        for x in (c.get("added") or [])[:2]:
            _bits.append(f"<span style='color:#1976D2'>新增 {x.get('name') or x.get('symbol')} "
                         f"{float(x.get('weight') or 0):.2f}%</span>")
        for x in (c.get("removed") or [])[:2]:
            _bits.append(f"<span style='color:#C62828'>剔除 {x.get('name') or x.get('symbol')}"
                         f"（原 {float(x.get('weight') or 0):.2f}%）</span>")
        if abs(float(c.get("cash_after") or 0.0) - float(c.get("cash_before") or 0.0)) >= 0.005:
            _bits.append(f"现金 {float(c.get('cash_before') or 0):.2f}→"
                         f"{float(c.get('cash_after') or 0):.2f}%")
        _n = (len(c.get("moved") or []) + len(c.get("added") or []) + len(c.get("removed") or []))
        if _n > len(_bits) and _n > 1:
            _bits.append(f"<span style='color:#8A94A6'>等 {_n} 项</span>")
        return (f"<span style='color:#9AA6B8'>{c.get('at') or '—'}</span>　"
                + "　".join(_bits[:4]))

    def _render_changes_only(self, p: dict) -> None:
        """只渲染「调仓记录」卡 —— 净值算不出来的早退分支也要有账本（否则会留着上一次的旧内容）。"""
        self._fill_records(p)

    def _fill_records(self, p: dict, events=(), cost_pct=None) -> None:
        """刷新「调仓记录」卡（★1.90：控件列表 + 不截断）。"""
        _chg = list(p.get("changes") or [])
        _ev = list(events or [])
        _n = len(_chg) + len(_ev)
        _meta = f"手动改成分 {len(_chg)} 次 · 再平衡 {len(_ev)} 次"
        if cost_pct is not None:
            _meta += f" · 成本拖累 {float(cost_pct):.2f}%"
        if _n > 6:
            _meta += f" · 共 {_n} 条（可滚）"
        self.reb_head.meta_label.setText(_meta)
        _recs = self._change_records(p, _ev)
        self.reb_list.set_records(_recs)
        self.lbl_reb.setVisible(not _recs)
        self.lbl_reb.setText("" if _recs else (
            "还没有调仓记录。<br>"
            "· <b>手动改成分</b>（改权重 / 加票 / 删票）—— 保存后立刻记一条；<br>"
            "· <b>再平衡</b>（回测口径）—— 只有「按月再平衡」且已过月末才产生；买入持有永远 0 次，这是对的。"))

    def _change_records(self, p: dict, events=()) -> list:
        """（★1.90 整形逻辑已搬到 `ui.widgets.portfolio_changes.build_records` —— 这里只转调）"""
        return build_records(p.get("changes") or [], events, self.name_of)

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
        # ★1.90：整组导入也算一次"成分变更"（第一条记录 = 从组里搬进来的这批票）
        _d0 = diff_members([], 0.0, members, 0.0)
        append_change(pf, {"at": _time.strftime("%m-%d %H:%M"), "kind": "import",
                           "added": _d0["added"], "removed": [], "moved": [],
                           "cash_before": 0.0, "cash_after": 0.0})
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
        dlg = PortfolioEditDialog(p, self, name_lookup=self.name_of, cap_provider=self.caps_of)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dlg.result_portfolio()
        # ★1.90：**把这次改动记账**（用户实测："随便改编辑成分，调仓记录里全是空的" —— 因为
        #   旧版只记"回测口径的月末再平衡"，手动改成分一条都不记）。
        _d = diff_members(p.get("members") or [], float(p.get("cash") or 0.0),
                          updated.get("members") or [], float(updated.get("cash") or 0.0))
        if _d.get("has_change"):
            append_change(updated, {
                "at": _time.strftime("%m-%d %H:%M"),
                "kind": "edit",
                "weight_mode": str(updated.get("weight_mode") or ""),
                "added": _d["added"], "removed": _d["removed"], "moved": _d["moved"],
                "cash_before": _d["cash_before"], "cash_after": _d["cash_after"]})
        try:
            if not self._store.save(updated):
                QMessageBox.warning(self, "保存失败", "组合没能写入磁盘（详见日志）。")
                return
        except ValueError as exc:            # 权重合计不 100 ⇒ 人话拦下（对话框已校验，兜底）
            QMessageBox.warning(self, "权重不合法", str(exc))
            return
        self._current = str(updated.get("id") or self._current)
        self.refresh()

    def _on_publish_group(self) -> None:
        """把组合成分写进**自选股组**（同名），并把 `source_group` 指过去。

        【为什么需要】组合与自选股是两套模型：组合存的是**成分快照**（`members`），`source_group`
        只是溯源用的名字标签 —— 所以用户手建的组合在行情页**当然看不到**（不是接口坏了）。
        这个动作 = **单向落地**：组合 → 自选组（覆盖同名组里这几只的归属）。之后组再变，
        组合不会自动跟着变（见 `_render` 的来源组不一致提示）。
        """
        p = self._store.load_one(self._current) if self._current else None
        if not p or not (p.get("members") or []):
            QMessageBox.information(self, "没有成分", "先在「✏ 编辑成分」里加几只票。")
            return
        gname = str(p.get("name") or "组合")[:12]      # 自选组名上限 12 字
        wl = self._watchlist()
        try:
            if not wl.has_group(gname):
                if not wl.create_group(gname):
                    QMessageBox.warning(self, "建组失败", f"自选股组「{gname}」没能创建。")
                    return
            n = 0
            for m in p.get("members") or []:
                sym = str(m.get("symbol") or "")
                if not sym:
                    continue
                nm = self.name_of(sym, m.get("name"))
                if wl.contains(sym):
                    if wl.set_group(sym, gname):
                        n += 1
                elif wl.add(sym, nm, gname):
                    n += 1
        except Exception as exc:            # noqa: BLE001
            QMessageBox.warning(self, "写入失败", f"{type(exc).__name__}: {exc}")
            return
        p["source_group"] = gname
        _why = "详见日志。"
        try:
            _ok = self._store.save(p)
        except Exception as exc:            # noqa: BLE001
            _ok = False
            _why = f"{type(exc).__name__}: {exc}"
        if not _ok:
            QMessageBox.warning(self, "组合没保存成功",
                                "票已写进自选股组，但组合的「来源组」没能写入磁盘。\n" + _why)
            return
        self.refresh()
        QMessageBox.information(
            self, "已写入自选股组",
            f"已把 {n} 只写进行情页的「自选股 → 分组 → {gname}」，组合现在引用该组。\n"
            "切到「📈 市场行情」即可看到同一批票。")

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
                                f"确定删除「{p.get('name')}」？\n（只删组合本身，不动自选股组）") \
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
