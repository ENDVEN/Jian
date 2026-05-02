# models/trade.py
import uuid
import hashlib
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class TradeRecord:
    """
    核心数据契约：一笔交易的标准结构。
    引入了“确定性哈希”机制，确保业务幂等性（防重复导入）。
    """
    account: str
    symbol: str
    direction: str
    entry_time: datetime
    exit_time: datetime
    lots: int
    net_profit: float
    commission: float
    
    # 将默认值设为空字符串，我们将通过 __post_init__ 智能生成
    trade_id: str = ""
    internal_id: str = ""
    
    strategy_tag: str = "未分类"
    entry_reason: str = ""
    reflection: str = ""
    screenshot_paths: str = ""

    def __post_init__(self):
        """
        数据模型初始化后的钩子函数 (Hook)。
        用于在这里执行复杂的 ID 生成逻辑。
        """
        # 1. 业务单号处理：如果是手工录入没有单号，生成一个带 "M_" 前缀的随机单号
        if not self.trade_id:
            self.trade_id = f"M_{uuid.uuid4().hex[:8].upper()}"

        # 2. 【核心魔法：确定性哈希】
        # 将账户名和单号拼接在一起，例如 "国内长线_001"
        unique_string = f"{self.account}_{self.trade_id}"
        
        # 使用 MD5 算法将这串字符转化为绝对固定的 32 位底层 ID
        # 只要 account 和 trade_id 一样，算出来的 internal_id 永远一模一样！
        self.internal_id = hashlib.md5(unique_string.encode('utf-8')).hexdigest()

    def to_dict(self):
        return self.__dict__.copy()