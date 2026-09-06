# core/engine.py
import pandas as pd
from models.trade import TradeRecord
from core.database import DatabaseManager
from data.data_feed import (
    detect_coverage_gaps,
    legs_from_payload,
    parse_cfmmc_files,
)
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
    # CFMMC 交割单导入全流程 (Import Pipeline)
    # ==========================================
    def parse_cfmmc(self, file_paths) -> dict:
        """
        解析交割单（耗时步骤，请放在 QThread 中执行）。

        会自动载入历史上未平仓的持仓腿一并参与 FIFO，
        因此分月导入时上月末的仓位能无缝延续到本月。
        """
        payload = self.db.load_open_legs()
        initial_legs = legs_from_payload(payload.to_dict('records')) if not payload.empty else []
        return parse_cfmmc_files(file_paths, initial_legs)

    def commit_cfmmc(self, result: dict) -> dict:
        """
        把解析结果落库（轻量步骤，在 UI 主线程执行以避免多线程写库）：
          防重入库 → 结转最新持仓 → 月度覆盖登记 → 漏月检测

        【架构纪律】UI 层只调用 parse_cfmmc / commit_cfmmc，绝不直接触碰 SQL。
        【顺序无关】文件在解析阶段已按全局时间重新排序，
        因此"分月多次导入"与"一次性导入"的结果完全一致。
        """
        stats = self.add_trades(result['trades'])

        # 结转本次导入结束后的最新未平持仓（按账户分组全量覆写，天然幂等）
        by_account: dict[str, list] = {}
        for leg in result['open_legs']:
            by_account.setdefault(leg['account'], []).append(leg)
        for account, legs in by_account.items():
            self.db.replace_open_legs(account, legs)

        # 登记月度覆盖，供漏月检测使用
        for item in result['coverage']:
            self.db.upsert_coverage(item)

        gaps = detect_coverage_gaps(result['coverage'], self.db.load_gaps())

        return {'stats': stats, 'report': result['report'], 'gaps': gaps}

    def confirm_coverage_gap(self, account: str, month: str):
        """用户确认某月为"有意跳过"，此后不再重复提醒"""
        self.db.add_gap(account, month)

    def get_orphans(self) -> pd.DataFrame:
        """当前所有待缝合的孤儿单（开仓腿缺失的平仓记录）"""
        return self.db.load_orphans()

    def stitch_orphan_trade(self, internal_id: str, entry_price: float,
                            entry_time=None, entry_fill_time: str = "",
                            extra_commission: float = 0.0) -> bool:
        """手工补录开仓信息，把孤儿单缝合为完整闭环交易"""
        changed = self.db.stitch_orphan(
            internal_id, entry_price, entry_time, entry_fill_time, extra_commission
        )
        if changed > 0:
            self.reload_data()
        return changed > 0

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
