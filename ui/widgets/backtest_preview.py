# ui/widgets/backtest_preview.py
"""回测页的**只读回放 / 复用参数 / 手动存档**（★2.04 / P2 拆件）。

从 `ui/views/backtest.py` 抽出；宿主是 `SingleStockBacktestView`（Mixin 依赖宿主的
`result` / `flow` / `strategy` / `_last_*` 等属性）。只搬方法，不改行为。
"""
from __future__ import annotations

import pandas as pd
from PyQt6.QtWidgets import QMessageBox

__all__ = ["BacktestPreviewMixin"]


class BacktestPreviewMixin:
    """§7-A4 历史存档：只读回放 / 复用参数（供「运行历史」子页回调）。"""

    def _leave_preview_state(self) -> None:
        """退出只读回放态（只改状态，不重绘）—— 恢复导出入口、收起横幅。"""
        self._preview_mode = False
        self._preview_prev = None
        self._preview_bar.setVisible(False)
        self.btn_export_result.setEnabled(True)

    def show_archived(self, record: dict) -> None:
        """**只读回放**一份历史存档（KPI + 净值曲线含买卖点 + 成交明细）。

        ⚠ 三件事必须做到，否则就是"串味"：
          ① **不改 `_last_result/_last_meta`** —— 否则用户在预览里点"导出"会导出
             "存档结果 + 上次回测参数"这对错误组合；
          ② 预览前**保存现场**（`_preview_prev`），「退出预览」能原样还给用户；
          ③ **禁用导出**（导出的是"本次运行"，预览不是）。
        存档不含逐日 OHLC ⇒ K 线页给明确提示（要看买卖点请「▶ 重跑」）。
        """
        from data.backtest_archive import record_to_result
        result = record_to_result(record)
        meta = record.get("meta") or {}
        if not self._preview_mode:           # 已在预览里再点别份：保留最初那份现场
            self._preview_prev = {
                "result": self._last_result, "meta": self._last_meta,
                "df": self._last_df, "draws": self._last_draws,
            }
        self._preview_mode = True
        self._preview_bar.setVisible(True)
        self.btn_export_result.setEnabled(False)

        name, symbol = meta.get("name") or "", meta.get("symbol") or ""
        self.result.render_result(
            result, name, symbol, df=pd.DataFrame(), draws=[],
            kline_hint="历史存档不含逐日 K 线 —— 要看买卖点请点「▶ 重跑」")
        kpi = record.get("kpi") or {}
        cum = float(kpi.get("cumulative_return") or 0.0)
        self.lbl_preview.setText(
            f"📄 只读回放历史存档 · {name} {symbol} · {meta.get('start_date') or ''}~"
            f"{meta.get('end_date') or ''} · 累计 {cum * 100:+.2f}% · "
            f"存档于 {record.get('created_at') or ''}")
        self.lbl_run_status.setText("📄 正在查看历史存档（只读），点上方「退出预览」回到当前结果。")

    def exit_preview(self) -> None:
        """退出只读回放，恢复预览前的现场（没有现场时给一行诚实回执）。"""
        if not self._preview_mode:
            return
        prev = self._preview_prev or {}
        result = prev.get("result")
        self._leave_preview_state()
        if result is None:
            self.lbl_run_status.setText("已退出预览（本次会话还没有回测结果）。")
            return
        self._last_result = result
        self._last_meta = prev.get("meta")
        self._last_df = prev.get("df") if prev.get("df") is not None else pd.DataFrame()
        self._last_draws = prev.get("draws") or []
        self._render_result(result)          # 重绘现场

    def load_archive_config(self, record: dict) -> None:
        """把一份历史存档的配置复用进编辑器（含切标的），供调整后再跑。"""
        config = dict(record.get("config") or {})
        meta = record.get("meta") or {}
        symbol = config.get("symbol") or meta.get("symbol") or ""
        name = meta.get("name") or symbol
        if self._preview_mode:
            self._leave_preview_state()      # 复用参数 = 离开只读回放（要动编辑器了）
        if symbol:
            self.current_symbol = symbol
            self.current_name = name
            self.txt_symbol.setText(symbol)
            self.lbl_symbol.setText(f"{name} ({symbol})")
        stale = self.strategy.apply_payload(config)
        # ★1.61 / §7-B16 H4：历史存档的 config 同样带 `asset_id` ⇒ 复用后给同款显式动作
        #   （默认保留存档里的函数原样；要换新版由用户点「⤒ 用最新版」）。
        self.strategy.prompt_stale(stale)
        self.lbl_run_status.setText("已从历史存档复用参数到编辑器，可调整或直接「▶ 开始回测」。"
                                    + self.strategy.stale_tip(stale))

    def save_to_history(self) -> str | None:
        """手动「💾 存为历史快照」（自动存档关掉时的兜底入口）。返回存档 id。"""
        if self._preview_mode:
            QMessageBox.information(self, "提示", "当前是历史存档的只读回放；"
                                                 "请先「退出预览」再存为历史。")
            return None
        if self._last_result is None:
            QMessageBox.information(self, "提示", "请先完成一次回测，再存为历史。")
            return None
        rid = self.flow.archive_now()
        if rid is None:
            QMessageBox.warning(self, "存档失败",
                                "这次结果没能写入存档（可能超过单份 2MB 上限）。")
            return None
        self.lbl_run_status.setText("💾 已存为历史快照（可在「🗂 运行历史」查看）。")
        page_history = getattr(self.main_win.page_backtest, "page_history", None)
        if page_history is not None:
            page_history.refresh()           # 存完立刻在列表里可见
        return rid
