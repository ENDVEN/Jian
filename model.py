from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class TradeRecord:
    """升级版单笔交易数据结构 (Model层)"""
    # 1. 客观交易数据 (可由CSV导入后筛选)
    trade_id: str                # 交易单号 (唯一标识)
    trader_name: str             # 交易员归属 (解决账户共用问题，如："我" 或 "张三")
    entry_time: datetime         # 开仓时间
    exit_time: datetime          # 平仓时间
    symbol: str                  # 交易品种 (如: 黄金2310)
    direction: str               # 方向 ('LONG' 或 'SHORT')
    lots: int                    # 手数
    entry_price: float           # 开仓价
    exit_price: float            # 平仓价
    commission: float            # 手续费
    slippage: float              # 滑点 (新加：记录因滑点产生的额外成本)
    net_profit: float            # 净盈亏
    
    # 2. 策略与主观复盘数据 (需手动录入或补充)
    strategy_tag: str            # 策略标签 (新加：如 "均线突破", "震荡网格", "试错单")
    entry_reason: Optional[str] = ""     # 开单思路
    reflection: Optional[str] = ""       # 事后反思复盘
    screenshot_path: Optional[str] = ""  # 截图文件路径

# 测试一下模拟数据
if __name__ == "__main__":
    trade = TradeRecord(
        trade_id="T002",
        trader_name="自己", 
        entry_time=datetime(2023, 10, 11, 21, 00),
        exit_time=datetime(2023, 10, 11, 23, 30),
        symbol="RB2401", # 螺纹钢
        direction="SHORT",
        lots=5,
        entry_price=3750.0,
        exit_price=3720.0,
        commission=25.0,
        slippage=10.0,   # 假设进出场各滑了1个点
        net_profit=1465.0, 
        strategy_tag="15分钟顶背离",
        reflection="进场位置很好，但受夜盘情绪影响，平仓过早。"
    )
    print(f"[{trade.strategy_tag}] 交易员:{trade.trader_name} 品种:{trade.symbol} 净盈亏:{trade.net_profit}")