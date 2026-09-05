# data/strategy_store.py
"""
回测策略本地持久化 (JSON, 位于用户数据目录，物理隔离不随代码分发)。

保存内容：函数源码 + 参数文本 + 买入/卖出条件 + 区间 + 备注。
同时维护轻量“回测档案”：每次用某策略在某个标的上跑出结果就记录最新指标，
用于页面内「策略对比」快速判断该股票更适合哪套策略。
"""
import json
import os
import time
import uuid

from config import settings

_STRATEGY_FILE = "backtest_strategies.json"


class StrategyStore:
    def __init__(self):
        self.path = os.path.join(settings.USER_DATA_DIR, _STRATEGY_FILE)
        self.data = {"strategies": [], "results": {}}
        self.load()

    # ---------------- 读写 ----------------
    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    loaded = json.load(f)
                self.data["strategies"] = loaded.get("strategies", [])
                self.data["results"] = loaded.get("results", {})
            except (OSError, ValueError) as e:
                print(f"策略库读取失败: {e}")
        else:
            self.data = {"strategies": [], "results": {}}

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except OSError as e:
            print(f"策略库写入失败: {e}")

    # ---------------- 策略 CRUD ----------------
    def list_strategies(self):
        return sorted(self.data["strategies"], key=lambda s: str(s.get("name", "")))

    def get(self, strategy_id: str):
        for item in self.data["strategies"]:
            if item.get("id") == strategy_id:
                return item
        return None

    def upsert(self, payload: dict) -> str:
        """新建或按同名更新，返回策略 id。payload 不含 id/时间戳字段"""
        name = str(payload.get("name", "")).strip()
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        for item in self.data["strategies"]:
            if str(item.get("name", "")).strip() == name:
                item.update(payload)
                item["id"] = item.get("id") or uuid.uuid4().hex
                item["updated_at"] = now
                self.save()
                return item["id"]
        strategy = {"id": uuid.uuid4().hex, "created_at": now, "updated_at": now}
        strategy.update(payload)
        self.data["strategies"].append(strategy)
        self.save()
        return strategy["id"]

    def delete(self, strategy_id: str) -> bool:
        before = len(self.data["strategies"])
        self.data["strategies"] = [s for s in self.data["strategies"] if s.get("id") != strategy_id]
        self.data["results"].pop(strategy_id, None)
        removed = len(self.data["strategies"]) < before
        if removed:
            self.save()
        return removed

    def find_same(self, payload: dict) -> str | None:
        """按 (函数+参数+买卖条件) 找已保存策略，供回测后自动关联"""
        signature = _signature(payload)
        for item in self.data["strategies"]:
            if _signature(item) == signature:
                return item.get("id")
        return None

    # ---------------- 回测档案 (按策略+标的) ----------------
    def record_result(self, strategy_id: str, symbol: str, metrics: dict):
        bucket = self.data["results"].setdefault(strategy_id, {})
        bucket[symbol] = {
            "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            **{k: metrics.get(k) for k in ("total_trades", "win_rate", "cumulative_return", "avg_return_pct")},
        }
        self.save()

    def metrics_snapshot(self, symbol: str) -> list[dict]:
        """返回 [{strategy, symbol 指标}]，用于策略对比"""
        snapshot = []
        for strategy in self.list_strategies():
            bucket = self.data["results"].get(strategy.get("id"), {})
            row = bucket.get(symbol)
            if row:
                snapshot.append({"strategy": strategy, "metrics": row})
        return snapshot


def _signature(payload: dict) -> str:
    return "|".join([
        str(payload.get("function", "")).strip(),
        str(payload.get("params_text", "")).strip(),
        str(payload.get("condition_buy", "")).strip(),
        str(payload.get("condition_sell", "")).strip(),
    ])
