# models/trade.py
import uuid
import hashlib
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class TradeRecord:
    """
    核心数据契约：一笔交易的标准结构。
    引入了强化版“确定性哈希”机制，确保业务幂等性（防重复导入）。
    """
    account: str
    symbol: str
    direction: str
    entry_time: datetime
    exit_time: datetime
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
        # 针对 CFMMC 结算单没有具体时间只有日期的情况。
        # 当平仓单被 FIFO 拆分时，利用进场日期和匹配手数作为盐值，确保拆分切片具有绝对唯一的 ID。
        entry_date_str = self.entry_time.strftime("%Y%m%d") if self.entry_time else "UNKNOWN"
        unique_string = f"{self.account}_{self.trade_id}_{entry_date_str}_{self.lots}"
        
        self.internal_id = hashlib.md5(unique_string.encode('utf-8')).hexdigest()

    def to_dict(self):
        return self.__dict__.copy()