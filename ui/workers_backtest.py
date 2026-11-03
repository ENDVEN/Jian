# ui/workers_backtest.py
"""回测 / 参数扫描 / 组合池化类 QThread（★2.04 / P2 拆件）。"""
from __future__ import annotations

import logging

from PyQt6.QtCore import QThread, pyqtSignal

from core.backtest import BacktestEngine
from core.param_sweep import run_sweep
from core.sweep_plan import GridPlan, StudyInterval

logger = logging.getLogger(__name__)

__all__ = ["BacktestRunWorker", "ParamSweepWorker", "PoolSweepWorker"]


class BacktestRunWorker(QThread):
    """回测计算（市场回测页）。

    异常一律在线程内吞掉并记日志，用 `None` 回包让 UI 给出统一的失败提示 ——
    绝不让异常穿透 QThread 造成静默失败或崩溃。
    """

    finished_signal = pyqtSignal(object)   # BacktestResult | None

    def __init__(self, df, symbol: str, buy_expr: str, sell_expr: str,
                 start_date: str, end_date: str, risk: dict = None,
                 fill_mode: str = None, trigger_tick=None, parent=None):
        super().__init__(parent)
        self.df = df
        self.symbol = symbol
        self.buy_expr = buy_expr
        self.sell_expr = sell_expr
        self.start_date = start_date
        self.end_date = end_date
        self.risk = risk or {}
        # v6.17 成交时点模型（默认 None -> 引擎侧归一回 next_open / 1 跳）
        self.fill_mode = fill_mode
        self.trigger_tick = trigger_tick

    def run(self):
        result = None
        try:
            result = BacktestEngine().run(
                self.df, self.buy_expr, self.sell_expr, symbol=self.symbol,
                start_date=self.start_date, end_date=self.end_date, risk=self.risk,
                fill_mode=self.fill_mode, trigger_tick=self.trigger_tick)
        except Exception as e:  # noqa: BLE001 —— 回测异常绝不穿透线程
            logger.error(f"市场回测-计算异常 [{self.symbol}]: {e}")
        self.finished_signal.emit(result)


class ParamSweepWorker(QThread):
    """§7-B15 参数扫描（SW-3）—— 只做调度；全部口径在 `core/param_sweep`。

    信号（照 CrossSectionWorker 范式）：
        progress(done, total, note)   # 组级进度；note = 当前组合键（或阶段说明）
        finished(job_id, outcome)     # `SweepOutcome`；**取消时也回包** ——
                                      # 已完成的组保留可续（§8-8，与下载队列同款，
                                      # ⚠ 与 CrossSectionWorker 取消回 None 的语义**故意不同**）
        failed(job_id, reason)        # 一句话原因（异常绝不穿透线程）

    · **竞态守卫（§9-O5）**：`job_id` 原样回包，页面用 `JobGuard.accept()` 判定；
    · **红线①「样本外只跑一次」的闸门不在本线程** —— 它在页面流程 + `sweep_archive`
      （SW-4/SW-5）：线程不该也不需要知道研究历史；
    · `cancel()` 在**组边界**生效（run_sweep 的 should_stop 钩子），不打断组内回测。
    """

    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(int, object)
    failed = pyqtSignal(int, str)

    def __init__(self, job_id: int, df, spec, grid: GridPlan, interval: StudyInterval,
                 stage: str = "both", done_keys=(), parent=None,
                 commission_rate: float = None):
        super().__init__(parent)
        self._job_id = int(job_id)
        self._df = df
        self._spec = spec
        self._grid = grid
        self._interval = interval
        self._stage = str(stage or "both")
        self._done_keys = frozenset(done_keys)
        # ★1.79 / §7-B15 第二轮①：**佣金档透传**。`run_sweep` 本来就吃这个参数
        #   （core/param_sweep.py:144 → 两段 engine.run），而本线程此前从不转出来
        #   ⇒ 全仓"成本敏感性"一直是零实现（审计 §7 可疑点①：宣称全参透传、实际恒为默认万3）。
        #   `None` = 不传 ⇒ 走 `run_sweep` 自己的默认（老行为逐字不变）。
        self._commission_rate = commission_rate
        self._cancel = False
        self.cancelled = False          # 事后判读：这次是不是被用户取消掉的

    def cancel(self):
        """供 UI 的「中断」按钮调用（只置一个 bool，跨线程安全）。"""
        self._cancel = True

    def run(self):
        try:
            _kw = {}
            if self._commission_rate is not None:
                _kw['commission_rate'] = float(self._commission_rate)
            outcome = run_sweep(
                self._df, self._spec, self._grid, self._interval,
                stage=self._stage,
                done_keys=self._done_keys,
                should_stop=lambda: self._cancel,
                on_progress=lambda d, t, note: self.progress.emit(int(d), int(t), str(note)),
                **_kw)
            self.cancelled = outcome.cancelled
            self.finished.emit(self._job_id, outcome)
        except Exception as e:  # noqa: BLE001 —— 异常绝不穿透线程
            logger.error(f"参数扫描异常 [{getattr(self._spec, 'symbol', '')}]: {e}")
            self.failed.emit(self._job_id, str(e))


class PoolSweepWorker(QThread):
    """组合池化：逐只 × 逐折跑 `run_sweep`（★1.85 / §7-B17 P4）。

    ⚠ 只做"调度 + 取数"，口径全在 `core.portfolio_sweep.aggregate`（纯函数、有断言）。
    ⚠ 每折的样本内/样本外由调用方给（扩张窗口），**本类不自己切**（避免两处口径）。
    """

    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(object)      # {symbol: [{ic, ret}, ...]}（缺数据的票 = []）
    failed = pyqtSignal(str)

    def __init__(self, spec, grid, members, folds, commission=None, parent=None):
        super().__init__(parent)
        self._spec = spec
        self._grid = grid
        self._members = list(members or [])
        self._folds = list(folds or [])
        self._commission = commission

    def run(self):                     # noqa: C901 —— 逐只逐折，逻辑直白
        try:
            import numpy as _np

            from core.param_sweep import run_sweep
            from core.sweep_plan import StudyInterval
            from core.sweep_stats import rank_ic
            from data.market_db import DataLakeManager

            lake = DataLakeManager()
            total = max(1, len(self._members) * len(self._folds))
            done, out = 0, {}
            for sym, _w in self._members:
                df = lake.load_data("kline_daily", str(sym))
                if df is None or not len(df):
                    out[str(sym)] = []          # 缺数据 ⇒ 空（界面写"数据不足"，不补 0）
                    done += len(self._folds)
                    self.progress.emit(done, total, f"{sym}：本机无日线，跳过")
                    continue
                recs = []
                for fold in self._folds:
                    iv = StudyInterval(fold.is_start, fold.is_end, fold.oos_start, fold.oos_end)
                    oc = run_sweep(df, self._spec, self._grid, iv, stage="both",
                                   commission_rate=self._commission)
                    is_a, oos_a = [], []
                    for o in oc.completed.values():
                        if o.is_returns is None or o.oos_returns is None or not len(o.is_returns):
                            continue
                        is_a.append(float(_np.mean(o.is_returns)) * 244.0)
                        oos_a.append(float(_np.mean(o.oos_returns)) * 244.0)
                    if len(is_a) >= 3:
                        ic = float(rank_ic(_np.asarray(is_a), _np.asarray(oos_a)))
                        top = _np.argsort(_np.asarray(is_a))[::-1][:max(1, min(5, len(is_a)))]
                        ret = float(_np.median(_np.asarray(oos_a)[top]))
                    else:
                        ic, ret = None, None
                    recs.append({"ic": ic, "ret": ret})
                    done += 1
                    self.progress.emit(done, total, f"{sym} · 第 {fold.index}/{len(self._folds)} 折")
                out[str(sym)] = recs
            self.finished.emit(out)
        except Exception as exc:           # noqa: BLE001 —— 绝不穿透 QThread
            self.failed.emit(f"{type(exc).__name__}: {exc}")
