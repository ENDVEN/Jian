# data/sync_service.py
"""
行情同步服务 (Market Sync Service) —— 数据湖「增量维护」的统一门面 (v5.8)。

【为什么要有这一层】
  §9-H 记录的架构债：`ui/views/market.py` 与 `ui/views/backtest.py` 各自直接
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
    · 单批上限保护（防止误触超大规模任务）

【本模块是纯 Python、零 Qt 依赖】
  这样它可被 UI 的 QThread、未来的 CLI 脚本或定时任务原样复用。
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass

import pandas as pd

from data.akshare_feed import AkShareFeed
from data.market_db import DataLakeManager

logger = logging.getLogger(__name__)

# 数据湖分区
ZONE_KLINE = "kline_daily"
ZONE_INDEX = "index_daily"

# 【数据起点】个股/指数的默认拉取起点 = 2010-01-01（全历史）。
# 注意：它与"回测评估窗"(core/backtest.DEFAULT_START_DATE=2016) 是两回事 ——
# 数据窗只管"库里有多少历史"，评估窗只管"从哪天开始算收益"。
# 用 2010 是为了兼容市场行情页的既有行为：该页云端同步历史上就是 2010 起，
# 若收窄会让用户曾经能看到的更早 K 线凭空消失（数据主权/不静默缩水的红线）。
DEFAULT_MIN_DATE = "20100101"


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
    circuit_breaker: int = 12    # 连续失败达到该数即熔断
    skip_fresh: bool = True      # 本地已是最新的直接跳过（断点续传）
    # 【时效判据 = 0】只有"末日 == 今天"才算最新。
    # 不能放宽到 1：否则"昨天收盘后已同步"的标的在今天的收盘后窗口会被误跳过，
    # 永远滞后一天拿不到当日 bar（A 股日线 bar 当天收盘后才发布）。
    # 代价 = 休市/盘中点同步会做一次"空增量"（见 refresh_one 的空增量处理，不算失败）。
    fresh_within_days: int = 0
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
    """行情同步门面：状态查询 + 增量/全量刷新 + 合并去重落盘。

    对外 API:
        status(symbol, zone)          -> {cached, last_date}
        refresh_one(symbol, zone, ...) -> {ok, symbol, rows, added, skipped, message, ...}
    """

    def __init__(self):
        self.lake = DataLakeManager()

    # ==========================================
    # 状态查询
    # ==========================================
    def status(self, symbol: str, zone: str = ZONE_KLINE) -> dict:
        """本地缓存状态（供管理页 / 回测页判断是否需要联网）"""
        symbol = str(symbol or "").strip()
        cached = bool(symbol) and self.lake.exists(zone, symbol)
        return {
            "symbol": symbol,
            "zone": zone,
            "cached": cached,
            "last_date": self.lake.get_latest_date(zone, symbol) if cached else "",
        }

    # ==========================================
    # 单只刷新
    # ==========================================
    def refresh_one(self, symbol: str, zone: str = ZONE_KLINE, force_full: bool = False,
                    min_date: str = None, policy: ThrottlePolicy = None,
                    sleep_fn=time.sleep) -> dict:
        """
        把单个标的同步到最新（或强制全量重拉）。

        :param force_full: True = 忽略本地已有数据，从 min_date 全量重拉。
                           用于修正"前复权历史价格漂移"——增量永远修不回历史，
                           所以这个开关必须保留（UI 上叫「强制全量重拉」）。
        :param min_date:   首次拉取的起点 (YYYYMMDD)，默认 DEFAULT_MIN_DATE(2016-01-01)
        :return: {ok, symbol, zone, rows, added, skipped, first, last, message}
        """
        symbol = str(symbol or "").strip()
        policy = policy or ThrottlePolicy()
        # reason 供 UI 决定"怎么安抚用户"：
        #   "ok"/"fresh"/"no_new"  = 成功或视为成功；
        #   "network"              = 网络类异常（断网/超时/被限流）→ 提示稍后重试；
        #   "no_data"              = 两源都返回空 → 最可能是代码有误 / 已退市 / 长期停牌；
        #   "error"                = 其它异常。
        result = {
            "ok": False, "symbol": symbol, "zone": zone, "rows": 0, "added": 0,
            "skipped": False, "reason": "", "first": None, "last": None, "message": "",
        }
        if not symbol:
            result["message"] = "标的为空"
            return result

        # ---- 1) 本地现状 ----
        old = pd.DataFrame() if force_full else self.lake.load_data(zone, symbol)
        old_rows = 0 if old.empty else len(old)
        start_date = min_date or DEFAULT_MIN_DATE

        if not old.empty and "date" in old.columns:
            try:
                last = pd.to_datetime(old["date"], errors="coerce").max()
                if pd.notna(last):
                    if not force_full and self._is_fresh(last, policy.fresh_within_days) \
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
        incremental = (not force_full and not old.empty)

        policy.sleep(sleep_fn)
        new = pd.DataFrame()
        last_err = "未返回数据"
        last_reason = ""
        attempts = 1 if incremental else (policy.max_retries + 1)
        for attempt in range(attempts):
            try:
                new = self._fetch(symbol, zone, start_date)
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

        # ---- 4) 落盘 ----
        if not self.lake.save_data(zone, symbol, merged):
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
    def _fetch(symbol: str, zone: str, start_date: str) -> pd.DataFrame:
        if zone == ZONE_INDEX:
            return AkShareFeed.fetch_index_daily(symbol, min_date=start_date or DEFAULT_MIN_DATE)
        if zone == ZONE_KLINE:
            return AkShareFeed.fetch_daily_auto(symbol, start_date=start_date)
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
    def _is_fresh(last_date, within_days: int) -> bool:
        try:
            last = pd.to_datetime(last_date)
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


def estimate_seconds(count: int, policy: ThrottlePolicy) -> int:
    """粗略预估批量任务耗时（秒），仅供 UI 提示，不保证精确"""
    return int(count * policy.interval * (1 + policy.jitter / 2))


# ==========================================
# 失败原因分类与"人话"文案
# ==========================================
# 常见网络类错误关键词（akshare 会层层抛出 requests/httpx/urllib 的异常）
_NET_HINTS = (
    "timeout", "timed out", "time out", "connection", "connect", "socket",
    "network", "urlopen", "http error", "ssl", "read timed", "proxy",
    "max retries", "name resolution", "11001", "10060", "remote end",
)


def _classify_error(error: Exception) -> str:
    """异常 -> "network"（网络/超时/被限流）或 "error"（其它）"""
    if isinstance(error, (ConnectionError, TimeoutError, OSError)):
        return "network"
    text = f"{type(error).__name__}: {error}".lower()
    return "network" if any(hint in text for hint in _NET_HINTS) else "error"


def short_fetch_reason(result: dict) -> str:
    """给批量任务的失败清单用：一句话说清这只要怎么归类"""
    reason = (result or {}).get("reason")
    if reason == "network":
        return "网络请求失败（断网 / 超时 / 被限流）"
    if reason == "no_data":
        return "无行情数据（代码有误？或已退市 / 长期停牌）"
    return str((result or {}).get("message", "") or "未知原因")


def friendly_fetch_message(symbol: str, result: dict) -> str:
    """给单个标的后台同步失败时的弹窗用：说明"最可能是什么 + 该怎么办"。

    【背景】退市股（如 600277，2024-06 退市）会因行情源不再提供而取不到数据。
    旧文案一律说"代码不存在 / 网络抖动"，极具误导性 ——
    用户明明没输错，只是该股已经退市了。
    """
    symbol = str(symbol or "")
    reason = (result or {}).get("reason")
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
