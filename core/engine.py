# core/engine.py
import pandas as pd
from models.trade import TradeRecord
from core.database import DatabaseManager
from config import settings

class DataEngine:
    def __init__(self):
        self.db = DatabaseManager()
        self.df = pd.DataFrame()
        self.strategies = [settings.DEFAULT_STRATEGY]
        
        self.reload_data()

    def reload_data(self):
        self.df = self.db.load_all_trades()
        self.strategies = [settings.DEFAULT_STRATEGY]
        if not self.df.empty:
            self.df = self.df.sort_values(by='exit_time').reset_index(drop=True)
            
            new_strats = self.df['strategy_tag'].dropna().unique().tolist()
            for st in new_strats:
                if st not in self.strategies and st != settings.DEFAULT_STRATEGY:
                    self.strategies.append(st)

    def add_trades(self, trades: list[TradeRecord]) -> dict:
        """接收新数据并交由 DB 处理，返回插入统计报告"""
        if not trades: 
            return {'total': 0, 'inserted': 0, 'ignored': 0}
            
        stats_report = self.db.insert_trades(trades)
        
        # 只有在真正有新增数据时，才触发耗时的全体数据重载
        if stats_report['inserted'] > 0:
            self.reload_data()
            
        return stats_report

    def clear_account(self, acc_name: str) -> bool:
        if self.df.empty: return False
        self.db.delete_account(acc_name)
        self.reload_data()
        return True

    def delete_strategy(self, st_name: str) -> bool:
        if self.df.empty: return False
        self.db.clear_strategy(st_name, settings.DEFAULT_STRATEGY)
        self.reload_data()
        return True

    def delete_trade(self, idx: int) -> bool:
        if self.df.empty or idx not in self.df.index: return False
        
        # 【修改点】使用 internal_id 定位删除
        internal_id = self.df.at[idx, 'internal_id']
        self.db.delete_trade(internal_id)
        self.reload_data()
        return True
        
    def update_trade_strategy(self, idx: int, new_st: str):
        if self.df.empty or idx not in self.df.index: return
        
        # 【修改点】使用 internal_id 更新
        internal_id = self.df.at[idx, 'internal_id']
        self.db.update_strategy(internal_id, new_st)
        self.reload_data()

    def update_trade_review(self, idx: int, reason: str, reflection: str, paths: str):
        if self.df.empty or idx not in self.df.index: return
        
        # 【修改点】使用 internal_id 更新
        internal_id = self.df.at[idx, 'internal_id']
        self.db.update_review(internal_id, reason, reflection, paths)
        self.reload_data()