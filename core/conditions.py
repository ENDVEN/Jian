# core/conditions.py
"""
买卖条件配置 → DSL 表达式（**唯一真源**，§7-B15 SW-3 补）。

【为什么单独成件】"条件配置 dict → DSL 文本"这件事原本只长在 **UI 控件**
（`ui/widgets/condition_gate.ConditionGate.expression()`），只有"用户在界面点回测"
这一条路能用；**任何从存档里读条件再跑回测的地方**（§7-B15 参数研究）都拿不到它 ——
实测事故：参数研究把条件 **dict 直接递给 `BacktestEngine.run`**，而引擎第 333 行
`FormulaEngine.signal(buy_expression, ...)` 期待的是**表达式字符串** ⇒
`tokenize(dict)` 在 `src[i]` 上抛 `KeyError: 0`，**每一组都失败**（12/12 全灭，
页面看起来就是"点了没反应"）。⇒ 把纯计算部分下沉到 core，UI 与 data 两侧共用一份。

【形状兼容（两种都要认，读档方不该自己猜）】
- **新形状**（现在保存的）：`{"logic": "all"|"any"|"atleast", "n": 2, "conditions": [行, ...]}`
- **旧形状**（v1.6x 之前保存的策略）：直接是**单条件行** `{"variable": ..., "rule": ..., "value": ...}`
  —— 与 `data/strategy_store._signature` 认旧档同一口径（"旧档字段缺失一律回落"，§7-B15 方案书 §2）。
- **已是文本**：某些历史存档 / 冒烟直接存的是表达式字符串 ⇒ 原样透传（幂等）。

【红线】本模块**零 Qt、零 IO**：只有字符串与 dict 的纯变换。UI 侧（条件积木控件）
导它做预览；data 侧（存档）与 core 侧（编排/指纹）导它做求值前的归一。
"""
from __future__ import annotations

# 组合逻辑键（与 `ui/widgets/condition_gate` 的 cb_logic 同源；持久化进策略存档）
LOGIC_ALL = "all"              # 全部满足（AND；= 至少 N 个且 N=条件数）
LOGIC_ANY = "any"              # 任一满足（OR）
LOGIC_AT_LEAST = "atleast"     # 至少 N 个满足

_ROW_KEYS = ("variable", "rule", "value")


def build_condition_expression(variable: str, rule: str, value) -> str:
    """单个积木条件行 → DSL 表达式（空串 = 规则不认识 / 数值非法）。

    ⚠ 这是**全 app 唯一**的"规则键 → 算子"映射（原来在 `ui/widgets/condition_gate.py`）。
    """
    try:
        value_txt = f"{float(value):.6g}"
    except (TypeError, ValueError):
        return ""
    name = str(variable or "").strip()
    if not name:
        return ""
    return {
        "eq": f"{name} = {value_txt}",
        "gt": f"{name} > {value_txt}",
        "lt": f"{name} < {value_txt}",
        "ge": f"{name} >= {value_txt}",
        "le": f"{name} <= {value_txt}",
        "ne": f"{name} <> {value_txt}",
        "rise": f"CROSS({name}, 0.5)",
        "fall": f"CROSS(0.5, {name})",
    }.get(str(rule or ""), "")


def row_expression(row) -> str:
    """一行条件（dict）→ DSL；变量缺失/规则不认识 ⇒ 空串（调用方据此判"条件不足"）。"""
    if not isinstance(row, dict):
        return ""
    return build_condition_expression(row.get("variable"), row.get("rule"), row.get("value"))


def gate_rows(cfg) -> list[dict]:
    """把任一形状的条件配置**摊平成条件行列表**（旧单条件形状 → 单行）。

    用途：读档方要"有几行条件 / 变量名是什么"时不必各写一套形状判断
    （`_signature` 认旧档、页面回显、快照内联都要同一口径）。
    """
    if isinstance(cfg, str):
        text = cfg.strip()
        return [{"variable": text, "rule": "expr", "value": None}] if text else []
    if not isinstance(cfg, dict):
        return []
    if "conditions" in cfg:
        return [dict(r) for r in (cfg.get("conditions") or []) if isinstance(r, dict)]
    # 旧形状：整块就是一行
    return [dict(cfg)] if any(k in cfg for k in _ROW_KEYS) else []


def gate_expression(cfg) -> str:
    """条件配置 → DSL 表达式（**求值前唯一入口**）。空串 = 条件不足（调用方必须诚实拒绝）。

    组合口径与界面控件逐字一致（`ConditionGate.expression()` 搬到 core，UI 已改为调用本函数）：
    单行 → 该行；AT_LEAST(N>1) → `COUNT_TRUE(...) >= N`；ANY → `(a) OR (b)`；其余 → `(a) AND (b)`。
    """
    if isinstance(cfg, str):
        return cfg.strip()                      # 已是表达式（历史存档 / 冒烟直喂）
    if not isinstance(cfg, dict):
        return ""
    if "conditions" in cfg:
        exprs = [e for e in (row_expression(r) for r in (cfg.get("conditions") or [])) if e]
        if not exprs:
            return ""
        logic = str(cfg.get("logic") or LOGIC_ALL)
        try:
            n = max(1, int(cfg.get("n", 1)))
        except (TypeError, ValueError):
            n = 1
        if logic == LOGIC_AT_LEAST and len(exprs) > 1:
            return f"COUNT_TRUE({', '.join(exprs)}) >= {min(n, len(exprs))}"
        if len(exprs) == 1:
            return exprs[0]
        if logic == LOGIC_ANY:
            return "(" + ") OR (".join(exprs) + ")"
        return "(" + ") AND (".join(exprs) + ")"
    return row_expression(cfg)                  # 旧形状：单条件行
