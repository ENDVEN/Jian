# core/analyzer.py
import pandas as pd

class TradeAnalyzer:
    """
    核心交易分析引擎。
    只负责数据的数学统计与回撤计算，不包含任何 UI 代码。
    """
    def __init__(self, df: pd.DataFrame, initial_capital: float = 1000000):
        self.df = df.copy()
        self.initial_capital = initial_capital
        
        # 数据清洗与标准化
        self.df['entry_time'] = pd.to_datetime(self.df['entry_time'], errors='coerce')
        self.df['exit_time'] = pd.to_datetime(self.df['exit_time'], errors='coerce')
        for col in ['net_profit', 'commission', 'lots']:
            if self.df[col].dtype == object: 
                self.df[col] = pd.to_numeric(self.df[col].astype(str).str.replace(',', ''), errors='coerce')
                
        self.df = self.df.sort_values(by='exit_time').reset_index(drop=True)
        self.df['equity'] = self.initial_capital + self.df['net_profit'].cumsum()

    def generate_raw_report(self):
        """生成原始的核心统计指标字典"""
        df = self.df
        if len(df) == 0: return None 
        
        winning_trades, losing_trades = df[df['net_profit'] > 0], df[df['net_profit'] <= 0]
        win_count, total_count = len(winning_trades), len(df)
        avg_win = winning_trades['net_profit'].sum() / win_count if win_count > 0 else 0
        avg_loss = losing_trades['net_profit'].sum() / len(losing_trades) if len(losing_trades) > 0 else 0
        pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0
        
        df['peak'] = df['equity'].cummax()
        df['drawdown_pct'] = (df['peak'] - df['equity']) / df['peak']
        
        return {
            "initial_capital": self.initial_capital, 
            "net_profit": df['net_profit'].sum(), 
            "return_rate": (df['equity'].iloc[-1] - self.initial_capital) / self.initial_capital, 
            "total_commission": df['commission'].sum(), 
            "total_trades": total_count, 
            "win_rate": win_count / total_count if total_count > 0 else 0, 
            "pl_ratio": pl_ratio, 
            "winning_trades": win_count, 
            "losing_trades": total_count - win_count, 
            "max_drawdown": df['drawdown_pct'].max(), 
            "avg_win": avg_win, 
            "avg_loss": avg_loss, 
            "max_profit": df['net_profit'].max(), 
            "max_loss": df['net_profit'].min()
        }