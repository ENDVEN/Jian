# ui/widgets/history_kinds.py
"""「🗂 运行历史」的 kind **声明式注册表**（§7-A4 · v1.46 重做）。

【为什么要有它】旧版把 M2/M3 硬塞进 M1 的形状里，`if kind` 分支散在**六处**
（存档构造 / 索引规范化 / 表头 / 单元格取值 / 预览 / 动作可用集）——每改一种 kind 都要
同时改 6 个地方，而且彼此靠"列位置"隐式耦合（第 5 列表头叫"胜率"还是"命中率"取决于
一个字典）。本模块把它收敛成**一行一种 kind**的声明：

    · `columns`     —— 列表列（标题 / 取值 / 对齐 / 是否按正负着色 / 是否吃掉剩余宽度）
    · `facet_label` —— 过滤下拉是"标的"还是"范围"
    · `actions`     —— 这种 kind 允许哪些动作（载入查看 / 复用 / 重跑 / 送行情 / 重点 / 删除）

⇒ 列表层、预览层、动作层一律**查表**，不再认识具体 kind（`grep "if kind"` 应为 0 命中）。

【数据契约】取值函数的入参是 `BacktestArchive._entry_of()` 产出的**规范化索引项**
（M1 与 M2/M3 在那里已经同形）⇒ 本模块不需要知道记录的原始结构。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from data.backtest_archive import KIND_LABELS, KIND_M1, KIND_M2, KIND_M3, SOURCE_LABELS

__all__ = [
    'ColumnSpec', 'KindSpec', 'KIND_SPECS', 'spec_of', 'ACTION_ORDER',
    'ACC_VIEW', 'ACC_REUSE', 'ACC_RERUN', 'ACC_SEND', 'ACC_PIN', 'ACC_DEL',
]

# 动作标识（页面按它连信号；注册表按它决定"这种 kind 给不给这个动作"）
ACC_VIEW = 'view'      # 👁 载入查看（只读回放 —— 只有 M1 有净值/逐笔可回放）
ACC_REUSE = 'reuse'    # ↺ 复用参数
ACC_RERUN = 'rerun'    # ▶ 重跑
ACC_SEND = 'send'      # 📤 送行情页
ACC_PIN = 'pin'        # ☆ 重点
ACC_DEL = 'del'        # 🗑 删除
ACTION_ORDER = (ACC_VIEW, ACC_REUSE, ACC_RERUN, ACC_SEND, ACC_PIN, ACC_DEL)


@dataclass(frozen=True)
class ColumnSpec:
    """一列的声明：**列由定义决定，不由位置决定**。"""
    title: str
    getter: Callable[[dict], str]
    align: str = 'left'          # 'left' | 'center'
    signed: str = ''             # '' | 'win' | 'cum' —— 数值列按正负着色（选中行交给样式表）
    stretch: bool = False        # 吃掉剩余宽度（防横向滚动条；同一 kind 至多一个）
    tip_getter: Callable[[dict], str] = None   # 单元格 tooltip（None ⇒ 不给）


@dataclass(frozen=True)
class KindSpec:
    kind: str
    tab_label: str               # 过滤下拉的条目文字
    facet_label: str             # 过滤轴的标题：标的 / 范围
    search_hint: str
    scan: bool                   # True ⇒ 横截面型（无净值/逐笔）⇒ 预览走"四态占比条"
    columns: tuple
    actions: frozenset


# ==========================================
# 取值小件（纯函数）
# ==========================================
def _pin(e: dict) -> str:
    return '★' if e.get('pinned') else ''


def _pin_tip(e: dict) -> str:
    return '★ 重点：不被自动淘汰' if e.get('pinned') else '标为「★ 重点」'


def _time(e: dict) -> str:
    return str(e.get('created_at') or '')[5:16]      # MM-DD HH:MM


def _time_tip(e: dict) -> str:
    return str(e.get('created_at') or '')


def _source(e: dict) -> str:
    return SOURCE_LABELS.get(e.get('source'), '自动')


def _num(value) -> str:
    return '—' if value is None else str(value)


def _pct_signed(value) -> str:
    if value is None:
        return '—'
    try:
        return f'{float(value) * 100:+.1f}%'
    except (TypeError, ValueError):
        return '—'


def _pct0(value) -> str:
    if value is None:
        return '—'
    try:
        return f'{float(value) * 100:.0f}%'
    except (TypeError, ValueError):
        return '—'


def _span(start, end) -> str:
    start, end = str(start or ''), str(end or '')
    return f'{start[2:]}~{end[2:]}' if start and end else '—'


# ---- M1：单股回测 ----
def _m1_symbol(e: dict) -> str:
    return f"{e.get('name') or ''} {e.get('symbol') or ''}".strip() or '—'


def _m1_strategy(e: dict) -> str:
    return e.get('strategy_name') or '（未保存）'


COLUMNS_M1 = (
    ColumnSpec('★', _pin, 'center', tip_getter=_pin_tip),
    ColumnSpec('时间', _time, 'center', tip_getter=_time_tip),
    ColumnSpec('标的', _m1_symbol, stretch=True),
    ColumnSpec('策略', _m1_strategy, stretch=True),
    ColumnSpec('区间', lambda e: _span(e.get('start_date'), e.get('end_date')), 'center'),
    ColumnSpec('胜率', lambda e: _pct0(e.get('win_rate')), 'center', signed='win'),
    ColumnSpec('累计', lambda e: _pct_signed(e.get('cumulative_return')), 'center', signed='cum'),
    ColumnSpec('笔数', lambda e: _num(e.get('total_trades')), 'center'),
    ColumnSpec('来源', _source, 'center'),
)


# ---- M2/M3：横截面 / 广度（同一个形状，只差"基准日"还是"区间"）----
def _s_scope(e: dict) -> str:
    return e.get('scope_label') or '（未知范围）'


def _s_scope_tip(e: dict) -> str:
    code = str(e.get('scope_code') or '').strip()
    return f'{e.get("scope_label") or "未知范围"}（{code}）' if code else str(e.get('scope_label') or '')


def _s_condition(e: dict) -> str:
    return e.get('condition_label') or '—'


def _scan_columns(day_title: str) -> tuple:
    day_getter = ((lambda e: e.get('day') or '—') if day_title == '基准日'
                  else (lambda e: _span(e.get('range_start'), e.get('day'))))
    return (
        ColumnSpec('★', _pin, 'center', tip_getter=_pin_tip),
        ColumnSpec('时间', _time, 'center', tip_getter=_time_tip),
        ColumnSpec('范围', _s_scope, stretch=True, tip_getter=_s_scope_tip),
        ColumnSpec('条件', _s_condition, tip_getter=lambda e: e.get('condition_label') or ''),
        ColumnSpec(day_title, day_getter, 'center'),
        ColumnSpec('命中率', lambda e: _pct0(e.get('hit_rate')), 'center'),
        ColumnSpec('命中', lambda e: _num(e.get('hit')), 'center'),
        ColumnSpec('数据不足', lambda e: _num(e.get('insufficient')), 'center'),
        ColumnSpec('来源', _source, 'center'),
    )


# M1 六件事齐全；M2/M3 **没有"只读回放净值"语义** ⇒ 不给「载入查看」，
# **也不给「送行情页」**：横截面 / 广度是**统计口径**（一批标的的命中分布），
# 不是"某只个股的行情"，送去行情页看单只 K 线本身没有意义。
# 〔用户 2026-09-25 拍板：撤销 v1.46 早先"既然公式就是完整公式、顺手开放"的做法〕
_ACTIONS_M1 = frozenset(ACTION_ORDER)
_ACTIONS_SCAN = frozenset({ACC_REUSE, ACC_RERUN, ACC_PIN, ACC_DEL})

KIND_SPECS = {
    KIND_M1: KindSpec(KIND_M1, KIND_LABELS[KIND_M1], '标的', '按 标的 / 策略 搜索',
                      False, COLUMNS_M1, _ACTIONS_M1),
    KIND_M2: KindSpec(KIND_M2, KIND_LABELS[KIND_M2], '范围', '按 范围 / 条件 搜索',
                      True, _scan_columns('基准日'), _ACTIONS_SCAN),
    KIND_M3: KindSpec(KIND_M3, KIND_LABELS[KIND_M3], '范围', '按 范围 / 条件 搜索',
                      True, _scan_columns('区间'), _ACTIONS_SCAN),
}


def spec_of(kind) -> KindSpec:
    """取某个 kind 的声明；不认识的一律回落 M1（**不抛异常** —— 坏存档不该拖垮整页）。"""
    return KIND_SPECS.get(str(kind or ''), KIND_SPECS[KIND_M1])
