# ui/workers_imports.py
"""期货交割单解析 worker（★2.04 / P2 拆件）。"""
from __future__ import annotations

import logging

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)

__all__ = ["FuturesImportWorker"]


class FuturesImportWorker(QThread):
    """
    后台解析期货交割单。

    【职责边界】**只解析、不落库**：`engine.parse_cfmmc()` 是耗时步骤，落库
    （`engine.commit_cfmmc()`）由 UI 主线程收结果后执行 —— 避免子线程**写** SQLite
    与主线程读数据争抢同一份内存状态。

    ⚠ 诚实记一笔（§9-T4-② 的历史挂账）：解析内部**会读** SQLite
    （`parse_cfmmc` → `db.load_open_legs()` 取历史未平仓腿，好让分月导入无缝衔接）。
    所以准确说法是"**子线程只读、不写库**"，而不是旧注释里的"子线程完全不碰 SQLite"。
    """

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, engine, file_paths, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.file_paths = file_paths

    def run(self):
        try:
            self.finished.emit(self.engine.parse_cfmmc(self.file_paths))
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))
