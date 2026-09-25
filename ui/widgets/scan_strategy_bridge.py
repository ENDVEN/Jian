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
from ui.dialogs.list_manager import ListManagerDialog

__all__ = ['ScanStrategyBridge']


class ScanStrategyBridge:
    """筛选方案库桥接（页面持有状态，本类提供 存/载/管 三件事）。"""

    def __init__(self, page):
        self.page = page
        self.store = get_scan_strategy_store()

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
        self.store.upsert(payload)
        p.lbl_receipt.setText(f'✅ 已存为筛选方案「{name}」，下次可一键载入。')

    def load(self) -> None:
        """选一个已存方案 → 整体还原进页面配置。"""
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
        if not target:
            return
        p.apply_config(target.get('config') or {})
        p.lbl_receipt.setText(f'📚 已载入筛选方案「{name}」—— 点「▶ 开始扫描」按它取截面。')

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
