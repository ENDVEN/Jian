# data/scan_strategy_store.py
"""M2/M3「筛选方案」本地持久化 (JSON，位于用户数据目录，物理隔离不随代码分发)。

【为什么不并入 strategy_store（§7-B12 拍板：边界干净、留重构空间）】
  · M1 策略 = 单股回测配置（买卖条件 / 风控 / 指数门控 / 成交模型 / 区间 / 标的）；
  · M2/M3 方案 = 横截面筛选配置（函数 / 参数 / 粗筛阈值 / 统计范围 / 指数 / 复权）。
    两者字段几乎不相交，混进一个文件会互相污染签名与载入分支；各存各的，将来任一侧
    重构都不牵连另一侧。

【M2 与 M3 共用一份池】两页配置形状一致（函数/参数/阈值/范围/指数/复权），
一份方案可在一页存、另一页载入 —— 是特性不是巧合（同一套"一个引擎两种视图"）。

【存什么】只存**轻量配置**，绝不存扫描结果（结果只进会话缓存 data/scan_store，D3）。

【原子写】tmp + os.replace（与 preferences / 各 *_store 同源），坏写不毁旧档。
"""
import json
import os
import time
import uuid

from config import settings

_STRATEGY_FILE = "scan_strategies.json"

# 一份方案的可持久字段（缺字段由消费方回落默认；这里只列"存哪些"）
_CONFIG_KEYS = ("scope", "index_code", "formula", "params", "thresholds", "adjust")


class ScanStrategyStore:
    """筛选方案库（CRUD，按名字唯一）。"""

    def __init__(self):
        self.path = os.path.join(settings.USER_DATA_DIR, _STRATEGY_FILE)
        self.data = {"strategies": []}
        self.load()

    # ---------------- 读写 ----------------
    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    loaded = json.load(f)
                self.data["strategies"] = [
                    s for s in loaded.get("strategies", []) if isinstance(s, dict)]
            except (OSError, ValueError) as e:
                print(f"筛选方案库读取失败: {e}")
                self.data["strategies"] = []
        else:
            self.data["strategies"] = []

    def save(self) -> bool:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
            return True
        except OSError as e:
            print(f"筛选方案库写入失败: {e}")
            return False

    # ---------------- CRUD ----------------
    def list_strategies(self) -> list:
        return sorted(self.data["strategies"], key=lambda s: str(s.get("name", "")))

    def get(self, strategy_id: str):
        for item in self.data["strategies"]:
            if item.get("id") == strategy_id:
                return item
        return None

    def upsert(self, payload: dict) -> str:
        """新建或按同名覆盖，返回方案 id。payload 不含 id/时间戳。"""
        name = str(payload.get("name", "")).strip()
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        config = {k: payload.get(k) for k in _CONFIG_KEYS}
        for item in self.data["strategies"]:
            if str(item.get("name", "")).strip() == name:
                item["config"] = config
                item["updated_at"] = now
                self.save()
                return item["id"]
        strategy = {"id": uuid.uuid4().hex, "name": name, "config": config,
                    "created_at": now, "updated_at": now}
        self.data["strategies"].append(strategy)
        self.save()
        return strategy["id"]

    def delete(self, strategy_id: str) -> bool:
        before = len(self.data["strategies"])
        self.data["strategies"] = [s for s in self.data["strategies"]
                                   if s.get("id") != strategy_id]
        removed = len(self.data["strategies"]) < before
        if removed:
            self.save()
        return removed


_STORE: ScanStrategyStore | None = None


def get_scan_strategy_store() -> ScanStrategyStore:
    """进程内单例（与 `get_scan_store()` 同款）：M2/M3 共享一份方案池，
    存/删一处生效、另一页立刻看到（各 new 一个会各存内存副本、互相看不见）。"""
    global _STORE
    if _STORE is None:
        _STORE = ScanStrategyStore()
    return _STORE
