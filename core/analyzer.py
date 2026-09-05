# core/analyzer.py
import pandas as pd

from config import settings


class TradeAnalyzer:
    """
    核心交易分析引擎。
    只负责数据的数学统计与回撤计算，不包含任何 UI 代码。
    """
    # 参与数值运算、必须保证为干净数值型的列
    NUMERIC_COLUMNS = ['net_profit', 'commission', 'lots']
    # v1.1：交易只保留单一时间锚点 trade_time
    TIME_COLUMNS = ['trade_time']

    def __init__(self, df: pd.DataFrame, initial_capital: float = None):
        self.initial_capital = settings.INITIAL_CAPITAL if initial_capital is None else initial_capital
        self.df = self._clean_data(df)
        
        if 'trade_time' in self.df.columns:
            self.df = self.df.sort_values(by='trade_time').reset_index(drop=True)
        self.df['equity'] = self.initial_capital + self.df['net_profit'].cumsum()

    def _clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """统一的数据清洗与类型标准化管道"""
        clean_df = df.copy()

        for col in self.TIME_COLUMNS:
            if col in clean_df.columns:
                clean_df[col] = pd.to_datetime(clean_df[col], errors='coerce')

        for col in self.NUMERIC_COLUMNS:
            if col not in clean_df.columns:
                continue
            if clean_df[col].dtype == object:
                # 兼容 '1,234.5' 这类带千分位分隔符的脏数据
                clean_df[col] = clean_df[col].astype(str).str.replace(',', '')
            clean_df[col] = pd.to_numeric(clean_df[col], errors='coerce').fillna(0)

        return clean_df

    @staticmethod
    def _calc_drawdown(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """
        一次性算出资金峰值与回撤百分比。
        【性能要点】cummax 只做一次并同时供 peak 列与回撤使用；
        峰值归零时回撤取 0，避免除零产生 inf。
        """
        peak = df['equity'].cummax()
        drawdown = ((peak - df['equity']) / peak.where(peak > 0)).fillna(0)
        return peak, drawdown

    def generate_raw_report(self):
        """生成原始的核心统计指标字典"""
        df = self.df
        if len(df) == 0: return None 
        
        winning_trades, losing_trades = df[df['net_profit'] > 0], df[df['net_profit'] <= 0]
        win_count, total_count = len(winning_trades), len(df)
        avg_win = winning_trades['net_profit'].sum() / win_count if win_count > 0 else 0
        avg_loss = losing_trades['net_profit'].sum() / len(losing_trades) if len(losing_trades) > 0 else 0
        pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0
        
        df['peak'], df['drawdown_pct'] = self._calc_drawdown(df)
        
        # 资金基数为 0 时回落到 1，避免收益率被算成 inf
        capital_base = self.initial_capital if self.initial_capital else 1.0
        
        return {
            "initial_capital": self.initial_capital, 
            "net_profit": df['net_profit'].sum(), 
            "return_rate": (df['equity'].iloc[-1] - self.initial_capital) / capital_base, 
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
