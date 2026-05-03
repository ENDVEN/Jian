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
    def fetch_futures_roster() -> pd.DataFrame:
        """
        【新增】国内期货全品种标准花名册。
        期货品种固定，硬编码可实现 0 毫秒极速加载，防断网。
        """
        futures_map = {
            "RB": "螺纹钢", "HC": "热轧卷板", "I": "铁矿石", "JM": "焦煤", "J": "焦炭",
            "FG": "玻璃", "SM": "锰硅", "SF": "硅铁", "ZC": "郑醇", "SA": "纯碱", 
            "CU": "沪铜", "AL": "沪铝", "ZN": "沪锌", "PB": "沪铅", "NI": "沪镍", "SN": "沪锡",
            "AU": "沪金", "AG": "沪银", "SS": "不锈钢",
            "RU": "天然橡胶", "BU": "沥青", "SP": "纸浆", "EG": "乙二醇",
            "TA": "PTA", "MA": "甲醇", "V": "PVC", "PP": "聚丙烯", "L": "塑料", "EB": "苯乙烯",
            "UR": "尿素", "PF": "短纤", "NR": "20号胶",
            "M": "豆粕", "Y": "豆油", "A": "豆一", "B": "豆二", "P": "棕榈油", "C": "玉米", "CS": "玉米淀粉",
            "JD": "鸡蛋", "RM": "菜籽粕", "OI": "菜籽油", "CF": "棉花", "SR": "白糖", "AP": "苹果",
            "CJ": "红枣", "PK": "花生", "LH": "生猪",
            "IF": "沪深300股指", "IH": "上证50股指", "IC": "中证500股指", "IM": "中证1000股指",
            "TS": "2年期国债", "TF": "5年期国债", "T": "10年期国债",
            "SC": "原油", "LU": "低硫燃油", "FU": "燃油"
        }
        df = pd.DataFrame(list(futures_map.items()), columns=['symbol', 'name'])
        return df

    @staticmethod
    def fetch_a_share_roster() -> pd.DataFrame:
        """拉取 A 股全市场代码与名称对照表"""
        logging.info("开始从云端拉取 A股全市场名册...")
        try:
            df = ak.stock_zh_a_spot_em()
            if df.empty: return pd.DataFrame()
            rename_map = {'代码': 'symbol', '名称': 'name'}
            df = df.rename(columns=rename_map)[['symbol', 'name']]
            df = df[df['symbol'].str.match(r'^\d{6}$')]
            return df
        except Exception as e:
            logging.error(f"拉取花名册失败: {str(e)}")
            return pd.DataFrame()

    @staticmethod
    def fetch_futures_daily(symbol: str) -> pd.DataFrame:
        """
        【新增】拉取期货主力连续合约日线数据。
        :param symbol: 根代码，如 "RB"
        """
        logging.info(f"开始拉取期货 {symbol} 主力连续日线数据...")
        try:
            # AkShare/新浪接口中，主力连续合约通常以 0 结尾，如 RB0
            fetch_sym = f"{symbol.upper()}0"
            df = ak.futures_main_sina(symbol=fetch_sym)
            
            if df.empty:
                return pd.DataFrame()
                
            rename_map = {
                '日期': 'date', '开盘价': 'open', '最高价': 'high', 
                '最低价': 'low', '收盘价': 'close', '成交量': 'volume'
            }
            df = df.rename(columns=rename_map)
            df['date'] = pd.to_datetime(df['date'])
            for col in ['open', 'close', 'high', 'low', 'volume']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                    
            df['symbol'] = symbol.upper()
            return df
            
        except Exception as e:
            logging.error(f"拉取期货数据失败: {str(e)}")
            return pd.DataFrame()

    @staticmethod
    def fetch_a_share_daily(symbol: str, start_date: str = "20100101", end_date: str = None) -> pd.DataFrame:
        """拉取 A 股历史日线数据"""
        if not end_date: end_date = datetime.now().strftime("%Y%m%d")
        logging.info(f"开始拉取 A股 {symbol} 日线数据...")
        try:
            df = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
            if df.empty: return pd.DataFrame()
            rename_map = {'日期': 'date', '开盘': 'open', '收盘': 'close', '最高': 'high', '最低': 'low', '成交量': 'volume'}
            df = df.rename(columns=rename_map)
            df['date'] = pd.to_datetime(df['date'])
            for col in ['open', 'close', 'high', 'low', 'volume']:
                if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce')
            df['symbol'] = symbol
            return df
        except Exception as e:
            logging.error(f"拉取数据失败: {str(e)}")
            return pd.DataFrame()