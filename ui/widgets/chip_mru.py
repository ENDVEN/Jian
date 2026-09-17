# ui/widgets/chip_mru.py
"""工具行 chips 的「最近使用优先」解析（v6.21 · §7-B6 STEP 3c）—— **纯函数、零 Qt、零状态**。

【为什么独立成文件】规则本身（已启用 ∪ 最近前 N / 灰态留位 / 溢出裁剪）跟 Qt 无关；
放在页面里就只能"造一个主窗口"才能验——抽出来后有 20 余项纯函数断言守着（§10-12）。

【规则（§7-B6-D，用户 2026-09-16 拍板）】
  1. 显示集合 = **已启用项 ∪ 最近使用前 N**，按"最近使用倒序"排；
  2. **已启用的项一定看得见** —— 否则会出现"我开了 BOLL，工具行却没有、不知道它开着"；
  3. **取消勾选不移除**（变灰留在原位），直到被挤出前 N —— 否则关掉后就没法从工具行点回来；
  4. 溢出用 `＋ 更多` 菜单收纳，那个菜单是**完整候选池**的入口（配置不能完全不可见）。
"""
from __future__ import annotations

# 候选池：主图 = 均线 / 布林带 / 自定义公式叠层；副图 = 量 / MACD / 公式副图 1–3
MAIN_POOL = ("ma", "boll", "formula")
SUB_POOL = ("volume", "macd", "sub1", "sub2", "sub3")
CHIP_POOLS = {"main": MAIN_POOL, "sub": SUB_POOL}

# 工具行上最多显示几个（溢出进"＋ 更多"）
CHIP_LIMIT = 3
# "最近用过"的历史长度：**必须比可见数长**，否则取消勾选的项会立刻被挤出、没机会留位变灰
HISTORY_LIMIT = 6

CHIP_LABELS = {
    "ma": "MA", "boll": "BOLL", "formula": "公式",
    "volume": "量", "macd": "MACD",
    "sub1": "公式副图 1", "sub2": "公式副图 2", "sub3": "公式副图 3",
}


def chip_kind(key: str) -> str:
    """`key` 属于哪个池（未知返回空串）。"""
    key = str(key or "")
    for kind, pool in CHIP_POOLS.items():
        if key in pool:
            return kind
    return ""


def chip_label(key: str) -> str:
    return CHIP_LABELS.get(str(key or ""), str(key or ""))


def normalize_recent(values, *, pool=None, history: int = HISTORY_LIMIT) -> list[str]:
    """清洗历史：去重 / 丢掉池外的键 / 截断长度（坏偏好不许污染界面）。"""
    allowed = tuple(pool) if pool else tuple(key for keys in CHIP_POOLS.values() for key in keys)
    out: list[str] = []
    for raw in (values or []):
        key = str(raw or "")
        if key in allowed and key not in out:
            out.append(key)
    return out[:max(0, int(history))]


def push_recent(recent, key: str, *, pool=None, history: int = HISTORY_LIMIT) -> list[str]:
    """把 `key` 推到队首（"最近使用"= 最近**启用**过一次）。

    注意：**取消勾选不会调用它** —— 关闭的项要留在原位变灰（规则 3）。

    ⚠ `pool` 在 v6.24（§7-B8 R13）变成**必须传**的东西：候选池不再是一张静态表
    （配方库加一条就有新 key），不传的话新键会被 `normalize_recent` 当成池外键**丢掉**
    —— 表现是"配方用过了却不进最近使用"，而且**不报错**。
    """
    key = str(key or "")
    if not key:
        return normalize_recent(recent, pool=pool, history=history)
    rest = [k for k in normalize_recent(recent, pool=pool, history=history + 1) if k != key]
    return [key] + rest[:max(0, int(history) - 1)]


def resolve_chips(recent, enabled, *, limit: int = CHIP_LIMIT, pool=None) -> list[str]:
    """算出工具行上**该显示哪些 chip、按什么顺序**。

    :param recent:  最近使用历史（队首最新）
    :param enabled: 当前**已启用**的键（顺序无所谓；内部按最近序排）
    :param limit:   最多显示几个
    :param pool:    候选池（给定时池外的键一律不显示 —— 例如"公式副图 2"在公式里根本不存在时）

    顺序 = 最近使用倒序；**已启用项优先占位**，关闭的灰态项用剩余空位补上。
    """
    allowed = tuple(pool) if pool else None
    limit = max(0, int(limit))
    # ⚠ 历史必须**用它自己那个池**来清洗（v6.24）：默认池是静态表，会把动态 key
    #   （配方）静默丢掉 ⇒ 表现是"配方关掉后不在工具行留灰位"，违反 §7-B6-D 规则 3
    history = normalize_recent(recent, pool=pool)
    enabled_set = {str(k) for k in (enabled or []) if str(k)}

    def _allowed(key: str) -> bool:
        return allowed is None or key in allowed

    ordered: list[str] = []
    for key in history:
        if _allowed(key) and key not in ordered:
            ordered.append(key)
    for key in sorted(enabled_set):          # 已启用但不在历史里的（理论上不该有）兜底
        if _allowed(key) and key not in ordered:
            ordered.append(key)

    on = [key for key in ordered if key in enabled_set]
    off = [key for key in ordered if key not in enabled_set]
    return (on + off)[:limit]


def hidden_keys(recent, enabled, *, limit: int = CHIP_LIMIT, pool=None) -> list[str]:
    """被挤进 `＋ 更多` 菜单的**非空**集合（= 池内、但没显示在工具行上的键）。"""
    shown = set(resolve_chips(recent, enabled, limit=limit, pool=pool))
    allowed = tuple(pool) if pool else tuple(key for keys in CHIP_POOLS.values() for key in keys)
    return [key for key in allowed if key not in shown]
