# models/trade.py
import uuid
import hashlib
from dataclasses import dataclass
from datetime import datetime


@dataclass
class TradeRecord:
    """
    核心数据契约：一笔已闭环交易的标准结构 (v1.1)。

    【v1.1 设计变更】将原 entry_time / exit_time 双时间合并为单一 trade_time：
    - 期货交割单 (CFMMC) 每笔成交只带"交易日期"，现实中并不存在可区分的
      开仓时间 / 平仓时间字段，旧的双时间结构会在表格中制造虚假信息。
    - trade_time 取"平仓/结算交易日"（即该笔闭环交易盈亏实现之日），
      作为日历热力图、绩效曲线与交易回放的唯一时间锚点。

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

    def __post_init__(self):
        """数据模型初始化钩子"""
        if not self.trade_id:
            self.trade_id = f"M_{uuid.uuid4().hex[:8].upper()}"

        # 【核心修正：防拆分碰撞哈希】
        # 同一平仓单被 FIFO 拆成多个切片时，用交易日期与匹配手数作为盐值，
        # 确保每个切片拥有绝对唯一的 internal_id，且支持重复导入与幂等拦截。
        time_str = self.trade_time.strftime("%Y%m%d") if self.trade_time else "UNKNOWN"
        unique_string = f"{self.account}_{self.trade_id}_{time_str}_{self.lots}"
        
        self.internal_id = hashlib.md5(unique_string.encode('utf-8')).hexdigest()

    def to_dict(self):
        return self.__dict__.copy()
