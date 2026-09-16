# data/akshare_feed.py
import akshare as ak
import pandas as pd
import logging
from datetime import datetime

from core.utils import MINUTE_PERIODS, normalize_period

# 系统内部统一的标准量价列名 (Canonical OHLCV Schema)
OHLCV_COLUMNS = ['date', 'open', 'high', 'low', 'close', 'volume']

# 新浪/东财日线接口的中文列名统一映射 (兼容两个接口不同时期的列名)
KLINE_CN_RENAME = {
    '日期': 'date', '开盘': 'open', '收盘': 'close', '最高': 'high', '最低': 'low', '成交量': 'volume',
    '开盘价': 'open', '收盘价': 'close', '最高价': 'high', '最低价': 'low',
}

# 东财接口超时上限 (秒)：作为兜底源时不允许无限期挂起
EM_TIMEOUT_SECONDS = 15

# ★v6.23：东财 `stock_zh_a_hist` 的「成交量」单位是**手**（1 手 = 100 股），新浪是**股**。
# 【为什么必须统一】两个源混进同一个分区就会出现 100× 的量能台阶（实据：本机 300750 的
#   历史 2018-07-20..2026-04-30 是"手"、2026-05-06 之后是"股"，量柱在接缝处突变 ×159 ——
#   用户看到的就是"大面积显示错误"）。单位是两个接口的**已知事实**，不是猜。
EM_VOLUME_UNIT = 100

# OHLC 里必须存在的价格列（缺一即该行不可用）
_PRICE_COLUMNS = ('open', 'high', 'low', 'close')


def em_volume_to_shares(df: pd.DataFrame) -> pd.DataFrame:
    """东财兜底源的「成交量」由**手**换算成**股**（`×EM_VOLUME_UNIT`），列名不变。

    单独抽成纯函数（而不是塞在请求里）：① 便于断言"换算只做一次、列缺失时不崩"；
    ② 让"单位统一"这件事在源码里有一个**唯一可搜索的落点**（§10-9 单一来源）。
    """
    if df is None or df.empty or '成交量' not in df.columns:
        return df
    out = df.copy()
    out['成交量'] = pd.to_numeric(out['成交量'], errors='coerce') * EM_VOLUME_UNIT
    return out


def drop_unusable_price_rows(df: pd.DataFrame, label: str = "") -> pd.DataFrame:
    """丢掉**价格不可用**的行（非正价 / 缺价），并**出声**记录（v6.23 物理护栏）。

    【为什么要有它】实据：300750 的本地历史里出现过 `open=-4.03 / close=-0.68`（历史遗留
    口径的产物）。一根负价会把主图 y 轴拽到负数区、**整张图被压扁** —— 用户描述为
    "大面积显示错误"。这类行在任何口径下都无意义，所以入口处直接拦掉。

    ⚠ **不静默**：丢弃行数写进 logger.warning，并把前几个日期打在日志里（§10-4）。
    """
    cols = [c for c in _PRICE_COLUMNS if c in df.columns]
    if not cols:
        return df
    prices = df[cols]
    bad = prices.isna().any(axis=1) | (prices <= 0).any(axis=1)
    count = int(bad.sum())
    if not count:
        return df
    stamp = ""
    if "date" in df.columns:
        try:
            stamp = " 日期示例: " + ", ".join(
                pd.to_datetime(df.loc[bad, "date"]).dt.strftime("%Y-%m-%d").head(5).tolist())
        except Exception:  # noqa: BLE001 —— 仅日志，失败不影响主流程
            stamp = ""
    logging.warning(f"[数据护栏] {label or '未知标的'} 丢弃非正价/缺价行 {count} 行"
                    f"（价格 ≤ 0 或缺失时该行无意义，绝不进数据湖）。{stamp}")
    return df.loc[~bad]

# ==========================================
# 复权口径（v6.13 · P8 复权切换）
# ==========================================
# 取值直接照抄 akshare 的 `adjust` 参数（新浪/东财两家一致），**不要自己造枚举**：
#   ADJUST_QFQ  "qfq" 前复权 —— 全 app 历史默认行为，随除权整体漂移；
#   ADJUST_NONE ""    不复权 —— 保留真实历史成交价（看历史缺口/缺口回补用）。
# ⚠ UI 层**不要**从这里 import（§9-H：ui/ 不得出现 AkShareFeed/本模块依赖）——
#    请用 `data/sync_service.py` 里重新导出的 ADJUST_* 与 `zone_for_adjust()`。
ADJUST_QFQ = "qfq"
ADJUST_NONE = ""

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


def is_stock_code(symbol: str) -> bool:
    """智能识别市场归属：纯 6 位数字为 A 股，含字母为期货。

    【为什么是模块级函数】它是纯判断、无副作用、不联网，
    UI 层可以安全直接引用（与 is_index_symbol 同一手法），
    而**任何真正的抓取**都必须经 data/sync_service.MarketSyncService（§9-H）。
    """
    return str(symbol).strip().isdigit()


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
        # ★v6.23 物理护栏：非正价 / 缺价的行一律不进数据湖（否则一根负价会把整张图压扁）
        df = drop_unusable_price_rows(df, symbol_value)
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
    def _fetch_a_share_via_em(symbol: str, start_date: str, end_date: str,
                              adjust: str = ADJUST_QFQ) -> pd.DataFrame:
        """东财日线 (兜底源)：兼容北交所等新浪未覆盖的标的。

        ★v6.23：出口处把「成交量」从**手**换算成**股**（见 `EM_VOLUME_UNIT`）——
        否则同一分区里会同时存在两种单位，量能副图出现 100× 台阶。
        """
        try:
            df = ak.stock_zh_a_hist(
                symbol=symbol, period="daily", start_date=start_date,
                end_date=end_date, adjust=adjust or "", timeout=EM_TIMEOUT_SECONDS,
            )
            if df is not None and not df.empty and '成交量' in df.columns:
                df = em_volume_to_shares(df)
                logging.info(f"东财兜底源成交量已由「手」换算为「股」(×{EM_VOLUME_UNIT}) [{symbol}]")
            return df if df is not None else pd.DataFrame()
        except Exception as e:
            logging.warning(f"A股日线东财源失败 [{symbol}]: {e}")
            return pd.DataFrame()

    @staticmethod
    def fetch_a_share_daily(symbol: str, start_date: str = "20100101", end_date: str = None,
                            adjust: str = ADJUST_QFQ) -> pd.DataFrame:
        """
        拉取 A 股历史日线数据。

        【数据源路由】主源 = 新浪 (stock_zh_a_daily)，与期货主力接口同源，
        在国内多数网络环境（含受限代理）均可直达；
        新浪失败/无法识别的市场 (如北交所) 自动降级到东财 (stock_zh_a_hist)。
        **两个源都按同一个 `adjust` 取值拉取** —— 复权口径必须整条链路一致，
        否则"主源失败降级"会静默换一种复权（这是最阴的数据事故）。

        :param adjust: `ADJUST_QFQ` 前复权（默认，全 app 既有行为）/
                       `ADJUST_NONE` 不复权（P8 新增，存 `kline_daily_raw` 分区）。
        """
        if not end_date: end_date = datetime.now().strftime("%Y%m%d")
        logging.info(f"开始拉取 A股 {symbol} 日线数据 (adjust={adjust or 'none'})...")

        # 1) 主源：新浪 (需带市场前缀)
        sina_symbol = AkShareFeed._to_sina_stock_symbol(symbol)
        if sina_symbol:
            try:
                df = ak.stock_zh_a_daily(symbol=sina_symbol, start_date=start_date,
                                         end_date=end_date, adjust=adjust or "")
                if df is not None and not df.empty:
                    return AkShareFeed._normalize_ohlcv(df, KLINE_CN_RENAME, symbol)
            except Exception as e:
                logging.warning(f"A股日线新浪源失败 [{sina_symbol}]: {e}")

        # 2) 兜底：东财 (覆盖北交所与新浪暂未支持的标的)
        em_df = AkShareFeed._fetch_a_share_via_em(symbol, start_date, end_date, adjust=adjust)
        if not em_df.empty:
            return AkShareFeed._normalize_ohlcv(em_df, KLINE_CN_RENAME, symbol)

        logging.error(f"A股日线拉取失败: {symbol} (主源与兜底源均未返回数据)")
        return pd.DataFrame()

    @staticmethod
    def fetch_daily_auto(symbol: str, start_date: str = None, end_date: str = None,
                         adjust: str = ADJUST_QFQ) -> pd.DataFrame:
        """
        【智能路由】根据代码形态自动选择数据源。
        纯数字 (600519) -> A股接口；含字母 (RB) -> 期货主力接口。

        :param start_date: 增量拉取起点 (YYYYMMDD)。A股支持；期货主力接口不支持，
                           传入时会被忽略（仍返回全量），由上层统一做合并去重。
        :param adjust: 仅对 A 股有效（期货无复权概念，参数被忽略）—— 见 `fetch_a_share_daily`。
        """
        if is_stock_code(symbol):
            return AkShareFeed.fetch_a_share_daily(symbol, start_date=start_date,
                                                   end_date=end_date, adjust=adjust)
        return AkShareFeed.fetch_futures_daily(symbol)

    # ==========================================
    # 分钟线 (v6.21 · §7-B6 STEP 3 / §7 D3)
    # ==========================================
    # 【立项前实测结论 · 2026-09-16 探针（临时脚本，跑完即删）】
    #   ① 新浪 `stock_zh_a_minute` 可用，**固定回吐最近 1970 根**（实测 600519）：
    #        1m ≈ 9 个交易日 / 5m ≈ 42 / 15m ≈ 124 / 30m ≈ 247 / 60m ≈ 493
    #      ⇒ 各档位**历史深度不同**，所以分钟档位**各自独立取数、绝不本地聚合**
    #        （把 1m 聚合成 5m 只会把历史从 42 天缩到 9 天）。
    #   ② 东财 `stock_zh_a_hist_min_em` 在本机被代理拦截（ProxyError）⇒ **不接入**：
    #        未验证的降级路径等于埋雷 —— 与 §9-H 同源纪律一致（宁可少一条路，
    #        也不要一条从没跑通的路）。
    #   ③ `adjust` 参数**实测不生效**（前复权 vs 不复权逐根比对 1970 根差异 = 0）
    #      ⇒ 分钟**只有一种口径 = 真实成交价（不含复权）**。UI 必须明说这一点，
    #        绝不能把它伪装成"前复权的分钟线"（§5.3 口径唯一直说）。
    MINUTE_FETCH_LIMIT = 1970

    @staticmethod
    def fetch_a_share_minute(symbol: str, period: str = "5m") -> pd.DataFrame:
        """拉取 A 股分钟线（新浪源 · **不复权口径**，见本节头实测结论）。

        :param period: 分钟档位 `1m/5m/15m/30m/60m`（用 `core.utils.normalize_period` 归一）
        :return: 标准列 `date/open/high/low/close/volume`（`date` 含时分秒）；失败/非股票返回空表
        """
        period_key = normalize_period(period)
        if period_key not in MINUTE_PERIODS:
            logging.warning(f"非分钟周期被拒绝: {period}")
            return pd.DataFrame()
        sina_symbol = AkShareFeed._to_sina_stock_symbol(symbol)
        if not sina_symbol:
            logging.warning(f"分钟线仅支持 A 股代码（无法识别的市场）: {symbol}")
            return pd.DataFrame()
        try:
            # 新浪的 period 参数是**纯数字**（"5"），且只认 adjust 语义之外的原始价
            df = ak.stock_zh_a_minute(symbol=sina_symbol, period=period_key[:-1], adjust="")
        except Exception as e:  # noqa: BLE001 —— 网络异常绝不外泄到 UI
            logging.warning(f"A股分钟线拉取失败 [{symbol} {period_key}]: {e}")
            return pd.DataFrame()
        if df is None or df.empty:
            return pd.DataFrame()

        out = AkShareFeed._normalize_ohlcv(df, {"day": "date"}, symbol)
        # 新浪返回的 volume/amount 是字符串，`_normalize_ohlcv` 已按 OHLCV_COLUMNS 转数值；
        # 这里只保留标准六列 + 口算不清的冗余列一律丢掉（分钟表越小越好）。
        keep = [c for c in OHLCV_COLUMNS if c in out.columns]
        return out[keep].tail(AkShareFeed.MINUTE_FETCH_LIMIT).reset_index(drop=True)

    # ==========================================
    # 指数成分股 (批量预下载用)
    # ==========================================
    @staticmethod
    def fetch_index_constituents(code: str) -> pd.DataFrame:
        """
        拉取指数成分股代码列表（如 000300 沪深300 / 000905 中证500）。

        【容错】akshare 的成分股接口历史上换过多次名字，这里按优先级逐个试，
        任一成功即返回；全部失败返回空 DF，由上层提示用户改用其它来源，
        绝不抛异常打断批量任务。
        """
        code = str(code or "").strip()
        if not code:
            return pd.DataFrame()

        candidates = (
            ("index_stock_cons", {"symbol": code}),
            ("index_stock_cons_csindex", {"symbol": code}),
            ("index_stock_cons_sina", {"symbol": code}),
        )
        for func_name, kwargs in candidates:
            func = getattr(ak, func_name, None)
            if func is None:
                continue
            try:
                df = func(**kwargs)
                if df is None or df.empty:
                    continue
                col = next((c for c in df.columns if "代码" in str(c)), None)
                if col is None:
                    continue
                symbols = (df[col].astype(str).str.strip()
                           .str.extract(r"(\d{6})", expand=False).dropna().unique().tolist())
                if symbols:
                    return pd.DataFrame({"symbol": sorted(set(symbols))})
            except Exception as e:  # noqa: BLE001
                logging.warning(f"指数成分股接口 {func_name} 失败 [{code}]: {e}")
        logging.error(f"指数成分股拉取失败: {code} (所有候选接口均不可用)")
        return pd.DataFrame()

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
