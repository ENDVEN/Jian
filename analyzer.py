import pandas as pd
import numpy as np

class TradeAnalyzer:
    def __init__(self, df: pd.DataFrame, initial_capital: float = 1000000):
        # 接收包含交易记录的 DataFrame 和 初始资金
        self.df = df
        self.initial_capital = initial_capital
        
        # 非常重要：计算资金曲线前，必须按平仓时间先后排序
        self.df = self.df.sort_values(by='exit_time').reset_index(drop=True)

    def generate_report(self):
        df = self.df
        if len(df) == 0:
            return "没有交易数据，无法分析"

        # --- 基础数据分离 ---
        winning_trades = df[df['net_profit'] > 0]
        losing_trades = df[df['net_profit'] <= 0] 

        # --- 1. 核心铁三角：胜率、盈亏比、最大回撤 ---
        
        # 【胜率】
        total_count = len(df)
        win_count = len(winning_trades)
        loss_count = len(losing_trades)
        win_rate = win_count / total_count if total_count > 0 else 0

        # 【盈亏比】
        total_win_amount = winning_trades['net_profit'].sum()
        total_loss_amount = losing_trades['net_profit'].sum()
        avg_win = total_win_amount / win_count if win_count > 0 else 0
        avg_loss = total_loss_amount / loss_count if loss_count > 0 else 0
        # 盈亏比 = 平均盈利金额 / 平均亏损金额的绝对值
        pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')

        # 【最大回撤】(核心难点：利用资金峰值计算)
        # 资金曲线 = 初始资金 + 累计净利润
        df['equity'] = self.initial_capital + df['net_profit'].cumsum()
        # 历史资金最高峰
        df['peak'] = df['equity'].cummax()
        # 回撤百分比 = (峰值 - 当前资金) / 峰值
        df['drawdown_pct'] = (df['peak'] - df['equity']) / df['peak']
        max_drawdown = df['drawdown_pct'].max()

        # --- 2. 资金与收益表现 ---
        net_profit = df['net_profit'].sum()
        total_commission = df['commission'].sum()
        # 假设净利润是扣完手续费的，那么平仓盈亏(毛利) = 净利润 + 手续费 + 滑点
        gross_profit = net_profit + total_commission + df['slippage'].sum()
        return_rate = net_profit / self.initial_capital

        # --- 3. 手数与极值统计 ---
        total_lots = df['lots'].sum()
        win_lots = winning_trades['lots'].sum()
        loss_lots = losing_trades['lots'].sum()
        max_single_win = df['net_profit'].max()
        max_single_loss = df['net_profit'].min()

        # --- 4. 连续盈亏次数 (高级算法) ---
        # 把盈利标记为1，亏损标记为-1，然后找连续相同的段落
        is_win = (df['net_profit'] > 0).astype(int)
        streaks = (is_win != is_win.shift()).cumsum() 
        streak_counts = is_win.groupby(streaks).apply(lambda x: len(x) * (1 if x.iloc[0] == 1 else -1))
        
        max_consecutive_wins = streak_counts[streak_counts > 0].max() if any(streak_counts > 0) else 0
        max_consecutive_losses = abs(streak_counts[streak_counts < 0].min()) if any(streak_counts < 0) else 0

        # --- 5. 最多持仓品种数 (时间重叠算法) ---
        # 把所有的开仓和平仓当成独立事件，按时间排序，开仓+1，平仓-1
        events = []
        for _, row in df.iterrows():
            events.append((row['entry_time'], 1))  # 开单增加持仓
            events.append((row['exit_time'], -1))  # 平仓减少持仓
        events.sort(key=lambda x: x[0])
        current_holding = 0
        max_holding = 0
        for time, action in events:
            current_holding += action
            max_holding = max(max_holding, current_holding)

        # 组装返回最终的字典，直接对应你图片里的表格！
        return {
            "初始资金": f"￥{self.initial_capital:,.2f}",
            "收益率": f"{return_rate * 100:.2f}%",
            "净利润": f"￥{net_profit:,.2f}",
            "总手续费": f"￥{total_commission:,.2f}",
            "平仓盈亏": f"￥{gross_profit:,.2f}",
            "总手数": total_lots,
            "盈利手数": win_lots,
            "亏损手数": loss_lots,
            "交易次数": total_count,
            "盈利次数": win_count,
            "亏损次数": loss_count,
            "胜率": f"{win_rate * 100:.2f}%",
            "盈亏比": f"{pl_ratio:.2f}",
            "盈利金额": f"￥{total_win_amount:,.2f}",
            "亏损金额": f"￥{total_loss_amount:,.2f}",
            "平均盈利金额": f"￥{avg_win:,.2f}",
            "平均亏损金额": f"￥{avg_loss:,.2f}",
            "最大单笔盈利": f"￥{max_single_win:,.2f}",
            "最大单笔亏损": f"￥{max_single_loss:,.2f}",
            "最大回撤": f"{max_drawdown * 100:.2f}%",
            "连续盈利次数": int(max_consecutive_wins),
            "连续亏损次数": int(max_consecutive_losses),
            "最多同时持仓": max_holding
        }