# ui/widgets/sweep_snap_card.py
"""
🧪 参数研究 —— ⑨ **研究快照卡**（★R5b · 设计稿 p2 的 `#p2-hist`）。

【它干什么】把 `data.sweep_archive.SweepArchive` 的 `list / load / set_pinned / delete`
接上界面：一行一份快照（时间 · 区间 · 门槛 · 试验数 · IC/PBO + 状态标签），三个动作：
  · **回看**（只读回放：把该快照的**统计、结论条、KPI、候选表**填回界面，**绝不重跑、绝不改
    `_spec/_interval`** —— 红线①：不允许拿旧快照继续挑参数）；
  · **置顶**（`set_pinned`，★ 标记，排序里优先）；
  · **删除**（二次确认后 `delete`）。

【本版的两条诚实边界（不装懂）】
  ① **回看不重绘四张图**：快照只存了 `Top-N 逐日收益`（`daily_top`），不足以复原
     `metrics` 全量（散点/热力图/邻域/滚动 IC 都要全网格的年化与邻域）⇒ 回看时图区显示
     "回看模式不重绘图形（要看图请按原参数重跑）"，而不是画一张**看着像真的**的假图。
  ② **状态标签**：存档里**没有** stale/tampered 这两个字段（设计稿里提到、数据层没实现）⇒
     只显示**能算出来的**两件事：`★ 置顶` 与 `旧版本存档`（`app_version` 与本机不一致）。
     宁可少显示，也不假装有"篡改检测"。
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QMessageBox, QPushButton,
                             QVBoxLayout, QWidget)

from config import settings
from ui.widgets.styles import ACCORD_STATE_COLOR, SEC_HINT_QSS, SUMMARY_GHOST_QSS
from ui.widgets.sweep_parts import _hint, panel_card, panel_head

logger = logging.getLogger(__name__)

SNAP_SHOW_MAX = 20      # 列表最多显示几条（多了滚动看，不做分页）


class SweepSnapshotsMixin:
    """快照卡的行为（宿主 = `ui.views.param_sweep.ParamSweepView`）。"""

    # ---------------- 列表 ----------------
    def _refresh_snapshots(self) -> None:
        """重建快照行（`list()` = 索引条目，seq 新→旧）。"""
        box = getattr(self, "snap_rows", None)
        if box is None:
            return
        while box.count():
            item = box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        entries = []
        try:
            entries = self._archive.list() or []
        except Exception as e:  # noqa: BLE001 —— 存档坏了不拖垮页面
            logger.warning("快照索引读取失败：%s", e)
        self.lbl_snap_meta.setText(
            f"共 {len(entries)} 份（新→旧）" + (f"，只显示前 {SNAP_SHOW_MAX} 份"
                                            if len(entries) > SNAP_SHOW_MAX else ""))
        if not entries:
            box.addWidget(_hint("还没有快照 —— 跑完样本内 + 样本外后点「💾 存快照」"))
            return
        for e in entries[:SNAP_SHOW_MAX]:
            box.addWidget(self._snap_row(e))
        box.addStretch(1)

    def _snap_row(self, e: dict) -> QWidget:
        """一行：`时间 · 区间 · 门槛 · 试验数 · IC/PBO` + 状态标签 + 三个动作。"""
        rid = str(e.get("id") or "")
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        iv = (f"{e.get('is_start', '')}~{e.get('is_end', '')} → "
              f"{e.get('oos_start', '')}~{e.get('oos_end', '')}")
        ic = e.get("rank_ic")
        pbo = e.get("pbo")
        gate = e.get("min_trades")          # 老索引没有这一项 ⇒ 如实显示 "—"（不写 None）
        txt = (f"{str(e.get('created_at') or '')[:16].replace('T', ' ')} · {iv} · "
               f"门槛 {'—' if gate is None else gate} · 试验 {e.get('n_combos')} · "
               f"IC {'—' if ic is None else f'{float(ic):.2f}'} · "
               f"PBO {'—' if pbo is None else f'{float(pbo):.0%}'}")
        lab = QLabel(txt)
        lab.setStyleSheet(SEC_HINT_QSS)
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        if e.get("pinned"):
            lab.setText("★ " + lab.text())
            lab.setStyleSheet(SEC_HINT_QSS + f"color:{ACCORD_STATE_COLOR['ok']};font-weight:600;")
        lay.addWidget(lab, 1)
        if str(e.get("app_version") or "") not in ("", str(settings.APP_VERSION)):
            tag = QLabel("旧版本")
            tag.setStyleSheet(SEC_HINT_QSS + "color:#E65100;")
            tag.setToolTip(f"该快照存于 v{e.get('app_version')}，本机 v{settings.APP_VERSION}"
                           "（算法口径可能已变，回看只读、不做对比结论）")
            lay.addWidget(tag)
        for text, tip, slot in (("回看", "只读回放：把该快照的统计与候选表填回界面（不重跑）",
                                 self._on_snap_replay),
                                ("★", "置顶 / 取消置顶", self._on_snap_pin),
                                ("删除", "删除该快照（二次确认）", self._on_snap_delete)):
            btn = QPushButton(text)
            btn.setStyleSheet(SUMMARY_GHOST_QSS)
            btn.setToolTip(tip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, r=rid, s=slot: s(r))
            lay.addWidget(btn)
        return row

    # ---------------- 三个动作 ----------------
    def _on_snap_replay(self, rid: str) -> None:
        """**只读回放**（红线①）：填统计/结论条/KPI/候选表；**不重跑、不动 `_spec/_interval`**。"""
        snap = self._archive.load(rid)
        if not snap:
            self.form.set_receipt(f"快照 {rid} 读不出来（文件缺失或损坏）—— 诚实报告，不猜内容")
            return
        st = snap.get("stats") or {}
        iv = snap.get("interval") or {}
        grid = snap.get("grid") or {}
        ic, pbo = st.get("rank_ic"), st.get("pbo")
        n_done, n_failed = int(st.get("n_done") or 0), int(st.get("n_failed") or 0)
        gate = (snap.get("gate") or {}).get("min_trades")
        self._replay_rid = rid                      # 让"再跑一次"能自己退出回放态
        self.lbl_verdict.setStyleSheet(SEC_HINT_QSS)
        self.lbl_verdict.setText(
            f"<b>只读回放</b>（快照 {rid} · v{snap.get('app_version')}）：试验数 "
            f"<b>{grid.get('n_combos')}</b>（完成 {n_done} / 失败 {n_failed}）· "
            f"Rank IC <b>{'—' if ic is None else f'{float(ic):.2f}'}</b> · PBO "
            f"<b>{'—' if pbo is None else f'{float(pbo):.0%}'}</b><br>"
            f"区间 <b>{iv.get('is_start', '')} ~ {iv.get('is_end', '')}</b>（样本内）→ "
            f"<b>{iv.get('oos_start', '')} ~ {iv.get('oos_end', '')}</b>（样本外）· "
            f"门槛 <b>{gate}</b> 笔 · 标的 <b>{snap.get('symbol')}</b> · "
            f"策略 <b>{(snap.get('strategy') or {}).get('name')}</b><br>"
            "⚠ 这是**历史快照的只读回放**：图区不重绘、也不参与任何挑参数（红线①）。"
            "要看图或继续研究 ⇒ 按上面的参数重跑一次。")
        kpi = getattr(self, "kpi", None) or {}
        if kpi:
            from ui.widgets.kpi_card import set_kpi    # 就地 import：与页面同源
            set_kpi(kpi["n"], "试验数", str(grid.get("n_combos")), f"完成 {n_done}")
            set_kpi(kpi["is"], "样本内", f"{str(iv.get('is_start'))[:7]} ~ "
                                         f"{str(iv.get('is_end'))[:7]}", "快照记录")
            set_kpi(kpi["oos"], "样本外", f"{str(iv.get('oos_start'))[:7]} ~ "
                                          f"{str(iv.get('oos_end'))[:7]}", "只验一次")
            set_kpi(kpi["ic"], "Rank IC", "—" if ic is None else f"{float(ic):.2f}",
                    "快照记录")
            set_kpi(kpi["pbo"], "PBO", "—" if pbo is None else f"{float(pbo):.0%}",
                    "快照记录")
        # ★R5b：优先用**展示行**（含未过门槛的，能复原当时那张表）；老快照没有它 ⇒ 回落 candidates
        self._fill_table(st.get("rows") or st.get("candidates") or [])
        if getattr(self, "_chart_empty_backup", None) is None:   # 原空态文案要留着（重跑恢复）
            self._chart_empty_backup = self.chart_empty.text()
        self.chart_empty.setText("回看模式 —— 图区不重绘（快照里只存了 Top-N 逐日收益，"
                                 "不足以复原四张图；要看图请按原参数重跑）")
        self.chart_empty.show()
        self.scatter.hide()
        self.heatmap.hide()
        self.btn_save.setEnabled(False)
        self.form.set_receipt(f"已回看快照 {rid}（只读）：统计与候选表来自存档，**没有重跑**；"
                              "再点「▶ 跑样本内」会退出回看态")

    def _on_snap_pin(self, rid: str) -> None:
        entries = {str(e.get("id")): e for e in (self._archive.list() or [])}
        cur = bool((entries.get(rid) or {}).get("pinned"))
        ok = self._archive.set_pinned(rid, not cur)
        self.form.set_receipt(("已置顶 " if not cur else "已取消置顶 ") + rid if ok
                              else f"置顶失败：{rid} 读不出来")
        self._refresh_snapshots()

    def _on_snap_delete(self, rid: str) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("删除快照")
        box.setText(f"删除快照 {rid}？")
        box.setInformativeText("删了就找不回来（它是你当时的区间/门槛/统计记录）。")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            self.form.set_receipt(f"已取消删除 {rid}")
            return
        ok = self._archive.delete(rid)
        self.form.set_receipt(f"已删除快照 {rid}" if ok else f"删除失败（文件不在）：{rid}")
        self._refresh_snapshots()


def build_snapshot_card(page) -> QWidget:
    """⑨ 研究快照卡（★R5b）：头条 + 一行状态 + 列表容器（行为在 `SweepSnapshotsMixin`）。"""
    card = panel_card()
    head = panel_head("研究快照", "每存一次 = 一份可复现的记录（回看只读，不重跑）")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)
    lay.addWidget(head)
    body = QWidget()
    lay.addWidget(body, 1)
    bl = QVBoxLayout(body)
    bl.setContentsMargins(8, 6, 8, 8)
    bl.setSpacing(4)
    page.lbl_snap_meta = QLabel("")
    page.lbl_snap_meta.setStyleSheet(SEC_HINT_QSS)
    bl.addWidget(page.lbl_snap_meta)
    box = QVBoxLayout()
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(3)
    bl.addLayout(box)
    page.snap_rows = box
    page.snap_card = card
    return card
