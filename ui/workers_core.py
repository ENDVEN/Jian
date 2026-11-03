# ui/workers_core.py
"""任务竞态守卫（★2.04 / P2 拆件）。"""
from __future__ import annotations

__all__ = ["JobGuard"]


class JobGuard:
    """竞态守卫（§9-O5）：**只接受最新一次任务的结果**，迟到的旧回包一律丢弃。

    页面侧两行就够：
        self._guard = JobGuard()
        job = self._guard.next()                     # 发起任务时取号
        worker.finished.connect(self._on_done)
    def _on_done(self, job_id, outcome):
        if not self._guard.accept(job_id):           # 迟到 ⇒ 直接丢
            return

    【为什么做成公共件】"发起新任务 ⇒ 旧回包作废"在本项目至少三处需要（数据管理页的分区扫描、
    批量下载弹窗的成分股解析、扫描页的多个动作）。各写一遍 `_token` 计数器，迟早有一处忘了比
    ⇒ **旧结果覆盖新结果**，而且界面看起来完全正常（§11.5-11「同类防护只改一处」的正解）。
    ✅ v1.38/§7-E2：`ui/dialogs/bulk_download.py` 原先那套手写判据（`_cons_token`）已改用本类 ——
      至此"发起新任务 ⇒ 旧回包作废"在全仓**只有一处实现**（§11.5-11「同类防护做全套」还清这笔挂账）。
    """

    def __init__(self):
        self._latest = 0

    def next(self) -> int:
        """发起一次新任务：作废此前所有任务的回包，返回本次的 `job_id`"""
        self._latest += 1
        return self._latest

    def accept(self, job_id) -> bool:
        """这个回包是不是**当前最新**那次任务的？（类型容错：`"3"` 与 `3` 同等看待）"""
        try:
            return int(job_id) == self._latest
        except (TypeError, ValueError):
            return False

    @property
    def latest(self) -> int:
        return self._latest
