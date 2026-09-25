# ui/widgets/backtest_flow.py
"""
📐 回测「运行流程」（1.22 自 `ui/views/backtest.py` 拆出 · §9-L 第二批后半）。

【职责】把"页面上的配置"变成"一次回测结果"：
  ① 选标的（走 DataEngine 门面，UI 不碰 DAO）；
  ② 发起前校验 + **在发起瞬间定格参数快照**（`_last_meta`，导出的可复现性靠它）；
  ③ 数据就绪链：先指数（若启用门控）后个股，本地缺数据就交给 `SingleSyncWorker` 温柔抓取；
  ④ 在真实行情上执行函数段（**同一次求值**产出 变量 + 绘图 IR）→ 拼指数门控列；
  ⑤ 交给 `BacktestRunWorker` 后台计算 → 结果落进结果区 + 归档进策略对比。

【设计约定（关键）】**状态全部留在页面** —— 页面是这些状态的唯一所有者：
  `current_symbol/current_name`、`_pending_run/_pending_params/_pending_risk/_pending_fill/
  _pending_index`、`_last_meta/_last_df/_last_draws/_last_result`、三个线程句柄。
  本模块只承载"行为"：所有读写都走 `self.page.X`。
  这样线程回调、断点续跑、验收断言读到的永远是同一份状态，不会出现"两处副本"。

【竞态防护】两处过期结果丢弃（pandas/线程交错）是历史事故的疫苗（§9-O5），搬动时原样保留。
"""
import pandas as pd
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QMessageBox

import logging

from core.formula import FormulaEngine
from core.formula.program import (FormulaProgramError, execute_programs,
                                  execute_programs_with_draws)
from core.preferences import preferences
from core.utils import align_by_date
from data.akshare_feed import is_index_symbol, is_stock_code
from data.backtest_archive import SOURCE_AUTO, SOURCE_MANUAL, BacktestArchive, build_record
from data.sync_service import ZONE_INDEX, ZONE_KLINE, friendly_fetch_message
from data.trade_calendar import latest_settled_trading_day
from ui.download_hub import SingleSyncGate
from ui.workers import BacktestRunWorker, CalendarWorker, SingleSyncWorker

logger = logging.getLogger(__name__)


def _date_from_preset(preset: str) -> QDate:
    """快捷区间 → 起始日期；未命中的一律回落到「回测意义窗」下沿 2016-01-01"""
    today = QDate.currentDate()
    if preset == "近3个月":
        return today.addMonths(-3)
    if preset == "近6个月":
        return today.addMonths(-6)
    if preset == "近1年":
        return today.addYears(-1)
    if preset == "近3年":
        return today.addYears(-3)
    if preset == "近5年":
        return today.addYears(-5)
    return QDate(2016, 1, 1)


class BacktestFlow:
    """回测运行流程（页面持有的"状态" + 本类提供的"行为"）。"""

    def __init__(self, page):
        self.page = page
        # ★v1.43 / §7-B11：单只同步与后台队列的互斥占位（指数 / 个股各一个）。
        #   唯一公共件 —— 别再各存 `self._token` 手工释放（漏一条 return 路径就永久占住）。
        self._index_gate = SingleSyncGate(page)
        self._stock_gate = SingleSyncGate(page)

    # ==========================================
    # 选标的
    # ==========================================
    def select_symbol(self):
        p = self.page
        keyword = p.txt_symbol.text().strip()
        if not keyword:
            QMessageBox.information(p, "提示", "请输入股票代码或名称。")
            return
        res_df = p.main_win.engine.search_symbol(keyword)   # 经 DataEngine 门面，UI 不碰 DAO
        if res_df.empty:
            QMessageBox.warning(p, "未找到", f"花名册中没有 '{keyword}'。")
            return
        symbol = str(res_df.iloc[0]['symbol'])
        name = str(res_df.iloc[0]['name'])
        if not is_stock_code(symbol):
            QMessageBox.warning(p, "仅支持A股", f"'{name} ({symbol})' 不是A股标的。")
            return
        p.current_symbol = symbol
        p.current_name = name
        p.txt_symbol.setText(symbol)
        p.lbl_symbol.setText(f"{name} ({symbol})"
                             + (" · 已缓存" if p.data_lake.exists("kline_daily", symbol) else ""))
        p._render_compare()

    def _on_range_preset(self, preset: str):
        """区间快捷档 → 只改起始日（结束日永远由用户自己定，不静默改口径）。"""
        self.page.date_start.setDate(_date_from_preset(preset))

    # ==========================================
    # 默认回测终点（§7-B10 · 最近已定稿交易日）
    # ==========================================
    def start_calendar_fetch(self):
        """页面初始化时后台拉一次交易日历（缓存命中即零网络）；结果回来把默认终点
        精修到「最近一个已定稿交易日」。拿不到日历（离线）→ 保持系统日，不阻断。"""
        p = self.page
        p._calendar_thread = CalendarWorker(parent=p)
        p._calendar_thread.finished_signal.connect(self._on_calendar)
        p._calendar_thread.start()

    def _on_calendar(self, calendar):
        """日历就绪回包：`list[date] | None`（None = 拿不到，交回退路径）。"""
        p = self.page
        p._calendar = calendar or None
        target = latest_settled_trading_day(calendar=calendar)
        if target is None:
            self._note("离线：终点按系统日期",
                       "未取到交易日历（离线），回测终点默认按系统日期；"
                       "回测时会自动校验本地数据并补全。")
            return
        qd = QDate(target.year, target.month, target.day)
        if qd <= p.date_end.maximumDate() and qd != p.date_end.date():
            p.date_end.setDate(qd)             # 默认终点 = 最近已定稿交易日
        self._note(f"终点默认 = 最近交易日 {qd.toString('yyyy-MM-dd')}",
                   "回测区间默认终点已按交易日历落在最近一个已定稿交易日。")

    def _note(self, short: str, full: str = '') -> None:
        """工具栏单行只放短文本（窄屏不撑窗），完整说明进 tooltip。"""
        p = self.page
        p.lbl_range_note.setText(short)
        p.lbl_range_note.setToolTip(full or short)

    @staticmethod
    def _qdate_last(df):
        """df 的最新交易日 → `QDate`；空 / 无 date 列 → None。"""
        if df is None or getattr(df, "empty", True) or "date" not in df.columns:
            return None
        try:
            last = pd.to_datetime(df["date"], errors="coerce").max()
        except (TypeError, ValueError):  # noqa: BLE001
            return None
        if pd.isna(last):
            return None
        return QDate(last.year, last.month, last.day)

    def _apply_end_date_receipt(self, df):
        """回测前诚实化（§7-B10 / 用户拍板 #3#4）：若该标的本地最新日仍早于 date_end
        （离线 / 补不到）→ 把终点**回退到有数据那天**并给一行回执，绝不静默截断。
        用户手动设过的更早终点不被前移（只回退）。"""
        p = self.page
        last = self._qdate_last(df)
        need = p.date_end.date()
        if last is None:
            return
        if last < need:
            p.date_end.setDate(last)           # 只回退、不前移
            self._note(
                f"⚠ 本地到 {last.toString('yyyy-MM-dd')}（未到 {need.toString('yyyy-MM-dd')}），已按前者回测",
                f"本地数据到 {last.toString('yyyy-MM-dd')}，未达目标终点 "
                f"{need.toString('yyyy-MM-dd')}（离线/未补全），已按前者回测。")
            if p._last_meta:
                p._last_meta["end_date"] = last.toString("yyyy-MM-dd")
        elif p._calendar:
            target = latest_settled_trading_day(calendar=p._calendar)
            if target is not None:
                self._note(f"已到最近交易日 {need.toString('yyyy-MM-dd')}",
                           "本地数据已覆盖最近交易日，开始回测。")

    # ==========================================
    # 发起回测（校验 + 定格快照）
    # ==========================================
    def start_backtest(self):
        p = self.page
        if not p.current_symbol:
            QMessageBox.information(p, "提示", "请先选择一只A股标的。")
            return
        if not p._programs:
            QMessageBox.information(p, "提示", "请先完成函数检测。")
            return
        buy_expr = (p.gate_buy.expression() or "").strip()
        sell_expr = (p.gate_sell.expression() or "").strip()
        if not buy_expr or not sell_expr:
            QMessageBox.warning(p, "条件缺失", "买入/卖出至少各配置一个有效条件。")
            return
        p._pending_run = (buy_expr, sell_expr)
        p._pending_params = p._parse_params_text(p.txt_params.text())
        p._pending_risk = p._risk_config()
        p._pending_fill = p._fill_config()      # v6.17 成交时点模型（发起瞬间定格）

        # 指数 regime 门控配置 (阶段C)：仅当启用且至少一侧配了条件才需要指数数据
        index_cfg = None
        if p.chk_index_enable.isChecked():
            symbol = p._index_symbol()
            if not is_index_symbol(symbol):
                QMessageBox.warning(p, "指数代码",
                                    "请输入有效的新浪指数代码，形如 sh000001 / sz399001。")
                return
            idx_buy = (p.gate_index_buy.expression() or "").strip()
            idx_sell = (p.gate_index_sell.expression() or "").strip()
            if idx_buy or idx_sell:
                index_cfg = {"symbol": symbol, "expr_buy": idx_buy, "expr_sell": idx_sell}
        p._pending_index = index_cfg

        # 【v5.14 导出】在发起回测这一刻定格参数快照（此后编辑框怎么改都不影响导出内容）
        strategy_name = ""
        if p._active_strategy_id:
            saved = p.store.get(p._active_strategy_id)
            strategy_name = str(saved.get("name", "")) if saved else ""
        p._last_meta = {
            "symbol": p.current_symbol,
            "name": p.current_name,
            "strategy_name": strategy_name,
            "start_date": p.date_start.date().toString("yyyy-MM-dd"),
            "end_date": p.date_end.date().toString("yyyy-MM-dd"),
            "segments": [t.strip() for t in p.segments.texts() if t.strip()],
            "params_text": p.txt_params.text().strip(),
            "buy_expr": buy_expr,
            "sell_expr": sell_expr,
            "risk": p._risk_config(),
            "index": index_cfg,
            "fill": p._fill_config(),
        }
        # §7-A4：同时定格**编辑器完整配置**（存档要用它还原成"可复用/可重跑"的载荷）。
        # ⚠ 必须在发起瞬间定格：若等回测跑完再 `payload()`，用户中途改过的编辑器内容
        #   会被存进"这次结果"的快照里 —— 存档就不再是"跑出来那次"的忠实复现。
        p._last_config = p.strategy.payload()

        self._prepare_index_then_stock()

    # ==========================================
    # 数据就绪链：先指数(若启用) 后个股
    # ==========================================
    def _prepare_index_then_stock(self):
        """阶段C 数据就绪链：先指数(若启用) 后个股，均就绪后执行回测"""
        p = self.page
        if not p._pending_index:
            self._prepare_stock_then_run()
            return
        symbol = p._pending_index["symbol"]
        idx_df = p.data_lake.load_data(ZONE_INDEX, symbol)
        if idx_df.empty:
            if self._index_gate.blocked_by(symbol, ZONE_INDEX):
                # 同一个文件不能两个写者（§7-B11）：宁可不出结果，也不拿写了一半的数据回测
                self._set_busy(False, f"指数 {symbol} 正在后台下载队列里，请稍后再跑。")
                return
            self._set_busy(True, f"本地无指数 {symbol} 数据，正在联网同步...")
            p._index_thread = SingleSyncWorker(symbol, zone=ZONE_INDEX, parent=p)
            p._index_thread.finished.connect(self._on_index_synced)
            self._index_gate.hold(symbol, ZONE_INDEX)
            p._index_thread.start()
        else:
            self._prepare_stock_then_run()

    def _on_index_synced(self, result: dict):
        p = self.page
        self._index_gate.release()
        # 【竞态防护】同步期间用户可能改了指数代码，过期结果必须丢弃 (v5.12 · §9-O5)
        pending = getattr(p, '_pending_index', None) or {}
        if str(result.get("symbol", "")) != str(pending.get("symbol", "")):
            return
        if not result.get("ok"):
            self._set_busy(False, "")
            symbol = str(result.get("symbol", ""))
            QMessageBox.warning(
                p, "指数同步失败",
                friendly_fetch_message(symbol, result)
                + "\n\n（指数代码须形如 sh000001 / sz399001）")
            return
        self._prepare_stock_then_run()

    def _prepare_stock_then_run(self):
        p = self.page
        df = p.data_lake.load_data(ZONE_KLINE, p.current_symbol)
        # 滞后自动补（§7-B10 / 拍板 #3）：由“仅无数据才补”放宽为
        # “该标的本地末日 < 回测终点也补”（含 `df.empty`）。
        need = p.date_end.date()
        local_last = self._qdate_last(df)
        if df.empty or local_last is None or local_last < need:
            if self._stock_gate.blocked_by(p.current_symbol, ZONE_KLINE):
                # 这只标的正在批量下载 ⇒ 本地文件可能被另一个写者改着，不拿它跑回测
                self._set_busy(False, f"{p.current_symbol} 正在后台下载队列里，请稍后再跑。")
                return
            # ★v6.66：回测只认**前复权**那一份（`ZONE_KLINE`）—— 补数据时也要说清，别让用户以为
            #   自己切到不复权后回测也会跟着换口径（回测/扫描口径与图表口径是**两件事**，§10-10）
            self._set_busy(True, f"本地前复权日线未到 {need.toString('yyyy-MM-dd')}，正在联网补全...")
            p._sync_thread = SingleSyncWorker(p.current_symbol, zone=ZONE_KLINE, parent=p)
            p._sync_thread.finished.connect(self._on_synced)
            self._stock_gate.hold(p.current_symbol, ZONE_KLINE)
            p._sync_thread.start()
        else:
            self._on_data_ready(df)

    def _on_synced(self, result: dict):
        p = self.page
        self._stock_gate.release()
        symbol = str(result.get("symbol", p.current_symbol) or p.current_symbol)
        # 【竞态防护】拉取期间用户可能已切到别的标的，过期结果必须丢弃 (v5.12 · §9-O5)。
        # 与行情工作台 trading_desk._on_sync_finished 同一手法 —— 同类防护要做就做全套。
        if symbol != p.current_symbol:
            self._set_busy(False, "")
            return
        if not result.get("ok"):
            self._set_busy(False, "行情同步失败。")
            QMessageBox.warning(p, "同步失败", friendly_fetch_message(symbol, result))
            return
        df = p.data_lake.load_data(ZONE_KLINE, symbol)
        if df.empty:
            self._set_busy(False, "行情同步失败，请检查网络。")
            QMessageBox.critical(p, "同步失败", f"无法获取 {symbol} 日线数据。")
            return
        self._on_data_ready(df)

    # ==========================================
    # 求值 + 拼门控 + 交后台计算
    # ==========================================
    def _on_data_ready(self, df):
        p = self.page
        # 回测前诚实化：补完后若本地末日仍早于 date_end → 回退终点 + 回执（不静默截断）。
        # 必须在下方定格 worker 的 end_date / 写回 _last_meta 之前执行。
        self._apply_end_date_receipt(df)
        params = getattr(p, '_pending_params', {})
        try:
            # v6.4 / §7-B3 P3：同一次求值**同时**产出 变量 + 绘图 IR（不二次求值）
            results, draws = execute_programs_with_draws(p._programs, df, params)
        except FormulaProgramError as e:
            self._set_busy(False, "")
            QMessageBox.critical(p, "函数执行失败", f"在真实行情上执行函数失败：\n{e}")
            return
        p._last_draws = draws

        merged = df.copy()
        collisions = sorted(set(results) & set(merged.columns))
        if collisions:
            self._set_busy(False, "")
            QMessageBox.critical(p, "命名冲突",
                                 f"函数变量与行情列重名: {', '.join(collisions)}。请改名后重试。")
            return
        for name, series in results.items():
            merged[name] = series.values

        buy_expr, sell_expr = p._pending_run
        risk = getattr(p, '_pending_risk', {}) or {}
        fill = getattr(p, '_pending_fill', None) or {}

        # 阶段C：指数 regime 门控列拼接 (引擎零改动)
        index_cfg = getattr(p, '_pending_index', None)
        if index_cfg:
            try:
                gated = self._attach_index_gates(merged, index_cfg, params)
            except FormulaProgramError as e:
                self._set_busy(False, "")
                QMessageBox.critical(p, "指数求值失败",
                                     "指数 regime 门控求值失败。请确认函数段仅依赖 K线列"
                                     "(C/O/H/L/V)，若函数含个股专属逻辑请拆成单独段。\n\n" + str(e))
                return
            if gated is not None:
                merged, buy_expr, sell_expr = gated

        p._last_df = merged.copy()
        self._set_busy(True, "回测计算中...")
        p._run_thread = BacktestRunWorker(
            merged, p.current_symbol, buy_expr, sell_expr,
            p.date_start.date().toString("yyyy-MM-dd"),
            p.date_end.date().toString("yyyy-MM-dd"),
            risk=risk,
            fill_mode=fill.get("fill_mode"), trigger_tick=fill.get("trigger_tick"))
        p._run_thread.finished_signal.connect(self._on_result)
        p._run_thread.start()

    def _attach_index_gates(self, merged: pd.DataFrame, index_cfg: dict, params: dict):
        """在个股 df 上拼入指数门控列，并返回合成后的 (merged, buy_expr, sell_expr)。

        实现要点 (引擎零改动)：
        1) 对指数日线执行同一批函数段 -> 变量加 IDX_ 前缀，供指数 Gate 表达式引用；
        2) 指数 Gate 表达式在指数行情上求值 -> 布尔门控；
        3) 门控布尔序列用 align_by_date 对齐到个股交易日 (缺失日 ffill, 前导默认 0)；
        4) 门控列(IDX_GATE_BUY/SELL)拼入 merged，买卖表达式 AND/OR 引用该列。
        """
        p = self.page
        symbol = index_cfg.get("symbol")
        idx_buy_expr = (index_cfg.get("expr_buy") or "").strip()
        idx_sell_expr = (index_cfg.get("expr_sell") or "").strip()
        if not idx_buy_expr and not idx_sell_expr:
            return merged, p._pending_run[0], p._pending_run[1]

        idx_df = p.data_lake.load_data("index_daily", symbol)
        if idx_df.empty:
            QMessageBox.critical(p, "指数数据缺失",
                                 f"本地没有指数 {symbol} 数据，请重试运行(将自动联网同步)。")
            return None

        # 1) 指数侧执行函数段 -> IDX_ 变量列
        idx_vars = execute_programs(p._programs, idx_df, params)
        idx_ext = idx_df.copy()
        for name, series in idx_vars.items():
            idx_ext[f"IDX_{name}"] = series.values

        def build_gate(expr: str):
            if not expr:
                return None
            try:
                gate = FormulaEngine.signal(expr, idx_ext, params)
            except Exception as e:
                raise FormulaProgramError(f"指数门控表达式 {expr} 求值失败: {e}") from None
            # 以指数日期为索引 -> 对齐到个股交易日
            dated = pd.Series(gate.to_numpy(), index=pd.to_datetime(idx_ext['date']))
            aligned = align_by_date({"G": dated}, pd.to_datetime(merged['date']))["G"]
            return pd.Series(aligned.to_numpy(), index=merged.index)

        gate_buy = build_gate(idx_buy_expr)
        gate_sell = build_gate(idx_sell_expr)
        merged = merged.copy()
        if gate_buy is not None:
            merged["IDX_GATE_BUY"] = gate_buy.to_numpy()
        if gate_sell is not None:
            merged["IDX_GATE_SELL"] = gate_sell.to_numpy()

        buy_expr, sell_expr = p._pending_run
        if gate_buy is not None:
            buy_expr = f"({buy_expr}) AND IDX_GATE_BUY"
        if gate_sell is not None:
            sell_expr = f"({sell_expr}) OR IDX_GATE_SELL"
        return merged, buy_expr, sell_expr

    # ==========================================
    # 结果落地
    # ==========================================
    def _on_result(self, result):
        p = self.page
        self._set_busy(False, "")
        if result is None:
            QMessageBox.critical(p, "回测失败",
                                 "回测失败。请确认条件变量存在于函数输出中，并检查参数/公式。")
            return
        p._last_result = result
        p._render_result(result)
        summary = result.summary()
        p.strategy.archive_result(summary)   # 归档进"当前/同配置策略"，供跨策略对比
        self._auto_archive(result)           # §7-A4：开关开时自动落一份不可变历史快照

    def _auto_archive(self, result) -> None:
        """自动存档（开关关 / 无 meta 则跳过）；失败只记日志，绝不打断回测。"""
        p = self.page
        cfg = preferences.get("backtest_archive") or {}
        if not cfg.get("auto", True):
            return
        if not getattr(p, "_last_meta", None):
            return
        try:
            p._last_archive_id = BacktestArchive().save(build_record(
                result, p._last_meta, config=self._frozen_config(), source=SOURCE_AUTO))
        except Exception as e:  # noqa: BLE001 —— 存档失败不能拖垮回测回执
            logger.warning("回测自动存档失败（忽略）: %s", e)

    def archive_now(self):
        """手动"存为历史"：落一份当前结果快照，返回 id（无结果/无 meta 返回 None）。"""
        p = self.page
        if getattr(p, "_last_result", None) is None or not getattr(p, "_last_meta", None):
            return None
        return BacktestArchive().save(build_record(
            p._last_result, p._last_meta, config=self._frozen_config(),
            source=SOURCE_MANUAL))

    def _frozen_config(self) -> dict:
        """存档用的配置快照：优先用发起瞬间定格的那份（`_last_config`）。

        旧代码路径（无定格）才回落到"当前编辑器"—— 但那是次优解：它会存进
        "跑完之后"的编辑器状态，与这次结果不一定是同一次配置。
        """
        p = self.page
        cfg = getattr(p, "_last_config", None)
        if cfg:
            return cfg
        return p.strategy.payload()

    def _set_busy(self, busy: bool, text: str = ""):
        """忙碌态：禁用入口 + 可选回执文字（回执落在摘要条右端，§10-14 的 L2）。"""
        p = self.page
        p.btn_run.setEnabled(not busy)
        p.btn_select.setEnabled(not busy)
        p.btn_detect.setEnabled(not busy)
        if text:
            p.lbl_run_status.setText(text)
