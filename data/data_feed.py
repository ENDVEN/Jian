# data/data_feed.py
import pandas as pd
import random
from datetime import datetime, timedelta

def generate_extreme_mock_data(num_trades=150):
    """生成测试用的极端波动假数据"""
    trades = []
    base_time = datetime.now().replace(day=1, hour=9, minute=0) 
    accounts = ['国内长线账户', '国内短线账户', '外盘IBKR']
    strategies = ['均线突破', '震荡网格', 'MACD背离', '裸K情绪']

    for i in range(num_trades):
        trade_time = base_time + timedelta(days=random.randint(0, 27), hours=random.randint(1, 10))
        net_profit = random.uniform(1000, 8000) if random.random() < 0.45 else random.uniform(-4000, -500)
        
        trades.append({
            "trade_id": f"M{i:04d}", 
            "account": random.choice(accounts),
            "symbol": random.choice(['IF2310', 'RB2401', 'AU2312', 'NQ100']),
            "direction": random.choice(['LONG', 'SHORT']),
            "entry_time": trade_time, "exit_time": trade_time + timedelta(hours=random.randint(1, 48)),
            "lots": random.randint(1, 5), "net_profit": net_profit,
            "commission": random.uniform(10, 30), 
            "strategy_tag": random.choice(strategies),
            "entry_reason": "", "reflection": "" 
        })
    return pd.DataFrame(trades)

def parse_cfmmc_excel(file_path):
    """解析 CFMMC 标准格式的期货交割单 Excel 文件"""
    xls = pd.ExcelFile(file_path)
    account_name = "CFMMC真实账户"
    try:
        if '客户交易结算月报' in xls.sheet_names:
            df_info = pd.read_excel(xls, sheet_name='客户交易结算月报')
            client_row = df_info[df_info.iloc[:, 0] == '客户名称']
            if not client_row.empty: 
                account_name = str(client_row.iloc[0, 2]).strip()
    except Exception: pass
    
    df_raw = pd.read_excel(xls, sheet_name='成交明细')
    header_idx = df_raw[df_raw.iloc[:, 0] == '交易日期'].index[0]
    df_trades = pd.read_excel(xls, sheet_name='成交明细', header=header_idx + 1)
    df_trades = df_trades[df_trades['交易日期'].notna() & (df_trades['交易日期'] != '合计')]
    
    open_positions = {}
    matched_trades = []
    
    for _, row in df_trades.iterrows():
        symbol, action, direction = str(row['合约']).strip(), str(row['开/平']).strip(), str(row['买/卖']).strip()
        dt_str = str(row['交易日期']).split(' ')[0] + " " + str(row['成交时间']).strip()
        try: trade_time = pd.to_datetime(dt_str)
        except: trade_time = datetime.now()
        
        try: lots = int(float(row['手数']))
        except: lots = 0
        
        if lots == 0: continue
        
        if action == '开':
            if symbol not in open_positions: open_positions[symbol] = {'买': [], '卖': []}
            open_positions[symbol][direction].append({'entry_time': trade_time, 'lots': lots, 'commission': float(row['手续费']) if not pd.isna(row['手续费']) else 0.0})
        elif action in ['平', '平今', '平昨']:
            opposite_dir = '卖' if direction == '买' else '买'
            lots_to_close = lots
            profit = pd.to_numeric(row['平仓盈亏'], errors='coerce')
            profit = profit if not pd.isna(profit) else 0.0
            close_commission = float(row['手续费']) if not pd.isna(row['手续费']) else 0.0
            
            if symbol in open_positions and open_positions[symbol][opposite_dir]:
                while lots_to_close > 0 and open_positions[symbol][opposite_dir]:
                    open_trade = open_positions[symbol][opposite_dir][0]
                    matched_lots = min(lots_to_close, open_trade['lots'])
                    matched_trades.append({'trade_id': str(row['成交序号']), 'account': account_name, 'symbol': symbol, 'direction': 'LONG' if opposite_dir == '买' else 'SHORT', 'entry_time': open_trade['entry_time'], 'exit_time': trade_time, 'lots': matched_lots, 'net_profit': profit * (matched_lots / lots), 'commission': close_commission * (matched_lots / lots) + open_trade['commission'] * (matched_lots / open_trade['lots']), 'strategy_tag': '未分类', 'entry_reason': '', 'reflection': '', 'screenshot_paths': ''})
                    lots_to_close -= matched_lots
                    open_trade['lots'] -= matched_lots
                    if open_trade['lots'] == 0: open_positions[symbol][opposite_dir].pop(0)
            
            if lots_to_close > 0: 
                matched_trades.append({'trade_id': str(row['成交序号']), 'account': account_name, 'symbol': symbol, 'direction': 'LONG' if opposite_dir == '买' else 'SHORT', 'entry_time': trade_time, 'exit_time': trade_time, 'lots': lots_to_close, 'net_profit': profit * (lots_to_close / lots), 'commission': close_commission * (lots_to_close / lots), 'strategy_tag': '未分类', 'entry_reason': '', 'reflection': '', 'screenshot_paths': ''})
                
    return pd.DataFrame(matched_trades)