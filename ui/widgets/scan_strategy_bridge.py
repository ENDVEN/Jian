# ui/widgets/scan_strategy_bridge.py
"""M2/M3「筛选方案」载入 / 存为 / 管理 桥接（§7-B12 P3）。

【与 M1 策略库同构、但独立】M1 用 `StrategyBridge`+`strategy_store`；M2/M3 用本类
  + `scan_strategy_store`（不同数据形状，各存各的，边界干净）。

【约定（与 backtest_strategy / desk_* 一致）】状态留在页面，本类只承载行为：
  页面须提供 `current_config() -> dict`、`apply_config(cfg) -> None`、`lbl_receipt`。
  M2 与 M3 共享 `get_scan_strategy_store()` 单例 —— 一份方案池，一页存、另一页可载入。
"""
from __future__ import annotations

from PyQt6.QtWidgets import QInputDialog, QMessageBox

from data.scan_strategy_store import get_scan_strategy_store
# ★1.61 / §7-B16：方案保存时把函数**收编进资产库**（引用挂 config.asset_id）；
#   载入只认内联 formula（红线②：绝不静默换函数），资产有更新版 ⇒ 回执提示。
from data.formula_store import SOURCE_SCAN, get_formula_store
from data.hub_assets import stale_snapshot, upsert_asset
from ui.dialogs.list_manager import ListManagerDialog
from ui.widgets.hub_latest import LatestFunctionPrompt   # ★1.61 §7-B16 H4 公共件（M1 与 M2/M3 共用）

__all__ = ['ScanStrategyBridge']


class ScanStrategyBridge:
    """筛选方案库桥接（页面持有状态，本类提供 存/载/管 三件事）。"""

    def __init__(self, page):
        self.page = page
        self.store = get_scan_strategy_store()
        # ★1.61 / §7-B16 H4：「总库有更新版」的提示与显式更新 —— **公共件**
        #   （与 M1 逐行相同的逻辑只此一份，见 `ui/widgets/hub_latest.py`）。
        self._latest = LatestFunctionPrompt(
            page, subject='本方案', noun='筛选条件',
            kept='粗筛阈值 / 统计范围 / 复权口径',
            fill=self._fill_latest, receipt='lbl_receipt',
            receipt_tail='点「▶ 开始扫描」按它取截面。')

    # ==========================================
    # ★1.61 / §7-B16 H4：「总库有更新版」—— 提示可见 + 更新要显式动作
    #   实现全在公共件 `ui/widgets/hub_latest.LatestFunctionPrompt`（M2 与 M3 共用同一份
    #   方案池 ⇒ 两页提示口径必然同源）；这里只留三个同名薄壳，页面与冒烟照旧调它们。
    # ==========================================
    def _fill_latest(self, texts, params_text: str) -> int:
        """把最新版回填进筛选条件（**只碰条件本身**，阈值 / 范围 / 复权一字不动）。"""
        p = self.page
        p._formula_pane.txt_formula.setPlainText('\n'.join(texts))
        p._formula_pane.txt_params.setText(params_text)
        return len(texts)

    def stale_tip(self, stale) -> str:
        """统一的一句人话（不点按钮 = 保持原样，这是默认动作，必须在文案里说出来）。"""
        return self._latest.tip(stale)

    def prompt_stale(self, stale) -> bool:
        """记下待更新的资产并显隐摘要条上的「⤒ 用最新版」（None = 收起）。

        ⚠ **只显隐按钮，绝不改筛选条件** —— 红线②：已存方案的函数要么保持原样（默认），
          要么由用户点一下才换成新版。
        """
        return self._latest.prompt(stale)

    def apply_latest_function(self) -> int:
        """「⤒ 用最新版」：**只**替换筛选条件，其余配置一字不动（红线②）。

        这是**显式动作**（用户点了才发生），所以允许读资产内容；载入路径（`load`）
        依旧只读内联 `formula`。
        """
        return self._latest.apply()

    def save(self) -> None:
        """把当前配置存成命名方案（同名覆盖）。空条件不给存。"""
        p = self.page
        cfg = p.current_config()
        if not str(cfg.get('formula') or '').strip():
            QMessageBox.information(p, '提示', '筛选条件是空的 —— 先写一段条件再「存为方案」。')
            return
        name, ok = QInputDialog.getText(p, '存为筛选方案', '方案名称:')
        name = (name or '').strip()
        if not ok or not name:
            return
        payload = dict(cfg)
        payload['name'] = name
        # ★1.61 / §7-B16：函数收编进资产库（内容命中即复用；同名不同内容 ⇒ 后缀新建）
        #   并把引用挂进 config —— M2/M3 的函数字段（formula）同时保留为内联快照。
        asset = upsert_asset(get_formula_store(), name, [str(cfg.get('formula') or '')],
                             str(cfg.get('params') or ''), SOURCE_SCAN)
        payload.setdefault('config', {})
        payload['config']['asset_id'] = asset['id']
        self.store.upsert(payload)
        # 刚把当前内容存成方案 ⇒ 快照与资产的关系已重新建立，「有更新版」提示随之作废。
        self.prompt_stale(None)
        p.lbl_receipt.setText(f'✅ 已存为筛选方案「{name}」，下次可一键载入。')

    def load(self) -> None:
        """「📚 载入」：选一个已存方案 → 交给 `load_plan`（与浮窗**同一段**还原逻辑）。"""
        p = self.page
        strategies = self.store.list_strategies()
        if not strategies:
            QMessageBox.information(p, '载入筛选方案', '还没有保存过方案 —— 先「💾 存为方案」。')
            return
        names = [str(s.get('name', '')) for s in strategies]
        name, ok = QInputDialog.getItem(p, '载入筛选方案', '选择方案：', names, 0, False)
        if not ok or not name:
            return
        target = next((s for s in strategies if str(s.get('name', '')) == name), None)
        if target:
            self.load_plan(str(target.get('id')))

    # ==========================================
    # ★1.61 / §7-B16：**函数总库浮窗的「📚 本页方案」区**用的三件事
    #   方案库仍在本文件；浮窗只是**另一个入口** —— 载入 / 保存 / 删除一律复用同一套实现。
    # ==========================================
    def plans(self) -> list[dict]:
        """全部筛选方案（浮窗列表用）。"""
        return self.store.list_strategies()

    @staticmethod
    def plan_label(plan: dict) -> str:
        """列表行的第二行文案（统计范围 + 粗筛项数 + 复权口径）。"""
        cfg = plan.get('config') or {}
        scope = {0: '我的自选', 1: '指数成分', 2: '全 A'}.get(cfg.get('scope'), '统计范围')
        thr = cfg.get('thresholds') or {}
        n_thr = sum(1 for v in thr.values() if v not in (None, 0, '', False, []))
        return f"{scope} · 粗筛 {n_thr} 项 · 前复权"

    def load_plan(self, plan_id: str) -> bool:
        """按 id 载入方案（浮窗用）—— 与「📚 载入」同一段还原 + 同一句回执。

        ⚠ 红线②：载入只认内联 `formula`（配置区含函数一并还原，是既有行为）；
          资产有更新版 ⇒ 一句可见提示 + 一个**显式动作**按钮（默认保留原样，绝不静默换函数）。
        ⚠ `prompt_stale` 必须排在 `apply_config` **之后**：apply_config 会写 formula 文本，
          提示面按"最后一次载入的结果"置位，顺序反了就会被自己的写入冲掉。
        """
        p = self.page
        target = next((s for s in self.store.list_strategies()
                       if str(s.get('id')) == str(plan_id)), None)
        if not target:
            return False
        p.apply_config(target.get('config') or {})
        cfg = target.get('config') or {}
        stale = stale_snapshot(str(cfg.get('asset_id') or ''),
                               [str(cfg.get('formula') or '')], str(cfg.get('params') or ''))
        self.prompt_stale(stale)
        p.lbl_receipt.setText(f'📚 已载入筛选方案「{target.get("name")}」—— '
                              f'点「▶ 开始扫描」按它取截面。{self.stale_tip(stale)}')
        return True

    def delete_plan(self, plan_id: str) -> bool:
        """按 id 删方案（浮窗用）—— 与「管理」走同一套库操作。

        ⚠ **必须二次确认**：H7 起浮窗把"本页方案"和函数资产并进**一个列表**，删除是列表里的
          一格按钮 —— 少了确认就是"手一抖方案没了"（`manage()` 里那套确认随旧入口一起退役了，
          这道闸门必须跟着搬到**唯一剩下的入口**上，§11.5-11：同类防护不许只改一处）。
        """
        plan = next((s for s in self.store.list_strategies()
                     if str(s.get('id')) == str(plan_id)), None)
        if plan is None:
            return False
        reply = QMessageBox.question(
            self.page, '删除筛选方案',
            f"确定删除筛选方案「{plan.get('name') or '未命名'}」吗？\n\n"
            "（只删这份方案存档；已收编的函数资产还在「ƒ 函数库」里）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return False
        return bool(self.store.delete(str(plan_id)))

    def manage(self) -> None:
        """管理（删除）已存方案；按名字定位、删磁盘档。"""
        p = self.page
        strategies = self.store.list_strategies()
        if not strategies:
            QMessageBox.information(p, '管理筛选方案', '还没有保存过方案。')
            return
        names = [str(s.get('name', '')) for s in strategies]

        def _delete(name):
            target = next((s for s in self.store.list_strategies()
                           if str(s.get('name', '')) == str(name)), None)
            return bool(target and self.store.delete(target.get('id')))

        ListManagerDialog('管理筛选方案', names, _delete, p).exec()
