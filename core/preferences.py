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
    # 1.22（样板 A）：回测页界面状态 —— 低频配置默认**全部收起**（空间留给回测结果），
    # 展开状态"记住上次"（用户 2026-09-16 拍板）。
    #   {"pane": "fn"|"cond"|"index"|"risk"|"fill"|None, "last": "fn"}
    #   pane = 当前展开的编辑卡片；last = 最近用过的那张（「⚙ 编辑配置」的落点）
    "backtest_ui": None,
    # 1.23（§7-B6）：**行情工作台**界面状态 —— 与 backtest_ui 同源做法（记住上次）。
    #   {"minute_period": "5m",            # 上次用的分钟档位
    #    "main_chips": ["ma", ...],        # 工具行"最近使用"的主图叠加（MRU，前 3 可见）
    #    "sub_chips": ["volume", ...],     # 同上（副图）
    #    "rail_collapsed": False,          # 左栏是否折起
    #    "panel_page": "watch"}            # 上次停留的工具页
    "desk_ui": None,
    # 1.25（§9-U 收口）：**复盘页**界面状态 —— 宏观(日历+图表)/微观(清单+编辑)的
    # 竖向分栏高度。旧版是写死的 5:4 拉伸比，短屏上回放图被挤且无法让位；
    # 现在分栏可拖，并"记住上次"（与 backtest_ui / desk_ui 同源做法）。
    #   {"v_sizes": [560, 340]}
    "review_ui": None,
    # v6.37（§7-B1/B2 STEP 4）：**全市场筛选页**界面状态 —— 与 backtest_ui / desk_ui 同源做法。
    #   {"scope": 0|1|2,            # 统计范围：0=我的自选 1=指数成分 2=全 A 花名册
    #    "index_code": "000300",    # 上次用的指数（scope=1 时）
    #    "formula": "...",          # 上次的筛选条件（多段）
    #    "params": "N=20",          # 上次的公式参数
    #    "thresholds": {...}}       # 粗筛阈值（core.cross_section.ScanThresholds.to_dict()）
    #   ⚠ 只存轻量配置，**绝不存扫描结果**（结果只进会话缓存 data/scan_store，D3）。
    "scan_ui": None,
    # 1.29（§7-B1/B2 STEP 5）：**广度统计页（M3）**界面状态 —— 与 scan_ui 同源做法，多四样：
    #   {"range": "1y",             # 显示区间：3m/6m/1y/3y/5y/all（切区间 = 纯切片，零成本）
    #    "smooth": true,            # MA5 平滑
    #    "ratio": false,            # 占比口径（家数 ÷ 有效样本）
    #    "overlay": true,           # 指数副图
    #    "overlay_code": "sh000001"}# 副图指数（index_daily 分区；缺了自动补拉一次）
    #   ⚠ 同上：只存轻量配置，绝不存扫描结果。
    "breadth_ui": None,
    # v1.37（§7-A4）：**回测历史存档**设置 —— 自动存档开关（默认开）。
    #   {"auto": True}   # 每次回测成功出结果后自动落一份不可变快照
    #   ⚠ 只存开关；存档本体在 ~/.jian_data/backtest_results/（每份一个文件），不写进偏好。
    "backtest_archive": {"auto": True},
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
