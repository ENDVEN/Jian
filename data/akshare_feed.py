# data/akshare_feed.py
import akshare as ak
import pandas as pd
import logging
from datetime import datetime

class AkShareFeed:
    """
    数据源接入层 (Data Fetcher)。
    专职负责从 AkShare 免费拉取各类金融数据，并清洗成系统统一的标准格式。
    """
    
    @staticmethod
    def fetch_a_share_roster() -> pd.DataFrame:
        """
        【新增】拉取 A 股全市场代码与名称对照表 (花名册)
        """
        logging.info("开始从云端拉取 A股全市场名册...")
        try:
            # 调取东方财富的A股实时行情接口，这里包含了所有最新的股票代码和名称
            df = ak.stock_zh_a_spot_em()
            
            if df.empty:
                logging.warning("未能获取到全市场名册。")
                return pd.DataFrame()
                
            # 字段重命名，只提取我们需要的核心元数据
            rename_map = {'代码': 'symbol', '名称': 'name'}
            df = df.rename(columns=rename_map)[['symbol', 'name']]
            
            # 清洗过滤：只保留纯 6 位数字的标准 A 股代码 (剔除板块、指数或退市占位符)
            df = df[df['symbol'].str.match(r'^\d{6}$')]
            
            return df
            
        except Exception as e:
            logging.error(f"拉取花名册失败: {str(e)}")
            return pd.DataFrame()

    @staticmethod
    def fetch_a_share_daily(symbol: str, start_date: str = "20100101", end_date: str = None) -> pd.DataFrame:
        """
        拉取 A 股单只股票的历史日线数据 (前复权)。
        :param symbol: 股票代码，如 "600519" (不带后缀)
        """
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")
            
        logging.info(f"开始从云端拉取 A股 {symbol} 日线数据 ({start_date}-{end_date})...")
        
        try:
            df = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
            
            if df.empty:
                logging.warning(f"未能获取到 {symbol} 的数据。")
                return pd.DataFrame()
                
            rename_map = {
                '日期': 'date',
                '开盘': 'open',
                '收盘': 'close',
                '最高': 'high',
                '最低': 'low',
                '成交量': 'volume',
                '成交额': 'amount',
                '换手率': 'turnover'
            }
            df = df.rename(columns=rename_map)
            
            df['date'] = pd.to_datetime(df['date'])
            for col in ['open', 'close', 'high', 'low', 'volume', 'amount', 'turnover']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                    
            df['symbol'] = symbol
            
            return df
            
        except Exception as e:
            logging.error(f"拉取数据失败: {str(e)}")
            return pd.DataFrame()