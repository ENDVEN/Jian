# core/engine.py
import pandas as pd
from models.trade import TradeRecord

# 引入全局配置
from config import settings

class DataEngine:
    """
    核心数据引擎 (The Single Source of Truth)。
    负责在内存中持有和管理所有的交易数据与状态。
    """
    def __init__(self):
        self.df = pd.DataFrame()
        # 使用配置中心定义的默认策略名
        self.strategies = [settings.DEFAULT_STRATEGY]

    def load_initial_mock(self, mock_func):
        """加载测试数据"""
        try:
            trades = mock_func(50)
            self.add_trades(trades)
        except Exception as e:
            print(f"Mock数据加载失败: {e}")

    def add_trades(self, trades: list[TradeRecord]):
        """添加新交易，输入必须是 TradeRecord 的列表"""
        if not trades: return
        
        new_df = pd.DataFrame([t.to_dict() for t in trades])
        
        if self.df.empty:
            self.df = new_df
        else:
            self.df = pd.concat([self.df, new_df], ignore_index=True)
        
        new_strats = new_df['strategy_tag'].dropna().unique().tolist()
        for st in new_strats:
            if st not in self.strategies:
                self.strategies.append(st)

    def clear_account(self, acc_name: str) -> bool:
        if self.df.empty: return False
        self.df = self.df[self.df['account'] != acc_name].reset_index(drop=True)
        return True

    def delete_strategy(self, st_name: str) -> bool:
        """删除策略，将关联交易归为默认策略"""
        if self.df.empty: return False
        
        # 使用配置中心定义的默认策略名
        self.df.loc[self.df['strategy_tag'] == st_name, 'strategy_tag'] = settings.DEFAULT_STRATEGY
        if st_name in self.strategies:
            self.strategies.remove(st_name)
        return True

    def delete_trade(self, idx: int) -> bool:
        if self.df.empty or idx not in self.df.index: return False
        self.df = self.df.drop(idx).reset_index(drop=True)
        return True
        
    def update_trade_strategy(self, idx: int, new_st: str):
        if self.df.empty or idx not in self.df.index: return
        self.df.at[idx, 'strategy_tag'] = new_st
        if new_st not in self.strategies:
            self.strategies.append(new_st)

    def update_trade_review(self, idx: int, reason: str, reflection: str, paths: str):
        if self.df.empty or idx not in self.df.index: return
        self.df.at[idx, 'entry_reason'] = reason
        self.df.at[idx, 'reflection'] = reflection
        self.df.at[idx, 'screenshot_paths'] = paths