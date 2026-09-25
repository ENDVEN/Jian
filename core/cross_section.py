# core/cross_section.py
"""M2 全市场横截面筛选 / M3 广度统计 —— 纯计算内核（§7-B1/B2 主案 · D2 / D5）

【职责边界】本模块 **零 UI、零网络、零全局状态**：
  · 只做"给定日线 → 三态结果 / 逐日广度"的计算；
  · 不碰 preferences、不碰数据库（花名册由调用方传 `names`）、不发任何请求；
  · 磁盘只 **读**，且**按"列是否存在"裁剪**（§9.1：分区列结构不一致、有源透传列）。

【口径铁律】四态里 **"数据不足" ≠ "未命中"**（§7-B1/B2 A 节第 6 条）：

    HIT           命中      有数据、公式为真
    MISS          未命中    有数据、公式为假
    INSUFFICIENT  数据不足  **因数据原因无法判定**：该日无行 / 停牌 / 历史太短 / 缺列 / 求值失败
    FILTERED      被粗筛剔除 数据没问题，只是**不满足阈值**（价格 / 成交额 / 换手率 / ST …）

  ⇒ **广度占比的分母 = 通过粗筛的有效样本（HIT+MISS）**，不是"全市场只数"；
    否则一批新上市股会把占比系统性压低，而且**没人看得出**。

【为什么与 M1 同一套口径】`prepare_frame` 与 `core/backtest.py:BacktestEngine.run` 的数据准备
**一字不差**（同序、同 dropna、同 dtypes）；`tests/smoke_chart.py` 有"两处产出逐位一致"的可执行断言
—— 谁改了一处而漏另一处，冒烟立刻红（§11.5-11「同类防护只改一处」的正解）。

【性能】P4 实测（§7-B1/B2 B3）：本机 368 只 ≈1.8 s；全市场外推 ≈26 s（**未优化**的逐行累加）。
⇒ 本模块逐日家数走「**日期 → 整数下标 + 一次 `np.bincount`**」，不写逐行 Python 循环。
"""
from __future__ import annotations

import logging
import os
import time
from collections import Counter
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from core.formula.program import FormulaProgramError, execute_programs, parse_program

logger = logging.getLogger(__name__)

__all__ = [
    'HIT', 'MISS', 'INSUFFICIENT', 'FILTERED', 'STATUS_LABELS',
    'R_NO_ROW', 'R_SUSPENDED', 'R_SHORT', 'R_MISSING_COL', 'R_FORMULA', 'R_LABELS',
    'ScanThresholds', 'CrossSectionResult', 'ScanCancelled',
    'prepare_frame', 'read_daily', 'columns_for', 'scan', 'scan_lake', 'tally_status',
    'human_amount', 'human_mktcap', 'signal_names', 'DEFAULT_CHUNK',
]

# ==========================================
# 1) 状态码与原因（唯一出处：界面 / 体检 / 日志都读这里，别再各写一套文案）
# ==========================================
HIT = 'hit'
MISS = 'miss'
INSUFFICIENT = 'insufficient'
FILTERED = 'filtered'

STATUS_LABELS = {
    HIT: '命中',
    MISS: '未命中',
    INSUFFICIENT: '数据不足',
    FILTERED: '被粗筛剔除',
}

# 「数据不足」的细目 —— 界面/体检要能说清"为什么不足"，而不是一句"没数据"
R_NO_ROW = 'no_row'              # 当日无行（停牌 / 未下载 / 已退市）
R_SUSPENDED = 'suspended'        # 有行但成交量为 0（停牌行）
R_SHORT = 'short_history'        # 有效数据不够 min_bars 个交易日（新上市 …）
R_MISSING_COL = 'missing_column'  # 阈值/公式要用的列在这个标的上**不存在**（§9.1）
R_FORMULA = 'formula_error'      # 该标的求值抛错（缺列 / 全空 …）

R_LABELS = {
    R_NO_ROW: '当日无数据（停牌 / 未下载 / 已退市）',
    R_SUSPENDED: '当日停牌（成交量为 0）',
    R_SHORT: '有效数据不足',
    R_MISSING_COL: '缺少所需列',
    R_FORMULA: '公式求值失败',
}

# 状态码（uint8 矩阵用，**顺序有意义**：≥ MISS 表示"入了有效样本"）
_C_INSUFFICIENT, _C_FILTERED, _C_MISS, _C_HIT = 0, 1, 2, 3
_STATUS_CODE = {INSUFFICIENT: _C_INSUFFICIENT, FILTERED: _C_FILTERED,
                MISS: _C_MISS, HIT: _C_HIT}
_CODE_STATUS = {v: k for k, v in _STATUS_CODE.items()}

# 读数基线列（`amount` 恒读：既是最常用的阈值，也是最常用的展示列）
_BASE_COLUMNS = ('date', 'open', 'high', 'low', 'close', 'volume', 'amount')

# 分块粒度：每多少只报一次进度 / 轮询一次取消（D4）。200 ≈ 全市场 27 次回调 ——
# 足够让进度条"动得自然"，又不至于把时间花在回调本身（每次回调只是一次跨线程信号）。
DEFAULT_CHUNK = 200


# ==========================================
# 2) 粗筛阈值（D5：内置默认 + 全部可调 + 「↺ 恢复默认」）
# ==========================================
@dataclass
class ScanThresholds:
    """粗筛阈值。**关掉 = 不参与漏斗**：数值项填 `None`、布尔项填 `False`。

    ⚠ `min_bars` / 缺列 的失败算「**数据不足**」，其余算「**被粗筛剔除**」——
      这条分界是 §三态铁律的落地：新上市股不是"没命中"，是"没法判定"。
    """

    min_amount: float | None = 5e7          # 成交额 ≥（元）
    min_price: float | None = 2.0           # 收盘价 ≥（元）
    min_bars: int | None = 250              # 有效数据 ≥（个交易日）
    exclude_suspended: bool = True          # 剔除停牌（volume > 0）
    exclude_st: bool = True                 # 剔除 ST / 退市（按**当前**名称，历史不可追溯）
    exclude_limit: bool = True              # 剔除一字板（high == low）
    min_turnover: float | None = None       # 换手率 ≥（**小数口径**：0.0093 = 0.93%）
    min_float_mktcap: float | None = None   # 流通市值 ≥（元）
    max_float_mktcap: float | None = None   # 流通市值 ≤（元）
    min_change_pct: float | None = None     # 涨跌幅 ≥（小数：0.05 = +5%）
    max_change_pct: float | None = None     # 涨跌幅 ≤（小数）

    # ---------- 序列化（preferences 落盘 / 还原） ----------
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw) -> 'ScanThresholds':
        """从偏好还原。**坏数据逐字段回落默认**（§9-D：一条坏偏好不能拖垮整页）。

        ⚠ 数值项显式 `None` = **"关掉这一项"**，必须能存回来（`min_bars` 默认 250 也允许变 None，
          否则用户"关掉上市天数过滤"下次打开又自己长回来 —— 这类"记不住"最招人烦）。
        """
        out = cls()
        if not isinstance(raw, dict):
            return out
        for key, default in out.to_dict().items():
            if key not in raw:
                continue
            value = raw[key]
            if isinstance(default, bool):          # 注意：bool 是 int 的子类，必须先判
                setattr(out, key, bool(value))
                continue
            if value is None:
                setattr(out, key, None)            # 显式关闭（数值项）
                continue
            convert = int if isinstance(default, int) else float
            try:
                setattr(out, key, convert(value))
            except (TypeError, ValueError):
                continue                           # 转不动 ⇒ 保留默认，绝不抛
        return out

    def problems(self) -> list[str]:
        """自检：给界面用的**非阻断**提示（不抛异常，避免一个笔误让整页打不开）。"""
        bad = []
        if self.min_price is not None and self.min_price < 0:
            bad.append('价格下限不能为负')
        if self.min_amount is not None and self.min_amount < 0:
            bad.append('成交额下限不能为负')
        if self.min_bars is not None and self.min_bars < 0:
            bad.append('有效数据天数不能为负')
        if (self.min_change_pct is not None and self.max_change_pct is not None
                and self.min_change_pct > self.max_change_pct):
            bad.append('涨跌幅下限大于上限')
        if (self.min_float_mktcap is not None and self.max_float_mktcap is not None
                and self.min_float_mktcap > self.max_float_mktcap):
            bad.append('流通市值下限大于上限')
        return bad

    def reset(self) -> 'ScanThresholds':
        """「↺ 恢复默认」（界面按钮的后端；返回新对象，不改调用方）"""
        return ScanThresholds()


# ==========================================
# 3) 数据准备 / 读数（口径与 §9.1 纪律都在这两处）
# ==========================================
def prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    """日线 df → 引擎可直接吃的帧。

    ★ **与 `core/backtest.py:BacktestEngine.run` 的数据准备一字不差** —— M1/M2/M3 必须同口径，
      改这里就要同步改那里（`tests/smoke_chart.py` 有一致性断言钉住）。
    """
    if df is None or len(df) == 0 or 'date' not in df.columns:
        return pd.DataFrame()
    data = df.copy()
    data['date'] = pd.to_datetime(data['date'])
    data = data.sort_values('date').reset_index(drop=True)
    for col in ('open', 'high', 'low', 'close', 'volume'):
        if col in data.columns:
            data[col] = pd.to_numeric(data[col], errors='coerce')
    data = data.dropna(subset=['close', 'open'])
    return data


def columns_for(thresholds: ScanThresholds, snapshot_columns=()) -> tuple[str, ...]:
    """本次扫描要从湖里读哪些列（**按需裁剪**；缺列由逐标的判定兜住，§9.1）"""
    cols = list(_BASE_COLUMNS)
    if thresholds.min_turnover is not None:
        cols.append('turnover')
    if thresholds.min_float_mktcap is not None or thresholds.max_float_mktcap is not None:
        cols.append('outstanding_share')
    cols.extend(snapshot_columns or ())
    return tuple(dict.fromkeys(cols))


def read_daily(lake_dir: str, symbols=None, columns=None) -> dict[str, pd.DataFrame]:
    """读日线分区 → `{标的: df}`。

    · `symbols=None` ⇒ **一次 dataset 扫描**（全市场用它；分区里没有 `symbol` 列的文件会被忽略）；
    · `symbols=[...]` ⇒ **按文件读**（自选 / 指数成分这种小范围用它，别为 10 只票扫 5000 个文件）；
    · **列按"该文件自己有没有"裁剪**（§9.1：分区里混着中文列与期货列，禁止假设 schema 统一）。

    读不出来的单个文件**只记日志、不中断整轮**（坏文件不该让一次扫描全废）。
    """
    out: dict[str, pd.DataFrame] = {}
    if not lake_dir or not os.path.isdir(lake_dir):
        return out

    want = tuple(columns or ())
    if symbols is None:
        import pyarrow.dataset as ds
        try:
            dataset = ds.dataset(lake_dir, format='parquet')
        except Exception as e:  # noqa: BLE001
            logger.error(f"日线分区打不开 [{lake_dir}]: {e}")
            return out
        names = set(dataset.schema.names)
        cols = [c for c in (want or dataset.schema.names) if c in names] if want else None
        if want and 'symbol' not in cols:
            cols.append('symbol')          # 全量扫必须带 symbol 才能分组（缺它只能整块丢掉）
        try:
            frame = dataset.to_table(columns=cols).to_pandas()
        except Exception as e:  # noqa: BLE001
            logger.error(f"日线分区读取失败 [{lake_dir}]: {e}")
            return out
        if 'symbol' not in frame.columns:
            logger.error(f"日线分区缺少 symbol 列，无法按标的切分 [{lake_dir}]")
            return out
        for sym, chunk in frame.groupby('symbol', sort=False):
            out[str(sym)] = chunk.reset_index(drop=True)
        return out

    import pyarrow.parquet as pq
    for sym in symbols:
        path = os.path.join(lake_dir, f"{sym}.parquet")
        if not os.path.exists(path):
            continue
        try:
            file_names = set(pq.ParquetFile(path).schema_arrow.names)
            cols = [c for c in want if c in file_names] if want else None
            if not cols and want:
                logger.warning(f"日线文件没有任何需要的列，已跳过 [{sym}]")
                continue
            out[str(sym)] = pq.read_table(path, columns=cols).to_pandas()
        except Exception as e:  # noqa: BLE001 —— 坏文件只跳过自己
            logger.error(f"日线读取失败 [{sym}]: {e}")
    return out


# ==========================================
# 4) 粗筛：逐行两个掩码 + 逐标的硬原因
# ==========================================
def _is_st(name: str) -> bool:
    """名称是否含 ST / 退（D5：⚠ 只能按**当前**名称过滤，历史 ST 不可追溯）"""
    text = str(name or '')
    return ('ST' in text.upper()) or ('退' in text)


def _numeric(frame: pd.DataFrame, col: str) -> np.ndarray:
    return pd.to_numeric(frame[col], errors='coerce').to_numpy(dtype=float)


def _row_masks(frame: pd.DataFrame, th: ScanThresholds, is_st: bool = False):
    """返回 `(data_ok, passes, hard, note)`：

    · `data_ok` 逐行"数据充分"：**非停牌 + 累计交易日够 + 阈值用到的数值不许为空**；
    · `passes`  逐行"满足阈值"：价格 / 成交额 / 换手率 / 流通市值 / 涨跌幅 / 非一字板；
    · `hard`   非 None ⇒ **整只**记「数据不足」（缺列这类没法逐行挽救的问题），`note` 是原因文案。

    ★ 关键分界：**数值为空(NaN)的行算「数据不足」，不算「不符」**
      —— 否则"这只票没有 amount 列"会静默变成"成交额不达标"，
      与"新上市股被算成未命中"是同一类错误（§三态铁律）。
      坑：`ds.dataset()` 全量扫时，缺列的文件会**补出一列全 NaN**，
      光看 `col in frame.columns` 是分不出来的 —— 所以必须按行判空。
    """
    n = len(frame)
    if n == 0:
        return np.zeros(0, dtype=bool), np.zeros(0, dtype=bool), R_NO_ROW, R_LABELS[R_NO_ROW]

    # ---- 硬原因：阈值要用到的列**在这只票上根本不存在** ⇒ 整只数据不足
    need = []
    if th.min_amount is not None:
        need.append('amount')
    if th.min_turnover is not None:
        need.append('turnover')
    if th.min_float_mktcap is not None or th.max_float_mktcap is not None:
        need.append('outstanding_share')
    for col in need:
        if col not in frame.columns:
            return (np.zeros(n, dtype=bool), np.zeros(n, dtype=bool),
                    R_MISSING_COL, f'缺少所需列 {col}')

    close = _numeric(frame, 'close')
    volume = _numeric(frame, 'volume')
    unknown = np.isnan(close)

    data_ok = ~unknown
    if th.min_bars:
        # 第 k 行 = 该标的第 k+1 个交易日 ⇒ 不足 min_bars 的**前段**都是「数据不足」
        data_ok &= (np.arange(n) + 1) >= int(th.min_bars)
    if th.exclude_suspended:
        data_ok &= volume > 0          # NaN 走 False ⇒ 也归「数据不足」✅

    passes = np.ones(n, dtype=bool)
    if is_st:
        passes[:] = False              # ST/退市：整只剔除（只能按当前名称，见 D5 注）

    def _known(values: np.ndarray) -> np.ndarray:
        """顺手把 NaN 记进 `unknown`（调用方仍需自行比较）"""
        nonlocal unknown
        unknown |= np.isnan(values)
        return values

    if th.min_price is not None:
        passes &= _known(close) >= float(th.min_price)
    if th.min_amount is not None:
        passes &= _known(_numeric(frame, 'amount')) >= float(th.min_amount)
    if th.min_turnover is not None:
        passes &= _known(_numeric(frame, 'turnover')) >= float(th.min_turnover)
    if th.min_float_mktcap is not None or th.max_float_mktcap is not None:
        mktcap = _known(close * _numeric(frame, 'outstanding_share'))
        if th.min_float_mktcap is not None:
            passes &= mktcap >= float(th.min_float_mktcap)
        if th.max_float_mktcap is not None:
            passes &= mktcap <= float(th.max_float_mktcap)
    if th.min_change_pct is not None or th.max_change_pct is not None:
        prev = np.concatenate(([np.nan], close[:-1]))
        with np.errstate(divide='ignore', invalid='ignore'):
            change = close / prev - 1.0
        _known(change)                 # 首行没有"前收" ⇒ 数据不足（不是"涨跌幅不符"）
        if th.min_change_pct is not None:
            passes &= change >= float(th.min_change_pct)
        if th.max_change_pct is not None:
            passes &= change <= float(th.max_change_pct)
    if th.exclude_limit:
        high = _known(_numeric(frame, 'high'))
        low = _known(_numeric(frame, 'low'))
        passes &= high != low

    data_ok &= ~unknown               # 收口：凡是"算不出来"的行，一律记「数据不足」
    return data_ok, passes, None, ''


def filter_detail(frame: pd.DataFrame, th: ScanThresholds, i: int, is_st: bool = False) -> str:
    """第 `i` 行为什么没通过粗筛（只算一行，供「为什么没进候选」清单用）"""
    if is_st:
        return 'ST / 退市'
    close = float(pd.to_numeric(frame['close'], errors='coerce').iloc[i])
    if th.min_price is not None and not (close >= float(th.min_price)):
        return f'价格 < {th.min_price:g} 元'
    if th.min_amount is not None and 'amount' in frame.columns:
        amount = float(pd.to_numeric(frame['amount'], errors='coerce').iloc[i])
        if not (amount >= float(th.min_amount)):
            return f'成交额 < {human_amount(th.min_amount)}'
    if th.min_turnover is not None and 'turnover' in frame.columns:
        turn = float(pd.to_numeric(frame['turnover'], errors='coerce').iloc[i])
        if not (turn >= float(th.min_turnover)):
            return f'换手率 < {th.min_turnover * 100:g}%'
    if 'outstanding_share' in frame.columns:
        share = float(pd.to_numeric(frame['outstanding_share'], errors='coerce').iloc[i])
        mktcap = close * share
        if th.min_float_mktcap is not None and not (mktcap >= float(th.min_float_mktcap)):
            return f'流通市值 < {human_mktcap(th.min_float_mktcap)}'
        if th.max_float_mktcap is not None and not (mktcap <= float(th.max_float_mktcap)):
            return f'流通市值 > {human_mktcap(th.max_float_mktcap)}'
    if (th.min_change_pct is not None or th.max_change_pct is not None) and i > 0:
        prev = float(pd.to_numeric(frame['close'], errors='coerce').iloc[i - 1])
        with np.errstate(divide='ignore', invalid='ignore'):
            change = close / prev - 1.0 if prev else np.nan
        if th.min_change_pct is not None and not (change >= float(th.min_change_pct)):
            return f'涨跌幅 < {th.min_change_pct * 100:g}%'
        if th.max_change_pct is not None and not (change <= float(th.max_change_pct)):
            return f'涨跌幅 > {th.max_change_pct * 100:g}%'
    if th.exclude_limit:
        high = float(pd.to_numeric(frame['high'], errors='coerce').iloc[i])
        low = float(pd.to_numeric(frame['low'], errors='coerce').iloc[i])
        if high == low:
            return '一字板'
    return '未通过粗筛'


def _insufficient_reason(frame: pd.DataFrame, th: ScanThresholds, i: int) -> str:
    """第 `i` 行为什么"数据不足" —— 界面/体检要说清原因，不能只甩一句"没数据"。"""
    close = float(pd.to_numeric(frame['close'], errors='coerce').iloc[i])
    volume = float(pd.to_numeric(frame['volume'], errors='coerce').iloc[i])
    if not np.isfinite(close) or not np.isfinite(volume):
        return '数值缺失，无法判定'
    if th.exclude_suspended and not (volume > 0):
        return R_LABELS[R_SUSPENDED]
    if th.min_bars and (i + 1) < int(th.min_bars):
        return f'{R_LABELS[R_SHORT]} {int(th.min_bars)} 个交易日（当日仅 {i + 1} 个）'
    return '数据不完整，无法判定'


# ---- 用户量纲格式化（§10-10：界面与文案一律"万元 / 亿元"，不出现 50000000） ----
def human_amount(value: float) -> str:
    value = float(value)
    if abs(value) >= 1e8:
        return f'{value / 1e8:g} 亿元'
    if abs(value) >= 1e4:
        return f'{value / 1e4:g} 万元'
    return f'{value:g} 元'


def human_mktcap(value: float) -> str:
    return human_amount(value)


class ScanCancelled(Exception):
    """扫描被用户取消 —— **明确区别于"扫完了但没结果"**。

    ★ 取消**绝不返回半成品矩阵**：半个矩阵的命中家数、广度占比**全是错的**，
      而界面上看不出任何异常（正是三态铁律要防的那一类"静默错误"）。
      ⇒ 抛异常而不是"返回部分结果"，让调用方**在类型层面**无法把半成品当成品用。
    """


def _noop_progress(done: int, total: int, note: str) -> None:      # pragma: no cover
    """默认进度回调（不需要进度时就传它，避免调用点到处写 `if progress`）"""


def _as_signal(raw) -> np.ndarray:
    """公式输出 → 布尔信号：**非 0 为真、空值当假**（与 `EvalContext.truth_series` 同款）。

    空值当假而不是当真是**有意的**：热身期（MA 还没算出来）不该被判成"命中"；
    这类行绝大多数本来也落在 `min_bars` 的「数据不足」区里，不会污染命中率。
    """
    series = pd.Series(raw)
    numeric = pd.to_numeric(series, errors='coerce').to_numpy(dtype=float)
    return (numeric != 0) & ~np.isnan(numeric)


def _derived_metrics(frame: pd.DataFrame, i: int) -> dict:
    """★P2：从该标的日线序列就地算涨幅/流通市值（任意基准日都真、零新网络）。

    口径与常识一致：
      · 当日涨幅 = 今收/昨收 - 1；
      · 当月/当年涨幅 = 以**上一期最后一个交易日收盘**为基准（本期起点-1）；
      · 流通市值 = 收盘 × 流通股本。
    缺前值 / 无上期基准（数据从本期起算）/ 缺列 ⇒ 该字段 None（**诚实，绝不硬凑 0**）。
    """
    out = {'day_pct': None, 'month_pct': None, 'year_pct': None, 'float_mktcap': None}
    if frame is None or 'close' not in frame.columns or 'date' not in frame.columns:
        return out
    close = pd.to_numeric(frame['close'], errors='coerce').to_numpy(dtype=float)
    n = len(close)
    if i < 0 or i >= n or not np.isfinite(close[i]):
        return out
    cur = close[i]
    if i >= 1 and np.isfinite(close[i - 1]) and close[i - 1] != 0:
        out['day_pct'] = cur / close[i - 1] - 1.0
    dates = pd.to_datetime(frame['date']).to_numpy()
    for key, unit in (('month_pct', 'datetime64[M]'), ('year_pct', 'datetime64[Y]')):
        try:
            keys = dates.astype(unit)
            start = int(np.searchsorted(keys, keys[i], side='left'))   # 本期首个交易日
        except (TypeError, ValueError):
            continue
        base = start - 1                                                # 上期末个交易日
        if base >= 0 and np.isfinite(close[base]) and close[base] != 0:
            out[key] = cur / close[base] - 1.0
    if 'outstanding_share' in frame.columns:
        share = pd.to_numeric(frame['outstanding_share'], errors='coerce').to_numpy(dtype=float)
        if i < len(share) and np.isfinite(share[i]):
            out['float_mktcap'] = cur * share[i]
    return out


def signal_names(formula: str) -> list[str]:
    """这段筛选条件里可当"判定变量"的名字（界面下拉用；按声明顺序）"""
    return parse_program(formula).output_names


# ==========================================
# 5) 结果
# ==========================================
def tally_status(status: dict, total: int = None) -> dict:
    """四态计数（**唯一实现**）。

    `scan()` 与"缓存命中后再问一次某天"都走这里 —— 否则两处各写一遍，
    迟早出现"重扫是 120 只、缓存切片是 118 只"这种**没人能一眼看出的分裂**（§11.5-12）。
    """
    counter = Counter(status.values())
    return {
        'total': len(status) if total is None else int(total),
        HIT: counter.get(HIT, 0),
        MISS: counter.get(MISS, 0),
        INSUFFICIENT: counter.get(INSUFFICIENT, 0),
        FILTERED: counter.get(FILTERED, 0),
        'valid': counter.get(HIT, 0) + counter.get(MISS, 0),
    }

@dataclass
class CrossSectionResult:
    """一次扫描的产出。M2 = 看 `status`；M3 = 看 `breadth_*` / `breadth_frame()`。"""

    asof: pd.Timestamp | None = None
    formula: str = ''
    signal_name: str = ''
    thresholds: ScanThresholds = field(default_factory=ScanThresholds)
    status: dict = field(default_factory=dict)      # 标的 → HIT/MISS/INSUFFICIENT/FILTERED
    detail: dict = field(default_factory=dict)      # 标的 → 原因文案
    snapshot: dict = field(default_factory=dict)    # 标的 → {列: 值}（asof 当行）
    counts: dict = field(default_factory=dict)      # 四态计数 + valid + total
    dates: pd.DatetimeIndex | None = None           # 交易日轴（广度 / 矩阵用）
    counters: np.ndarray | None = None              # (交易日, 4) 逐日四态家数
    symbols: list = field(default_factory=list)     # 矩阵行序（= keep_matrix 时的行标）
    missing_files: list = field(default_factory=list)   # 请求了但**本地没有日线文件**的标的
    status_matrix: np.ndarray | None = None         # (标的, 交易日) uint8 状态码
    warnings: list = field(default_factory=list)
    elapsed_ms: float = 0.0

    # ---------- M2 ----------
    @property
    def hits(self) -> list[str]:
        return [s for s, st in self.status.items() if st == HIT]

    @property
    def valid_count(self) -> int:
        """有效样本数 = 命中 + 未命中（**广度占比的分母**）"""
        return int(self.counts.get(HIT, 0)) + int(self.counts.get(MISS, 0))

    def status_on(self, date) -> dict:
        """某一天的横截面三态 —— 有缓存矩阵时**秒回**（改日期不重算，D3）。

        返回 `{标的: 状态}`；没开 `keep_matrix` 时返回空 dict（调用方应改用 `scan`）。
        """
        if self.status_matrix is None or self.dates is None:
            return {}
        stamp = pd.Timestamp(date)
        idx = int(self.dates.searchsorted(stamp))
        if idx >= len(self.dates) or self.dates[idx] != stamp:
            return {}
        column = self.status_matrix[:, idx]
        out = {sym: _CODE_STATUS[int(code)] for sym, code in zip(self.symbols, column)}
        # 本地没文件的标的：每一天都是「数据不足」（与 scan() 当日口径同源，
        # 否则"扫描时 429 只、切日期后变 27 只"这种数字跳变会让用户以为软件坏了）
        for sym in self.missing_files:
            out[sym] = INSUFFICIENT
        return out

    def counts_on(self, date) -> dict:
        """某一天的横截面四态计数 —— **缓存命中时用它**（不必重扫），口径与 `scan` 同源。"""
        return tally_status(self.status_on(date))

    # ---------- M3 ----------
    def breadth_frame(self, start=None) -> pd.DataFrame:
        """广度表：index = 交易日，columns = hits / valid / filtered / insufficient / ratio。

        `ratio` 的分母 = **有效样本**（valid），不是全市场只数 —— 见本模块头「口径铁律」。
        """
        if self.counters is None or self.dates is None:
            return pd.DataFrame()
        frame = pd.DataFrame({
            'hits': self.counters[:, _C_HIT],
            'valid': self.counters[:, _C_MISS] + self.counters[:, _C_HIT],
            'filtered': self.counters[:, _C_FILTERED],
            'insufficient': self.counters[:, _C_INSUFFICIENT],
        }, index=self.dates)
        frame['ratio'] = np.where(frame['valid'] > 0, frame['hits'] / frame['valid'], np.nan)
        if start is not None:
            frame = frame[frame.index >= pd.Timestamp(start)]
        return frame


# ==========================================
# 6) 扫描主入口
# ==========================================
def scan(groups: dict, formula: str, params: dict = None, thresholds: ScanThresholds = None,
         asof=None, names: dict = None, signal_name: str = None, snapshot_columns=(),
         breadth: bool = True, keep_matrix: bool = False,
         progress=None, should_stop=None, chunk: int = DEFAULT_CHUNK,
         missing=None) -> CrossSectionResult:
    """跑一次扫描：**一个引擎，两种视图**（§7-B1/B2 C 节）。

    :param groups: `{标的: 日线 df}`（`read_daily` 的产出）
    :param formula: 筛选条件（**最后一条变量语句**就是判定变量；也可用 `signal_name` 指定）
    :param names: `{标的: 名称}`，供"剔除 ST/退市"用；**不传则该项不生效并给出 warning**（不静默）
    :param asof: 横截面基准日（None ⇒ 全体最新交易日；轴外的日子**就近落位**并出声）
    :param missing: 请求了但**本地没有日线文件**的标的名单（v6.42）—— 绝不静默丢弃：
        每一天都记「数据不足」并进 `counts.total` 与 warnings（用户实测：名单 429 只
        却只扫出 27 只，界面上完全看不出为什么 —— 这就是静默丢标的的罪）
    :param breadth: 是否累计逐日家数（M3）；`keep_matrix` 也会点亮它
    :param progress: `f(done, total, note)` —— **每 `chunk` 只**报一次（供后台线程发进度信号）
    :param should_stop: `f() -> bool` —— **块边界**轮询；为真则抛 `ScanCancelled`
    :returns: `CrossSectionResult`

    公式**编译**失败会直接抛 `FormulaProgramError`（用户笔误，立刻报）；
    单个标的**求值**失败只把该标的记成「数据不足」并在 `warnings` 里出声（数据问题，不废整轮）。
    """
    t0 = time.perf_counter()
    th = thresholds or ScanThresholds()
    names = names or {}
    chunk = max(1, int(chunk or 1))
    warnings: list[str] = []

    program = parse_program(formula)
    declared = program.output_names
    if not declared:
        raise FormulaProgramError('筛选条件里没有可判定的变量：请写成「变量名 := 表达式」。')
    want = str(signal_name or declared[-1]).strip().upper()
    sig_key = next((name for name in declared if name.upper() == want), None)
    if sig_key is None:
        raise FormulaProgramError(
            f"筛选条件里没有变量 '{signal_name}'（现有：{'、'.join(declared)}）。")
    if program.unsupported:
        warnings.append('本期不渲染的绘图函数已忽略：' + '、'.join(program.unsupported))
    if th.exclude_st and not names:
        warnings.append('未提供花名册名称，「剔除 ST / 退市」本轮**未生效**（不静默跳过，请先同步花名册）')

    prepared: dict[str, pd.DataFrame] = {}
    for sym, frame in (groups or {}).items():
        clean = prepare_frame(frame)
        if not clean.empty:
            prepared[str(sym)] = clean
    # 本地没文件的标的（v6.42）：不静默丢弃 —— 每一天都记「数据不足」，
    # 并进总数与 warnings（矩阵里没有它们的行 ⇒ 广度/切片时由 missing_files 兼容层补上）
    missing_syms = [str(s) for s in (missing or []) if str(s) not in prepared]
    if not prepared:
        # ★ 整份名单都没有本地文件时也不能回"空结果"（v6.42 用户实测：扫描返回全空白，
        #   什么解释都没有）—— 逐只记「数据不足」+ 出声，让界面永远有东西可看。
        no_file = {s: INSUFFICIENT for s in missing_syms}
        det = {s: '本地没有日线文件（未下载）—— 用页面的下载入口可一次补齐'
                  for s in missing_syms}
        w = list(warnings)
        if missing_syms:
            w.append(f'{len(missing_syms)} 只标的本地没有日线文件（已记「数据不足」，'
                     f'可先补齐本地数据后再扫）')
        else:
            w.append('没有任何可用标的（读数为空）')
        return CrossSectionResult(
            formula=formula, signal_name=sig_key, thresholds=th,
            status=no_file, detail=det,
            counts=tally_status(no_file, total=len(missing_syms)),
            missing_files=missing_syms, warnings=w,
            elapsed_ms=(time.perf_counter() - t0) * 1000)

    # ---- 基准日 ----
    if asof is None:
        asof = max(frame['date'].iloc[-1] for frame in prepared.values())
    asof = pd.Timestamp(asof)

    # ---- 交易日轴（所有标的日期的并集）----
    need_axis = breadth or keep_matrix
    axis_np = None
    dates = None
    counters = None
    n_axis = 0
    if need_axis:
        dates = pd.DatetimeIndex(np.unique(np.concatenate(
            [frame['date'].to_numpy() for frame in prepared.values()]))).sort_values()
        axis_np = dates.to_numpy()
        n_axis = len(dates)
        counters = np.zeros((n_axis, 4), dtype=np.int64)

        # ---- 基准日**就近落位**（v6.42）：用户选到周末/节假日/本地没有数据的一天，
        #      不该让整轮扫描"全市场数据不足"地空跑 —— 用最近的交易日并**出声**
        #      （warnings 已有 UI 出口）。轴上的日子（含 asof=None 取的最新日）原样不动。
        idx = int(dates.searchsorted(asof))
        if idx >= len(dates) or dates[idx] != asof:
            cand = [c for c in (idx - 1, idx) if 0 <= c < len(dates)]
            near = min(cand, key=lambda c: abs((dates[c] - asof).days))   # 平手取前一日
            warnings.append(f'基准日 {asof.date()} 不在交易日轴上，已就近落到 '
                            f'{dates[near].date()}（周末/节假日/本地无数据）')
            asof = dates[near]

    symbols = sorted(prepared)
    total = len(symbols)
    status_matrix = np.zeros((len(symbols), n_axis), dtype=np.uint8) if keep_matrix else None
    status: dict[str, str] = {}
    detail: dict[str, str] = {}
    snapshot: dict[str, dict] = {}
    failed: list[str] = []

    for k, sym in enumerate(symbols):
        # 【取消】只在**块边界**轮询（每只都查一次是没必要的开销）
        if should_stop is not None and k % chunk == 0 and should_stop():
            raise ScanCancelled(f'已取消（已算 {k}/{total} 只）')
        frame = prepared[sym]
        dates_np = frame['date'].to_numpy()
        is_st = th.exclude_st and bool(names) and _is_st(names.get(sym, ''))
        data_ok, passes, hard, note = _row_masks(frame, th, is_st=is_st)

        # ---- 公式求值（编译已通过；这里只可能因"这只票的数据"失败）----
        sig = None
        if hard is None:
            try:
                values = execute_programs([program], frame, params or {})[sig_key]
                sig = _as_signal(values)
                if len(sig) != len(frame):
                    raise FormulaProgramError(f'信号长度 {len(sig)} 与行情长度 {len(frame)} 不一致')
            except FormulaProgramError as e:
                hard = R_FORMULA
                note = R_LABELS[R_FORMULA]
                sig = None
                failed.append(f'{sym}: {e}')
                data_ok = np.zeros(len(frame), dtype=bool)
                passes = np.zeros(len(frame), dtype=bool)

        # ---- 逐行状态码（**唯一的判定处**：M2/M3 都从它来，不会两处口径打架）----
        row = np.full(len(frame), _C_INSUFFICIENT, dtype=np.uint8)
        eligible = data_ok & passes
        row[data_ok & ~passes] = _C_FILTERED
        if sig is not None:
            row[eligible & sig] = _C_HIT
            row[eligible & ~sig] = _C_MISS

        # ---- 逐日累计：一次 bincount 收四个状态（不写逐行 Python 循环）----
        if need_axis:
            pos = np.searchsorted(axis_np, dates_np)
            counters += np.bincount(pos * 4 + row, minlength=n_axis * 4).reshape(n_axis, 4)
            if status_matrix is not None:
                status_matrix[k, pos] = row

        # ---- M2：基准日那一行的三态 ----
        i = int(np.searchsorted(dates_np, np.datetime64(asof), side='right')) - 1
        has_row = i >= 0 and pd.Timestamp(dates_np[i]) == asof
        if not has_row:
            status[sym], detail[sym] = INSUFFICIENT, R_LABELS[R_NO_ROW]
        elif is_st:
            status[sym], detail[sym] = FILTERED, 'ST / 退市'
        elif hard is not None:
            status[sym], detail[sym] = INSUFFICIENT, note or R_LABELS[hard]
        elif not data_ok[i]:
            status[sym], detail[sym] = INSUFFICIENT, _insufficient_reason(frame, th, i)
        elif not passes[i]:
            status[sym], detail[sym] = FILTERED, filter_detail(frame, th, i)
        else:
            status[sym] = HIT if bool(sig[i]) else MISS
            detail[sym] = ''

        if has_row and snapshot_columns:
            record = {}
            for col in snapshot_columns:
                value = frame[col].iloc[i] if col in frame.columns else None
                record[col] = None if value is None or pd.isna(value) else float(value)
            record.update(_derived_metrics(frame, i))   # ★P2 派生涨幅/市值（仅 M2 取快照时算）
            snapshot[sym] = record

        # 【进度】每 chunk 只报一次 + 收尾必报（否则进度条永远差最后一格）
        if progress is not None and (k % chunk == chunk - 1 or k == total - 1):
            progress(k + 1, total, sym)

    if failed:
        warnings.append(f'{len(failed)} 只标的求值失败（已记「数据不足」）：'
                        + '；'.join(failed[:3]) + ('…' if len(failed) > 3 else ''))
    for sym in missing_syms:
        status[sym] = INSUFFICIENT
        detail[sym] = '本地没有日线文件（未下载）—— 用页面的下载入口可一次补齐'
    if missing_syms:
        warnings.append(f'{len(missing_syms)} 只标的本地没有日线文件（已记「数据不足」，'
                        f'有效样本只来自有文件的 {total} 只；可先补齐本地数据后再扫）')

    counts = tally_status(status, total=total + len(missing_syms))
    return CrossSectionResult(
        asof=asof, formula=formula, signal_name=sig_key, thresholds=th,
        status=status, detail=detail, snapshot=snapshot, counts=counts,
        dates=dates, counters=counters, symbols=symbols,
        missing_files=missing_syms,
        status_matrix=status_matrix,
        warnings=warnings, elapsed_ms=(time.perf_counter() - t0) * 1000,
    )


def scan_lake(lake_dir: str, formula: str, symbols=None, params: dict = None,
              thresholds: ScanThresholds = None, asof=None, names: dict = None,
              signal_name: str = None, snapshot_columns=(), progress=None,
              should_stop=None, chunk: int = DEFAULT_CHUNK, **kwargs) -> CrossSectionResult:
    """`read_daily` + `scan` 的一站式封装（供 Worker / 冒烟用）。

    ⚠ `symbols=None` 会把分区里**所有**标的算进来（含期货、含中文列的那些）
      —— 要"全 A 股"就传花名册给的代码列表。

    【进度分两段】先报一次 `(0, 0, '读取日线分区')`（**此时还不知道总数** —— 分区里有多少只
      要扫完才知道），读数完再进"逐标的计算"段（那一段的 `total` 才是真总数）。
      为什么不给读数段细粒度进度：`symbols=None` 走的是一次 `dataset` 扫（P1b 实测 0.46 ms/只），
      **拆碎它只会更慢**（P1a 实测逐个读慢约 4×）。
    """
    th = thresholds or ScanThresholds()
    notify = progress or _noop_progress
    notify(0, 0, '读取日线分区')
    columns = columns_for(th, snapshot_columns)
    groups = read_daily(lake_dir, symbols=symbols, columns=columns)
    if should_stop is not None and should_stop():
        raise ScanCancelled('已取消（读数阶段）')
    # 按文件读时，本地没文件的标的会被 `read_daily` 静默跳过 ——
    # 这里把差集算出来交给 `scan()` 记「数据不足」（v6.42：绝不静默丢标的）
    missing = ([str(s) for s in symbols if str(s) not in groups]
               if symbols is not None else [])
    return scan(groups, formula, params=params, thresholds=th, asof=asof, names=names,
                signal_name=signal_name, snapshot_columns=snapshot_columns,
                missing=missing,
                progress=progress, should_stop=should_stop, chunk=chunk, **kwargs)
