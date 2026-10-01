# ui/widgets/sweep_regimes.py
"""
🧪 参数研究 —— **切块与区间**（★R3 拆件：时间轴卡 + 区间预设的组织 + 「⟳ 重新切块」）。

【为什么单独成件】`ui/views/param_sweep.py` 在 R3 之后到 **507 行**（§4 越线）：它同时管
"卡片布局 + 运行与红线闸门 + 结果展示 + 切块与区间"。R3 的主题恰恰是**切块与区间**
（时间轴重做 + Shift 只设样本外 + 本机重算），所以整块搬出来 —— 页面回到"装配 + 编排"，
本件专管区间侧的一切。

【形态】与结果侧同一个范式：**混入类** `SweepRegimesMixin`（宿主 = `ParamSweepView`）
+ 一个卡片构造函数 `build_timeline_card(page)`（页面 `__init__` 里 `rl.addWidget(...)`）。
公共面（`page._load_regimes` / `_payload_presets` / `_on_timeline_pick` / `_on_timeline_pick_oos`
/ `_rebuild_regimes` / `page.timeline` / `page.btn_recut`）**一字不变** ⇒ 既有断言与调用点不动。

【口径】切块算法与配对**全在** `core.index_regimes`（与离线脚本 `scripts/analyze_index_regimes.py`
同一份）；本件只做"喂序列 / 取 payload / 落缓存 / 回填控件 / 说人话"（§10-4：不许造数据、
不许第二套口径）。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QFrame, QPushButton, QVBoxLayout)

from core.index_regimes import (SHANGHAI_INDEX_SYMBOL, ZONE_INDEX, IntervalPreset,
                                ensure_payload, index_close_from_lake,
                                kind_entries, load_cache)
from ui.widgets.styles import FLAT_QSS
from ui.widgets.sweep_chart import RegimeTimeline, regime_legend_row
from ui.widgets.sweep_parts import panel_card, panel_head

__all__ = ["SweepRegimesMixin", "build_timeline_card"]


def build_timeline_card(page) -> QFrame:
    """造图① 的卡（上证切块全景 + 「⟳ 重新切块」+ 图例），并把 `timeline / btn_recut` 挂到 `page`。

    ⚠ 高度交给控件自己（`RegimeTimeline` 的最小高 = 价格线 + 色带 + 年份刻度所需）——
      页面别再 `setMinimumHeight(56)` 把它压回去（那样三层会挤在一起，"看不懂"就是这么来的）。
    """
    card = panel_card()
    head = panel_head("上证切块全景",
                      "上证收盘线 + 涨/跌/震荡段 · 点一段 = 设样本内、紧随段 = 样本外 · "
                      "Shift+点 = 只设样本外")
    page.btn_recut = QPushButton("⟳ 重新切块")
    page.btn_recut.setStyleSheet(FLAT_QSS)
    page.btn_recut.setCursor(Qt.CursorShape.PointingHandCursor)
    page.btn_recut.setToolTip("按本机上证指数日线重算切块与配对"
                              "（写 ~/.jian_data/index_regimes.json，与离线脚本同源）")
    page.btn_recut.clicked.connect(lambda: page._rebuild_regimes())
    head.layout().addWidget(page.btn_recut)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)
    lay.addWidget(head)
    page.timeline = RegimeTimeline()
    page.timeline.segment_picked.connect(page._on_timeline_pick)
    page.timeline.segment_oos_picked.connect(page._on_timeline_pick_oos)
    lay.addWidget(page.timeline)
    lay.addWidget(regime_legend_row())
    return card


class SweepRegimesMixin:
    """区间侧方法集（宿主 = `ui.views.param_sweep.ParamSweepView`）。"""

    # ================= 切块 / 预设的装载 =================
    def _load_regimes(self) -> None:
        payload = load_cache()
        presets = self._payload_presets(payload)
        # ★R2：口径条（单边上涨 / 单边下跌 / 震荡箱体 + 各自最近一对 + why）由 core 组织
        #   —— "下拉怎么分组"是数据语义，不许在 UI 里重写一份（§10：口径唯一真源）。
        self.form.set_regime_presets(presets, kind_entries(presets))
        # ★R3：时间轴要**价格线**（"看得懂"的第一要素）—— 取口与离线脚本共用
        self.timeline.set_payload(payload, index_close_from_lake(self._lake))

    @staticmethod
    def _payload_presets(payload: dict | None) -> list[IntervalPreset]:
        """缓存 payload → 预设对象列表（**原样**，不拼标签、不塞"自定义"）。

        ★R2：组织方式（口径 / 近 N 组 / 自定义）由 `core.index_regimes.kind_entries` +
        `windows_of` 负责，标签里的四日期由表单拼（"哪一段"是用户唯一要选的东西，
        §11.5-112 ③ 的教训：同一句文案几十条根本没法选）。本方法只做"payload → 对象"。
        """
        return [IntervalPreset(p["key"], p["label"], p["is_start"], p["is_end"],
                               p["oos_start"], p["oos_end"], bool(p.get("default")))
                for p in ((payload or {}).get("presets") or [])
                if isinstance(p, dict) and p.get("is_start") and p.get("key") != "fold"]

    # ================= 时间轴交互 =================
    def _on_timeline_pick(self, is_start: str, is_end: str, oos_start: str, oos_end: str) -> None:
        # ★R2："自定义"现在住在**口径**下拉里（窗口下拉只放真实窗口）⇒ 走表单的 select_custom
        self.form.select_custom()
        self.form.set_dates(is_start, is_end, oos_start, oos_end)
        self.form.set_interval_receipt(f"已从切块时间轴选取：{is_start}~{is_end} 调 → "
                                       f"{oos_start}~{oos_end} 验")

    def _on_timeline_pick_oos(self, oos_start: str, oos_end: str) -> None:
        """★R3 · Shift+点：**只把这段设为样本外**（样本内保持不动，设计稿 p2 的第二种点法）。"""
        iv = self.form.interval()
        self.form.select_custom()
        self.form.set_dates(iv.is_start, iv.is_end, oos_start, oos_end)
        self.form.set_interval_receipt(
            f"只把 {oos_start}~{oos_end} 设为「样本外」（样本内保持 {iv.is_start}~{iv.is_end}）")

    def _rebuild_regimes(self, path: str | None = None) -> str:
        """★R3 ·「⟳ 重新切块」：按本机上证日线重算切块 + 配对 + 落缓存 + 刷新（左栏 + 时间轴）。

        :param path: 缓存落点（**冒烟注入临时目录**用；None = 用户数据目录）
        :return: 一句话回执（同时写进数据回执 —— 用户能复述、断言能读）
        """
        s = index_close_from_lake(self._lake)
        if s is None or not len(s):
            msg = (f"数据湖里没有 {ZONE_INDEX}/{SHANGHAI_INDEX_SYMBOL}（上证指数日线）—— "
                   "先去 🗄 数据管理 预下载指数，再点「⟳ 重新切块」")
            self.form.set_data_receipt(msg)
            return msg
        payload, _hit = ensure_payload(s, path=path, force=True)
        presets = self._payload_presets(payload)
        self.form.set_regime_presets(presets, kind_entries(presets))
        self.timeline.set_payload(payload, s)
        msg = (f"切块已重算：{len(payload['segments'])} 段 · {len(payload['presets'])} 对预设"
               f"（数据到 {payload['data_end']}）")
        self.form.set_data_receipt(msg)
        return msg
