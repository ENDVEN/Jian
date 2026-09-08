# data/market_db.py
import os
import logging
from datetime import datetime

import pandas as pd
import pyarrow.parquet as pq

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

    # ==========================================
    # 清点 / 删除 (v5.8 · §7-A3 数据管理页)
    # ==========================================
    def folder_of(self, zone: str) -> str:
        """该分区在磁盘上的真实目录（供管理页显示路径用）"""
        return self._get_filepath(zone, "").rsplit(os.sep, 1)[0]

    def list_zone(self, zone: str) -> list[str]:
        """列出该分区已缓存的标的名（不含 .parquet 后缀）"""
        folder = self.folder_of(zone)
        if not os.path.isdir(folder):
            return []
        return sorted(
            os.path.splitext(name)[0]
            for name in os.listdir(folder)
            if name.lower().endswith(".parquet")
        )

    def delete_data(self, zone: str, filename: str) -> bool:
        """
        删除单个标的的缓存。

        【Windows 注意】若该文件正被读取（句柄未释放）会抛 PermissionError，
        这里统一捕获为 False 并记日志 —— 上层按"可能被占用"提示用户，
        绝不让一个删除动作把整个管理页搞崩。
        """
        path = self._get_filepath(zone, filename)
        if not os.path.exists(path):
            return False
        try:
            os.remove(path)
            return True
        except PermissionError:
            logger.error(f"数据湖删除失败（文件被占用）[{zone}/{filename}]")
            return False
        except OSError as e:
            logger.error(f"数据湖删除失败 [{zone}/{filename}]: {e}")
            return False

    def clear_zone(self, zone: str) -> tuple[int, int]:
        """清空整个分区，返回 (成功删除数, 总数)"""
        names = self.list_zone(zone)
        ok = sum(1 for name in names if self.delete_data(zone, name))
        return ok, len(names)

    def inventory(self, zone: str, with_dates: bool = True) -> list[dict]:
        """
        清点某个分区：每个标的的行数 / 日期范围 / 体积 / 修改时间。

        【性能要点】行数与日期范围一律从 parquet footer 的元数据与列统计里取，
        **不把数据读进内存** —— 全市场 5000+ 个文件也能在秒级扫完。
        """
        folder = self.folder_of(zone)
        items: list[dict] = []
        if not os.path.isdir(folder):
            return items

        for name in sorted(os.listdir(folder)):
            if not name.lower().endswith(".parquet"):
                continue
            path = os.path.join(folder, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            rows, first, last = (0, None, None)
            if with_dates:
                rows, first, last = self._peek(path)
            items.append({
                "name": os.path.splitext(name)[0],
                "rows": rows,
                "first_date": first,
                "last_date": last,
                "bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            })
        return items

    def zone_stats(self) -> dict:
        """各分区的 (条目数, 字节数) 汇总，供左侧清单显示"""
        stats = {}
        for zone in self.zones:
            folder = self.folder_of(zone)
            count = total = 0
            if os.path.isdir(folder):
                for name in os.listdir(folder):
                    if not name.lower().endswith(".parquet"):
                        continue
                    try:
                        total += os.path.getsize(os.path.join(folder, name))
                        count += 1
                    except OSError:
                        continue
            stats[zone] = {"count": count, "bytes": total}
        return stats

    # ---------------- 内部工具 ----------------
    @staticmethod
    def _peek(path: str) -> tuple[int, str | None, str | None]:
        """只读 parquet footer 取 (行数, 首日, 末日)；任何异常都安全降级为 (0,None,None)"""
        try:
            pf = pq.ParquetFile(path)
            meta = pf.metadata
            rows = meta.num_rows
            names = list(pf.schema_arrow.names)
            if "date" not in names or meta.num_row_groups == 0:
                return rows, None, None

            idx = names.index("date")
            first_rg = meta.row_group(0).column(idx).statistics
            last_rg = meta.row_group(meta.num_row_groups - 1).column(idx).statistics
            first = first_rg.min if (first_rg is not None and first_rg.has_min_max) else None
            last = last_rg.max if (last_rg is not None and last_rg.has_min_max) else None
            return rows, _fmt_day(first), _fmt_day(last)
        except Exception as e:  # noqa: BLE001 —— 清点绝不能因单个坏文件中断
            logger.debug(f"数据湖清点失败，已跳过 [{path}]: {e}")
            return 0, None, None


def _fmt_day(value) -> str | None:
    """把 parquet 统计里的日期值规整成 YYYY-MM-DD；失败返回 None"""
    if value is None:
        return None
    try:
        return pd.to_datetime(value).strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001
        return None