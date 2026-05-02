# models/trade.py
import uuid
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class TradeRecord:
    """
    核心数据契约：一笔交易的标准结构。
    无论外部数据多么杂乱，进入系统前必须被转化为这个类的实例。
    """
    account: str
    symbol: str
    direction: str  # 通常为 "LONG" 或 "SHORT"
    entry_time: datetime
    exit_time: datetime
    lots: int
    net_profit: float
    commission: float
    
    # 以下为带有默认值的字段
    trade_id: str = field(default_factory=lambda: f"T_{uuid.uuid4().hex[:8].upper()}")
    strategy_tag: str = "未分类"
    entry_reason: str = ""
    reflection: str = ""
    screenshot_paths: str = ""

    def to_dict(self):
        """将模型转换为字典，专供底层的 Pandas DataFrame 引擎使用"""
        return self.__dict__.copy()