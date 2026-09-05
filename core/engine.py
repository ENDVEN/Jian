# core/engine.py
import pandas as pd
from models.trade import TradeRecord
from core.database import DatabaseManager
from config import settings


class DataEngine:
    """
    中央数据引擎 (内存状态 + DB 报告的协调者)。

    【架构纪律】本类是对 UI 层暴露的唯一数据门面：
    UI 不直接触碰 SQL，引擎负责把数据库事实反馈成清晰的布尔/统计结果。
    """
    def __init__(self):
        self.db = DatabaseManager()
        self.df = pd.DataFrame()
        self.strategies = [settings.DEFAULT_STRATEGY]
        
        self.reload_data()

    def reload_data(self):
        """全量重载业务数据，并按交易时间重建连续索引 (UI 依赖该索引定位记录)"""
        self.df = self.db.load_all_trades()
        self.strategies = [settings.DEFAULT_STRATEGY]
        if self.df.empty:
            return

        self.df = self.df.sort_values(by='trade_time').reset_index(drop=True)
        
        discovered = self.df['strategy_tag'].dropna().unique().tolist()
        self.strategies += [
            st for st in discovered 
            if st != settings.DEFAULT_STRATEGY and st not in self.strategies
        ]

    def add_trades(self, trades: list[TradeRecord]) -> dict:
        """接收新数据并交由 DB 处理，返回插入统计报告"""
        if not trades: 
            return {'total': 0, 'inserted': 0, 'ignored': 0}
            
        stats_report = self.db.insert_trades(trades)
        
        # 只有在真正有新增数据时，才触发耗时的全体数据重载
        if stats_report['inserted'] > 0:
            self.reload_data()
            
        return stats_report

    # ==========================================
    # 删除 / 更新操作
    # 均以数据库受影响行数为准返回布尔结果，供 UI 做精确反馈
    # ==========================================
    def clear_account(self, acc_name: str) -> bool:
        """清空某账户全部流水，返回是否确有数据被删除"""
        deleted = self.db.delete_account(acc_name)
        self.reload_data()
        return deleted > 0

    def delete_strategy(self, st_name: str) -> bool:
        """删除某策略 (其下记录回落为默认策略)，返回是否确有记录被改写"""
        changed = self.db.clear_strategy(st_name, settings.DEFAULT_STRATEGY)
        self.reload_data()
        return changed > 0

    def delete_trade(self, idx: int) -> bool:
        """按当前 DataFrame 行索引删除单笔记录"""
        if self.df.empty or idx not in self.df.index:
            return False
        
        # 通过 internal_id 定位删除，杜绝索引漂移误删
        internal_id = self.df.at[idx, 'internal_id']
        deleted = self.db.delete_trade(internal_id)
        self.reload_data()
        return deleted > 0
        
    def update_trade_strategy(self, idx: int, new_st: str):
        """修改某笔记录的策略分类"""
        if self.df.empty or idx not in self.df.index:
            return
        
        internal_id = self.df.at[idx, 'internal_id']
        self.db.update_strategy(internal_id, new_st)
        self.reload_data()

    def update_trade_review(self, idx: int, reason: str, reflection: str, paths: str):
        """保存某笔记录的复盘文字与截图路径"""
        if self.df.empty or idx not in self.df.index:
            return
        
        internal_id = self.df.at[idx, 'internal_id']
        self.db.update_review(internal_id, reason, reflection, paths)
        self.reload_data()
