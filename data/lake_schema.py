# data/lake_schema.py
"""数据湖**列合约**（★1.78 · §9.1 收口：让"湖里有哪些列算数"由**一处**说了算）。

【为什么要它】§9.1 的根因不是"多了几个杂列"，而是**隐性依赖**：
  `turnover` / `outstanding_share` 被下游当"一定有"，可实际上**只有新浪源给、东财兜底源不给**，
  而代码里从没显式提过它们 ⇒ 任何一次列裁剪都会让「换手率 / 流通市值过滤」**静默失效**
  （"静默"是本项目最忌讳的一类事故）。
  ⇒ 本合约把每个分区的列分三类，**下游一律按类判**：
    · 缺 `required`  ⇒ 这只标的记三态「**数据不足**」（任何口径都别用它）；
    · 缺 `optional`  ⇒ 用它的那一项记「**数据不足**」（**绝不当 0** —— 那会误杀一片）；
    · `forbidden`    ⇒ **永不进湖**（新落盘必须裁掉；存量 parquet 不动，要瘦身走「重新全量下载」）。

【与落盘白名单的关系】`data/akshare_feed.py: DAILY_KEEP_COLUMNS` 是"**落盘时裁哪些列**"的实现；
  本文件是"**哪些列算数**"的声明。两者必须**交叉一致**（`smoke_chart` 有断言钉住）——
  否则"声明说支持、落盘却裁掉"就是下一个静默事故。

【纪律】要新订阅一列 ⇒ **先在本文件登记**（并写清"兜底源给不给"），再动白名单与读取方；
  只读某一列前先问 `split_columns(...)`，别写 `if col in df.columns` 然后各处理各的（§11.5-57 同族）。


⚠ **声明型 · 待接线（★1.84）**：本模块目前**没有任何生产代码读取**（只有测试与注释引用）；它把"隐性依赖"变成了"有名字的隐性依赖"，但**不构成可执行拦截**。真接 = 把 M2/M3 的判定改走 `split_columns()`（独立一轮）。"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = ['ZoneSchema', 'SCHEMA', 'DAILY', 'KNOWN_UNSUPPORTED', 'schema_for',
           'split_columns']


@dataclass(frozen=True)
class ZoneSchema:
    """一个分区的列合约（`zone` 名与 data 层的分区名同源）。"""

    zone: str
    required: tuple          # 缺 ⇒ 该标的三态「数据不足」
    optional: tuple = ()     # 缺 ⇒ 用它的那一项记「数据不足」（绝不当 0）
    forbidden: tuple = ()    # 永不进湖（新落盘裁掉；存量不动）


DAILY = ZoneSchema(
    zone='kline_daily',
    required=('date', 'open', 'high', 'low', 'close', 'volume', 'symbol'),
    # ★把"隐性依赖"显式登记（§9.1 第 2 条）：这两列**只有新浪源给**、东财兜底源没有
    #   ⇒ 缺了就不算换手率 / 流通市值（记「数据不足」），**绝不当 0**。
    optional=('amount', 'turnover', 'outstanding_share'),
)

SCHEMA = {
    'kline_daily': DAILY,
    # 指数日线：无 `amount`（实测 29 个文件都没有）⇒ 显式登记为 optional，不许当 required
    'index_daily': ZoneSchema('index_daily', DAILY.required, ('amount',)),
    # 分钟线：实测"只有 6 列、无 symbol" ⇒ 这两样在合约里都是 optional（require 就会砍坏数据）
    'kline_min': ZoneSchema('kline_min', ('date', 'open', 'high', 'low', 'close', 'volume'),
                            ('amount', 'symbol')),
    'kline_daily_raw': DAILY,
}

# 已知**不支持**的列（历史透传进来的杂列）：登记在此 = "我们**看过**它们、明确不认"（§9.1 末条）。
#   ⚠ **不**把东财中文列映射成 amount / turnover：单位分别是百分数 / 小数，
#     直接映射就是 §9-V 的 100× 静默事故 ⇒ 宁可登记为"不支持"，让用它的项记「数据不足」。
KNOWN_UNSUPPORTED = ('持仓量', '动态结算价', '股票代码', '成交额', '振幅', '涨跌幅',
                     '涨跌额', '换手率')


def schema_for(zone: str) -> ZoneSchema:
    """按分区取合约（未知分区 ⇒ 日线合约，读盘只多不少、不撒谎）。"""
    return SCHEMA.get(str(zone), DAILY)


def split_columns(df, zone: str) -> dict:
    """按合约把 `df` 的列分成四堆（**下游只该看这个结果**）。

    :return: `{'required_ok', 'missing_required', 'missing_optional', 'extra'}`
      · 缺 `required` ⇒ **这只标的记三态「数据不足」**（别拿半根数据算）；
      · 缺 `optional` ⇒ 用它的那一项记「数据不足」（**绝不当 0**）；
      · `extra` = 合约外的列（历史杂列 / 未来新增未登记列）—— 看到它说明**有人没登记就落盘了**，
        要么补登记、要么加进 `KNOWN_UNSUPPORTED`。
    """
    # ⚠ 不许写 `getattr(df, 'columns', []) or []` —— `df.columns` 是 pandas **Index**，
    #   它的布尔求值会抛 "truth value of an Index is ambiguous"（本轮实测踩到；§11.5-135 同族）。
    cols = set(getattr(df, 'columns', [])) if df is not None else set()
    sch = schema_for(zone)
    return {
        'required_ok': [c for c in sch.required if c in cols],
        'missing_required': [c for c in sch.required if c not in cols],
        'missing_optional': [c for c in sch.optional if c not in cols],
        'extra': sorted(cols - set(sch.required) - set(sch.optional)),
    }
