# data/akshare_feed.py
import akshare as ak
import pandas as pd
import logging
from datetime import datetime

# 系统内部统一的标准量价列名 (Canonical OHLCV Schema)
OHLCV_COLUMNS = ['date', 'open', 'high', 'low', 'close', 'volume']

# 新浪/东财日线接口的中文列名统一映射 (兼容两个接口不同时期的列名)
KLINE_CN_RENAME = {
    '日期': 'date', '开盘': 'open', '收盘': 'close', '最高': 'high', '最低': 'low', '成交量': 'volume',
    '开盘价': 'open', '收盘价': 'close', '最高价': 'high', '最低价': 'low',
}

# 东财接口超时上限 (秒)：作为兜底源时不允许无限期挂起
EM_TIMEOUT_SECONDS = 15

# 常用大盘/行业指数预设 (供 UI 下拉 + 名称展示；symbol 即新浪指数接口代码)。
# 分组仅供可读性；顺序即下拉展示顺序。已按真实接口逐一代测确认可用 (2026-09)。
INDEX_PRESETS = {
    # —— 大盘核心 ——
    "sh000001": "上证指数",
    "sz399001": "深证成指",
    "sh000300": "沪深300",
    "sh000905": "中证500",
    "sh000852": "中证1000",
    "sh000906": "中证800",
    # —— 大盘风格/红利 ——
    "sh000016": "上证50",
    "sh000010": "上证180",
    "sh000009": "上证380",
    "sh000015": "上证红利",
    "sh000922": "中证红利",
    # —— 科创 / 创业 / 成长 ——
    "sh000688": "科创50",
    "sh000698": "科创100",
    "sz399006": "创业板指",
    "sz399673": "创业板50",
    "sz399608": "科技100",
    "sz399005": "中小板指",
    "sz399330": "深证100",
    # —— 热门行业 / 主题 ——
    "sz399997": "中证白酒",
    "sz399987": "中证酒",
    "sz399986": "中证银行",
    "sz399975": "证券公司",
    "sz399989": "中证医疗",
    "sz399396": "国证食品饮料",
    "sz399998": "中证军工",
    "sz399995": "中证基建",
    "sh000928": "中证能源",
    "sh000936": "中证电信",
    # —— 北交所 ——
    "bj899050": "北证50",
}


def is_index_symbol(symbol: str) -> bool:
    """粗判是否为新浪指数代码形态：市场前缀(sh/sz/bj) + 6 位数字"""
    sym = str(symbol or "").strip().lower()
    return len(sym) == 8 and sym[:2] in ("sh", "sz", "bj") and sym[2:].isdigit()


class AkShareFeed:
    """
    数据源接入层 (Data Fetcher)。
    专职负责从 AkShare 免费拉取各类金融数据，并清洗成系统统一的标准格式。

    【架构纪律】本类是唯一允许感知 AkShare 接口细节的地方，
    上层 UI 只需调用 fetch_daily_auto()，由本类负责路由到股票或期货接口。
    """

    # ==========================================
    # 花名册 (Roster)
    # ==========================================
    @staticmethod
    def fetch_futures_roster() -> pd.DataFrame:
        """
        国内期货全品种标准花名册。
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
        return pd.DataFrame(list(futures_map.items()), columns=['symbol', 'name'])

    @staticmethod
    def fetch_a_share_roster() -> pd.DataFrame:
        """拉取 A 股全市场代码与名称对照表"""
        logging.info("开始从云端拉取 A股全市场名册...")
        try:
            df = ak.stock_zh_a_spot_em()
            if df.empty: return pd.DataFrame()
            df = df.rename(columns={'代码': 'symbol', '名称': 'name'})[['symbol', 'name']]
            return df[df['symbol'].str.match(r'^\d{6}$')]
        except Exception as e:
            logging.error(f"拉取花名册失败: {str(e)}")
            return pd.DataFrame()

    # ==========================================
    # 日线行情 (Daily K-Line)
    # ==========================================
    @staticmethod
    def is_stock_code(symbol: str) -> bool:
        """智能识别市场归属：纯 6 位数字为 A 股，含字母为期货"""
        return str(symbol).strip().isdigit()

    @staticmethod
    def _normalize_ohlcv(df: pd.DataFrame, rename_map: dict, symbol_value: str) -> pd.DataFrame:
        """
        【统一清洗管道】将任意来源的脏数据规整为系统标准格式。
        - 重命名列名 -> 统一英文
        - 日期转 datetime 并剔除无法解析的行
        - 价格与成交量强制转数值
        - 打上标的标签
        """
        df = df.rename(columns=rename_map)
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        df = df.dropna(subset=['date'])

        for col in OHLCV_COLUMNS[1:]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        df['symbol'] = symbol_value
        return df.reset_index(drop=True)

    @staticmethod
    def fetch_futures_daily(symbol: str) -> pd.DataFrame:
        """
        拉取期货主力连续合约日线数据。
        :param symbol: 根代码，如 "RB"
        """
        root = symbol.upper()
        logging.info(f"开始拉取期货 {root} 主力连续日线数据...")
        try:
            # AkShare/新浪接口中，主力连续合约通常以 0 结尾，如 RB0
            df = ak.futures_main_sina(symbol=f"{root}0")
            if df.empty:
                return pd.DataFrame()
            return AkShareFeed._normalize_ohlcv(df, KLINE_CN_RENAME, root)
        except Exception as e:
            logging.error(f"拉取期货数据失败: {str(e)}")
            return pd.DataFrame()

    @staticmethod
    def _to_sina_stock_symbol(symbol: str) -> str:
        """
        把 6 位 A股代码转换成新浪接口要求的带市场前缀代码。
        - "600519" -> "sh600519" (沪市: 60/68/90 开头)
        - "000001" -> "sz000001" (深市: 00/30/20 开头)
        - 已是 "sh/sz/bj" 前缀的代码原样返回
        - 无法识别的市场返回 "" (交由东财兜底源处理)
        """
        sym = str(symbol).strip()
        if sym[:2].lower() in ('sh', 'sz', 'bj'):
            return sym.lower()
        if not sym.isdigit() or len(sym) != 6:
            return ""
        if sym.startswith(('60', '68', '90', '50', '51', '56', '58', '52')):
            return f"sh{sym}"
        if sym.startswith(('00', '30', '20', '15', '16', '12')):
            return f"sz{sym}"
        return ""

    @staticmethod
    def _fetch_a_share_via_em(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """东财日线 (兜底源)：兼容北交所等新浪未覆盖的标的"""
        try:
            df = ak.stock_zh_a_hist(
                symbol=symbol, period="daily", start_date=start_date,
                end_date=end_date, adjust="qfq", timeout=EM_TIMEOUT_SECONDS,
            )
            return df if df is not None else pd.DataFrame()
        except Exception as e:
            logging.warning(f"A股日线东财源失败 [{symbol}]: {e}")
            return pd.DataFrame()

    @staticmethod
    def fetch_a_share_daily(symbol: str, start_date: str = "20100101", end_date: str = None) -> pd.DataFrame:
        """
        拉取 A 股历史日线数据 (前复权)。

        【数据源路由】主源 = 新浪 (stock_zh_a_daily)，与期货主力接口同源，
        在国内多数网络环境（含受限代理）均可直达；
        新浪失败/无法识别的市场 (如北交所) 自动降级到东财 (stock_zh_a_hist)。
        """
        if not end_date: end_date = datetime.now().strftime("%Y%m%d")
        logging.info(f"开始拉取 A股 {symbol} 日线数据...")

        # 1) 主源：新浪 (需带市场前缀)
        sina_symbol = AkShareFeed._to_sina_stock_symbol(symbol)
        if sina_symbol:
            try:
                df = ak.stock_zh_a_daily(symbol=sina_symbol, start_date=start_date,
                                         end_date=end_date, adjust="qfq")
                if df is not None and not df.empty:
                    return AkShareFeed._normalize_ohlcv(df, KLINE_CN_RENAME, symbol)
            except Exception as e:
                logging.warning(f"A股日线新浪源失败 [{sina_symbol}]: {e}")

        # 2) 兜底：东财 (覆盖北交所与新浪暂未支持的标的)
        em_df = AkShareFeed._fetch_a_share_via_em(symbol, start_date, end_date)
        if not em_df.empty:
            return AkShareFeed._normalize_ohlcv(em_df, KLINE_CN_RENAME, symbol)

        logging.error(f"A股日线拉取失败: {symbol} (主源与兜底源均未返回数据)")
        return pd.DataFrame()

    @staticmethod
    def fetch_daily_auto(symbol: str) -> pd.DataFrame:
        """
        【智能路由】根据代码形态自动选择数据源。
        纯数字 (600519) -> A股接口；含字母 (RB) -> 期货主力接口。
        """
        if AkShareFeed.is_stock_code(symbol):
            return AkShareFeed.fetch_a_share_daily(symbol)
        return AkShareFeed.fetch_futures_daily(symbol)

    # ==========================================
    # 大盘指数日线 (Index Daily) 阶段C
    # ==========================================
    @staticmethod
    def fetch_index_daily(symbol: str, min_date: str = "20050101") -> pd.DataFrame:
        """
        拉取大盘/板块指数历史日线 (新浪源 stock_zh_index_daily)。

        :param symbol: 新浪指数代码，必须带市场前缀，如 "sh000001"(上证) / "sz399001"(深成)
        :param min_date: 裁剪早于该日的数据 (格式 YYYYMMDD)，降低存储与回测开销。
                         注意：仅做截断不减未来，指数数据自 1990 年起全量可得。
        """
        sym = str(symbol or "").strip().lower()
        if not is_index_symbol(sym):
            logging.error(f"指数代码格式错误: {symbol} (需形如 sh000001 / sz399001)")
            return pd.DataFrame()
        logging.info(f"开始拉取指数 {sym} 日线数据...")
        try:
            df = ak.stock_zh_index_daily(symbol=sym)
            if df is None or df.empty:
                return pd.DataFrame()
            # 新浪指数接口已返回标准英文列 date/open/high/low/close/volume；
            # 统一走清洗管道：日期强转 + 数值强转 + 打标 (无中文列需重命名)
            df = AkShareFeed._normalize_ohlcv(df, {}, sym)
            try:
                cutoff = pd.Timestamp(min_date)
                df = df[df['date'] >= cutoff]
            except Exception:
                pass
            return df.reset_index(drop=True)
        except Exception as e:
            logging.error(f"拉取指数日线失败 [{sym}]: {e}")
            return pd.DataFrame()
