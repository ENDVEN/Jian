# data/sync_service.py
"""
行情同步服务 (Market Sync Service) —— 数据湖「增量维护」的统一门面 (v5.8)。

【为什么要有这一层】
  §9-H 记录的架构债：行情页（当时是 `ui/views/market.py`，**v6.12 已删除**、现为
  `ui/views/trading_desk.py`）与 `ui/views/backtest.py` 各自直接
  import `AkShareFeed` 拉数，"本地有没有 → 要不要拉 → 怎么合并 → 怎么落盘"这套流程
  在 UI 层形成了两份实现。本服务把这件事收敛成**唯一一份**，
  UI 只认本门面（§10-3 架构纪律：UI 绝不直接发网络请求 / 直接读写数据湖）。

【温柔抓取策略 · 防封 IP / 限速】
  用户明确要求：批量抓取必须温柔，不能让用户被封 IP 或触发限流。
  因此所有节流参数集中在 `ThrottlePolicy`，且在 UI 上可见可调：
    · 单线程串行 + 可调间隔（默认 0.6s）
    · 间隔随机抖动 ±jitter（打散"机器人固定频率"特征）
    · 失败指数退避重试（1s / 2s / 4s）
    · 连续失败熔断（默认 12 次即停，判定"疑似被限流"）
    · 本地已是最新的自动跳过（断点续传：中断后重跑不重复劳动）
      —— ★v1.40/§7-E5：「最新」以**真交易日历里最近一个已收盘定稿的交易日**为准
      （由调度层注入 `ThrottlePolicy.expected_latest`），而不是"日历日 == 今天"。
      否则周末 / 节假日 / 盘中会把全池都判成不新鲜，白跑一遍空增量（5400 只 ≈ 50 分钟）。
    · 单批上限保护（防止误触超大规模任务）

【本模块是纯 Python、零 Qt 依赖】
  这样它可被 UI 的 QThread、未来的 CLI 脚本或定时任务原样复用。
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

from core.utils import MINUTE_DEPTH_DAYS, MINUTE_PERIODS, normalize_period
from data.akshare_feed import ADJUST_NONE, ADJUST_QFQ, AkShareFeed
from data.market_db import DataLakeManager

logger = logging.getLogger(__name__)

# 数据湖分区
ZONE_KLINE = "kline_daily"
ZONE_INDEX = "index_daily"
# ★v6.13/P8 复权切换：**不复权**日线单独一个分区（两份数据无法互相推导，只能各存一份）
ZONE_KLINE_RAW = "kline_daily_raw"

# ★v6.21 / §7-B6 STEP 3（= §7 D3 分钟周期）：**分钟线分区**。
# 【为什么单独分区 + 按档位分键】分钟各档位的历史深度不同（实测 1m≈9 天 / 60m≈493 天），
# 同一标的的 1m 与 5m **无法互相推导** ⇒ 必须各存一份。
ZONE_MIN = "kline_min"
MINUTE_KEY_SEP = "@"

# 复权口径（从数据源层重新导出给 UI 用，见本文件头"UI 只认门面"的纪律）
# ⚠ ui/ 必须从这里 import，**禁止**直接 import data.akshare_feed（§9-H 红线）
__all__ = ["MarketSyncService", "ThrottlePolicy", "ADJUST_QFQ", "ADJUST_NONE",
           "ADJUST_CHOICES", "ADJUST_LABELS", "adjust_label", "zone_for_adjust",
           "ZONE_KLINE", "ZONE_KLINE_RAW", "ZONE_INDEX", "ZONE_MIN", "estimate_seconds",
           "format_duration",
           "short_fetch_reason", "friendly_fetch_message", "friendly_constituent_message",
           "looks_like_proxy_error", "abort_reason_text",
           "DEFAULT_MIN_DATE", "MINUTE_PERIODS", "MINUTE_DEPTH_DAYS",
           "minute_key", "split_minute_key",
           "DAILY_SETTLE_HHMM", "is_daily_bar_settled", "DAILY_ZONES"]


def minute_key(symbol: str, period: str) -> str:
    """`(标的, 分钟档位)` -> 数据湖文件名（键）。

    `DataLakeManager` 的"键"就是文件名，所以约定 `600519@5m`。
    ⚠ **页面/UI 只准调本函数**，别自己拼字符串（§11.5-19：跨模块的键必须有规范化入口，
    否则"切了 5m 却读了 1m 那份"这类串档不会报错、只会静默显示错数据）。
    """
    return f"{str(symbol or '').strip()}{MINUTE_KEY_SEP}{normalize_period(period)}"


def split_minute_key(key: str):
    """`600519@5m` -> `("600519", "5m")`；不是分钟键时返回 `(key, "")`。"""
    text = str(key or "")
    if MINUTE_KEY_SEP not in text:
        return text, ""
    symbol, _, period = text.rpartition(MINUTE_KEY_SEP)
    period_key = normalize_period(period)
    if period_key in MINUTE_PERIODS:
        return symbol, period_key
    return text, ""

ADJUST_CHOICES = (ADJUST_QFQ, ADJUST_NONE)
ADJUST_LABELS = {ADJUST_QFQ: "前复权", ADJUST_NONE: "不复权"}


def adjust_label(adjust: str) -> str:
    """复权口径的中文名（未知回落"前复权"，与全局默认一致）。"""
    return ADJUST_LABELS.get(str(adjust or ""), ADJUST_LABELS[ADJUST_QFQ])


def zone_for_adjust(adjust: str) -> str:
    """复权口径 -> 数据湖分区。

    **UI 只认这个函数，别自己拼字符串**（§11.5-19：跨模块的"键"必须有规范化入口，
    否则"切了不复权却读了前复权分区"这类串档不会报错、只会静默显示错数据）。
    """
    return ZONE_KLINE if str(adjust or "").strip().lower() == ADJUST_QFQ else ZONE_KLINE_RAW

# 【数据起点】个股/指数的默认拉取起点 = 2010-01-01（全历史）。
# 注意：它与"回测评估窗"(core/backtest.DEFAULT_START_DATE=2016) 是两回事 ——
# 数据窗只管"库里有多少历史"，评估窗只管"从哪天开始算收益"。
# 用 2010 是为了兼容市场行情页的既有行为：该页云端同步历史上就是 2010 起，
# 若收窄会让用户曾经能看到的更早 K 线凭空消失（数据主权/不静默缩水的红线）。
DEFAULT_MIN_DATE = "20100101"

# ==========================================
# 日线收盘定稿守卫 (v6.45 / §7-B10 STEP 0-1 · 单一真源)
# ==========================================
# 【为什么】盘中同步会把"今天那根未完成 bar"写进日线库，而 `_is_fresh` 只比到"天"、
# 增量起点又是 last+1 永不回补 ⇒ 半根 bar 一旦落库再也刷不掉，污染收盘口径的回测/扫描
# （成交额 / 换手 / 收盘类判定全错且界面看不出）。判据**只此一处**，M1/M2/M3 一律复用。
# 默认 15:05（A 股 15:00 收 + 5 分钟缓冲）；做成常量可配。
DAILY_SETTLE_HHMM = 1505

# 受定稿守卫约束的日线类分区（分钟 `kline_min` 本就是盘中语义，不裁）
DAILY_ZONES = (ZONE_KLINE, ZONE_KLINE_RAW, ZONE_INDEX)


def is_daily_bar_settled(bar_date, now=None, settle_hhmm: int = DAILY_SETTLE_HHMM) -> bool:
    """某根日线 bar 是否已"收盘定稿"（纯函数 · 零 Qt · 零网络）。

    - `bar_date < 今天`  → 恒 True（历史/昨日的日线早已定稿）；
    - `bar_date == 今天` → 仅当 `now >= 今天 settle_hhmm`（默认 15:05）才 True；
    - `bar_date > 今天`  → False（未来日绝不算定稿）。

    :param bar_date: `date` / `datetime` / `pd.Timestamp` / 可被 pandas 解析的日期串
    :param now:      判定时刻（默认 `datetime.now()`；测试可注入假 now）
    """
    now = now or datetime.now()
    try:
        d = pd.Timestamp(bar_date).date()
    except (ValueError, TypeError):  # noqa: BLE001 —— 解析不了即视为未定稿（保守不写）
        return False
    today = now.date()
    if d < today:
        return True
    if d > today:
        return False
    settle = now.replace(hour=settle_hhmm // 100, minute=settle_hhmm % 100,
                         second=0, microsecond=0)
    return now >= settle


def _drop_unsettled_tail(df: pd.DataFrame, now=None,
                         settle_hhmm: int = DAILY_SETTLE_HHMM) -> pd.DataFrame:
    """落盘前裁掉"今天且未定稿"的那一根日线（历史/昨日/盘后当天一律保留）。

    幂等：已定稿或不含今天行时原样返回；无 `date` 列 / 空表原样返回。
    """
    if df is None or df.empty or "date" not in df.columns:
        return df
    now = now or datetime.now()
    today = now.date()
    try:
        dates = pd.to_datetime(df["date"], errors="coerce").dt.date
    except (TypeError, ValueError):  # noqa: BLE001
        return df
    if not (dates == today).any():          # 不含今天 ⇒ 无需判定，直接返回
        return df
    if is_daily_bar_settled(today, now, settle_hhmm):
        return df                            # 今天已定稿 ⇒ 保留当天根
    keep = dates != today
    return df[keep].reset_index(drop=True)


@dataclass
class ThrottlePolicy:
    """温柔抓取策略（防封 IP / 限速）。

    默认值的取舍：宁可慢一点，也不要把用户 IP 搞封 —— 全市场 5000 只按默认
    0.6s 间隔约需 50 分钟，这是"知情且可接受"的代价，UI 会提前把预计耗时显示出来。
    """

    interval: float = 0.6        # 每次请求前的等待秒数
    jitter: float = 0.3          # 间隔随机抖动比例（0.3 = ±30%）
    max_retries: int = 3         # 单只最多重试次数（不含首次）
    backoff_base: float = 1.0    # 指数退避基数：1s → 2s → 4s
    circuit_breaker: int = 12    # 连续失败达到该数即熔断（**任意原因**）
    # ★v1.38 / §7-E2：**代理类失败单独用更小的阈值**（见下）。
    # 【为什么不能共用 12】12 连败是给"偶发网络抖动"留的余量；而本机代理瞬断时
    #   失败率是 100%（§9.3 实测：一轮里**每一只**都报 ProxyError），
    #   12 次 = 白等十几次超时（每次都好几秒）。用户该做的动作是"立刻去查代理"，
    #   不是"等一等" ⇒ 这种失败率必须**提前停手并直说原因**。
    proxy_circuit_breaker: int = 3
    skip_fresh: bool = True      # 本地已是最新的直接跳过（断点续传）
    # 【回退判据（**仅在拿不到日历时**用）= 0】只有"末日 == 今天"才算最新。
    # 不能放宽到 1：否则"昨天收盘后已同步"的标的在今天的收盘后窗口会被误跳过，
    # 永远滞后一天拿不到当日 bar（A 股日线 bar 当天收盘后才发布）。
    fresh_within_days: int = 0
    # ★v1.40 / §7-E5：**注入式"该到哪天"** = 最近一个**已收盘定稿**的交易日（`datetime.date`）。
    # 【为什么必须有】上面那条判据比的是**日历日**，而"今天"不一定是交易日 ——
    #   周末 / 法定节假日 / 盘中（< 15:05 定稿）时"末日 == 今天"永不成立 ⇒
    #   **全池每一只都判为"不新鲜"**，逐只发一次注定返空的请求：
    #   5400 只 × 0.6s ≈ 50 分钟，换来**零变化**（§7-E5 实测复核）。
    #   更刺眼的是：这些场景下 M1/M2/M3 的滞后提示**早已用真交易日历**正确判定"已最新"，
    #   于是"UI 说已最新、下载层却跑满 50 分钟"—— 两把尺子打架，用户看到的就是体验落差。
    # 【为什么是"注入"而不是在这里自己算】`data/trade_calendar` 已依赖本模块
    #   （它 import `is_daily_bar_settled`），本模块反向 import 会**成环**；
    #   且日历**每批只该取一次**（冷缓存时含一次网络），绝不能每只标的都取。
    #   ⇒ 由已持有日历的调度层（`ui/workers.SyncWorker`）注入。
    # 【`None` 的语义】完全回落到 `fresh_within_days` 那套旧判据 ⇒ **零行为变化**（可安全回滚）。
    expected_latest: date | None = None
    max_symbols: int = 20000     # 单批上限保护

    def sleep(self, sleep_fn=time.sleep):
        """按策略等待一次（带抖动）。interval<=0 时不等待"""
        if self.interval <= 0:
            return
        base = self.interval
        if self.jitter:
            base *= random.uniform(1 - self.jitter, 1 + self.jitter)
        sleep_fn(max(0.0, base))


class MarketSyncService:
    """行情同步门面：状态查询 + 增量/全量刷新 + 合并去重落盘 + 名册类查询。

    对外 API:
        status(symbol, zone)          -> {cached, last_date}
        refresh_one(symbol, zone, ...) -> {ok, symbol, rows, added, skipped, message, ...}
        fetch_index_constituents(code) -> {ok, symbols, reason, message}   # v6.9 收编
    """

    def __init__(self):
        self.lake = DataLakeManager()

    # ==========================================
    # 名册类查询（成分股等"名单"，非行情序列）
    # ==========================================
    def fetch_index_constituents(self, index_code: str, policy: ThrottlePolicy = None,
                                 sleep_fn=time.sleep) -> dict:
        """抓取指数成分股名单 —— **联网抓取的唯一入口**（§9-H 红线）。

        【为什么必须收编到这里】成分股不是时间序列（不落数据湖），但它同样是
        **联网抓取**。§9-H 划的红线是"任何联网抓取必须经本门面"—— 若 UI 线程
        自己 `import AkShareFeed` 发请求，就重演了当初 kline 直连的老问题
        （§9-T4-①：`ConstituentsWorker` 曾直接调行情源）。
        收编之后 `ui/` 全层**不再出现 `AkShareFeed` 符号**，且有源码级断言守门。

        :return: {"ok": bool, "symbols": [str], "index_code": str,
                  "reason": "ok"/"no_data"/"network"/"error", "message": str,
                  "count": int, "snapshot_date": str}   # v6.42：只数与快照日供 UI 诚实上报
        """
        index_code = str(index_code or "").strip()
        result = {"ok": False, "symbols": [], "index_code": index_code,
                  "reason": "", "message": "", "count": 0, "snapshot_date": ""}
        if not index_code:
            result["message"] = "未指定指数代码"
            return result

        policy = policy or ThrottlePolicy()
        try:
            # 与行情同步共用同一套温柔节流：名单接口也不破例猛拉
            policy.sleep(sleep_fn)
            df = AkShareFeed.fetch_index_constituents(index_code)
        except Exception as e:  # noqa: BLE001 —— 网络层异常绝不外泄到 UI
            logger.warning(f"指数成分股解析异常 [{index_code}]: {e}")
            result["reason"] = _classify_error(e)
            result["message"] = str(e)
            return result

        symbols = []
        snapshot_date = ""
        if df is not None and not df.empty and "symbol" in df.columns:
            symbols = [str(s).strip() for s in df["symbol"].dropna().tolist() if str(s).strip()]
            if "snapshot_date" in df.columns:
                vals = [str(v).strip() for v in df["snapshot_date"].tolist() if str(v).strip()]
                snapshot_date = max(vals) if vals else ""
        if not symbols:
            # 行情源"没有这个指数的名单"与"网络挂了"是两回事，必须区分（§10-10）
            result.update(reason="no_data", message="接口未返回成分股")
            return result

        result.update(ok=True, symbols=symbols, reason="ok", message="OK",
                      count=len(symbols), snapshot_date=snapshot_date)
        return result

    # ==========================================
    # 状态查询
    # ==========================================
    def status(self, symbol: str, zone: str = ZONE_KLINE, period: str = None) -> dict:
        """本地缓存状态（供管理页 / 回测页判断是否需要联网）。

        :param period: 仅 `zone=ZONE_MIN` 用（分钟按档位各存一份，见 `minute_key`）
        """
        symbol = str(symbol or "").strip()
        key = minute_key(symbol, period) if zone == ZONE_MIN else symbol
        cached = bool(symbol) and self.lake.exists(zone, key)
        return {
            "symbol": symbol,
            "zone": zone,
            "key": key,
            "period": normalize_period(period) if zone == ZONE_MIN else "",
            "cached": cached,
            "last_date": self.lake.get_latest_date(zone, key) if cached else "",
        }

    # ==========================================
    # 单只刷新
    # ==========================================
    def refresh_one(self, symbol: str, zone: str = ZONE_KLINE, force_full: bool = False,
                    min_date: str = None, policy: ThrottlePolicy = None,
                    sleep_fn=time.sleep, period: str = None) -> dict:
        """
        把单个标的同步到最新（或强制全量重拉）。

        :param force_full: True = 忽略本地已有数据，从 min_date 全量重拉。
                           用于修正"前复权历史价格漂移"——增量永远修不回历史，
                           所以这个开关必须保留（UI 上叫「重新全量下载」）。
        :param min_date:   首次拉取的起点 (YYYYMMDD)，默认 DEFAULT_MIN_DATE = **2010-01-01**。
                           ⚠ 注意别写成 2016：2016 是"回测评估窗"
                           (core/backtest.DEFAULT_START_DATE)，不是"数据窗"。
                           数据窗必须保持 2010（个股全历史），写成 2016 会让用户
                           曾经能看到的 2010~2016 K 线凭空消失（§9-M3 回归，勿犯）。
        :return: {ok, symbol, zone, rows, added, skipped, first, last, message}
        """
        symbol = str(symbol or "").strip()
        policy = policy or ThrottlePolicy()
        # reason 供 UI 决定"怎么安抚用户"：
        #   "ok"/"fresh"/"no_new"  = 成功或视为成功；
        #   "proxy"                = **疑似本机代理问题**（v1.38/§7-E2：Requests 的
        #                            ProxyError 也是 OSError 子类，必须**先于** network 判定）
        #                            → 提示去查代理软件，而不是"稍后重试"；
        #   "network"              = 网络类异常（断网/超时/被限流）→ 提示稍后重试；
        #   "no_data"              = 两源都返回空 → 最可能是代码有误 / 已退市 / 长期停牌；
        #   "error"                = 其它异常。
        period_key = normalize_period(period) if zone == ZONE_MIN else ""
        # 分钟按档位各存一份 ⇒ 湖里的键 = `600519@5m`；而 `result["symbol"]` 仍回**纯标的**
        # （页面用它做竞态守卫，§9-O5 —— 页面不需要知道键的存在）。
        key = minute_key(symbol, period_key) if zone == ZONE_MIN else symbol
        result = {
            "ok": False, "symbol": symbol, "zone": zone, "key": key, "period": period_key,
            "rows": 0, "added": 0,
            "skipped": False, "reason": "", "first": None, "last": None, "message": "",
        }
        if not symbol:
            result["message"] = "标的为空"
            return result

        # ---- 1) 本地现状 ----
        old = pd.DataFrame() if force_full else self.lake.load_data(zone, key)
        old_rows = 0 if old.empty else len(old)
        start_date = min_date or DEFAULT_MIN_DATE

        if not old.empty and "date" in old.columns:
            try:
                last = pd.to_datetime(old["date"], errors="coerce").max()
                if pd.notna(last):
                    # ⚠ 分钟**不做"已最新就跳过"**：它的"最新"精确到分钟（盘中每分钟都在变），
                    # 而 `_is_fresh` 只比到"天" ⇒ 盘中会把 10:00 的旧快照当成"已是今天=最新"。
                    # 分钟快照单只约 5 秒，宁可每次都真拉一次（用户点同步就是要最新）。
                    if zone != ZONE_MIN and not force_full \
                            and self._is_fresh(last, policy.fresh_within_days,
                                               policy.expected_latest) \
                            and policy.skip_fresh:
                        result.update(ok=True, skipped=True, rows=old_rows,
                                      first=self._first_day(old), last=last.strftime("%Y-%m-%d"),
                                      reason="fresh", message="本地已是最新，已跳过")
                        return result
                    # 增量起点 = 本地末日 + 1 天（多留一点重叠，方便前复权修正）
                    start_date = (last + pd.Timedelta(days=1)).strftime("%Y%m%d")
            except Exception as e:  # noqa: BLE001
                logger.debug(f"本地末日解析失败 [{symbol}]: {e}")

        # ---- 2) 拉取（温柔节流 + 指数退避重试）----
        # 增量模式（本地已有数据）下的"空返回"通常意味着：周末 / 节假日 / 当日 bar 尚未发布。
        # 那不是失败，不该重试、更不该计入熔断 —— 直接按"已最新"返回。
        # ⚠ 分钟：新浪固定回吐"最近 1970 根"整段快照 ⇒ 永远按"首次拉取"语义对待
        # （空返回 = 真失败，保留退避重试 + 熔断计数），绝不把网络故障美化成"已是最新"。
        incremental = (not force_full and not old.empty and zone != ZONE_MIN)

        policy.sleep(sleep_fn)
        new = pd.DataFrame()
        last_err = "未返回数据"
        last_reason = ""
        attempts = 1 if incremental else (policy.max_retries + 1)
        for attempt in range(attempts):
            try:
                new = self._fetch(symbol, zone, start_date, period_key)
            except Exception as e:  # noqa: BLE001 —— 网络层异常绝不外泄到 UI
                new = pd.DataFrame()
                last_err = str(e)
                last_reason = _classify_error(e)
            if not new.empty:
                break
            if attempt < attempts - 1:
                sleep_fn(policy.backoff_base * (2 ** attempt))

        if new.empty:
            if incremental:
                old_last = self._last_day(old) or ""
                result.update(ok=True, skipped=True, rows=old_rows,
                              first=self._first_day(old), last=old_last,
                              reason="no_new",
                              message="增量区间无新数据（休市 / 当日未开盘；"
                                      "若长期如此，该股可能已退市或长期停牌）")
                return result
            result["reason"] = last_reason or "no_data"
            result["message"] = last_err
            return result

        # ---- 3) 合并去重（新数据优先，便于顺带修正前复权漂移）----
        merged = new if (force_full or old.empty) else self._merge(old, new)

        # ---- 3.5) 定稿守卫（§7-B10 STEP 1）：日线类分区落盘前裁掉"今天未定稿"那根 ----
        # ⚠ v1.40/§7-E5 后这是**第二道防线**（第一条是"日历感知的新鲜度判据"）：
        #   · 有日历时（`expected_latest` 非 None）盘中根本不会走到这里 —— 末日已 >= 上一交易日
        #     ⇒ 直接 `fresh` 跳过，连请求都不发；
        #   · 无日历时（None，回落旧判据）盘中会拉到今天半根 bar，仍由这里裁掉。
        # 两条路径的**自洽终点一致**：盘后本地末日=上一交易日 ⇒ 不跳过 ⇒ 起点=昨天+1=今天
        # ⇒ 拉到完整当天并落库（无需改增量起点语义）。
        if zone in DAILY_ZONES:
            merged = _drop_unsettled_tail(merged)

        # ---- 4) 落盘 ----
        if not self.lake.save_data(zone, key, merged):
            result["message"] = "落盘失败"
            return result

        result.update(
            ok=True, rows=len(merged), added=max(0, len(merged) - old_rows),
            first=self._first_day(merged), last=self._last_day(merged),
            reason="ok", message="OK",
        )
        return result

    # ==========================================
    # 内部实现
    # ==========================================
    @staticmethod
    def _fetch(symbol: str, zone: str, start_date: str, period: str = None) -> pd.DataFrame:
        if zone == ZONE_MIN:
            # 分钟：新浪接口**不吃 start_date**（固定回吐最近 1970 根），
            # 所以"增量"在分钟上退化为"整段快照 + 合并去重"（见 refresh_one 的 _merge）。
            return AkShareFeed.fetch_a_share_minute(symbol, period=period or "5m")
        if zone == ZONE_INDEX:
            return AkShareFeed.fetch_index_daily(symbol, min_date=start_date or DEFAULT_MIN_DATE)
        if zone == ZONE_KLINE_RAW:
            # 复权切换（v6.13）：同一套源、换一个 adjust；期货无复权概念，参数被忽略
            return AkShareFeed.fetch_daily_auto(symbol, start_date=start_date,
                                                adjust=ADJUST_NONE)
        if zone == ZONE_KLINE:
            return AkShareFeed.fetch_daily_auto(symbol, start_date=start_date,
                                                adjust=ADJUST_QFQ)
        return pd.DataFrame()

    @staticmethod
    def _merge(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
        """旧 + 新 合并去重（同日以新数据为准），按日期升序。

        【为什么要 keep='last'】A 股是前复权数据，同一天的历史价格可能已被修正。
        让新数据覆盖旧数据，等于"每次增量顺带把重叠区间刷新一遍"。
        """
        both = pd.concat([old, new], ignore_index=True)
        both["date"] = pd.to_datetime(both["date"], errors="coerce")
        both = both.dropna(subset=["date"])
        both = both.drop_duplicates(subset=["date"], keep="last")
        return both.sort_values("date").reset_index(drop=True)

    @staticmethod
    def _is_fresh(last_date, within_days: int, expected_latest=None) -> bool:
        """本地末日是否已"新鲜到不用再拉"。

        ★v1.40/§7-E5：`expected_latest`（最近一个**已收盘定稿**的交易日）给定时，
        改判 `last >= expected_latest` —— 这才是"该到哪天"的**唯一真源**，
        与 M1/M2/M3 的滞后提示**同一把尺子**（`data.trade_calendar.latest_settled_trading_day`）。
        未给定时保持**旧语义**（`(今天 - last).days <= within_days`），零行为变化。

        【为什么"大于等于"也要算新鲜】本地末日可能**超过** expected（例如用户手动
        「重新全量下载」拉到过更近的 bar、或日历缓存落后）—— 那更不该拦。
        """
        try:
            last = pd.to_datetime(last_date)
            if pd.isna(last):
                return False
            if expected_latest is not None:
                exp = pd.to_datetime(expected_latest)
                if pd.isna(exp):
                    return False
                return last.normalize() >= exp.normalize()
            return (pd.Timestamp.today().normalize() - last.normalize()).days <= within_days
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _first_day(df: pd.DataFrame):
        try:
            value = pd.to_datetime(df["date"], errors="coerce").min()
            return None if pd.isna(value) else value.strftime("%Y-%m-%d")
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _last_day(df: pd.DataFrame):
        try:
            value = pd.to_datetime(df["date"], errors="coerce").max()
            return None if pd.isna(value) else value.strftime("%Y-%m-%d")
        except Exception:  # noqa: BLE001
            return None


def estimate_seconds(count: int, policy: ThrottlePolicy, stale_count: int = None) -> int:
    """粗略预估批量任务耗时（秒），仅供 UI 提示，不保证精确。

    ★v1.40/§7-E5：`stale_count`（**真正会发请求**的只数）给定时按它算 ——
    已新鲜的一只不发请求、零耗时。旧版一律按 `count` 算，于是哪怕该干的是 0 件，
    界面也永远显示"约 50 分钟"（**等于把用户劝退**，§7-E5 实测复核）。
    未给定时保持旧语义：结果视为**上限**（调用方应据此说"最多约…"）。
    """
    n = count if stale_count is None else max(0, int(stale_count))
    return int(n * policy.interval * (1 + policy.jitter / 2))


def format_duration(seconds) -> str:
    """把预估秒数说成人话（`45 秒` / `12 分钟` / `1.5 小时`）—— **唯一出口**。

    ★v1.40/§7-E5：批量弹窗与 M2/M3 的二次确认都要说"大概多久"。
    别在 UI 里各写一遍（§11.5：跨模块的**展示口径**同样必须有单一出口，
    否则同一件事在两个页面会显示成两种说法）。
    """
    seconds = max(0, int(seconds or 0))
    if seconds < 60:
        return f"{seconds} 秒"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.0f} 分钟"
    return f"{minutes / 60:.1f} 小时"


# ==========================================
# 失败原因分类与"人话"文案
# ==========================================
# 常见网络类错误关键词（akshare 会层层抛出 requests/httpx/urllib 的异常）
_NET_HINTS = (
    "timeout", "timed out", "time out", "connection", "connect", "socket",
    "network", "urlopen", "http error", "ssl", "read timed", "proxy",
    "max retries", "name resolution", "11001", "10060", "remote end",
)

# ★v1.38 / §7-E2：**本机代理问题**的指纹（与 _NET_HINTS **分开**，见下面 _classify_error 的说明）
_PROXY_HINTS = (
    "proxyerror",                      # requests.exceptions.ProxyError 的类名
    "unable to connect to proxy",      # 实测报错原文（§9.3）
    "cannot connect to proxy",
    "proxy",                           # 兜底：消息里出现 proxy 这个词基本就是代理问题
)


def _error_text(value) -> str:
    """异常 / 文本 -> 小写文本（分类判据的唯一取值方式，避免各处各写一遍格式化）"""
    if isinstance(value, BaseException):
        return f"{type(value).__name__}: {value}".lower()
    return str(value or "").lower()


def looks_like_proxy_error(value) -> bool:
    """是不是**本机代理问题**的失败指纹（v1.38 / §7-E2）—— 纯函数，文案层与熔断层共用。

    【为什么要单独一个判据】§9.3 实测：本机系统代理（Clash 类）瞬断时，
    一轮同步里**每一只**都报 `ProxyError('Unable to connect to proxy')`。
    用户该做的动作是"**去查代理软件**"，而不是"稍后重试 / 调大间隔" ——
    与普通断网、被限流**必须分开安抚**（§10-10）。

    :param value: 异常实例，或已经是文本（大小写不敏感）
    """
    text = _error_text(value)
    return any(hint in text for hint in _PROXY_HINTS)


def _classify_error(error: Exception) -> str:
    """异常 -> "proxy"（疑似本机代理问题）/ "network"（网络/超时/被限流）/ "error"（其它）。

    ⚠⚠ **判定顺序是有讲究的，别随手调换**：
      `requests.exceptions.ProxyError` 继承自 `requests.exceptions.ConnectionError`
      → `RequestException` → `IOError`(**就是内建 OSError**)。
      所以若先走 `isinstance(error, (..., OSError))`，代理失败会被**先归成 network**
      —— 这正是 §9.3 里"文案归类没错、但用户看不出该去查代理"的真实成因。
      ⇒ **必须先看文本指纹，再退回 isinstance**。
    """
    text = _error_text(error)
    if looks_like_proxy_error(text):
        return "proxy"
    if isinstance(error, (ConnectionError, TimeoutError, OSError)):
        return "network"
    return "network" if any(hint in text for hint in _NET_HINTS) else "error"


def short_fetch_reason(result: dict) -> str:
    """给批量任务的失败清单用：一句话说清这只要怎么归类"""
    reason = (result or {}).get("reason")
    if reason == "proxy":
        return "疑似本机代理问题（请检查代理软件是否在运行）"
    if reason == "network":
        return "网络请求失败（断网 / 超时 / 被限流）"
    if reason == "no_data":
        return "无行情数据（代码有误？或已退市 / 长期停牌）"
    return str((result or {}).get("message", "") or "未知原因")


# 【代理文案的唯一出处】三处（单个标的弹窗 / 成分股弹窗 / 批量回执）共用同一套措辞。
# ⚠ **绝不写死 `127.0.0.1:7897`**：那是诊断记录（§9.3）里**某一台机器**的端口，
#   写进用户文案就是对新用户撒谎；端口只留在 §9.3 的历史记录里。
_PROXY_WHAT = ("本机系统代理（Clash / V2Ray 等）在同步过程中断连，或中途切换了节点。"
               "这类失败的特征是：短时间内每一只都报同一句「无法连接代理」的错误。"
               "（这不是行情源挂了、也不是被限流，所以「稍后重试」通常没用，先查代理。）")


def friendly_fetch_message(symbol: str, result: dict) -> str:
    """给单个标的后台同步失败时的弹窗用：说明"最可能是什么 + 该怎么办"。

    【背景】退市股（如 600277，2024-06 退市）会因行情源不再提供而取不到数据。
    旧文案一律说"代码不存在 / 网络抖动"，极具误导性 ——
    用户明明没输错，只是该股已经退市了。
    """
    symbol = str(symbol or "")
    reason = (result or {}).get("reason")
    if reason == "proxy":
        return (f"{symbol} 未能同步：疑似本机代理问题。\n\n"
                f"最可能是什么：{_PROXY_WHAT}\n\n"
                f"怎么办：① 检查代理软件是否在运行、规则是否覆盖了行情域名；\n"
                f"② 切换节点后重试；③ 若不需要代理，可临时关闭系统代理再同步。")
    if reason == "network":
        return (f"{symbol} 未能同步：网络请求失败。\n\n"
                f"可能原因：① 当前断网；② 请求超时；③ 请求过于频繁被行情源临时限流。\n"
                f"建议稍后重试；批量任务请调大「同步间隔」。")
    if reason == "no_data":
        return (f"{symbol} 未返回任何行情数据。\n\n"
                f"可能原因：① 代码/名称输入有误；\n"
                f"② 该股已退市或长期停牌，行情源不再提供（属正常现象，本地已缓存的历史仍可用）；\n"
                f"③ 次新/特殊标的，两个行情源暂未收录。")
    return (f"{symbol} 未能同步：{result.get('message', '未知原因')}\n\n"
            f"建议稍后重试；若反复失败请到「🗄 数据管理」查看是否已停止更新。")


def friendly_constituent_message(index_code: str, result: dict) -> str:
    """指数成分股解析失败时的人话提示（§10-10：分类安抚，而非统一吓唬）。

    同样区分"网络类失败"与"行情源本来就没收录这个指数" —— 后者不是用户的错，
    且明确告诉他可行的替代来源。
    """
    index_code = str(index_code or "")
    reason = (result or {}).get("reason")
    if reason == "proxy":
        return (f"未能获取 {index_code} 的成分股：疑似本机代理问题。\n\n"
                f"最可能是什么：{_PROXY_WHAT}\n\n"
                f"怎么办：① 检查代理软件是否在运行；② 切换节点后重试；\n"
                f"③ 若不需要代理，可临时关闭系统代理再解析。")
    if reason == "network":
        return (f"未能获取 {index_code} 的成分股：网络请求失败。\n\n"
                f"可能原因：① 当前断网；② 请求超时；③ 请求过于频繁被临时限流。\n"
                f"建议稍后重试。")
    if reason == "no_data":
        return (f"未能获取 {index_code} 的成分股：行情源未返回名单。\n\n"
                f"可能原因：① 代码有误；② 该指数不在行情源收录范围内"
                f"（部分行业/主题指数常缺）；③ 接口临时变更。\n"
                f"建议：改用「粘贴代码列表」或「全市场 A 股」。")
    return (f"未能获取 {index_code} 的成分股：{result.get('message', '未知原因')}\n\n"
            f"建议：① 稍后重试；② 改用「粘贴代码列表」或「全市场 A 股」。")


def abort_reason_text(stats: dict) -> str:
    """批量任务**被中断的原因**（一句话，不带括号；没被中断返回空串）。

    【为什么做成公共件】`SyncWorker` 的 `finished` 回包有三个消费方
    （批量预下载弹窗 / 数据管理页 / M2-M3 的更新与补齐），
    三处各写一遍"（已中断）"就会漏 —— 代理中断必须**说清为什么提前停**，
    否则用户只看到一个"已中断"，还是不知道该去查代理（§11.5-11 同类防护做全套）。
    """
    stats = stats or {}
    if not stats.get("aborted"):
        return ""
    if stats.get("aborted_by") == "proxy":
        return "疑似本机代理问题，已提前停手以免白等（请检查代理软件）"
    if stats.get("aborted_by") == "cancel":
        return "已被你中断"
    return "连续失败过多，已停手保护（疑似被限流）"


def failure_hint(stats: dict) -> str:
    """“为什么会有标的没下到”的**教学文案 = 唯一出口**。

    【为什么收成公共件】旧版这段在批量预下载弹窗与数据管理页**各写一份**，
    而且两份已经不一致（一份列了“④ 代理”，另一份没列）—— 同一类防护只改一处
    必然漏另一处（§11.5-11）。代理类失败要**前置**说出来：它是唯一
    “重试无用、必须先去查代理”的原因（§7-E2）。
    ⚠ 依旧不许写死本机端口（§9.3 / §11.5-76③）。
    """
    stats = stats or {}
    base = ("常见原因：① 代码输入有误；② 该股已退市 / 长期停牌，"
            "行情源不再提供（属正常现象）；③ 网络抖动或被限流。")
    if stats.get("aborted_by") == "proxy":
        return ("④ 本机代理软件断连 —— 表现为短时间每一只都失败，"
                "请先检查代理软件（重试无用）。\n" + base)
    return base
