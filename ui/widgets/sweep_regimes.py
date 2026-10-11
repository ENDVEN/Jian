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
from PyQt6.QtWidgets import (QFrame, QLabel, QPushButton, QVBoxLayout)

from core.index_regimes import (SHANGHAI_INDEX_SYMBOL, ZONE_INDEX, IntervalPreset,
                                ensure_payload, index_close_from_lake,
                                kind_entries, load_cache)
from data.sync_service import friendly_fetch_message
from ui.widgets.styles import FLAT_QSS
from ui.widgets.sweep_chart import RegimeTimeline, regime_legend_row
from ui.widgets.sweep_parts import panel_card, panel_head
from ui.workers import SingleSyncWorker      # ★1.70：一键补指数走全站唯一的线程件

__all__ = ["SweepRegimesMixin", "build_timeline_card", "FOLD_KIND"]

# ★1.70 / §11.5-129：**"没有切块"时的兜底口径** —— 用户实测（2026-10-11）：
#   本机从没下过上证指数 ⇒ 切块算不出来 ⇒ **窗口下拉是空的**，四个日期格还是控件初值
#   ⇒ 用户原话"样本区间根本选不了"（整页被锁死）。本兜底**不需要任何指数数据**，
#   只用"所选标的本机数据的日期范围"对折：前半段调参、后半段验证 —— 离线也能开跑。
FOLD_KIND = "fold"
_FOLD_ENTRY = {
    "kind": FOLD_KIND,
    "label": "按本机数据对折（无需切块）",
    "why": "把所选标的本机数据的日期范围按中点拆两半：前半段调参、后半段验证。"
           "不走切块缓存 ⇒ 没有上证指数数据时也能开始。",
}


def build_timeline_card(page) -> QFrame:
    """造图① 的卡（上证切块全景 + 「⟳ 重新切块」+ 图例），并把 `timeline / btn_recut` 挂到 `page`。

    ⚠ 高度交给控件自己（`RegimeTimeline` 的最小高 = 价格线 + 色带 + 年份刻度所需）——
      页面别再 `setMinimumHeight(56)` 把它压回去（那样三层会挤在一起，"看不懂"就是这么来的）。
    ★1.70 / §11.5-129：新增两件**就地**的东西 —— `lbl_recut`（回执写在这里，按钮旁边）
      与 `btn_fetch_index`（缺上证指数时出现，一键补数据）。旧版回执只写左栏「数据回执」，
      用户点了按钮、**按钮旁边毫无变化** ⇒ 判定"这按钮没用"（§11.5-125 同族）。
    """
    card = panel_card()
    head = panel_head("上证切块全景",
                      "上证收盘线 + 涨/跌/震荡段 · 点一段 = 设样本内、紧随段 = 样本外 · "
                      "Shift+点 = 只设样本外")
    page.btn_fetch_index = QPushButton("⬇ 下载上证指数")
    page.btn_fetch_index.setStyleSheet(FLAT_QSS)
    page.btn_fetch_index.setCursor(Qt.CursorShape.PointingHandCursor)
    page.btn_fetch_index.setToolTip(f"一键下载上证指数日线（{SHANGHAI_INDEX_SYMBOL}）—— "
                                    "补完**自动重算切块**，不用再点一次")
    page.btn_fetch_index.clicked.connect(lambda: page._fetch_index_then_recut())
    page.btn_fetch_index.setVisible(False)          # 只在"缺数据"时露面（有数据就别添乱）
    head.layout().addWidget(page.btn_fetch_index)
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
    # 就地回执（整行 + 可换行）：放在**卡片内、按钮正下方**，点了就能看见结果/出路。
    page.lbl_recut = QLabel("")
    page.lbl_recut.setWordWrap(True)
    page.lbl_recut.setStyleSheet("font-size: 11.5px; color: #8A94A6; padding: 0 12px;")
    page.lbl_recut.setVisible(False)
    lay.addWidget(page.lbl_recut)
    page.timeline = RegimeTimeline()
    page.timeline.segment_picked.connect(page._on_timeline_pick)
    page.timeline.segment_oos_picked.connect(page._on_timeline_pick_oos)
    lay.addWidget(page.timeline)
    lay.addWidget(regime_legend_row())
    return card


class SweepRegimesMixin:
    """区间侧方法集（宿主 = `ui.views.param_sweep.ParamSweepView`）。"""

    # ================= 切块 / 预设的装载 =================
    @staticmethod
    def _entries_for(presets) -> list[dict]:
        """口径下拉条目 = 三类 regime（`core.kind_entries` 组织）+ **兜底「按本机数据对折」**。

        ★1.70 / §11.5-129：为什么"对折"要**常驻**而不是只在空缓存时加 —— 三种 regime 口径都
        依赖切块缓存，而缓存必须有上证指数日线才能算；新机器/没下过指数的机器上它是空的
        ⇒ 窗口下拉空、四格还是控件初值 ⇒ 用户"样本区间根本选不了"（整页锁死）。
        "对折"只用**所选标的本机数据的日期范围**，离线可用 ⇒ 给用户一条**总能走的路**。
        """
        return kind_entries(presets) + [dict(_FOLD_ENTRY)]

    def _load_regimes(self) -> None:
        payload = load_cache()
        presets = self._payload_presets(payload)
        # ★R2：口径条（单边上涨 / 单边下跌 / 震荡箱体 + 各自最近一对 + why）由 core 组织
        #   —— "下拉怎么分组"是数据语义，不许在 UI 里重写一份（§10：口径唯一真源）。
        self.form.set_regime_presets(presets, self._entries_for(presets))
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

        ★1.70 / §11.5-129：回执**就地**写进切块卡（`lbl_recut`，按钮正下方），缺数据时同时
          露出「⬇ 下载上证指数」—— 旧版只写左栏「数据回执」，用户点了按钮旁边毫无变化，
          判定"这按钮没用"（用户实测原话："我点击这个重新切块没用啊"）。

        :param path: 缓存落点（**冒烟注入临时目录**用；None = 用户数据目录）
        :return: 一句话回执（同时写进卡内与数据回执 —— 用户能复述、断言能读）
        """
        s = index_close_from_lake(self._lake)
        if s is None or not len(s):
            msg = (f"数据湖里没有上证指数日线（{ZONE_INDEX}/{SHANGHAI_INDEX_SYMBOL}）—— "
                   "点右边「⬇ 下载上证指数」一键补上（补完会自动重切）；"
                   "或把口径改成「按本机数据对折」，不需要指数数据也能开始。")
            return self._recut_receipt(msg, need_index=True)
        payload, _hit = ensure_payload(s, path=path, force=True)
        presets = self._payload_presets(payload)
        self.form.set_regime_presets(presets, self._entries_for(presets))
        self.timeline.set_payload(payload, s)
        msg = (f"切块已重算：{len(payload['segments'])} 段 · {len(payload['presets'])} 对预设"
               f"（数据到 {payload['data_end']}）")
        return self._recut_receipt(msg, need_index=False)

    # ---------- 卡内回执 + 一键补指数（★1.70 / §11.5-129）----------
    def _recut_receipt(self, msg: str, *, need_index: bool) -> str:
        """回执写在**按钮旁边**（卡内整行），并决定「⬇ 下载上证指数」露不露面。返回 msg。"""
        lbl = getattr(self, "lbl_recut", None)
        if lbl is not None:
            lbl.setText(msg)
            lbl.setToolTip(msg)
            lbl.setVisible(True)
            lbl.setStyleSheet("font-size: 11.5px; padding: 0 12px; color: "
                              + ("#C62828" if need_index else "#2E7D32"))
        self.form.set_data_receipt(msg)              # 左栏那份照旧（别处会看它）
        btn = getattr(self, "btn_fetch_index", None)
        if btn is not None:
            btn.setVisible(bool(need_index))
        return msg

    def _fetch_index_then_recut(self) -> None:
        """★1.70：一键补上证指数日线 ⇒ **补完自动重切**（把"缺数据"从死路变成一步可解）。"""
        worker = getattr(self, "_index_worker", None)
        if worker is not None and worker.isRunning():
            return                                     # 防重复点击（同一只不并发拉）
        self._recut_receipt(f"正在下载上证指数日线（{SHANGHAI_INDEX_SYMBOL}）…",
                            need_index=True)
        btn = getattr(self, "btn_fetch_index", None)
        if btn is not None:
            btn.setEnabled(False)
        self._index_worker = SingleSyncWorker(SHANGHAI_INDEX_SYMBOL, zone=ZONE_INDEX,
                                              parent=self)
        self._index_worker.finished.connect(self._on_index_fetched)
        self._index_worker.start()

    def _on_index_fetched(self, result: dict) -> None:
        """下载回包：成功 ⇒ **自动重切**；失败 ⇒ 说人话 + 保留下载按钮（可重试）。"""
        btn = getattr(self, "btn_fetch_index", None)
        if btn is not None:
            btn.setEnabled(True)
        if not (result or {}).get("ok"):
            reason = friendly_fetch_message(SHANGHAI_INDEX_SYMBOL, result or {})
            self._recut_receipt(f"上证指数下载没成功：{reason} —— 可再点一次重试，"
                                "或到 🗄 数据管理 用「指数预设」批量补", need_index=True)
            return
        self._rebuild_regimes()                        # 补完就地重切（用户不用再点一次）
