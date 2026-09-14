# data/formula_store.py
"""公式配方库（函数资产化）—— §7-B3 P7。

【为什么需要】
  行情页 / 回测页的公式此前**只活在内存里**：切个页面、重启一次就没了，用户每次都得
  重新粘贴一遍（P7 要解决的第一件事）。这里把「函数段 + 参数 + 每段的目标窗格」存成
  一个**有名字的配方**，可反复载入、可跨页面互送。

【与 strategy_store 同源，但不合并】
  同样的 JSON 原子写（tmp + `os.replace`）、同样的 `~/.jian_data/` 物理隔离、
  同样的 `upsert` 语义（按 `name` 命中即更新）。
  但**配方 ≠ 策略**：配方只有"公式本身"；策略 = 配方（公式）+ 买卖条件 + 风控 +
  区间 + 指数门控，存在 `strategy_store.py`。
  把配方送进回测页后，用户再补条件/风控 —— 这正是"资产化 + 互送"的分工（§10-3）。

【零 Qt 依赖】两个页面 + 配方库对话框共用 `get_formula_store()` 这**一个**内存实例 ——
  各自 new 一个实例会互相覆盖（后保存的把别人刚加的条目冲掉）。
"""
from __future__ import annotations

import json
import os
import time
import uuid

from config import settings

FORMULA_FILE = "formula_library.json"
SCHEMA_VERSION = 1

# 目标窗格取值（唯一事实来源 = 本处；UI 的中文标签在
# `ui/dialogs/formula_overlay.py` 的 TARGET_CHOICES，二者由冒烟断言强制一致）
VALID_TARGETS = ("main", "sub1", "sub2", "sub3")
DEFAULT_TARGET = "main"

SOURCE_MARKET = "market"
SOURCE_BACKTEST = "backtest"
SOURCE_LABELS = {SOURCE_MARKET: "行情页", SOURCE_BACKTEST: "回测页"}


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def new_id() -> str:
    return uuid.uuid4().hex[:8]


# ==========================================
# 纯函数：归一化（入参按"最脏的可能"防御，§11.5-18）
# ==========================================
def normalize_segments(segments) -> list[dict]:
    """把各种形态的"函数段"统一成 `[{"text": str, "target": str}, ...]`。

    容忍三种输入（三个调用方各给一种）：
      · 行情页：`[(text, target), ...]`  —— 元组
      · 回测页：`[text, ...]`            —— 只有文本（回测无窗格概念）
      · 存储：`[{"text":..., "target":...}, ...]`
    空段被丢弃；非法 target 回落到 `main`（**绝不因为一个坏 target 丢掉整段函数**）。
    """
    result: list[dict] = []
    for entry in (segments if segments is not None else []):
        text, target = "", DEFAULT_TARGET
        if isinstance(entry, dict):
            text = entry.get("text", "")
            target = str(entry.get("target") or DEFAULT_TARGET)
        elif isinstance(entry, (tuple, list)):
            if len(entry) >= 2:
                text, target = entry[0], str(entry[1] or DEFAULT_TARGET)
            elif len(entry) == 1:
                text = entry[0]
        else:
            text = entry
        text = str(text or "").strip()
        if not text:
            continue
        result.append({"text": text,
                       "target": target if target in VALID_TARGETS else DEFAULT_TARGET})
    return result


def segments_as_tuples(formula: dict) -> list[tuple]:
    """给行情页用：`[(text, target), ...]`"""
    return [(seg["text"], seg["target"])
            for seg in normalize_segments((formula or {}).get("segments"))]


def segments_as_texts(formula: dict) -> list[str]:
    """给回测页用：`[text, ...]`（回测不区分窗格）"""
    return [seg["text"] for seg in normalize_segments((formula or {}).get("segments"))]


def make_formula(name: str, segments, *, params_text: str = "",
                 source: str = SOURCE_MARKET, formula_id: str = "") -> dict:
    """构造一条**已归一化**的配方（全 app 唯一构造入口）。

    :raises ValueError: 名称为空 / 没有任何有效函数段 —— 调用方据此提示用户，
                        绝不存一条"空配方"（载入它等于什么都没发生，纯属添乱）。
    """
    name = str(name or "").strip()
    if not name:
        raise ValueError("配方名称不能为空")
    clean = normalize_segments(segments)
    if not clean:
        raise ValueError("没有可保存的函数内容（先粘贴函数并「检测」通过）")
    now = _now()
    return {
        "id": str(formula_id) or new_id(),
        "name": name,
        "segments": clean,
        "params_text": str(params_text or "").strip(),
        "source": source if source in SOURCE_LABELS else SOURCE_MARKET,
        "created_at": now,
        "updated_at": now,
        "used_at": "",
    }


# ==========================================
# 仓库
# ==========================================
class FormulaStore:
    """配方仓库（JSON 原子写）。对外只认 list/get/upsert/delete/touch ——
    存储换成 DB 时**只换实现、不动调用方**（与 `AnnotationStore` 同款纪律）。"""

    def __init__(self, path: str = None):
        self.path = path or os.path.join(settings.USER_DATA_DIR, FORMULA_FILE)
        self.formulas: list[dict] = []
        self.load()

    # ---------------- 持久化 ----------------
    def load(self) -> None:
        """读盘；单条坏数据只跳过自己，绝不拖垮整库。"""
        self.formulas = []
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError) as e:
            print(f"配方库读取失败: {e}")
            return
        raw = payload.get("formulas") if isinstance(payload, dict) else payload
        for entry in (raw or []):
            if not isinstance(entry, dict):
                continue
            try:
                formula = make_formula(
                    entry.get("name"), entry.get("segments"),
                    params_text=entry.get("params_text"), source=entry.get("source"),
                    formula_id=entry.get("id"))
            except (ValueError, TypeError, AttributeError):
                continue
            formula["created_at"] = str(entry.get("created_at") or formula["created_at"])
            formula["updated_at"] = str(entry.get("updated_at") or formula["updated_at"])
            formula["used_at"] = str(entry.get("used_at") or "")
            self.formulas.append(formula)

    def save(self) -> bool:
        """原子写：先写 `.tmp` 再 `os.replace`。"""
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump({"version": SCHEMA_VERSION, "formulas": self.formulas},
                          handle, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
            return True
        except OSError as e:
            print(f"配方库写入失败: {e}")
            return False

    # ---------------- 查询 ----------------
    def all(self) -> list[dict]:
        return list(self.formulas)

    def count(self) -> int:
        return len(self.formulas)

    def names(self) -> list[str]:
        return [f["name"] for f in self.formulas]

    def get(self, formula_id: str) -> dict | None:
        for formula in self.formulas:
            if formula["id"] == formula_id:
                return formula
        return None

    def get_by_name(self, name: str) -> dict | None:
        name = str(name or "").strip()
        for formula in self.formulas:
            if formula["name"] == name:
                return formula
        return None

    def list_formulas(self) -> list[dict]:
        """列表展示顺序：**最近用过的在前**，其余按名称 —— 用户复用的通常是最近那条。"""
        return sorted(self.formulas, key=lambda f: (f.get("used_at") or "", f["name"]),
                      reverse=True)

    def last_used(self) -> dict | None:
        """最近一次被载入的配方（行情页启动时自动恢复它 ⇒ 解决"公式重启就丢"）。"""
        used = [f for f in self.formulas if f.get("used_at")]
        return max(used, key=lambda f: f["used_at"]) if used else None

    # ---------------- 写入 ----------------
    def upsert(self, formula: dict) -> dict:
        """按 `name` 命中即更新（同名覆盖 = 用户"覆盖保存"的直觉），返回落库对象。"""
        payload = dict(formula or {})
        clean = make_formula(payload.get("name"), payload.get("segments"),
                             params_text=payload.get("params_text"),
                             source=payload.get("source"),
                             formula_id=payload.get("id"))
        existing = self.get_by_name(clean["name"])
        if existing is not None:
            clean["id"] = existing["id"]           # 同名视为同一条：保留原 id
            clean["created_at"] = existing.get("created_at", clean["created_at"])
            clean["used_at"] = existing.get("used_at", "")
            self.formulas[self.formulas.index(existing)] = clean
        else:
            self.formulas.append(clean)
        self.save()
        return clean

    def touch(self, formula_id: str) -> bool:
        """记录"这次用过了"（载入即更新 `used_at`）——也是自动恢复的依据。"""
        formula = self.get(formula_id)
        if formula is None:
            return False
        formula["used_at"] = _now()
        self.save()
        return True

    def rename(self, formula_id: str, new_name: str) -> bool:
        new_name = str(new_name or "").strip()
        formula = self.get(formula_id)
        if formula is None or not new_name:
            return False
        clash = self.get_by_name(new_name)
        if clash is not None and clash is not formula:
            return False                # 重名会让"按名覆盖"变得危险，直接拒绝
        formula["name"] = new_name
        formula["updated_at"] = _now()
        self.save()
        return True

    def delete(self, formula_id: str) -> bool:
        before = len(self.formulas)
        self.formulas = [f for f in self.formulas if f["id"] != formula_id]
        removed = len(self.formulas) < before
        if removed:
            self.save()
        return removed


# ==========================================
# 全 app 共享单例
# ==========================================
_STORE: FormulaStore | None = None


def get_formula_store() -> FormulaStore:
    """两个页面 + 配方库对话框必须共用**同一个**内存实例。

    否则：回测页存了一条新配方 → 行情页那份内存副本仍是旧的 → 行情页随后保存时
    会把刚加的条目**整条写没**（同一份 JSON 的"最后写者赢"问题）。
    """
    global _STORE
    if _STORE is None:
        _STORE = FormulaStore()
    return _STORE
