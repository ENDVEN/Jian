# data/industry_store.py
"""M2 结果表「细分行业」本地缓存 (JSON，位于用户数据目录，物理隔离不随代码分发)。

【为什么单独一个缓存】行业是"代码→板块名"的属性映射，基本不随行情每天变，但也不是
  时间序列（不落数据湖）。★v6.68 起抓法 = **分页直取**（东财列表 `f100`：单页 100、全市场
  ~56 页）⇒ 用它**分批**补齐并长期缓存；扫描时**只读它**（不联网）。
  ⚠ 旧的"逐板块取成分（80+ 连击）"已退役 —— 它正踩东财"匿名高频"风控（§11.5-99）。

【诚实口径】没抓到的标的 → 行业列显示 '—'（绝不瞎猜板块）。抓取失败 → 保留旧映射。

【原子写】tmp + os.replace（与 preferences / 各 *_store 同源），坏写不毁旧档。
"""
import json
import os

from config import settings

_INDUSTRY_FILE = "industry_map.json"


class IndustryStore:
    """代码→行业 映射缓存。`path` 可注入（测试用临时文件）。"""

    def __init__(self, path: str = None):
        self.path = path or os.path.join(settings.USER_DATA_DIR, _INDUSTRY_FILE)
        self._map: dict = {}
        self.load()

    def load(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    # 兼容 {"map": {...}} 与直接 {symbol: 行业} 两种落形
                    raw = data.get("map") if isinstance(data.get("map"), dict) else data
                    self._map = {str(k): str(v) for k, v in raw.items() if str(v).strip()}
            except (OSError, ValueError) as e:
                print(f"行业映射读取失败（用空表，不阻断）: {e}")
                self._map = {}
        else:
            self._map = {}

    def save(self) -> bool:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"map": self._map, "count": len(self._map)},
                          f, ensure_ascii=False)
            os.replace(tmp, self.path)
            return True
        except OSError as e:
            print(f"行业映射写入失败: {e}")
            return False

    def replace(self, mapping: dict) -> bool:
        """用一份新抓到的映射整体覆盖并落盘（抓空了不动旧表，避免把好数据清空）。"""
        clean = {str(k): str(v) for k, v in (mapping or {}).items() if str(v).strip()}
        if not clean:
            return False
        self._map = clean
        return self.save()

    def merge(self, mapping: dict) -> bool:
        """★v6.68：把**分批**抓到的行业**并入**现有映射并落盘（断点续抓用）。

        【为什么不是 `replace`】分页是"每批几页"，各批只覆盖一部分标的 ⇒ 整体替换会把上一批
          已经拿到的好数据**清掉**；而空值也不该覆盖已有值（诚实口径：没抓到就保留旧的）。
        """
        clean = {str(k): str(v) for k, v in (mapping or {}).items() if str(v).strip()}
        if not clean:
            return False
        self._map.update(clean)
        return self.save()

    def get(self, symbol) -> str:
        """某标的的行业名；没抓到返回 ''（上层显示 '—'）。"""
        return self._map.get(str(symbol), '')

    def as_map(self) -> dict:
        """整张映射（供结果表渲染一次性读取；不联网）。"""
        return self._map

    def coverage(self) -> int:
        return len(self._map)

    def is_loaded(self) -> bool:
        return bool(self._map)


_STORE: IndustryStore | None = None


def get_industry_store() -> IndustryStore:
    """进程内单例（与 get_scan_strategy_store 同款）：M2/M3 共享一份行业映射缓存。"""
    global _STORE
    if _STORE is None:
        _STORE = IndustryStore()
    return _STORE
