# ui/widgets/layer_model.py
"""配方库 / 图层的**单一真源**（v6.24 · §7-B8 R13/R5）—— **零 Qt、纯数据 + 纯规则**。

【它取代了什么】**此前"哪些图层开着"的真源 = 左栏图层页里的 5 个 QCheckBox**
（`cb_ma / cb_boll / cb_formula / cb_vol / cb_macd`），外加 `_sub_visible` 这个
"公式副图 N 显示与否"的第二份状态 —— §11.5-11 早就点过名：
**同一件事有第二份状态，改一处必漏一处。**

【新契约（用户 2026-09-17 三轮/四轮拍板，逐条落成规则）】
  1. **真源 = 一份列表**（内置 + 用户配方混排），再也不存在 QCheckBox；
  2. **内置在前、你的在后**（用户原话），内置带 `内置` 标签、**只能开关、不能删改**；
  3. **内置项不改名**（"怕不懂的用户改了改不回来"）—— 连管理模式也不给 ✏/🗑；
  4. **去处只有两类 = 主图 / 副图**，**互不串门**（副图配方只能进副图）；
     副图内部的**格位由顺序决定**，配方**不绑定"第几格"** ⇒ 与"可调顺序"天然不冲突；
  5. **有参数的才有 ⚙**（`成交量` 没有参数 ⇒ **不给假入口**，"有就是有、没有就是没有"）；
  6. 参数**越界一律拒绝**（R16 闸②"检测到格式不对就恢复默认值"的判据就在这里）。

【为什么零 Qt】上面这些是**业务规则**（谁能删、谁能改、去处怎么定、参数合不合法），
塞进 Qt 里就只能"造个主窗口"才验得动；抽出来之后是一串纯函数断言（§10-12）。

【key 的命名纪律（§11.5-19）】内置 key 是 `ma/boll/volume/macd`；
用户配方一律加前缀 `formula:` ⇒ **用户把配方起名叫 "ma" 也不会撞库**
（撞库的后果是"开了一个却亮了另一个"，而且极难查）。
"""
from __future__ import annotations

from data.formula_store import normalize_segments

TARGET_MAIN = "main"
TARGET_SUB = "sub"
TARGET_LABELS = {TARGET_MAIN: "主图", TARGET_SUB: "副图"}
# 顺序即"配方库里的分区顺序"：主图在前（叠在 K 线上，是更常看的那类）
TARGET_ORDER = (TARGET_MAIN, TARGET_SUB)

FORMULA_PREFIX = "formula:"

# 【草稿槽】"当前正在编辑、还没存成配方"的那一份函数。
#   为什么它必须存在：老的「自定义公式」总开关（`cb_formula`）管的就是它 ——
#   用户贴进来的函数**不必先存盘**就该能显示。存盘后由保存的那条配方接手。
DRAFT_KEY = "draft"
DRAFT_NAME = "当前编辑的公式"

# 内置指标的参数规格：`(参数名, 默认值, 下界, 上界, 人话提示)`。
# ⚠ 上下界**每条参数各自不同**（P8：统一提示"1~250"对"倍数"是误导）；
#   人话提示会进 tooltip 与越界回执（§10-4：说出原因，不只说"不合法"）。
BUILTIN_ITEMS = (
    {"key": "ma", "name": "均线 MA", "target": TARGET_MAIN, "builtin": True,
     "params": (("周期1", 5, 1, 250, "短均线，通常 5~20"),
                ("周期2", 20, 1, 250, "中均线，通常 20~60"),
                ("周期3", 60, 1, 250, "长均线，通常 60~250")),
     # 引擎签名：`TAEngine.add_ma(df, windows=(5,20,60))` ⇒ 三个参数打进一个元组
     "engine": {"windows": ("周期1", "周期2", "周期3")}},
    {"key": "boll", "name": "布林带 BOLL", "target": TARGET_MAIN, "builtin": True,
     "params": (("周期", 20, 2, 250, "常用 20"),
                ("倍数", 2.0, 0.5, 10.0, "标准差倍数，常用 2")),
     "engine": {"window": "周期", "num_std": "倍数"}},
    {"key": "volume", "name": "成交量", "target": TARGET_SUB, "builtin": True,
     "params": (),                      # ★ 没有参数 ⇒ **不给 ⚙**（不做假入口）
     "engine": {}},
    {"key": "macd", "name": "MACD", "target": TARGET_SUB, "builtin": True,
     "params": (("快线", 12, 1, 250, "常用 12"),
                ("慢线", 26, 1, 250, "常用 26"),
                ("信号", 9, 1, 250, "常用 9")),
     "engine": {"fast": "快线", "slow": "慢线", "signal": "信号"}},
)
BUILTIN_KEYS = tuple(item["key"] for item in BUILTIN_ITEMS)
# 默认开哪些：与改造前的初始态**逐一对齐**（量=开；MA/BOLL/MACD=关）
DEFAULT_ENABLED = ("volume",)


def recipe_target(formula) -> str:
    """配方 → 去处（**只有两类**）。判据 = **所有函数段都指向 main ⇒ 主图；否则副图**。

    为什么这样判（而不是"近似归组"）：
      · 新存的配方在保存时已被**强制统一去处**（R6 四轮拍板："一条公式只能去一个地方"）；
      · 历史存档万一是混的，按"**有副图段就是副图**"归类 —— 副图是**更受约束**的那个去处
        （主图叠 K 线，多一条线通常无害；副图会**多出一个窗格**，那是更明显的副作用）。
    空配方（没有有效段）⇒ 按主图（调用方不该把空配方放进列表，见 `make_formula` 的守卫）。
    """
    segments = normalize_segments((formula or {}).get("segments"))
    targets = {seg["target"] for seg in segments}
    return TARGET_MAIN if targets <= {TARGET_MAIN} else TARGET_SUB


def formula_key(formula) -> str:
    """用户配方在模型里的 key（带前缀，**绝不与内置撞库**）。"""
    return f"{FORMULA_PREFIX}{(formula or {}).get('id') or ''}"


def _coerce(value, spec):
    """按参数规格把输入转成"合法值"；不合法返回 None（调用方据此拒绝或回默认）。"""
    _name, _default, lo, hi, _hint = spec
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):   # NaN / inf
        return None
    if not (lo <= number <= hi):
        return None
    # 整数参数保持整数（`周期 5` 不该显示成 `5.0`）
    if float(lo).is_integer() and float(hi).is_integer() and float(_default).is_integer():
        return int(round(number))
    return float(number)


class LayerModel:
    """图层/配方的单一真源：**顺序 + 开关 + 参数**都在这里，别处一律只读它。

    :param formulas: 用户配方（`formula_store` 的条目；本类只读它、不落库）
    :param enabled:  已启用的 key 列表（来自上次偏好；坏值会被清洗掉）
    :param params:   `{内置 key: {参数名: 值}}`（来自上次偏好；坏值回落默认）
    """

    def __init__(self, formulas=None, enabled=None, params=None, draft=None):
        self.builtin_items = [dict(item) for item in BUILTIN_ITEMS]
        # ---- 组装条目列表：**内置在前、你的在后**（用户原话的顺序） ----
        self.items: list[dict] = list(self.builtin_items)
        # ⚠ 索引**必须先有**（哪怕是空的）：`set_draft` 一进来就要查它
        self._by_key: dict = {}
        self.set_draft(draft)
        for formula in (formulas or []):
            name = str((formula or {}).get("name") or "").strip()
            if not name:
                continue
            self.items.append({
                "key": formula_key(formula), "name": name,
                "target": recipe_target(formula), "builtin": False,
                "params": (), "engine": {},
                "formula_id": str((formula or {}).get("id") or ""),
            })
        self._reindex()

        # ---- 参数：先铺默认，再把合法偏好盖上去 ----
        self._params: dict = {}
        for item in self.builtin_items:
            self._params[item["key"]] = {spec[0]: spec[1] for spec in item["params"]}
        for key, values in (params or {}).items():
            for name, value in (values or {}).items():
                self.set_param(key, name, value)

        # ---- 开关：清洗（未知 key 一律丢掉，绝不留下幽灵项）----
        self._enabled: set = set()
        for key in (enabled if enabled is not None else DEFAULT_ENABLED):
            key = str(key or "")
            if key in self._by_key:
                self._enabled.add(key)

    # ==========================================
    # 草稿槽（当前编辑、未存盘的那份函数）
    # ==========================================
    def set_draft(self, segments) -> str:
        """登记/替换"当前编辑的公式"；传空 ⇒ 撤掉草稿槽。返回它的去处（main / sub / ""）。

        ⚠ 草稿**不落盘、不进配方库** —— 它只是"还没存的那份工作"的挂靠点。
        """
        target = recipe_target({"segments": segments}) if segments else ""
        existing = self._by_key.get(DRAFT_KEY)
        if not target:
            if existing is not None:
                self._drop(existing)
            return ""
        if existing is None:
            # 位置 = **内置之后、已存配方之前**（"你的"里最临时的放最前）
            item = {"key": DRAFT_KEY, "name": DRAFT_NAME, "target": target,
                    "builtin": False, "params": (), "engine": {}, "formula_id": ""}
            self.items.insert(len(self.builtin_items), item)
            self._reindex()
        else:
            existing["target"] = target
        return target

    def has_draft(self) -> bool:
        return DRAFT_KEY in self._by_key

    def _drop(self, item: dict) -> None:
        self.items.remove(item)
        self._reindex()

    def _reindex(self) -> None:
        """`items` 变了就必须重建索引 —— 否则 `item()/has()` 会指向已经不在列表里的幽灵。"""
        self._by_key = {item["key"]: item for item in self.items}

    # ==========================================
    # 查询
    # ==========================================
    def keys(self) -> list[str]:
        return [item["key"] for item in self.items]

    def item(self, key) -> dict:
        return self._by_key.get(str(key or ""), {})

    def has(self, key) -> bool:
        return str(key or "") in self._by_key

    def is_builtin(self, key) -> bool:
        return bool(self.item(key).get("builtin"))

    def target_of(self, key) -> str:
        return str(self.item(key).get("target") or "")

    def label(self, key) -> str:
        """显示名。内置项**用内置名**（不可改名）；用户配方用配方名。"""
        return str(self.item(key).get("name") or "")

    def items_for(self, target) -> list[dict]:
        """某一类的条目（**内置在前、你的在后** —— 列表本身已按这个顺序组装）。"""
        return [item for item in self.items if item["target"] == target]

    def items_by_target(self) -> list[tuple]:
        """`[(target, [条目, ...]), ...]`，按 `TARGET_ORDER`；空类**不返回**（UI 不为空类画分区）。"""
        return [(target, items) for target in TARGET_ORDER
                if (items := self.items_for(target))]

    def pool_for(self, target) -> tuple:
        """该类**当前全部**可选 key —— 这就是 chips 的候选池（**动态**，不再硬编码）。

        ⚠ 它取代了 `chip_mru.CHIP_POOLS` 的静态常量：配方库里加一条，工具行立刻能选到它。
        """
        return tuple(item["key"] for item in self.items_for(target))

    def pool_of_key(self, key) -> str:
        """某 key 属于哪一类（未知返回空串）—— chips 用它判断"该进主图还是附图池"。"""
        return self.target_of(key)

    # ==========================================
    # 开关（**唯一状态**）
    # ==========================================
    def enabled(self, key) -> bool:
        return str(key or "") in self._enabled

    def set_enabled(self, key, value) -> bool:
        """开关某一项。**未知 key 返回 False 且不记忆**（不许出现幽灵项）。"""
        key = str(key or "")
        if key not in self._by_key:
            return False
        if value:
            self._enabled.add(key)
        else:
            self._enabled.discard(key)
        return True

    def toggle(self, key) -> bool:
        """点一下 chips 的行为：开变关、关变开（返回**操作后**的状态；未知 key 返回 False）。"""
        key = str(key or "")
        if key not in self._by_key:
            return False
        return self.set_enabled(key, key not in self._enabled)

    def enabled_keys(self, target=None) -> list[str]:
        """已启用的 key（**按列表顺序**，不是集合顺序 —— 顺序要可预期）。"""
        return [item["key"] for item in self.items
                if item["key"] in self._enabled
                and (target is None or item["target"] == target)]

    def enabled_list(self) -> list[str]:
        return self.enabled_keys()

    # ==========================================
    # 参数（R16 ⚙ 的唯一数据面）
    # ==========================================
    def param_specs(self, key) -> tuple:
        return tuple(self.item(key).get("params") or ())

    def has_params(self, key) -> bool:
        """**有参数才给 ⚙**（`成交量` 没有 ⇒ 不给假入口）。"""
        return bool(self.param_specs(key))

    def params_of(self, key) -> dict:
        return dict(self._params.get(str(key or ""), {}))

    def param_hint(self, key, name) -> str:
        for spec in self.param_specs(key):
            if spec[0] == name:
                return spec[4]
        return ""

    def param_range(self, key, name) -> tuple:
        for spec in self.param_specs(key):
            if spec[0] == name:
                return (spec[2], spec[3])
        return (None, None)

    def set_param(self, key, name, value) -> bool:
        """改一个参数。**越界 / 非数字 / 未知参数一律拒绝**（返回 False，不改动）。

        这就是 R16 闸②的判据来源：调用方拿到 False 就把该参数**恢复成默认值**并告知用户
        （"不放行、也不静默改"）。
        """
        specs = {spec[0]: spec for spec in self.param_specs(key)}
        spec = specs.get(str(name or ""))
        if spec is None:
            return False
        coerced = _coerce(value, spec)
        if coerced is None:
            return False
        self._params.setdefault(str(key), {})[spec[0]] = coerced
        return True

    def reset_params(self, key) -> dict:
        """一键恢复出厂值（R16 闸③）。返回恢复后的参数。"""
        specs = self.param_specs(key)
        if not specs:
            return {}
        self._params[str(key)] = {spec[0]: spec[1] for spec in specs}
        return self.params_of(key)

    def params_snapshot(self) -> dict:
        """给偏好持久化用：`{内置 key: {参数名: 值}}`（用户配方没有参数 ⇒ 不在里面）。"""
        return {key: dict(values) for key, values in self._params.items() if values}

    def engine_options(self) -> dict:
        """`TAEngine.apply(df, keys, **engine_options())` 的 `**options`。

        只对**已启用的内置项**产出（用户配方走公式引擎，与这里无关）。
        参数名 → 引擎形参的映射写在 `BUILTIN_ITEMS[*]["engine"]`，**一处**。
        """
        options: dict = {}
        for key in self.enabled_keys():
            mapping = self.item(key).get("engine") or {}
            if not mapping:
                continue
            values = self.params_of(key)
            kwargs: dict = {}
            for arg, source in mapping.items():
                if isinstance(source, (tuple, list)):
                    kwargs[arg] = tuple(values.get(name) for name in source)
                else:
                    kwargs[arg] = values.get(source)
            options[key] = kwargs
        return options

    def validate_params(self, key) -> tuple:
        """整组参数体检：`(ok, 人话说明)`（R16 的「校验」先过这一关，再拿真数据试算）。"""
        problems = []
        values = self.params_of(key)
        for spec in self.param_specs(key):
            name, _default, lo, hi, hint = spec
            value = values.get(name)
            if _coerce(value, spec) is None:
                problems.append(f"{name}={value} 不在 {lo}~{hi} 之间（{hint}）")
        return (not problems, "；".join(problems))
