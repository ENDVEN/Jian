# data/akshare_feed.py
import akshare as ak
import pandas as pd
import logging
import time
from datetime import datetime

from core.utils import MINUTE_PERIODS, normalize_period
from data import em_market

# ★v6.69：东财 `push2` 的**两条取数通道**（分页全市场列表 / 批量报价）已整块搬到
#   `data/em_market.py`（§11.7：本文件再长就该分文件），退避闸门在 `data/em_throttle.py`。
#   唯一变化是**规模**：企业版旧写法每次同步/扫描都会翻 ~56 页的全市场列表，
#   而新的批量报价**按标的取**（单只 1 个请求）⇒ 不再与行业分页互抢匿名额度（§11.5-100）。
#   下面两个常量保留为**别名**（旧调用点/文档/断言仍可引用，语义与 em_market 同源）。
INDUSTRY_PAGE_SIZE = em_market.EM_PAGE_SIZE
INDUSTRY_FS_A = em_market.EM_FS_A

# 系统内部统一的标准量价列名 (Canonical OHLCV Schema)
OHLCV_COLUMNS = ['date', 'open', 'high', 'low', 'close', 'volume']

# ★v1.39 / §7-E3：**落盘列白名单**（数据湖里"允许存在"的列，唯一出处）
# 【为什么要有它】v6.33 实测 + v1.39 复核实测（420 个日线文件）：`_normalize_ohlcv` 只 rename、
#   **不裁列** ⇒ 三类杂列进湖：① 新浪源透传 `turnover` / `outstanding_share`；
#   ② 东财兜底的中文列（`股票代码`/`成交额`/`振幅`/`涨跌幅`/`涨跌额`/`换手率`，1 个文件）；
#   ③ 期货列 `持仓量` / `动态结算价`（5 个文件）。
#   对照：**分钟路径有显式裁剪**（见 `fetch_a_share_minute` 的 `keep`），日线没有 ——
#   不对称就是漂移的开始（§9.1）。
# 【为什么白名单里必须有 amount / turnover / outstanding_share】**它们是下游的"受支持列"**：
#   `core/cross_section._BASE_COLUMNS` 恒读 `amount`，`columns_for()` 在启用换手率 / 流通市值
#   筛选时会读 `turnover` / `outstanding_share` —— 裁掉会让这两项筛选**当场全变「数据不足」**
#   （正是 §9.1 警告的"静默失效"）。§7-E3 拍板 P2：**保留**。
# 【为什么是 apply-if-present】各分区的列集合本来就不同（v1.39 实测：`index_daily` **无** `amount`、
#   `kline_min` 只有 6 列**无** `symbol`）⇒ 只"保留存在的白名单列"，**绝不 require**。
# 【本项明确不做】不给东财兜底源把 `成交额→amount` / `换手率→turnover` 做映射：东财 `换手率`
#   是**百分数**(0.93)、新浪 `turnover` 是**小数**(0.0093)，直接映射会把 **100× 口径**混进同一列
#   （§9-V 最怕的事故）；要做得先定单位换算 + 断言，属独立一环（§7-E3「不做」）。
DAILY_KEEP_COLUMNS = tuple(OHLCV_COLUMNS) + ('symbol', 'amount', 'turnover',
                                             'outstanding_share')

# 新浪/东财日线接口的中文列名统一映射 (兼容两个接口不同时期的列名)
KLINE_CN_RENAME = {
    '日期': 'date', '开盘': 'open', '收盘': 'close', '最高': 'high', '最低': 'low', '成交量': 'volume',
    '开盘价': 'open', '收盘价': 'close', '最高价': 'high', '最低价': 'low',
}

# ★v1.45 / §7-B11 后续：**全市场当日快照**（spot_em）→ 系统标准列的映射与裁剪。
# 【单位归一是本路径的命门】§9-V / §7-E3 最怕的 100× 事故：
#   · 成交量：东财 spot = **手** → 落库前 ×`EM_VOLUME_UNIT` 成「股」（与历史日线同分区一致）；
#   · 换手率：东财 spot = **百分数**(0.93) → ÷100 成**小数**(0.0093)（对齐新浪 `turnover`）；
#   · 成交额：元 → `amount`；流通市值：元 → `outstanding_share`（换手率/市值筛选下游所需）；
#   · 最新价：收盘后 == 当天 `close`（spot 是**不复权**真实价，qfq 最新一根本就等于真实价，
#     故**只追加当天这一根**自洽；⚠ 绝不用于回填历史复权段）。
# 快照无"哪一天"列 ⇒ 本映射**不含 date**（"该算哪天"由上层用真交易日历决定）。
SPOT_DAILY_RENAME = {
    '代码': 'symbol', '今开': 'open', '最高': 'high', '最低': 'low', '最新价': 'close',
    '成交量': 'volume', '成交额': 'amount', '换手率': 'turnover', '流通市值': 'outstanding_share',
    # ★v6.67：**昨收** —— 只当"今天有没有除权/除息"的**闸门**用（见 sync_service._try_apply_spot）：
    #   除权日的"昨收"是**除权调整后**的昨收（行情商的通行约定，否则当日涨跌幅会显示成 -30%），
    #   所以"快照昨收 != 本地最后一根收盘" ⇒ 今天发生除权 ⇒ **spot 秒补必须让路**。
    #   ⚠ 它**不在** `DAILY_KEEP_COLUMNS` 里 ⇒ 永远不会被写进数据湖（只是判据，不是数据）。
    '昨收': 'prev_close',
}
SPOT_DAILY_KEEP = ('symbol', 'open', 'high', 'low', 'close', 'volume', 'amount',
                   'turnover', 'outstanding_share', 'prev_close')

# ★P5 / §7-B12：全市场**当前估值快照**（供 M2 结果表 B 层列）——与日线秒补同一 spot_em 接口，
#   但只取非价量的估值字段，**绝不进 kline_daily**（那不是 bar）。都是"当前值"，上层仅在
#   基准日==数据最新交易日时才用，否则显 '—'（诚实口径，§5.3 / 三态铁律同源）。
SPOT_VALUATION_RENAME = {'代码': 'symbol', '市盈率-动态': 'pe', '市净率': 'pb', '总市值': 'total_mktcap'}
SPOT_VALUATION_KEEP = ('symbol', 'pe', 'pb', 'total_mktcap')

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


def normalize_cons_code(code: str) -> str:
    """成分股接口的代码规范化：`sh000300` / `SZ399006` / `000300` → **6 位纯数字**。

    【为什么必须有这一步】本项目并存**两套指数代码约定**：指数**日线**接口要
    带市场前缀（`sh000300`，见 `fetch_index_daily` / `INDEX_PRESETS`），而成分股
    三个候选接口（`index_stock_cons*`）只要 **6 位纯数字** —— M2/M3 的指数下拉
    复用了 `INDEX_PRESETS` 的带前缀键，直接透传会让三个接口**全部失败**
    （2026-09-20 用户实测抓到：选沪深300 每次都"接口未返回成分股"，而裸码正常）。
    规范化收在**行情源边界**这一处（§11.5-19：跨模块共享的键必须有规范化函数），
    调用方（M2 / M3 / 批量预下载）零改动。
    """
    text = str(code or "").strip().lower()
    if is_index_symbol(text):
        return text[2:]
    return text


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

    @staticmethod
    def fetch_market_spot_daily(symbols=None) -> pd.DataFrame:
        """★v6.69 / §7-B11 后续：**按标的**批量取"当天"日线快照（供秒补当天这一根）。

        【为什么改】旧写法 = `ak.stock_zh_a_spot_em()` —— 它内部 `pz=100` + **逐页翻**，
          **本身就是一串 ~56 页的隐藏突发**；而它与行业分页**同时开火**（一次扫描完成起两串）
          ⇒ 把东财**匿名额度**自己打光（§11.5-100，用户实测两条 4 秒内一起失败）。
          新写法走 `em_market.fetch_quotes()`：**一次可带 100 只** ⇒ 单只同步 = **1 个请求**、
          几百只池子 = 2~3 个请求（东财 `ulist.np/get` 实测字段齐全）。
        :param symbols: 标的清单；**None/空 ⇒ 回空表**（本通道不做"全市场一把抓"；
                        调用方据此诚实回退逐只真拉，绝不因快照挂了而中断整批）
        返回标准列 `SPOT_DAILY_KEEP`（**不含 date**，"该算哪天"由上层用真交易日历决定）；
        成交量已×`EM_VOLUME_UNIT`换算成股、换手率已÷100 归一为小数，非正价/缺价行已剔除。
        ⚠ 本方只做"取数 + 单位归一"这一件事；能否落库/落到哪个分区/定稿与否全在上层。
        """
        df = em_market.fetch_quotes(symbols)
        if df is None or df.empty:
            return pd.DataFrame(columns=list(SPOT_DAILY_KEEP))
        out = df[[c for c in SPOT_DAILY_KEEP if c in df.columns]].copy()
        if out.empty:                                    # 一个受支持列都没映上 ⇒ 诚实回空
            return pd.DataFrame(columns=list(SPOT_DAILY_KEEP))
        out = drop_unusable_price_rows(out, "spot批量报价")   # 同一道物理护栏
        return out.reset_index(drop=True)

    @staticmethod
    def fetch_market_spot_valuation(symbols=None) -> pd.DataFrame:
        """★v6.69：**按标的**批量取当前估值（市盈率-动态/市净率/总市值），供 M2 B 层列。

        返回列 `SPOT_VALUATION_KEEP`（symbol + pe + pb + total_mktcap，元）。**这是"当前值"、
        不是历史** ⇒ 上层只在基准日==数据最新交易日时才用，否则 '—'。
        `symbols` 为空 ⇒ 回空表（不联网）；失败（网络/接口变更）⇒ 回**空表**（上层诚实留空）。
        ⚠ 不进 kline_daily（非价量 bar）。
        """
        df = em_market.fetch_quotes(symbols)
        if df is None or df.empty:
            return pd.DataFrame(columns=list(SPOT_VALUATION_KEEP))
        out = df[[c for c in SPOT_VALUATION_KEEP if c in df.columns]].copy()
        if 'symbol' not in out.columns or out.empty:
            return pd.DataFrame(columns=list(SPOT_VALUATION_KEEP))
        return out.reset_index(drop=True)

    @staticmethod
    def fetch_industry_map() -> dict:
        """★P6：抓全市场「代码→细分行业」映射（东财行业板块成分，~80+ 次请求，一次性）。

        返回 `{symbol: 板块名}`。任一板块失败 ⇒ 跳过该板块（不毁整表）；全失败回 `{}`。
        ⚠ 成本高 ⇒ 上层缓存进 `industry_map.json`、后台刷新，**扫描时只读缓存不联网**。
        """
        try:
            boards = ak.stock_board_industry_name_em()
        except Exception as e:  # noqa: BLE001
            logging.warning(f"行业板块列表拉取失败: {e}")
            return {}
        if boards is None or boards.empty or '板块名称' not in boards.columns:
            return {}
        out: dict = {}
        for name in boards['板块名称'].astype(str).tolist():
            try:
                cons = ak.stock_board_industry_cons_em(symbol=name)
            except Exception as e:  # noqa: BLE001 —— 单板块失败不影响其余
                logging.warning(f"行业成分拉取失败[{name}]: {e}")
                continue
            if cons is None or cons.empty or '代码' not in cons.columns:
                continue
            for code in cons['代码'].astype(str).tolist():
                code = code.strip()
                if len(code) == 6 and code.isdigit():
                    out[code] = name
        return out

    # ==========================================
    # ★v6.68：全市场「代码→行业」**分页直取**（替代上面的 80+ 连击）
    #   ★v6.69：实现整块搬到 `data/em_market.py`（本文件只留门面）—— 同一份退避闸门
    #   （`data/em_throttle.py`）管住"分页通道"与"批量报价通道"，别再各写一套。
    # ==========================================
    @staticmethod
    def fetch_industry_page(page_start: int = 1, pages: int = 1, **kwargs) -> dict:
        """全市场「代码→所属行业」**分页直取**（东财 `clist` 的 `f100`）—— 转发 `data/em_market`。

        **契约不变**（老调用点/断言无需改）：分批（`pages`）、页间隔、单页失败**不上抛**，
        返回 `{"map", "page_start", "pages_done", "total_pages", "done", "error"}`；
        `kwargs` 可传 `sleep_fn` / `interval` / `should_stop`（关窗取消用）。
        """
        return em_market.fetch_industry_page(page_start, pages, **kwargs)

    # ==========================================
    # 交易日历 (Trading Calendar)  v6.45 / §7-B10
    # ==========================================
    @staticmethod
    def fetch_trade_calendar() -> pd.DataFrame:
        """拉取 A 股全历史交易日历（新浪源），清洗成单列 `date`（升序 datetime）。

        只负责"接口细节 + 清洗"这一件事；缓存 / 回退 / 判定在 `data/trade_calendar.py`。
        ⚠ 异常一律**向上抛**（不在这里吞），由调用方决定回退（拿不到日历≠网络故障都算失败）。
        """
        logging.info("开始从云端拉取交易日历...")
        df = ak.tool_trade_date_hist_sina()
        if df is None or df.empty:
            return pd.DataFrame(columns=['date'])
        col = 'trade_date' if 'trade_date' in df.columns else df.columns[0]
        out = pd.DataFrame({'date': pd.to_datetime(df[col], errors='coerce')}).dropna()
        return out.sort_values('date').reset_index(drop=True)

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
        - ★v1.39/§7-E3 **裁列**：只留 `DAILY_KEEP_COLUMNS` 里存在的列（把源透传的杂列挡在湖外）
        - 打上标的标签
        """
        df = df.rename(columns=rename_map)
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        df = df.dropna(subset=['date'])

        for col in OHLCV_COLUMNS[1:]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        df['symbol'] = symbol_value
        # ★v1.39/§7-E3 落盘前**裁列**（唯一白名单）：对齐分钟路径的做法，让"湖里的列集合"
        # 从"各源碰运气"变成"一处说了算"。⚠ apply-if-present（只减不增）——
        # `index_daily` 无 amount、`kline_min` 无 symbol 都是**正常**的，绝不 require。
        # ⚠ 位置在 `symbol` 赋值**之后**：白名单含 symbol，所以日线类分区照常带上它；
        #   而分钟路径接下来还会用 OHLCV_COLUMNS 再裁一次（symbol 被去掉）⇒ **分钟行为不变**。
        df = df[[c for c in DAILY_KEEP_COLUMNS if c in df.columns]]
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

        【代码规范】入参**兼容两种形态**（`sh000300` / `000300`），内部先经
        `normalize_cons_code` 归一成 akshare 要的 6 位纯数字 —— M2/M3 的指数下拉
        用的是 `INDEX_PRESETS` 的带前缀键（2026-09-20 用户实测：不规范化时三个
        候选接口全部失败，表现为"接口未返回成分股"）。

        【候选顺序 = 可信度排序（v6.42，用户实测驱动）】
        ① `index_stock_cons_csindex`（**中证指数官网**）：权威名单、给满 300/500 只，
           带「日期」快照列 ⇒ 诚实上报"名单是哪天的"；
        ② `index_stock_cons`（同花顺快照）：实测**缺斤短两**（沪深300→288 / 中证500→429），
           降为兜底；③ 新浪再兜底。旧顺序把同花顺排第 1 ⇒ "有效只数比指数名义少一截"
           的谜团根因就在这。

        【返回】`symbol` 列 + `snapshot_date` 列（官网「日期」/同花顺「纳入日期」的
        最大值；拿不到就留空串 —— 诚实，不猜）。

        【容错】akshare 的成分股接口历史上换过多次名字，这里按优先级逐个试，
        任一成功即返回；全部失败返回空 DF，由上层提示用户改用其它来源，
        绝不抛异常打断批量任务。
        """
        code = normalize_cons_code(code)
        if not (len(code) == 6 and code.isdigit()):
            logging.error(f"指数成分股代码格式不对: {code!r}"
                          f"（应为 6 位数字，如 000300；兼容 sh000300 形态）")
            return pd.DataFrame()

        candidates = (
            ("index_stock_cons_csindex", {"symbol": code}),
            ("index_stock_cons", {"symbol": code}),
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
                # ★ 选列必须精确（v6.42 回归教训）：官网 csindex 的 df 里也有「指数代码」列，
                #   旧逻辑"第一个含'代码'的列"会命中它 ⇒ 把指数自己当成唯一成分
                #   （用户实测：选沪深300 ⇒ "名单 1 只 · 缺 000300"）。
                #   先按权威列名精确找，再退"含代码但不含指数"的列 —— 绝不拿指数码当名单。
                col = next((c for c in df.columns
                            if str(c).strip() in ("成分券代码", "品种代码", "构成代码", "代码")),
                           None)
                if col is None:
                    col = next((c for c in df.columns
                                if "代码" in str(c) and "指数" not in str(c)), None)
                if col is None:
                    continue
                symbols = (df[col].astype(str).str.strip()
                           .str.extract(r"(\d{6})", expand=False).dropna().unique().tolist())
                if symbols:
                    symbols = sorted(set(symbols))
                    # 快照日期：官网「日期」/ 同花顺「纳入日期」—— 哪个列名在就用哪个
                    snap = ""
                    date_col = next((c for c in df.columns
                                     if str(c).strip() in ("日期", "纳入日期")), None)
                    if date_col is not None:
                        try:
                            vals = pd.to_datetime(df[date_col], errors="coerce").dropna()
                            if len(vals):
                                snap = str(vals.max().date())
                        except (TypeError, ValueError):  # noqa: BLE001 —— 日期列坏不连累名单
                            snap = ""
                    logging.info(f"指数成分股 [{code}] 来自 {func_name}: "
                                 f"{len(symbols)} 只，快照 {snap or '未知'}")
                    return pd.DataFrame({"symbol": symbols,
                                         "snapshot_date": [snap] * len(symbols)})
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
