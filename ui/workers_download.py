# ui/workers_download.py
"""批量下载 / 网络自检 / 缓存清理 / 更新检查类 QThread（★2.04 / P2 拆件）。"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd
from PyQt6.QtCore import QThread, pyqtSignal

from data.daily_store import merge_row, normalize_snapshot, write_snapshot
from data.sync_service import (MarketSyncService, ThrottlePolicy, ZONE_KLINE,
                               is_daily_bar_settled, network_self_check, short_fetch_reason)
from data.trade_calendar import (latest_settled_trading_day, previous_trading_day)
from ui.workers_throttle import (RateGovernor, _load_calendar_safely,
                                 inject_expected_latest)

logger = logging.getLogger(__name__)

__all__ = ["SyncWorker", "DailySnapshotWorker", "NetSelfCheckWorker",
           "CacheCleanWorker", "UpdateCheckWorker"]


def _resolve_worker_dep(name: str, fallback):
    """惰性取 `ui.workers.<name>`（兼容拆件前在门面上打的桩）。"""
    try:
        from ui import workers as _workers_mod
        return getattr(_workers_mod, name, fallback)
    except Exception:  # noqa: BLE001
        return fallback


class SyncWorker(QThread):
    """批量同步若干标的（数据管理页 / 预下载弹窗 / M2-M3 更新共用）

    信号：
        progress(done, total, symbol)
        failed(symbol, reason)
        finished(summary)   # {ok, fail, skipped, added, aborted, aborted_by, symbols_failed}
                            #   aborted_by ∈ ""/"cancel"/"proxy"/"circuit"（v1.38/§7-E2）
                            #   ⇒ 消费方用 `sync_service.abort_reason_text(stats)` 出人话，别各写一遍

    ★v1.44 / §7-B11 后续：`policy.concurrency > 1` 时走**批内并发池**（本类内部用
      `ThreadPoolExecutor` 编排现成的 `refresh_one`，数据层仍纯同步、零 Qt）；
      并发只发生在**单个 job 内部**（任务级仍由 DownloadHub 串行 K=1）。`concurrency <= 1`
      时逐字节走旧串行（裸构造 / 单测 / 回滚开关）。熔断与代理计数改为**跨线程共享**。
    """

    progress = pyqtSignal(int, int, str)
    failed = pyqtSignal(str, str)
    finished = pyqtSignal(dict)

    def __init__(self, symbols, zone: str = ZONE_KLINE, force_full: bool = False,
                 min_date: str = None, policy: ThrottlePolicy = None, parent=None):
        super().__init__(parent)
        self._symbols = [str(s).strip() for s in (symbols or []) if str(s).strip()]
        self._zone = zone
        self._force_full = force_full
        self._min_date = min_date
        self._policy = policy or ThrottlePolicy()
        self._cancel = False
        self._spot_ctx = None                  # ★v1.45：循环外取好的全市场快照上下文（或 None）

    # 供 UI 的「中断」按钮调用
    def cancel(self):
        self._cancel = True

    def _log_throughput(self, done: int, total: int) -> None:
        """★1.92 / F：**实测吞吐**（每 100 只记一行）—— 回答"到底哪里慢"。

        为什么要它：`estimate_seconds` 只能给理论值（N × interval）。真实环境还有
        源的响应延迟、重试、限流降档；只有实测 `只/秒` 能证明"瓶颈是不是只在间隔"。
        """
        if not done or done % 100:
            return
        t0 = getattr(self, "_t0", None)
        if not t0:
            return
        dt = max(1e-9, time.monotonic() - t0)
        rate = done / dt
        eta = (total - done) / rate if rate > 0 else 0.0
        logger.info("[吞吐] %d/%d 只 · 已用 %.1fs · 实测 %.2f 只/秒 · 按实测剩余约 %.0fs",
                    done, total, dt, rate, eta)

    def run(self):
        # ★2.04：兼容旧打桩点 `ui.workers.MarketSyncService`（拆件不改变测试边界）
        service = _resolve_worker_dep("MarketSyncService", MarketSyncService)()
        # ★v1.92 / F：吞吐计时的起点（只用于日志，不改任何调度）
        self._t0 = time.monotonic()
        # ★v1.45：日历一次取，inject 与 spot 共用（保证“每批只取一次”，§7-E5）
        calendar = _load_calendar_safely()
        policy = inject_expected_latest(self._policy, calendar=calendar)
        # ★v1.45 / §7-B11 后续：daily qfq job 且非盘中 ⇒ 1 次全市场快照，秒补“只差当天”那根
        self._spot_ctx = self._build_spot_ctx(service, policy, calendar)
        stats = {"ok": 0, "fail": 0, "skipped": 0, "added": 0, "spot_hit": 0,
                 "aborted": False, "aborted_by": "", "symbols_failed": [],
                 # ★v6.70 / §9-F②：**真正跑过一只请求**的清单（含“已最新跳过”）——
                 #   它是“中断后还剩哪些没碰”的**唯一正确依据**：`done` 只是计数，
                 #   并发下与提交顺序无关 ⇒ 拿 `symbols[done:]` 切会同时漏抓与重抓。
                 "symbols_attempted": [],
                 "total": len(self._symbols)}
        if (policy.concurrency or 1) > 1:
            self._run_pool(service, policy, stats)
        else:
            self._run_serial(service, policy, stats)
        # ★1.92 / F：收尾一行"实测账"（只/秒 + 当时的 interval/K）—— 下次再问"为什么慢"先看这行
        try:
            _dt = max(1e-9, time.monotonic() - self._t0)
            _n = len(stats.get("symbols_attempted") or [])
            stats["elapsed_s"] = round(_dt, 2)
            stats["per_sec"] = round(_n / _dt, 3)
            logger.info("[吞吐] 收尾：%d 只 / %.1fs = %.2f 只/秒（interval %.2fs · K=%s）",
                        _n, _dt, stats["per_sec"], policy.interval, policy.concurrency)
        except Exception as e:                 # noqa: BLE001 —— 日志不许影响收尾
            logger.debug("吞吐收尾日志失败: %s", e)
        self.finished.emit(stats)

    # ---- ★v1.45：全市场快照上下文（一次取、跨只复用；不满足安全前提 ⇒ None）----
    def _build_spot_ctx(self, service, policy, calendar):
        """daily qfq 且“无未定稿盘中会话”时，取 1 次全市场快照供逐只秒补当天。

        任一安全前提不满足 ⇒ 返回 None（整批退回逐只网络增量，零风险）：
          · 非 ZONE_KLINE（raw/分钟/指数）/ force_full ⇒ 不做；
          · 无日历 / expected_latest 缺失 ⇒ 无法安全判“只缺一根” ⇒ 不做；
          · 今天是交易日且未到定稿点（盘中）⇒ spot 是半截当日，写了脏 ⇒ 不做；
          · 快照接口不存在（打桩）/ 拉回空 ⇒ 不做。
        """
        if self._zone != ZONE_KLINE or self._force_full:
            return None
        if policy is None or getattr(policy, "expected_latest", None) is None:
            return None
        if not calendar:
            return None
        snap_fn = getattr(service, "fetch_spot_snapshot", None)
        if snap_fn is None:
            return None
        now = datetime.now()
        today = now.date()
        try:
            if (today in set(calendar)) and not is_daily_bar_settled(today, now):
                return None                    # 盘中：spot 是半截当日，绝不用
            prev = previous_trading_day(policy.expected_latest, calendar)
        except Exception:  # noqa: BLE001 —— 日历判定异常 ⇒ 保守不开秒补
            return None
        if prev is None:
            return None
        snap = snap_fn(self._symbols)
        if not snap:
            return None
        return {"prev": prev, "snap": snap}

    def _spot_kwargs(self, symbol):
        """给 `refresh_one` 的 spot 透传参（无 ctx ⇒ 空 ⇒ 走网络增量）。"""
        ctx = getattr(self, "_spot_ctx", None)
        if not ctx:
            return {}
        return {"spot_bar": ctx["snap"].get(symbol), "spot_prev": ctx["prev"]}

    # ---- 串行快路径（== v1.43 及以前的既有行为，零漂移）----
    def _run_serial(self, service, policy, stats):
        total = len(self._symbols)
        consecutive_fail = 0
        consecutive_proxy = 0

        for index, symbol in enumerate(self._symbols, start=1):
            if self._cancel:
                stats.update(aborted=True, aborted_by="cancel")
                break

            self.progress.emit(index, total, symbol)
            self._log_throughput(index, total)      # ★1.92 / F
            result = service.refresh_one(
                symbol, zone=self._zone, force_full=self._force_full,
                min_date=self._min_date, policy=policy, **self._spot_kwargs(symbol))
            stats["symbols_attempted"].append(symbol)     # ★v6.70 §9-F②：发了请求才算“碰过”

            if result.get("skipped"):
                stats["skipped"] += 1
                consecutive_fail = 0
                consecutive_proxy = 0
            elif result.get("ok"):
                stats["ok"] += 1
                stats["added"] += int(result.get("added", 0))
                if result.get("reason") == "spot":
                    stats["spot_hit"] = stats.get("spot_hit", 0) + 1
                consecutive_fail = 0
                consecutive_proxy = 0
            else:
                stats["fail"] += 1
                consecutive_fail += 1
                if str(result.get("reason") or "") == "proxy":
                    consecutive_proxy += 1          # ★v1.38/§7-E2：代理类失败单独计数
                else:
                    consecutive_proxy = 0
                stats["symbols_failed"].append(symbol)
                # 给 UI 一条"一句话归类"（代理 / 网络 / 无数据·退市？），避免技术报错直接甩给用户
                self.failed.emit(symbol, short_fetch_reason(result))
                # ★【代理全灭 ⇒ 提前停手】§9.3 实测：本机代理瞬断时失败率是 100%，
                #   按默认 12 连败熔断等于白等十几次超时；用户的正确动作是"立刻去查代理"。
                if consecutive_proxy >= max(1, policy.proxy_circuit_breaker):
                    stats.update(aborted=True, aborted_by="proxy")
                    break
                # 【温柔抓取·熔断】其余原因的连续失败过多判定为"疑似被限流"，主动停手保护用户 IP
                if consecutive_fail >= max(1, policy.circuit_breaker):
                    stats.update(aborted=True, aborted_by="circuit")
                    break

    # ---- 批内并发池（★v1.44 / §7-B11 后续）----
    def _run_pool(self, service, policy, stats):
        total = len(self._symbols)
        governor = RateGovernor()
        throttle = governor.throttle          # 作为共享 sleep_fn 注入 refresh_one
        lock = threading.Lock()
        stop = threading.Event()               # 熔断/取消 ⇒ 未启动的任务直接跳过
        done = [0]                             # 已完成计数（锁内自增，跨线程单调）
        consec = {"fail": 0, "proxy": 0}       # 连续失败计数（**跨线程共享**）
        breaker = max(1, policy.circuit_breaker)
        pbreaker = max(1, policy.proxy_circuit_breaker)

        def one(symbol):
            if stop.is_set() or self._cancel:
                return                          # 已停 ⇒ 排队任务不再发请求（保留真实进度）
            result = service.refresh_one(
                symbol, zone=self._zone, force_full=self._force_full,
                min_date=self._min_date, policy=policy, sleep_fn=throttle,
                **self._spot_kwargs(symbol))
            fail_reason = None
            with lock:
                done[0] += 1
                d = done[0]
                stats["symbols_attempted"].append(symbol)   # ★v6.70 §9-F②（与串行路径同口径）
                if result.get("skipped"):
                    stats["skipped"] += 1
                    consec["fail"] = consec["proxy"] = 0
                elif result.get("ok"):
                    stats["ok"] += 1
                    stats["added"] += int(result.get("added", 0))
                    if result.get("reason") == "spot":
                        stats["spot_hit"] = stats.get("spot_hit", 0) + 1
                    consec["fail"] = consec["proxy"] = 0
                else:
                    stats["fail"] += 1
                    consec["fail"] += 1
                    if str(result.get("reason") or "") == "proxy":
                        consec["proxy"] += 1
                    else:
                        consec["proxy"] = 0
                    stats["symbols_failed"].append(symbol)
                    fail_reason = short_fetch_reason(result)
                    trip_by = ""
                    if consec["proxy"] >= pbreaker:
                        trip_by = "proxy"
                    elif consec["fail"] >= breaker:
                        trip_by = "circuit"
                    if trip_by:
                        stats.update(aborted=True, aborted_by=trip_by)
                        stop.set()               # 任一线程达阈 ⇒ 全体收手
            self.progress.emit(d, total, symbol)
            self._log_throughput(d, total)          # ★1.92 / F（锁外，别占着锁写日志）
            if fail_reason is not None:
                self.failed.emit(symbol, fail_reason)

        # ★1.78：上限从**硬编码 4** 改成唯一常量 `MAX_DOWNLOAD_CONCURRENCY`（=8，用户 2026-10-16 拍板）
        #   —— 以前这个 4 与设置页/偏好夹取处的 4 是三处**各写一遍**，改一处漏两处是迟早的事。
        from data.sync_service import MAX_DOWNLOAD_CONCURRENCY as _MAXC
        workers = max(1, min(int(policy.concurrency), _MAXC, total or 1))
        ex = ThreadPoolExecutor(max_workers=workers)
        try:
            for symbol in self._symbols:
                ex.submit(one, symbol)
        finally:
            # ★1.70 / §11.5-124：收尾两条口径，**互不可少**：
            #   ① `wait=True`（照旧）：每一笔网络请求现在都有**硬超时**（`data/net_env` 在 requests
            #      层注入默认 20s）⇒ 在途那只**最迟 20 秒必然返回**，收尾自然有界，不会再出现
            #      "永远收不了尾 / 点中断毫无反应 / 关窗也卡住"。**真正的解药是超时，不是不等。**
            #      ⚠ 别改成本质上的"不等"：那会让 `finished` 在在途请求还没回来时就发出
            #        （"完成 = 全干完"的语义被打破、统计收尾后还在变），冒烟并发断言会红。
            #   ② `cancel_futures` **只在真的要停时才给 True**（用户点了中断 / 已熔断）⇒ 排队的立刻停发。
            #      ⚠ **绝不能无条件给 True**：正常跑完时它会把**还没启动**的任务直接取消
            #        （实测 5 只只跑 3 只 —— 冒烟"每只都收到 sleep_fn"断言红的根因，属静默漏抓）。
            _stopping = bool(self._cancel) or bool(stats.get("aborted"))
            ex.shutdown(wait=True, cancel_futures=_stopping)
        if self._cancel and not stats.get("aborted"):
            stats.update(aborted=True, aborted_by="cancel")   # 与串行一致：用户中断单独归类


class DailySnapshotWorker(QThread):
    """★2.05 / DATA-PLATFORM P1：**全市场日快照** → 每只一行合并进历史。

    与 `SyncWorker` 的区别：不再逐只发网络请求。全市场走东财 `clist`（56 页 / 约 52s），
    小池走 `ulist`（100 只/批）；随后只做本地文件合并（实测 5000 只约 30–50s）。
    这样日更总耗时目标 <2 分钟，而旧路径是 5000 次单只历史请求（约 80 分钟）。

    安全口径：
    - 快照先原子落盘（可恢复/审计），再逐只合并；
    - 只有“本地末日 == 上一交易日 且 快照昨收 == 本地收盘”才直接追加；
    - 缺口 / 除权 / 缺昨收 ⇒ 退回 `refresh_one` 单只修复，绝不把错误价格抄进历史；
    - 本地已 >= asof ⇒ 跳过。
    """

    progress = pyqtSignal(int, int, str)
    failed = pyqtSignal(str, str)
    finished = pyqtSignal(dict)

    def __init__(self, symbols, policy: ThrottlePolicy = None, parent=None):
        super().__init__(parent)
        self._symbols = [str(s).strip() for s in (symbols or []) if str(s).strip()]
        self._policy = policy or ThrottlePolicy()
        self._cancel = False

    def cancel(self):
        self._cancel = True

    @staticmethod
    def _asof(calendar):
        try:
            d = latest_settled_trading_day(calendar=calendar)
        except Exception:  # noqa: BLE001 —— 日历坏了就回退今天，绝不阻断
            d = None
        return pd.Timestamp(d).normalize() if d is not None else pd.Timestamp.today().normalize()

    @staticmethod
    def _can_append(old: pd.DataFrame, rec: dict, asof: pd.Timestamp, calendar) -> bool:
        """只有“本地恰好缺 asof 这一天、且昨收一致”才允许直接追加。"""
        if old is None or len(old) == 0:
            return True                      # 首次：先落当天一根，历史由后台补
        try:
            data = old.copy()
            data["date"] = pd.to_datetime(data["date"], errors="coerce")
            data = data.dropna(subset=["date"]).sort_values("date")
            if data.empty:
                return True
            last = data.iloc[-1]
            last_day = pd.Timestamp(last["date"]).normalize()
            if last_day >= asof:
                return False
            prev = previous_trading_day(asof.date(), calendar)
            if prev is None or last_day != pd.Timestamp(prev).normalize():
                return False
            prev_close = rec.get("prev_close")
            last_close = last.get("close")
            if prev_close is None or last_close is None:
                return False
            prev_close = float(prev_close)
            last_close = float(last_close)
            if last_close <= 0:
                return False
            return abs(prev_close - last_close) / last_close <= 1e-3
        except Exception:  # noqa: BLE001 —— 判不了就走单只真拉
            return False

    def run(self):
        service = _resolve_worker_dep("MarketSyncService", MarketSyncService)()
        calendar = _load_calendar_safely()
        policy = inject_expected_latest(self._policy, calendar=calendar)
        asof = self._asof(calendar)
        stats = {"ok": 0, "fail": 0, "skipped": 0, "added": 0,
                 "aborted": False, "aborted_by": "", "symbols_failed": [],
                 "symbols_attempted": [], "total": len(self._symbols),
                 "mode": "daily_snapshot", "asof": asof.strftime("%Y-%m-%d")}
        try:
            # 全市场（>=3000）才扫 56 页；500–2999 用 ulist 按池取，避免为小池拉全市场
            if len(self._symbols) >= 3000:
                snap = service.fetch_market_snapshot(
                    should_stop=lambda: self._cancel,
                    fallback_symbols=self._symbols)
            else:
                got = service.fetch_spot_snapshot(self._symbols, allow_fallback=True)
                snap = pd.DataFrame(list(got.values())) if got else pd.DataFrame()
            snap = normalize_snapshot(snap, asof)
            if self._cancel:
                stats.update(aborted=True, aborted_by="cancel")
                self.finished.emit(stats)
                return
            if snap.empty:
                stats["fail"] = len(self._symbols)
                self.failed.emit("", "日快照为空（网络/接口/非交易日）")
                self.finished.emit(stats)
                return

            # ★2.08：全市场快照只覆盖东财全 A，北交所/少数新票不在里面。
            #   先按花名册补一次新浪批量报价（bj 前缀已修），并合并进快照。
            full_market = len(self._symbols) >= 3000
            if full_market:
                missing = [s for s in self._symbols if s not in set(snap["symbol"])]
                if missing:
                    got = service.fetch_spot_snapshot(missing, allow_fallback=True)
                    extra = pd.DataFrame(list(got.values())) if got else pd.DataFrame()
                    if not extra.empty:
                        extra = normalize_snapshot(extra, asof)
                        if not extra.empty:
                            snap = pd.concat([snap, extra], ignore_index=True)
                            snap = snap.drop_duplicates(subset=["symbol"], keep="last")
                # 快照里有、花名册没有的新股 ⇒ 增量入库，不删旧名单
                try:
                    from data.roster_sync import merge_snapshot_symbols
                    stats["roster_added"] = merge_snapshot_symbols(
                        snap[["symbol", "name"]] if "name" in snap.columns else snap[["symbol"]])
                except Exception as e:  # noqa: BLE001 —— 名单增量失败不拖垮日更
                    logger.warning("新股并入花名册失败: %s", e)

            if not write_snapshot(snap, asof):
                stats["fail"] = len(self._symbols)
                self.failed.emit("", "日快照落盘失败")
                self.finished.emit(stats)
                return

            # 全市场把快照里出现的新股也纳入合并；小池仍只处理用户点名的标的。
            target = (list(dict.fromkeys(self._symbols + list(snap["symbol"])))
                      if full_market else list(self._symbols))
            stats["total"] = len(target)
            want = set(target)
            snap = snap[snap["symbol"].isin(want)].reset_index(drop=True)
            total = len(snap)
            lock = threading.Lock()
            empty_hist = []

            def _merge_one(rec):
                sym = str(rec.get("symbol") or "").strip()
                try:
                    if self._cancel:
                        return sym, "skipped", 0, None, False
                    old = service.lake.load_data(ZONE_KLINE, sym)
                    was_empty = old is None or len(old) == 0
                    if old is not None and len(old) and "date" in old.columns:
                        last_day = pd.to_datetime(old["date"], errors="coerce").max()
                        if pd.notna(last_day) and pd.Timestamp(last_day).normalize() >= asof:
                            return sym, "skipped", 0, None, False
                    if self._can_append(old, rec, asof, calendar):
                        merged = merge_row(old, pd.Series(rec))
                        if not service.lake.save_data(ZONE_KLINE, sym, merged):
                            return sym, "fail", 0, "落盘失败", was_empty
                        return sym, "ok", 1, None, was_empty
                    # 缺口 / 除权 / 缺昨收：走单只真实增量，宁可慢也不抄错
                    result = service.refresh_one(sym, zone=ZONE_KLINE, policy=policy)
                    if result.get("ok"):
                        return sym, "ok", int(result.get("added", 0)), None, was_empty
                    return sym, "fail", 0, short_fetch_reason(result), was_empty
                except Exception as e:  # noqa: BLE001 —— 单只失败不废整批
                    return sym, "fail", 0, f"{type(e).__name__}: {e}", False

            with ThreadPoolExecutor(max_workers=min(16, max(1, total))) as ex:
                futures = [ex.submit(_merge_one, rec) for rec in snap.to_dict("records")]
                for index, fut in enumerate(as_completed(futures), start=1):
                    sym, status, added, err, was_empty = fut.result()
                    with lock:
                        stats["symbols_attempted"].append(sym)
                        if status == "ok":
                            stats["ok"] += 1
                            stats["added"] += added
                            if was_empty:
                                empty_hist.append(sym)
                        elif status == "skipped":
                            stats["skipped"] += 1
                        else:
                            stats["fail"] += 1
                            stats["symbols_failed"].append(sym)
                    self.progress.emit(index, total, sym)
                    if err:
                        self.failed.emit(sym, err)
                    if self._cancel:
                        stats.update(aborted=True, aborted_by="cancel")
                        break
            missing = [s for s in target if s not in set(snap["symbol"])]
            if missing:
                # 停牌/退市/快照无行 ≠ 下载失败；如实记 missing，不制造 343 条假失败
                stats["skipped"] += len(missing)
                stats["symbols_missing"] = missing
            stats["symbols_empty"] = empty_hist
        except Exception as e:  # noqa: BLE001 —— 线程内兜底，回包必须有
            logger.error("日快照批量任务异常: %s", e)
            stats["fail"] = max(1, len(self._symbols) - stats["ok"] - stats["skipped"])
            stats["aborted"] = True
            stats["aborted_by"] = "error"
            self.failed.emit("", f"{type(e).__name__}: {e}")
        self.finished.emit(stats)


class NetSelfCheckWorker(QThread):
    """★v6.74 / §7-B13 S2-1b：**网络与取数自检**（后台跑，绝不阻塞界面）。

    【自检做多少】策略 / 代理 / DNS / 登录 / 档位 / 额度 / 退避 = **零请求**；
      只额外发 **1 个** `ulist`（1 只票）验"现在能不能取到数" ⇒ 不刷量（用户拍板口径）。
    【纪律】走门面 `network_self_check()`（§9-H：ui 不直连行情源）；
      结果**同时进日志**（`app.log`）把整段报告留痕，方便事后复盘。
    """

    finished = pyqtSignal(str)   # 人话报告（多行）；异常也回一段说明，绝不空回

    def __init__(self, probe: bool = True, parent=None):
        super().__init__(parent)
        self._probe = bool(probe)
        self._cancel = False

    def cancel(self):
        """关窗取消（自检本身很短，只标记不再发新请求）。"""
        self._cancel = True

    def run(self):
        try:
            _check = _resolve_worker_dep("network_self_check", network_self_check)
            text = '' if self._cancel else _check(self._probe)
        except Exception as e:  # noqa: BLE001 —— 自检炸了也要给用户一句话
            logger.warning(f"网络自检失败: {type(e).__name__}: {e}")
            text = f'网络自检失败：{type(e).__name__}: {e}'
        try:
            logger.info("网络自检报告：\n" + (text or '（已取消）'))
        except Exception:  # noqa: BLE001
            pass
        self.finished.emit(text or '（已取消）')


class CacheCleanWorker(QThread):
    """★v6.75 / §7-B13 S2-5：**缓存清理**（后台跑 —— 只删"可再生成"的东西）。

    【纪律】删除范围由 `data/storage_maintenance` 定义（**唯一实现处**：轮转日志 + `*.tmp`；
      数据湖 / 回测存档 / 截图 / 交易库 / **登录凭据**一律不碰）。本类只负责"别卡界面"。
    """

    finished = pyqtSignal(str)   # 人话回执

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            if self._cancel:
                text = '已取消（未清理任何文件）'
            else:
                from data.storage_maintenance import clear_cache
                text = str(clear_cache().get('text') or '')
        except Exception as e:  # noqa: BLE001 —— 清理失败要给用户一句话，不能空回
            logger.warning(f"缓存清理失败: {type(e).__name__}: {e}")
            text = f'缓存清理失败：{type(e).__name__}: {e}'
        logger.info(f"缓存清理：{text}")
        self.finished.emit(text or '清理完成')


class UpdateCheckWorker(QThread):
    """★v6.76 / §7-B13 S2-7：**手动检查更新**（后台）—— 明确回答「已是最新 / 有新版」。

    【为什么与 `core/updater.UpdateCheckerThread` 不合并】那一个是**启动时静默侦察**（只在有新版时
      发信号、断网无声）；手动检查必须**总有回执**（"已是最新 1.56" 也是一个答案）。两者读同一个
      `settings.UPDATE_CHECK_URL`、同一套版本比较口径（这里直接复用它的比较函数，不另写一份）。
    """

    finished = pyqtSignal(str)   # 人话回执（无论有没有新版、无论成不成功都有话说）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            text = '已取消（未检查）' if self._cancel else self._check()
        except Exception as e:  # noqa: BLE001 —— 断网/404/JSON 坏都必须给用户一句话
            logger.warning(f"手动检查更新失败: {type(e).__name__}: {e}")
            text = f'检查更新失败（网络或云端配置问题，不影响使用）：{type(e).__name__}: {e}'
        logger.info(f"检查更新：{text}")
        self.finished.emit(text)

    @staticmethod
    def _check() -> str:
        import json
        import urllib.request

        from config import settings
        from core.updater import UpdateCheckerThread

        req = urllib.request.Request(
            settings.UPDATE_CHECK_URL,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))
        remote = str((data or {}).get('version') or '').strip()
        notes = str((data or {}).get('notes') or '').strip()
        if not remote:
            return '云端没有可用的版本信息（不影响使用）'
        if UpdateCheckerThread()._is_newer(remote, settings.APP_VERSION):
            return (f"发现新版本 {remote}（当前 {settings.APP_VERSION}）"
                    + (f" —— {notes[:120]}" if notes else ''))
        return f"已是最新（当前 {settings.APP_VERSION}）"
