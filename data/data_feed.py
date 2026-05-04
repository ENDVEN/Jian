# data/data_feed.py
import pandas as pd
import uuid
import re
from datetime import datetime
from models.trade import TradeRecord

def clean_str(s):
    """强力清洗字符串中的所有空白字符（包括前后空格、制表符等）"""
    if pd.isna(s): return ""
    return re.sub(r'\s+', '', str(s))

def parse_cfmmc_excel(file_path) -> list[TradeRecord]:
    """解析 CFMMC 格式 Excel，支持动态表头与脏数据清洗"""
    xls = pd.ExcelFile(file_path)
    account_name = "CFMMC真实账户"
    
    # 尝试提取账户名称 (容错处理)
    try:
        if '客户交易结算月报' in xls.sheet_names:
            df_info = pd.read_excel(xls, sheet_name='客户交易结算月报', header=None)
            for idx, row in df_info.iterrows():
                if '客户名称' in str(row.values):
                    # 假设客户名称在这一行的某个位置，向后找非空的单元格
                    for cell in row.values[1:]:
                        if pd.notna(cell) and str(cell).strip():
                            account_name = str(cell).strip()
                            break
                    break
    except Exception:
        pass

    # 1. 动态定位表头行
    # 先无表头读入
    df_raw = pd.read_excel(xls, sheet_name='成交明细', header=None)
    
    # 寻找包含“交易日期”或“成交日期”的行作为真正的表头
    header_idx = -1
    for idx, row in df_raw.iterrows():
        row_str = str(row.values)
        if '交易日期' in row_str or '成交日期' in row_str:
            header_idx = idx
            break
            
    if header_idx == -1:
        raise ValueError("无法在交割单中找到包含 '交易日期' 的表头行，请检查文件格式。")

    # 2. 以正确的表头重新读取
    df_trades = pd.read_excel(xls, sheet_name='成交明细', header=header_idx)
    
    # 清理空行和合计行
    # 获取第一列的列名（通常是“交易日期”）
    date_col = df_trades.columns[0]
    df_trades = df_trades[df_trades[date_col].notna() & (~df_trades[date_col].astype(str).str.contains('合计'))]
    
    open_positions = {}
    matched_trades = []
    
    for _, row in df_trades.iterrows():
        # 【核心修复】：必须使用 clean_str 去除原始数据中首尾隐藏的空格 (如 ' 卖', ' 平')
        symbol = clean_str(row.get('合约', row.get('品种', '')))
        action = clean_str(row.get('开/平', ''))
        direction = clean_str(row.get('买/卖', ''))
        
        # 强制仅提取日期进行匹配
        date_str = clean_str(row[date_col]).split(' ')[0]
        try: 
            trade_date = pd.to_datetime(date_str)
        except: 
            trade_date = datetime.now()
            
        try: 
            lots = int(float(row['手数']))
        except: 
            lots = 0
            
        if lots == 0 or not symbol: 
            continue
            
        # 提取手续费和盈亏
        commission = float(row.get('手续费', 0.0)) if not pd.isna(row.get('手续费')) else 0.0
        profit = pd.to_numeric(row.get('平仓盈亏', 0.0), errors='coerce')
        profit = profit if not pd.isna(profit) else 0.0
        trade_id = clean_str(row.get('成交序号', f"C_{uuid.uuid4().hex[:8]}"))

        # ===== 核心 FIFO 匹配逻辑 =====
        if '开' in action:
            if symbol not in open_positions: 
                open_positions[symbol] = {'买': [], '卖': []}
            open_positions[symbol][direction].append({
                'entry_time': trade_date, 
                'lots': lots, 
                'commission': commission
            })
            
        elif '平' in action:
            opposite_dir = '卖' if '买' in direction else '买'
            lots_to_close = lots
            
            # FIFO 执行匹配
            if symbol in open_positions and open_positions[symbol][opposite_dir]:
                while lots_to_close > 0 and open_positions[symbol][opposite_dir]:
                    open_trade = open_positions[symbol][opposite_dir][0]
                    matched_lots = min(lots_to_close, open_trade['lots'])
                    
                    prop_profit = profit * (matched_lots / lots) if lots > 0 else 0.0
                    prop_comm = commission * (matched_lots / lots) + open_trade['commission'] * (matched_lots / open_trade['lots'])
                    
                    record = TradeRecord(
                        trade_id=trade_id, 
                        account=account_name, 
                        symbol=symbol,
                        direction='LONG' if opposite_dir == '买' else 'SHORT',
                        entry_time=open_trade['entry_time'], 
                        exit_time=trade_date,
                        lots=matched_lots, 
                        net_profit=prop_profit, 
                        commission=prop_comm
                    )
                    matched_trades.append(record)
                    
                    lots_to_close -= matched_lots
                    open_trade['lots'] -= matched_lots
                    if open_trade['lots'] == 0: 
                        open_positions[symbol][opposite_dir].pop(0)
            
            # 【过月持仓处理】：当有单子要平，但在当前导入的文件里找不到开仓记录时
            if lots_to_close > 0: 
                prop_profit = profit * (lots_to_close / lots) if lots > 0 else 0.0
                prop_comm = commission * (lots_to_close / lots)
                record = TradeRecord(
                    trade_id=trade_id, 
                    account=account_name, 
                    symbol=symbol,
                    direction='LONG' if opposite_dir == '买' else 'SHORT',
                    entry_time=trade_date, # 找不到历史开仓，暂时将进场日设为平仓日
                    exit_time=trade_date,
                    lots=lots_to_close, 
                    net_profit=prop_profit, 
                    commission=prop_comm
                )
                matched_trades.append(record)
                
    return matched_trades