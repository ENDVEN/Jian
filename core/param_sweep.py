# core/param_sweep.py
"""
参数稳健性研究（§7-B15）· 编排层（SW-3）。

零 Qt —— UI 经 `ui/workers.ParamSweepWorker` 调 `run_sweep`（线程壳只做调度与
信号转发，照 `CrossSectionWorker` 范式；口径全在本模块，冒烟可直接验证）。

口径（与 docs/JIAN_SWEEP_PLAN.md 同源，改动必须两边同步）：
- **复用 M1 唯一管线**：函数段 `execute_programs` 合并变量列 → `BacktestEngine().run(...)`
  —— 与 M1 现场运行（ui/widgets/backtest_flow）同一套；fill / risk / trigger_tick /
  commission **全参透传**（v3.1 勘误②）。**参数固定时与 M1 同参单跑逐位一致**
  （§8-17，冒烟钉死）。⚠ `engine.run` **不传 params** —— M1 的 BacktestRunWorker
  同样不传（条件表达式只引用已合并的变量列；参数只作用于函数段求值）。
- **两段独立回测**（方案书 §7 边界口径）：IS 与 OOS 各调一次 engine.run，
  样本外首日空仓等下一个信号；逐日收益从各自 equity 切出。
- **逐日收益** = `result.equity['equity']` 的 pct_change（首日 0）——
  PBO / IC 的唯一数据源（方案书 §5 关键设计）。交易数 = is_trades + oos_trades
  （门槛"交易次数"的统计口径，分项各自保留）。
- **交易日轴对齐守卫**：首组记录 IS/OOS 日期轴，后续组与首组不一致 ⇒ 该组记失败
  （绝不静默错位拼矩阵——错位的矩阵会让邻域/IC 全是错的且看不出来）。
- **可中断可续跑（§8-8，与下载队列同款语义）**：`should_stop` 钩子在**组边界**生效；
  取消时已完成的组照常返回（cancelled=True）。⚠ 与 M2 横截面的"绝不返回半成品"**不同**：
  参数扫描的各组回测彼此独立，"部分组完成"是有意义且诚实的结果——页面按
  `combo_key` 记账（`done_keys`），续跑只补没跑过的组。
- **诚实范围收缩**：策略携带**指数门控**配置 ⇒ 直接拒绝（MVP 不复刻阶段C 门控；
  将来支持时在 merged 层补同一套 `_attach_index_gates`，别在这里重写一份）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core.backtest import BacktestEngine, DEFAULT_COMMISSION_RATE
from core.conditions import gate_expression
from core.formula.program import (FormulaProgramError, execute_programs,
                                  parse_program)
from core.formula.runtime import FormulaEvalError
from core.sweep_plan import GridPlan, StudyInterval
from core.utils import parse_params_text


def combo_key(combo: dict) -> str:
    """组合的规范化键（续跑记账 / 存档索引用）：参数名排序 + %.6g 数值。

    与 `sweep_plan.make_dimension` 的 round(6) 同源 —— 0.30000000000000004 之类
    的浮点尾巴在这里也会被驯成 "0.3"。
    """
    return "|".join(f"{k}={float(combo[k]):.6g}" for k in sorted(combo))


@dataclass(frozen=True)
class SweepSpec:
    """一次参数扫描的策略侧输入（来自 M1 已保存策略整体，v3.1 真源 strategy_store）。"""

    symbol: str
    segments: tuple[str, ...]     # 函数段文本
    params_text: str              # 策略保存的参数文本（组合值覆盖其中的网格维）
    condition_buy: dict | str     # 条件**配置**（策略存档原样）或已是表达式文本
    condition_sell: dict | str
    risk: dict = field(default_factory=dict)
    fill_mode: str | None = None  # None = 引擎归一默认（与 M1 传 None 同形）
    trigger_tick: int | None = None
    has_index_gate: bool = False  # payload 带 index 配置 ⇒ run_sweep 拒绝

    @property
    def buy_expr(self) -> str:
        """条件配置 → DSL 表达式（**引擎只认表达式**；唯一真源 = `core.conditions`）。

        ★1.66 血案：本模块曾把条件 **dict 直接递给 `BacktestEngine.run`** ⇒ 引擎在
        `FormulaEngine.signal` 里 `tokenize(dict)` 抛 `KeyError: 0`，**每一组都失败**
        （页面表现就是"点了没反应 / 一组都跑不出来"）。⇒ 求值前必须过这一层，
        且与界面控件（`ConditionGate.expression()`）走**同一份**映射。
        空串 = 条件不足 ⇒ 调用方**必须诚实拒绝**，不许硬跑。
        """
        return gate_expression(self.condition_buy)

    @property
    def sell_expr(self) -> str:
        """同 `buy_expr`（卖出侧）。"""
        return gate_expression(self.condition_sell)


@dataclass(frozen=True)
class ComboOutcome:
    """一组参数的回测产物（逐日收益 + 交易数 + 日期轴）。

    `stage="is"/"oos"` 分段跑时，未跑的那段为 **None**（红线①：样本外只在
    用户明确要求时跑一次 —— 引擎层就不该顺手把两段都算掉）。
    """

    key: str
    combo: dict
    is_returns: np.ndarray | None
    oos_returns: np.ndarray | None
    is_dates: tuple[str, ...] | None
    oos_dates: tuple[str, ...] | None
    is_trades: int = 0
    oos_trades: int = 0

    @property
    def trades(self) -> int:
        """交易次数门槛的统计口径 = 两段合计（方案书 §2；分项各自保留可查）。"""
        return int(self.is_trades) + int(self.oos_trades)


@dataclass
class SweepOutcome:
    """一次 run_sweep 的产出（取消时 completed 里的组**保留可续**，§8-8）。"""

    completed: dict[str, ComboOutcome] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)   # combo_key → 人话原因
    cancelled: bool = False
    notes: list[str] = field(default_factory=list)         # 过程说明（诚实口径）


def _daily_returns(result_equity: pd.DataFrame) -> np.ndarray:
    """equity（date/equity/in_market/close）→ 逐日简单收益（首日 0）。"""
    eq = result_equity["equity"].astype(float)
    return eq.pct_change().fillna(0.0).to_numpy()


def _dates_of(result_equity: pd.DataFrame) -> tuple[str, ...]:
    d = pd.to_datetime(result_equity["date"])
    return tuple(d.dt.strftime("%Y-%m-%d"))


def _merged_frame(df: pd.DataFrame, programs, params: dict) -> pd.DataFrame:
    """函数段求值 → 变量列并进 df（与 M1 同一套；变量与行情列重名 ⇒ 人话报错）。"""
    results = execute_programs(programs, df, params)
    collisions = sorted(set(results) & set(df.columns))
    if collisions:
        raise ValueError(f"函数变量与行情列重名: {', '.join(collisions)}。请改名后重试")
    merged = df.copy()
    for name, series in results.items():
        merged[name] = series.values
    return merged


def run_sweep(df, spec: SweepSpec, grid: GridPlan, interval: StudyInterval, *,
              stage: str = "both",
              done_keys=frozenset(), should_stop=None, on_progress=None,
              commission_rate: float = DEFAULT_COMMISSION_RATE) -> SweepOutcome:
    """逐组跑回测，收集逐日收益。中断安全、可续跑（见模块 docstring）。

    `stage`：**"is"** 只跑样本内 / **"oos"** 只跑样本外 / **"both"** 两段都跑。
    红线①的流程形态 = 页面先 stage="is"、用户看完样本内再显式 stage="oos" ——
    引擎层绝不顺手把样本外算掉。
    """
    if stage not in ("is", "oos", "both"):
        raise ValueError(f"stage 只能是 is / oos / both（收到 {stage}）")
    if spec.has_index_gate:
        raise ValueError("该策略带指数门控，参数研究暂不支持（MVP 不复刻阶段C 门控）——"
                         "请先用不带指数门控的配方")
    buy_expr, sell_expr = spec.buy_expr, spec.sell_expr   # ★1.66：配置 → DSL（引擎只认表达式）
    if not buy_expr or not sell_expr:
        raise ValueError("买卖条件为空（或条件配置里没有有效条件行）⇒ 没有可回测的东西"
                         "（先在 M1 配好买卖条件再存策略）")
    if not grid.ok:
        raise ValueError(f"网格未通过闸门：{grid.rejection}")

    out = SweepOutcome()
    try:
        programs = [parse_program(t) for t in spec.segments if str(t or "").strip()]
    except FormulaProgramError as e:
        raise ValueError(f"函数段编译失败：{e}") from e
    if not programs:
        raise ValueError("策略没有可用的函数段（先在 M1 里写函数）")
    base_params = parse_params_text(spec.params_text)

    # 碰撞检查只与"变量名集合"有关，与参数取值无关 ⇒ 循环外做一次（用基准参数）
    _merged_frame(df, programs, base_params)

    engine = BacktestEngine()
    total = grid.n_combos
    todo = [c for c in grid.combos if combo_key(c) not in set(done_keys)]
    skipped = total - len(todo)
    if skipped:
        out.notes.append(f"续跑：跳过已完成的 {skipped} 组，本次补跑 {len(todo)} 组")
    ref_is: tuple[str, ...] | None = None
    ref_oos: tuple[str, ...] | None = None
    done = skipped
    if on_progress:
        on_progress(done, total, "续跑记账" if skipped else "开始")

    for combo in todo:
        if should_stop is not None and should_stop():
            out.cancelled = True                      # 已完成的组保留（§8-8），不丢弃
            break
        key = combo_key(combo)
        params = {**base_params, **combo}
        try:
            run_is = stage in ("is", "both")
            run_oos = stage in ("oos", "both")
            merged = _merged_frame(df, programs, params)
            res_is = engine.run(merged, buy_expr, sell_expr,
                                symbol=spec.symbol, start_date=interval.is_start,
                                end_date=interval.is_end, risk=spec.risk,
                                fill_mode=spec.fill_mode, trigger_tick=spec.trigger_tick,
                                commission_rate=commission_rate) if run_is else None
            res_oos = engine.run(merged, buy_expr, sell_expr,
                                 symbol=spec.symbol, start_date=interval.oos_start,
                                 end_date=interval.oos_end, risk=spec.risk,
                                 fill_mode=spec.fill_mode, trigger_tick=spec.trigger_tick,
                                 commission_rate=commission_rate) if run_oos else None
            if (run_is and res_is.equity.empty) or (run_oos and res_oos.equity.empty):
                out.failed[key] = "样本内或样本外区间没有行情数据（数据不足，不是缺陷）"
                continue
            is_dates = _dates_of(res_is.equity) if run_is else None
            oos_dates = _dates_of(res_oos.equity) if run_oos else None
            # 交易日轴对齐守卫：首组记轴，后续组必须逐日一致
            if run_is:
                if ref_is is None:
                    ref_is = is_dates
                elif is_dates != ref_is:
                    out.failed[key] = "该组合的样本内交易日轴与首组不一致（数据在扫描期间变了？）——诚实记失败，不拼错位矩阵"
                    continue
            if run_oos:
                if ref_oos is None:
                    ref_oos = oos_dates
                elif oos_dates != ref_oos:
                    out.failed[key] = "该组合的样本外交易日轴与首组不一致（数据在扫描期间变了？）——诚实记失败，不拼错位矩阵"
                    continue
            prev = out.completed.get(key)
            out.completed[key] = ComboOutcome(
                key=key, combo=dict(combo),
                is_returns=_daily_returns(res_is.equity) if run_is else (
                    prev.is_returns if prev else None),
                oos_returns=_daily_returns(res_oos.equity) if run_oos else (
                    prev.oos_returns if prev else None),
                is_dates=is_dates or (prev.is_dates if prev else None),
                oos_dates=oos_dates or (prev.oos_dates if prev else None),
                is_trades=len(res_is.trades) if run_is else (
                    prev.is_trades if prev else 0),
                oos_trades=len(res_oos.trades) if run_oos else (
                    prev.oos_trades if prev else 0))
        except (FormulaProgramError, FormulaEvalError) as e:
            out.failed[key] = f"条件求值失败：{e}"
        except Exception as e:  # noqa: BLE001 —— 单组失败不拖垮整轮（诚实记账）
            out.failed[key] = f"回测失败：{type(e).__name__}: {e}"
        done += 1
        if on_progress:
            on_progress(done, total, key)
    return out


def build_matrix(outcome: SweepOutcome, keys: list[str] | None = None) -> np.ndarray:
    """已完成组 → 逐日收益矩阵 (n_combos, is_days + oos_days)（IS 段在前拼接）。

    sweep_stats.pbo_cscv 的输入形状；行列顺序与 keys 一致（缺省 = 完成序）。
    任一组缺段（stage 只跑了单段）⇒ 诚实报错——统计只在两段都齐时才有意义。
    """
    keys = list(outcome.completed) if keys is None else list(keys)
    if not keys:
        return np.zeros((0, 0))
    rows = []
    for k in keys:
        co = outcome.completed[k]
        if co.is_returns is None or co.oos_returns is None:
            raise ValueError(f"组合 {k} 的样本内/样本外尚未跑全（先跑样本内、再跑样本外）")
        rows.append(np.concatenate([co.is_returns, co.oos_returns]))
    return np.vstack(rows)


def split_indices(outcome: SweepOutcome) -> tuple[np.ndarray, np.ndarray]:
    """IS / OOS 在拼接天轴上的索引（以首完成组为轴——交易日轴守卫保证各组一致）。"""
    for co in outcome.completed.values():
        if co.is_dates and co.oos_dates:
            n_is = len(co.is_dates)
            return np.arange(n_is), np.arange(n_is, n_is + len(co.oos_dates))
    raise ValueError("没有同时跑完两段的组合（先跑样本内、再跑样本外）")
