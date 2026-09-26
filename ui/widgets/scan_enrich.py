# ui/widgets/scan_enrich.py
"""扫描后**分批补全**行业/估值（★v6.74 · §7-B13）—— 用户 2026-09-27 拍板。

【为什么要有它】扫描的职责是"**立刻出命中结果**"；行业/估值是**辅助列**（要东财请求）。
  旧做法：扫描后打**一批**，失败就写在回执里放弃 ⇒ 用户看到"列一直是空的"，以为没抓到；
  连点还会把额度打光（"越点越死"）。用户提出的正确形态就是本模块：
  **先出扫描结果，然后让需要东财的那两列"隔一段时间自动补全到表里"**。

【节奏】每轮 ≤ `per_round` 个请求（1 请求 = 100 只，池子去重后按序切）、轮内由
  `data/em_market` 的**全局最小间隔**（≥0.8s）兜住、轮间 `gap` 秒（默认 30）⇒
  沪深300（3 请求）一轮就完；全 A（56 请求）约 19 轮 ≈ 10 分钟，全程**后台**、界面零等待。

【终态与防死循环】标记的是"**问过**"（`_asked`）而不是"拿到"——
  否则某只票没有行业字段时会被无限重问。⇒ 停止条件白盒可测：
  ① `next_chunk()` 为空（问完/池子空）；② **连续两轮一个都没拿到**（被限流/额度用完，早停省额度）；
  ③ 轮次上限；④ `cancel()`（关窗）。

【纪律】① `ui/` 不直连行情源：只调 `data/sync_service.fetch_enrich_map`（§9-H）；
  ② 线程只**取数**，合并与刷新在主线程做（Qt 信号）；③ 一轮失败**不重试**（交给下一轮）。
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from data.sync_service import fetch_enrich_map

logger = logging.getLogger(__name__)

BATCH_SIZE = 100                 # 一个请求覆盖多少只（与 `em_market.QUOTE_BATCH_SIZE` 同量级）
MAX_ROUNDS = 200                 # 防御性上限（正常池子几十轮就完）
FIRST_ROUND_DELAY_SECONDS = 2.5  # 首轮也**延迟**：别和"下载尾巴 / 扫描收尾"挤在同一秒
EMPTY_ROUNDS_TO_STOP = 2         # 连续两轮一个都没拿到 ⇒ 停了（被限流/额度用完，别再烧）


class EnrichRoundWorker(QThread):
    """跑**一轮**取数（轮内 N 个请求由门面按 100 只切块、串行 + 全局节流）。"""

    finished = pyqtSignal(object)     # `{symbol: {...}}`；失败 ⇒ `{}`

    def __init__(self, symbols, parent=None):
        super().__init__(parent)
        self._symbols = list(symbols or [])
        self._cancel = False

    def cancel(self):
        """关窗/取消（在**块与块之间**生效，最多多等一个请求）。"""
        self._cancel = True

    def run(self):
        try:
            data = {} if self._cancel else (fetch_enrich_map(self._symbols) or {})
        except Exception as e:                                    # noqa: BLE001 —— 一轮失败不致命
            logger.warning(f"补全一轮失败（{len(self._symbols)} 只）: {type(e).__name__}: {e}")
            data = {}
        self.finished.emit(data)


class EnrichScheduler(QObject):
    """扫描后按轮补全的**唯一调度器**（页面只接线：起 / 停 / 收包刷新）。"""

    progress = pyqtSignal(int, int, int)   # (已问, 总数, 距下一轮秒数)
    rows = pyqtSignal(object)              # 本轮拿到的新数据 `{symbol: {...}}`
    finished = pyqtSignal(str)             # 结束原因（人话，直接进回执/状态行）

    def __init__(self, symbols, per_round: int = 3, gap: int = 30, parent=None):
        super().__init__(parent)
        self._symbols = list(dict.fromkeys(str(s).strip() for s in (symbols or [])
                                           if str(s).strip()))
        self._per_round = max(1, int(per_round))
        self._gap = max(1, int(gap))
        self._asked = set()
        self._covered = set()
        self._empty_rounds = 0
        self._rounds = 0
        self._worker = None
        self._stopped = False
        self._active = False

    # ==========================================
    # 纯逻辑（**离网可测**：不碰 Qt 定时器、不发请求）
    # ==========================================
    @property
    def total(self) -> int:
        return len(self._symbols)

    @property
    def asked(self) -> int:
        return len(self._asked)

    @property
    def covered(self) -> int:
        return len(self._covered)

    def next_chunk(self) -> list:
        """本轮要问的标的（≤ `per_round × 100` 只；**只问没问过的**）。"""
        rest = [s for s in self._symbols if s not in self._asked]
        return rest[: self._per_round * BATCH_SIZE]

    def should_stop(self) -> str:
        """要停就先说清楚**为什么**（空串 = 继续）。"""
        if not self._symbols:
            return '池子为空，没有要补全的标的'
        if not self.next_chunk():
            return f'已补齐 {self.covered}/{self.total}'
        if self._empty_rounds >= EMPTY_ROUNDS_TO_STOP:
            return (f'连续 {EMPTY_ROUNDS_TO_STOP} 轮没拿到数据（东财限流或今日额度用尽）—— '
                    f'已问 {self.asked}/{self.total}，稍后再点一次扫描会自动接着补')
        if self._rounds >= MAX_ROUNDS:
            return f'达到轮次上限（{MAX_ROUNDS} 轮），已问 {self.asked}/{self.total}'
        return ''

    def progress_text(self, next_in: int = 0) -> str:
        """状态行文案（页面直接用，别自己拼）。"""
        tail = f' · 下一轮 {int(next_in)} 秒后' if next_in > 0 else ''
        if self.covered < self.asked:
            return (f'行业/估值补全：已问 {self.asked}/{self.total}'
                    f'（其中 {self.covered} 只有行业字段）{tail}')
        return f'行业/估值补全：{self.asked}/{self.total}{tail}'

    # ==========================================
    # 主流程
    # ==========================================
    def start(self) -> None:
        reason = self.should_stop()
        if reason:
            self.finished.emit(reason)
            return
        self._active = True
        self.progress.emit(self.asked, self.total, int(FIRST_ROUND_DELAY_SECONDS))
        QTimer.singleShot(int(FIRST_ROUND_DELAY_SECONDS * 1000), self._run_round)

    def cancel(self) -> None:
        self._stopped = True
        self._active = False
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
        logger.info('补全调度器已取消（关窗/手动）')

    def isRunning(self) -> bool:                # noqa: N802 —— 与 QThread 同名，调用点统一
        """是否**还在排轮 / 取数**（新扫描要先停上一轮；关窗也要问它）。"""
        return bool(self._active)

    def _run_round(self) -> None:
        if self._stopped:
            return
        reason = self.should_stop()
        if reason:
            self._active = False
            self.finished.emit(reason)
            return
        chunk = self.next_chunk()
        self._asked.update(chunk)                 # ★先标记"问过"⇒ 没有行业字段的票不会被反复问
        self._rounds += 1
        self._worker = EnrichRoundWorker(chunk, parent=self)
        self._worker.finished.connect(self._on_round_done)
        self._worker.start()

    def _on_round_done(self, data) -> None:
        if self._stopped:
            return
        got = data if isinstance(data, dict) else {}
        if got:
            self._empty_rounds = 0
            for sym, rec in got.items():
                if str((rec or {}).get('industry') or '').strip():
                    self._covered.add(sym)
            self.rows.emit(got)
        else:
            self._empty_rounds += 1
        reason = self.should_stop()
        if reason:
            self._active = False
            self.progress.emit(self.asked, self.total, 0)
            self.finished.emit(reason)
            return
        self.progress.emit(self.asked, self.total, self._gap)
        QTimer.singleShot(self._gap * 1000, self._run_round)      # 轮间**长休**
