# data/market_db.py
import os
import logging
import pandas as pd
from config import settings

logger = logging.getLogger(__name__)

class DataLakeManager:
    """
    工业级数据湖管家 (Enterprise Data Lake Manager)。
    采用“分区治理”理念，完美应对未来无限量、多维度的金融数据扩容需求。
    """
    def __init__(self):
        # 湖区根目录
        self.lake_root = os.path.join(settings.USER_DATA_DIR, "data_lake")
        
        # ==========================================
        # 核心架构：预先规划的未来无限扩容数据区 (Zones)
        # ==========================================
        self.zones = {
            # 1. 核心量价区 (Time-Series)
            "kline_daily": os.path.join(self.lake_root, "kline", "daily"),       # 股票/期货日线
            "kline_min": os.path.join(self.lake_root, "kline", "minute"),        # 未来预留：高频分时
            
            # 2. 宏观与指数区 (Macro & Indexes)
            "index_daily": os.path.join(self.lake_root, "macro", "index"),       # 宽基指数、申万行业指数
            "macro_eco": os.path.join(self.lake_root, "macro", "economy"),       # 宏观经济(CPI, M2, 社融等)
            
            # 3. 财务与基本面区 (Fundamentals)
            "fin_report": os.path.join(self.lake_root, "fundamentals", "report"),# 财报(资产负债表, 利润表, 现金流表)
            "valuation": os.path.join(self.lake_root, "fundamentals", "value"),  # 每日估值(PE, PB, PS, 股息率)
            
            # 4. 另类特色数据区 (Alternative)
            "sentiment": os.path.join(self.lake_root, "alternative", "sent"),    # 市场情绪、资金流向、龙虎榜
            "hot_topic": os.path.join(self.lake_root, "alternative", "hot")      # 东方财富/同花顺热度榜
        }
        
        # 启动时自动建立所有湖区的基础设施
        for path in self.zones.values():
            os.makedirs(path, exist_ok=True)

    def _get_filepath(self, zone: str, filename: str) -> str:
        """精准路由到指定的存储湖区"""
        if zone not in self.zones:
            raise ValueError(f"架构错误：未注册的存储区 '{zone}'。请先在 init 中规划！")
        return os.path.join(self.zones[zone], f"{filename}.parquet")

    def save_data(self, zone: str, filename: str, df: pd.DataFrame) -> bool:
        """
        通用极速落盘接口。
        例如：save_data("kline_daily", "600519", df)
             save_data("valuation", "600519", df)
        """
        if df is None or df.empty:
            return False
            
        filepath = self._get_filepath(zone, filename)
        try:
            df.to_parquet(filepath, engine='pyarrow', index=False)
            return True
        except Exception as e:
            logger.error(f"数据湖落盘失败 [{zone}/{filename}]: {e}")
            return False

    def load_data(self, zone: str, filename: str) -> pd.DataFrame:
        """通用极速加载接口"""
        filepath = self._get_filepath(zone, filename)
        if not os.path.exists(filepath):
            return pd.DataFrame()
            
        try:
            return pd.read_parquet(filepath, engine='pyarrow')
        except Exception as e:
            logger.error(f"数据湖读取失败 [{zone}/{filename}]: {e}")
            return pd.DataFrame()

    def exists(self, zone: str, filename: str) -> bool:
        """
        轻量级存在性探针。
        【性能要点】仅做文件系统检查，绝不触碰 Parquet 实体，
        避免在“判断是否需要联网”时把整个历史文件读进内存。
        """
        return os.path.exists(self._get_filepath(zone, filename))

    def get_latest_date(self, zone: str, filename: str, date_col: str = 'date') -> str:
        """智能增量探测：获取某份数据最近的更新日期"""
        df = self.load_data(zone, filename)
        if df.empty or date_col not in df.columns:
            return "20100101" # 默认从十年前开始拉取
        return pd.to_datetime(df[date_col]).max().strftime("%Y%m%d")