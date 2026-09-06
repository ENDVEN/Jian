# models/trade.py
import uuid
import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from core.preferences import TIME_SOURCE_DATE_ONLY


@dataclass
class TradeRecord:
    """
    核心数据契约：一笔已闭环交易的标准结构 (v1.2)。

    【v1.1 设计变更】将原 entry_time / exit_time 双时间合并为单一 trade_time：
    - 期货交割单 (CFMMC) 每笔成交只带"交易日期"，现实中并不存在可区分的
      开仓时间 / 平仓时间字段，旧的双时间结构会在表格中制造虚假信息。
    - trade_time 取"平仓/结算交易日"（即该笔闭环交易盈亏实现之日），
      作为日历热力图、绩效曲线与交易回放的唯一时间锚点。

    【v1.2 增强】在不推翻 trade_time 主锚点的前提下补齐四个真实数据维度：
      1. 成交价   : entry_price / exit_price —— 交割单「成交价」列，过月遗留单为 None
      2. 成交时刻 : entry_fill_time / exit_fill_time —— 交割单「成交时间」列 (HH:MM:SS)
      3. 合约乘数 : multiplier —— 由「成交额 / (成交价 × 手数)」反推 (IF=300 / IM=200)
      4. 完整性   : is_orphan —— 1 表示开仓腿不在本次导入范围内（待缝合）

    【时间双轨制】trade_time 永远是纯日期 (00:00:00)，绝不自动填充时分；
      真实成交时刻单独存放在 *_fill_time 中，由用户的"时间精度"偏好决定是否展示。
      这样既坚守"不虚构时间"的底线，又让日内/高频用户拥有精确到秒的管理能力，
      且两者切换零成本（数据始终完整保存，无需重新导入）。

    确定性哈希 (internal_id) 机制保持不变，用于防重复导入与跨月缝合。
    """
    account: str
    symbol: str
    direction: str
    trade_time: datetime
    lots: int
    net_profit: float
    commission: float

    trade_id: str = ""
    internal_id: str = ""

    strategy_tag: str = "未分类"
    entry_reason: str = ""
    reflection: str = ""
    screenshot_paths: str = ""

    # ---------------- v1.2 新增 ----------------
    # 开仓腿的真实成交时刻（完整 datetime，含时分）。
    # 这兑现了 v1.1 规则 7.4 的预留设计：成交明细每行都带"交易日期"与"成交时间"，
    # 因此开仓时刻是真实数据而非虚构；孤儿单 / 老数据为 None。
    # 注意：trade_time 仍是唯一主锚点（平仓/盈亏实现日），entry_time 只是补充附表字段。
    entry_time: Optional[datetime] = None

    # 成交价：过月遗留单 (is_orphan=1) 的 entry_price 为 None，绝不填 0 制造假象
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None

    # 成交时刻 (HH:MM:SS)，空串代表该腿没有可用的时分信息
    entry_fill_time: str = ""
    exit_fill_time: str = ""

    # 时刻来源：DATE_ONLY / STATEMENT / MANUAL，保证"时刻是哪来的"永远可追溯
    time_source: str = TIME_SOURCE_DATE_ONLY

    # 合约乘数（每点价值），0 表示未知
    multiplier: float = 0.0

    # 1 = 开仓腿缺失（过月遗留 / 未导入更早月份），需后续缝合或手工补录
    is_orphan: int = 0

    # FIFO 拆分切片序号：仅用于哈希防撞，不落库
    slice_index: int = 0
    slice_total: int = 1

    def __post_init__(self):
        """数据模型初始化钩子"""
        if not self.trade_id:
            self.trade_id = f"M_{uuid.uuid4().hex[:8].upper()}"

        # 【核心修正：防拆分碰撞哈希】
        # 同一平仓单被 FIFO 拆成多个切片时，用交易日期与匹配手数作为盐值，
        # 确保每个切片拥有绝对唯一的 internal_id，且支持重复导入与幂等拦截。
        time_str = self.trade_time.strftime("%Y%m%d") if self.trade_time else "UNKNOWN"
        unique_string = f"{self.account}_{self.trade_id}_{time_str}_{self.lots}"

        # 【v1.2 拆分防撞】当一笔平仓被拆成多个切片、且切片手数相同时，
        # 上述盐值会完全一样，导致 INSERT OR IGNORE 静默丢弃后续切片（数据丢失）。
        # 仅在真正发生拆分 (slice_total > 1) 时追加序号，
        # 保证 1:1 场景的哈希与历史数据完全一致，老库零影响。
        if self.slice_total > 1:
            unique_string = f"{unique_string}#{self.slice_index}"

        self.internal_id = hashlib.md5(unique_string.encode('utf-8')).hexdigest()

    # ==========================================
    # 派生语义 (Derived Semantics)
    # ==========================================
    @property
    def entry_action(self) -> str:
        """开仓动作文案：买入开仓 / 卖出开仓"""
        return "买入开仓" if self.direction == 'LONG' else "卖出开仓"

    @property
    def close_action(self) -> str:
        """平仓动作文案：卖出平仓 / 买入平仓"""
        return "卖出平仓" if self.direction == 'LONG' else "买入平仓"

    def points(self) -> Optional[float]:
        """
        点数盈亏（期货思维的核心指标）。
        LONG : exit - entry；SHORT : entry - exit。
        开仓价缺失（过月遗留单）时返回 None，绝不返回 0 制造假象。
        """
        if self.entry_price is None or self.exit_price is None:
            return None
        diff = self.exit_price - self.entry_price
        return diff if self.direction == 'LONG' else -diff

    def is_fully_stitched(self) -> bool:
        """是否已完整缝合（开仓腿信息齐全）"""
        return self.is_orphan == 0 and self.entry_price is not None

    def to_dict(self):
        return self.__dict__.copy()
