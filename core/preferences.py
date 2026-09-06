# core/preferences.py
"""
用户偏好持久化 (User Preferences Store)。

【设计定位】偏好属于"软件使用习惯"，不属于业务数据，
因此独立存放于 ~/.jian_data/preferences.json，与业务库 (jian_trades.db) 物理隔离。

【容错原则】任何读写失败 (文件缺失 / 内容损坏 / 权限不足) 都静默回落到默认值并记日志，
绝不允许一个偏好文件阻断主程序启动 —— 偏好永远是可有可无的"锦上添花"。

【时间精度 (time_precision)】本项目最重要的一个偏好项：
  - DATE_ONLY : 界面只呈现到"某一天"，适合波段 / 长线交易者
  - FILL_TIME : 呈现并使用真实成交时刻 (HH:MM:SS)，适合日内 / 高频交易者
  注意：它**只控制展示与排序粒度**，不改变任何盈亏数字，
  也不改变 trade_time 主锚点（永远纯日期）。因此用户随时可切换，无需重新导入。
"""
import json
import logging
import os

from config import settings

logger = logging.getLogger(__name__)

PREFERENCES_PATH = os.path.join(settings.USER_DATA_DIR, "preferences.json")

# 时间精度的两个合法取值
TIME_PRECISION_DATE = "DATE_ONLY"
TIME_PRECISION_FILL = "FILL_TIME"
TIME_PRECISION_OPTIONS = (TIME_PRECISION_DATE, TIME_PRECISION_FILL)

# 时间数据来源（写入 trade.time_source，保证"这个时刻是哪来的"永远可追溯）
TIME_SOURCE_DATE_ONLY = "DATE_ONLY"   # 交割单无时分，或用户选择忽略
TIME_SOURCE_STATEMENT = "STATEMENT"   # 交割单原生成交时间
TIME_SOURCE_MANUAL = "MANUAL"         # 用户手工补录

# 默认偏好：time_precision 留空，代表"尚未询问过用户"
DEFAULTS = {
    "time_precision": None,
}


class Preferences:
    """轻量 key-value 偏好仓库，进程内共享同一份内存快照。"""

    def __init__(self, path: str = PREFERENCES_PATH):
        self.path = path
        self._data = dict(DEFAULTS)
        self.load()

    # ==========================================
    # 基础读写
    # ==========================================
    def load(self):
        """从磁盘加载偏好；文件缺失或损坏时静默回落默认值。"""
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self._data.update(loaded)
        except Exception as e:
            logger.warning(f"偏好文件读取失败，已回落默认值: {e}")
            self._data = dict(DEFAULTS)

    def save(self) -> bool:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.warning(f"偏好文件写入失败: {e}")
            return False

    def get(self, key: str, default=None):
        return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value) -> bool:
        self._data[key] = value
        return self.save()

    # ==========================================
    # 语义化访问器 (Semantic Accessors)
    # ==========================================
    @property
    def time_precision(self):
        return self.get("time_precision")

    def needs_time_precision_choice(self) -> bool:
        """是否需要在首次导入时询问用户时间精度"""
        return self.get("time_precision") not in TIME_PRECISION_OPTIONS

    def set_time_precision(self, value: str) -> bool:
        if value not in TIME_PRECISION_OPTIONS:
            logger.warning(f"非法的时间精度取值: {value}")
            return False
        return self.set("time_precision", value)

    def use_fill_time(self) -> bool:
        """当前是否启用精确时分（未选择时按"仅日期"保守处理）"""
        return self.get("time_precision") == TIME_PRECISION_FILL


# 进程级单例：全程序共享同一份偏好快照
preferences = Preferences()
