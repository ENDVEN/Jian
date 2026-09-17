# data/watchlist_store.py
"""自选股（Watchlist）—— 用户关心的标的清单，JSON 原子写（§7-B3 P8）。

【为什么单独一份】"我关注哪些票"是**用户资产**，与"行情数据"完全无关：
  · 不放进数据湖（那是行情本身，体积大、可重建）；
  · 不放进花名册 `market_symbols`（那是**全市场**名单，几万条、由 `scripts/sync_roster.py` 覆写）；
  · 单独一个 `~/.jian_data/watchlist.json`，与 `preferences` / `strategy_store` /
    `annotations` / `formula_store` 同款：原子写（tmp + os.replace）、坏数据行只跳过自己。

【为什么存 dict 而不是纯代码列表】顺手存名称，用户看到的是"贵州茅台 600519"而不是"600519"；
  名称在每次载入/命中花名册时会被刷新（不把旧名当真相）。

【零 Qt 依赖】可被未来的复盘页/回测页复用（"我的自选"一键跑回测）。

【分组（v6.24 · §7-B8 R1）】分组既是**股票分类**，也是将来「组合配置」的最小单位
（一个分组 ≈ 一只用户自建的"基金"）。三条不可破的语义：
  · 同一只股票**只属于一个分组**（这是分类，不是标签集合）；
  · **删分组 ≠ 删股票**：删组只把成员解绑回 `DEFAULT_GROUP`（§5 铁律：绝不连带删数据）；
  · 组内顺序 = `entries` 里的相对顺序；`move` **只在同组内**上下移（不会把票挪进别的组）。
【空分组也要留得住】只存 `entries` 的话，"刚建好、还没放票的组"会立刻消失，
  用户下一步就无法把它选为落点 ⇒ 额外持久化一份 `groups`（声明过的组名）。
向后兼容：`SCHEMA_VERSION = 1` 的旧文件没有 `group` 字段 ⇒ 一律归到 `DEFAULT_GROUP`。
"""
from __future__ import annotations

import json
import os
import time

from config import settings

WATCHLIST_FILE = "watchlist.json"
SCHEMA_VERSION = 2       # v2 起有 group/groups（v1 文件读得进来，自动归到 DEFAULT_GROUP）
MAX_ITEMS = 300          # 防呆：自选股不该是"全市场清单"（那用花名册）
DEFAULT_GROUP = "我的自选"    # 未分组 / 删组解绑后的落点（**必须非空**，否则 UI 上是个看不见的标签）
MAX_GROUPS = 50          # 防呆：分组是给人看的分类，不是标签云
GROUP_NAME_MAX = 12      # 分组名上限（按面板宽度定：chips 一行放不下就失去意义了）


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def normalize_symbol(value) -> str:
    """统一成大写、无空白的代码（`sh600000` / `600519` / `RB2410`）。"""
    return str(value or "").strip().upper()


def normalize_group(value) -> str:
    """分组名的**唯一**规范化入口（§11.5-19：跨模块共享的"键"必须有规范化函数）。

    折叠内部空白 + 去首尾空白；空值一律落到 `DEFAULT_GROUP`
    —— **绝不产生空字符串分组**：那在 UI 上是一个看不见的标签，属坏数据。
    ⚠ 本函数**不做长度校验**（超长由 `create_group`/`rename_group` 显式拒绝，
    避免"静默截断用户的组名"这种看不懂的改名，§10-4）。
    """
    return " ".join(str(value or "").split()) or DEFAULT_GROUP


def make_entry(symbol, name: str = "", added_at: str = "", group: str = "") -> dict:
    """构造一条自选记录（全 app 唯一构造入口）。"""
    symbol = normalize_symbol(symbol)
    if not symbol:
        raise ValueError("标的代码不能为空")
    return {"symbol": symbol, "name": str(name or "").strip(),
            "group": normalize_group(group), "added_at": str(added_at) or _now()}


class WatchlistStore:
    """自选股仓库。对外只有 add/remove/move/symbols/entries —— 换存储不动调用方。"""

    def __init__(self, path: str = None):
        self.path = path or os.path.join(settings.USER_DATA_DIR, WATCHLIST_FILE)
        self.entries: list[dict] = []
        self.declared_groups: list[str] = []    # 声明过的组（含"刚建好还没放票"的空组）
        self.load()

    # ---------------- 持久化 ----------------
    def load(self) -> None:
        self.entries = []
        self.declared_groups = []
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError) as e:
            print(f"自选股读取失败: {e}")
            return
        raw = payload.get("entries") if isinstance(payload, dict) else payload
        seen = set()
        for item in (raw or []):
            try:
                entry = make_entry(
                    (item or {}).get("symbol") if isinstance(item, dict) else item,
                    (item or {}).get("name", "") if isinstance(item, dict) else "",
                    (item or {}).get("added_at", "") if isinstance(item, dict) else "",
                    # ★v6.24：旧文件（v1）没有 group ⇒ 空串 ⇒ 自动落到 DEFAULT_GROUP
                    (item or {}).get("group", "") if isinstance(item, dict) else "")
            except (ValueError, TypeError, AttributeError):
                continue
            if entry["symbol"] in seen:        # 坏数据/手工编辑可能造出重复项
                continue
            seen.add(entry["symbol"])
            self.entries.append(entry)

        declared = payload.get("groups") if isinstance(payload, dict) else None
        for name in (declared or []):
            text = normalize_group(name)
            if text not in self.declared_groups and len(self.declared_groups) < MAX_GROUPS:
                self.declared_groups.append(text)

    def save(self) -> bool:
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump({"version": SCHEMA_VERSION, "entries": self.entries,
                           "groups": self.declared_groups},
                          handle, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
            return True
        except OSError as e:
            print(f"自选股写入失败: {e}")
            return False

    # ---------------- 查询 ----------------
    def symbols(self) -> list[str]:
        """按用户排序返回代码（列表顺序 = 用户拖出来的顺序）"""
        return [entry["symbol"] for entry in self.entries]

    def entries_all(self) -> list[dict]:
        return list(self.entries)

    def names_map(self) -> dict:
        return {entry["symbol"]: entry["name"] for entry in self.entries}

    def display_name(self, symbol) -> str:
        symbol = normalize_symbol(symbol)
        for entry in self.entries:
            if entry["symbol"] == symbol:
                return entry["name"] or symbol
        return symbol

    def contains(self, symbol) -> bool:
        return normalize_symbol(symbol) in self.symbols()

    def count(self) -> int:
        return len(self.entries)

    # ---------------- 分组查询（v6.24 · §7-B8 R1）----------------
    def groups(self) -> list[str]:
        """全部分组名：**先按声明顺序**（= 用户建组顺序，稳定可预期），
        再补上"只在 entries 里出现、没被声明过"的组（坏数据/手工改文件的容忍）。

        ⚠ 这里**不含**"全部" —— "全部"是聚合视图，不是真实分组（别把它写进存储）。
        """
        result = list(self.declared_groups)
        for entry in self.entries:
            if entry["group"] not in result:
                result.append(entry["group"])
        return result

    def has_group(self, name) -> bool:
        return normalize_group(name) in self.groups()

    def group_counts(self) -> dict:
        """{组名: 成员数}（含空组 0 —— chips 上要能显示"0 只"，否则用户以为新建失败了）。"""
        counts = {name: 0 for name in self.groups()}
        for entry in self.entries:
            counts[entry["group"]] = counts.get(entry["group"], 0) + 1
        return counts

    def entries_in(self, group=None) -> list[dict]:
        """取某组的记录（保持列表顺序）。`group=None` = 全部（"全部"是聚合视图）。"""
        if group is None:
            return list(self.entries)
        target = normalize_group(group)
        return [entry for entry in self.entries if entry["group"] == target]

    def symbols_in(self, group=None) -> list[str]:
        return [entry["symbol"] for entry in self.entries_in(group)]

    def group_of(self, symbol) -> str:
        """某只股票所在组；不在自选里返回空串（区别于"在默认组"）。"""
        symbol = normalize_symbol(symbol)
        for entry in self.entries:
            if entry["symbol"] == symbol:
                return entry["group"]
        return ""

    # ---------------- 写入 ----------------
    def add(self, symbol, name: str = "", group=None) -> bool:
        """加入自选；已存在则只刷新名称。返回"是否新增"（False = 本来就在）。

        `group` 语义（**刻意区分"没给"与"给了"**，否则会静默改掉用户的分组）：
          · `group=None`（不传）⇒ 新增落 `DEFAULT_GROUP`；**已存在的保持原组不动**；
          · `group="X"`（显式）⇒ 新增进 X；**已存在的移进 X**
            （调用方文案是"加入自选并归入该分组"，用户确实想让它进那个组）。
        """
        target = normalize_group(group) if group is not None else ""
        entry = make_entry(symbol, name, group=target or DEFAULT_GROUP)
        for existing in self.entries:
            if existing["symbol"] == entry["symbol"]:
                changed = False
                if entry["name"] and existing["name"] != entry["name"]:
                    existing["name"] = entry["name"]
                    changed = True
                if target and existing["group"] != target:
                    existing["group"] = target
                    changed = True
                if changed:
                    self.save()
                return False
        if len(self.entries) >= MAX_ITEMS:
            raise ValueError(f"自选股最多 {MAX_ITEMS} 只，请先清理")
        if target and target not in self.declared_groups \
                and len(self.declared_groups) < MAX_GROUPS:
            self.declared_groups.append(target)      # 显式进组 ⇒ 顺手把组声明出来
        self.entries.append(entry)
        self.save()
        return True

    def remove(self, symbol) -> bool:
        symbol = normalize_symbol(symbol)
        before = len(self.entries)
        self.entries = [e for e in self.entries if e["symbol"] != symbol]
        removed = len(self.entries) < before
        if removed:
            self.save()
        return removed

    def clear(self) -> int:
        """清空自选（**同时清掉分组声明** —— 空组名留着只会让人误会）。

        返回删除的股票数。⚠ 这是"回到刚装好的样子"语义，调用方必须二次确认（§10-10）。
        """
        removed = len(self.entries)
        if removed or self.declared_groups:
            self.entries = []
            self.declared_groups = []
            self.save()
        return removed

    def update_name(self, symbol, name: str) -> bool:
        """花名册刷新后同步名称（旧名不当真相）。"""
        symbol = normalize_symbol(symbol)
        name = str(name or "").strip()
        if not symbol or not name:
            return False
        for existing in self.entries:
            if existing["symbol"] == symbol and existing["name"] != name:
                existing["name"] = name
                self.save()
                return True
        return False

    def move(self, symbol, delta: int) -> bool:
        """上移(-1)/下移(+1) —— **只在同一分组内**移动。

        【为什么必须限定组内】`entries` 是一条有序总表。若按总表索引交换相邻项，
        跨组边界时会把票**挪进别的组**（用户只是想在本组里调个顺序，却顺手改了分类）。
        返回 False 的三种情况：找不到、已在组内边界、组内只有它自己。
        """
        symbol = normalize_symbol(symbol)
        index = next((i for i, e in enumerate(self.entries) if e["symbol"] == symbol), -1)
        if index < 0:
            return False
        group = self.entries[index]["group"]
        same = [i for i, e in enumerate(self.entries) if e["group"] == group]
        pos = same.index(index)
        target = pos + int(delta)
        if target < 0 or target >= len(same) or target == pos:
            return False
        # 在**总表**里交换这两项的位置：只改变本组的相对顺序，其它组一格不动
        self.entries[same[pos]], self.entries[same[target]] = (
            self.entries[same[target]], self.entries[same[pos]])
        self.save()
        return True

    # ==========================================
    # 分组增 / 改 / 删（v6.24 · §7-B8 R1）
    # ==========================================
    def create_group(self, name) -> bool:
        """新建分组。返回是否真的新建。

        **一律显式拒绝**（不静默改名、不静默截断）：名为空 / 超长 / 已存在 / 超过 `MAX_GROUPS`。
        """
        text = " ".join(str(name or "").split())
        if not text or len(text) > GROUP_NAME_MAX:
            return False
        if text in self.groups() or len(self.groups()) >= MAX_GROUPS:
            return False
        self.declared_groups.append(text)
        self.save()
        return True

    def rename_group(self, old, new) -> bool:
        """重命名分组（连带把成员的组名一起改）。

        目标名**已存在 ⇒ 拒绝** —— 不静默合并两个分组（那是不可逆的分类丢失，§10-4）。
        """
        source = normalize_group(old)
        text = " ".join(str(new or "").split())
        if not text or len(text) > GROUP_NAME_MAX or text == source:
            return False
        if not self.has_group(source) or text in self.groups():
            return False
        self.declared_groups = [text if g == source else g for g in self.declared_groups]
        for entry in self.entries:
            if entry["group"] == source:
                entry["group"] = text
        self.save()
        return True

    def delete_group(self, name) -> int:
        """删除分组：成员**解绑回 `DEFAULT_GROUP`**，股票一条都不删（§5 铁律：绝不连带删数据）。

        返回被解绑的股票数。⚠ 默认分组不可删 —— 它是所有解绑动作的落点，删掉就没地方去了。
        """
        target = normalize_group(name)
        if target == DEFAULT_GROUP or not self.has_group(target):
            return 0
        self.declared_groups = [g for g in self.declared_groups if g != target]
        moved = 0
        for entry in self.entries:
            if entry["group"] == target:
                entry["group"] = DEFAULT_GROUP
                moved += 1
        self.save()
        return moved

    def set_group(self, symbol, group) -> bool:
        """把一只股票移到某个**已存在**的组。

        ⚠ 目标组必须已存在（或就是默认组）⇒ 拼错名字时返回 False，
        而不是"顺手建一个错别字组"（那是看不见的脏数据；建组请走 `create_group`）。
        """
        target = normalize_group(group)
        if target != DEFAULT_GROUP and target not in self.groups():
            return False
        symbol = normalize_symbol(symbol)
        for entry in self.entries:
            if entry["symbol"] == symbol:
                if entry["group"] == target:
                    return False
                entry["group"] = target
                self.save()
                return True
        return False

    def move_symbols_to_group(self, symbols, group) -> int:
        """批量移组（"从自选股里挑选…"那条路径）。返回真正移动的条数。"""
        target = normalize_group(group)
        if target != DEFAULT_GROUP and target not in self.groups():
            return 0
        wanted = {normalize_symbol(s) for s in (symbols or [])}
        moved = 0
        for entry in self.entries:
            if entry["symbol"] in wanted and entry["group"] != target:
                entry["group"] = target
                moved += 1
        if moved:
            self.save()
        return moved

    def reorder_group(self, group, symbols) -> bool:
        """按给定顺序**重排某一个分组内**的成员（拖拽排序的落盘入口，§7-B8 R15）。

        三条语义（**都是为了不"顺手改了分组"**）：
          · 只接受该组**现有成员的全集**：多给 / 少给 / 有重复一律**拒绝**（不猜、不补、不删）；
          · 其它分组的成员在总表里的**相对位置一格不动**（只改写本组占的那些"槽位"）；
          · 顺序没变化 ⇒ 返回 False（不白写一次盘）。
        返回是否真的落盘。
        """
        target = normalize_group(group)
        if target not in self.groups():
            return False
        wanted = [normalize_symbol(s) for s in (symbols or [])]
        current = self.symbols_in(target)
        if len(set(wanted)) != len(wanted) or sorted(wanted) != sorted(current):
            return False
        if wanted == current:
            return False
        slots = [index for index, entry in enumerate(self.entries)
                 if entry["group"] == target]
        by_symbol = {entry["symbol"]: entry for entry in self.entries
                     if entry["group"] == target}
        for slot, symbol in zip(slots, wanted):
            self.entries[slot] = by_symbol[symbol]
        self.save()
        return True
