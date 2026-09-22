# ui/widgets/backtest_strategy.py
"""
📐 回测「策略库桥接」（1.22 自 `ui/views/backtest.py` 拆出 · §9-L 第二批后半）。

【职责】页面上的编辑器状态 ⇄ 磁盘上的策略存档之间的那层：
  · `payload()`  —— 把当前编辑器状态打包成可持久化快照（含买卖条件 / 风控 / 指数门控 /
                    成交时点 / 区间 / 标的），**签名与旧档兼容**的约定都在这里；
  · `reload_combo()` / `on_strategy_selected()` —— 策略下拉的重建与"选用即还原"；
  · `save()` / `delete()` —— 存/删（带走回执文案）；
  · `archive_result()` —— 回测完成后把指标归档到"当前策略或同配置策略"，供跨策略对比；
  · `render_compare()` —— 对比表 + 对比柱图（图由结果区画，数据在这里取）。

【设计约定】与 `backtest_flow.py` 一致：**状态留在页面**（`store` / `_active_strategy_id`
  / 各个配置控件都是页面的），本模块只承载"行为"，读写一律经 `self.page.*`。
"""
from PyQt6.QtCore import QDate
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QInputDialog, QMessageBox, QTableWidgetItem

from config import settings


class StrategyBridge:
    """策略库桥接（页面持有状态，本类提供行为）。"""

    def __init__(self, page):
        self.page = page

    # ==========================================
    # 打包 / 还原
    # ==========================================
    def payload(self) -> dict:
        """把当前编辑器状态打包为可持久化的策略快照 (阶段A 多段结构)。

        存储约定：
        - segments: [各段函数文本]，UI 还原时精确恢复多段；
        - function: 各段以分号连接的合并文本，保留给 strategy_store 的
          find_same 签名与旧版载入逻辑 (分号连接 = 同一 EvalContext 顺序执行，语义等价)。
        """
        p = self.page
        texts = [t.strip() for t in p.segments.texts() if t.strip()]
        return {
            "name": "",
            "note": "",
            "segments": texts,
            "function": "; ".join(texts),
            "params_text": p.txt_params.text().strip(),
            "condition_buy": p.gate_buy.config(),
            "condition_sell": p.gate_sell.config(),
            "risk": p._risk_config(),
            "index": self._index_config(),
            # v6.17：成交时点模型也属于策略配置（进签名，避免不同口径互相污染对比）
            "fill": p._fill_config(),
            "start_date": p.date_start.date().toString("yyyy-MM-dd"),
            "end_date": p.date_end.date().toString("yyyy-MM-dd"),
            "symbol": p.current_symbol,
        }

    def reload_combo(self, keep_active: str = None):
        """重建策略下拉（尽量保持当前选中项；首次进入自动载入第一条）。"""
        p = self.page
        strategies = p.store.list_strategies()
        p.cmb_strategy.blockSignals(True)
        p.cmb_strategy.clear()
        for item in strategies:
            p.cmb_strategy.addItem(str(item.get("name", "未命名")), item.get("id"))
        idx = -1
        if keep_active:
            for i in range(p.cmb_strategy.count()):
                if p.cmb_strategy.itemData(i) == keep_active:
                    idx = i
                    break
        if idx >= 0:
            p.cmb_strategy.setCurrentIndex(idx)
        elif strategies:
            p.cmb_strategy.setCurrentIndex(0)
        p.cmb_strategy.blockSignals(False)
        if idx < 0 and strategies:
            self.on_strategy_selected(p.cmb_strategy.currentIndex())

    def on_strategy_selected(self, index: int):
        """选用某条策略 → 把快照整体还原进编辑器（旧档字段缺失一律回落默认）。"""
        p = self.page
        if index < 0:
            p._active_strategy_id = None
            return
        strategy = p.store.get(p.cmb_strategy.itemData(index))
        if not strategy:
            return
        p._active_strategy_id = strategy.get("id")
        self.apply_payload(strategy)
        p.lbl_run_status.setText(f"已载入策略「{strategy.get('name')}」，请选择股票后运行。")

    def apply_payload(self, strategy: dict) -> None:
        """把一份配置快照（策略 payload / 历史存档 config 同构）整体还原进编辑器。

        旧档字段缺失一律回落默认；与 `on_strategy_selected` 共用同一套还原口径（单一事实源）。
        不负责切标的（symbol 由调用方按需设），也不写回执（便于历史页自定义提示）。
        """
        p = self.page
        segments = strategy.get("segments") or [str(strategy.get("function", ""))]
        p.segments.set_texts([s for s in segments if s and s.strip()])
        p.txt_params.setText(str(strategy.get("params_text", "")))
        if strategy.get("start_date"):
            p.date_start.setDate(QDate.fromString(str(strategy["start_date"]), "yyyy-MM-dd"))
        if strategy.get("end_date"):
            p.date_end.setDate(QDate.fromString(str(strategy["end_date"]), "yyyy-MM-dd"))
        p.detect_function(quiet=True)
        # 还原买卖条件组 (新结构 {logic,n,conditions} 与旧平铺 dict 均兼容)
        p.gate_buy.load_config(strategy.get("condition_buy") or {})
        p.gate_sell.load_config(strategy.get("condition_sell") or {})
        # 还原风控参数 (旧策略无 risk 字段 -> 回落 0 全关闭)
        p._apply_risk_config(strategy.get("risk") or {})
        # 还原指数 regime 门控 (旧策略无 index 字段 -> 全关)
        self._apply_index_config(strategy.get("index") or {})
        # 还原成交模型 (旧策略无 fill 字段 -> 次日开盘 + 1 跳，等价改动前行为)
        p._apply_fill_config(strategy.get("fill") or {})

    # ==========================================
    # 指数门控（策略快照的一个字段，读写都在这里）
    # ==========================================
    def _index_config(self) -> dict:
        """读取当前指数门控状态 (阶段C)"""
        p = self.page
        return {
            "enabled": bool(p.chk_index_enable.isChecked()),
            "symbol": p._index_symbol(),
            "buy": p.gate_index_buy.config(),
            "sell": p.gate_index_sell.config(),
        }

    def _apply_index_config(self, cfg: dict):
        """从策略快照恢复指数门控；缺失/非法一律回落关闭"""
        p = self.page
        cfg = cfg or {}
        p.chk_index_enable.setChecked(bool(cfg.get("enabled", False)))
        symbol = str(cfg.get("symbol", "") or "").strip()
        if symbol:
            # 下拉中查找；不存在则以文本方式置入 (可编辑下拉支持任意新浪代码)
            idx = p.cmb_index.findData(symbol)
            if idx >= 0:
                p.cmb_index.setCurrentIndex(idx)
            else:
                p.cmb_index.setEditText(symbol)
        p.gate_index_buy.load_config(cfg.get("buy") or {})
        p.gate_index_sell.load_config(cfg.get("sell") or {})
        p._sync_index_enabled(p.chk_index_enable.isChecked())

    # ==========================================
    # 存 / 删 / 归档 / 对比
    # ==========================================
    def save(self):
        """保存当前配置为策略（同名则由 store 决定是覆盖还是新增）。"""
        p = self.page
        if not p._programs:
            QMessageBox.information(p, "提示", "请先完成函数检测后再保存。")
            return
        payload = self.payload()
        name, ok = QInputDialog.getText(p, "保存策略", "策略名称:")
        name = (name or "").strip()
        if not ok or not name:
            return
        payload["name"] = name
        strategy_id = p.store.upsert(payload)
        p._active_strategy_id = strategy_id
        self.reload_combo(keep_active=strategy_id)
        p.lbl_run_status.setText(f"✅ 已保存策略「{name}」，下次可直接选用。")

    def delete(self):
        """删除当前选中的策略（二次确认；不动磁盘上的回测结果归档）。"""
        p = self.page
        if not p._active_strategy_id:
            return
        strategy = p.store.get(p._active_strategy_id)
        if not strategy:
            return
        reply = QMessageBox.question(p, "删除策略", f"确认删除「{strategy.get('name')}」？")
        if reply == QMessageBox.StandardButton.Yes:
            p.store.delete(p._active_strategy_id)
            p._active_strategy_id = None
            self.reload_combo()
            self.render_compare()

    def archive_result(self, summary: dict):
        """回测完成后：关联到当前/同配置策略并归档指标，刷新对比"""
        p = self.page
        strategy_id = p._active_strategy_id
        if not strategy_id:
            strategy_id = p.store.find_same(self.payload())
        if strategy_id:
            p.store.record_result(strategy_id, p.current_symbol or "", summary)
            p._active_strategy_id = strategy_id
            self.reload_combo(keep_active=strategy_id)
            self.render_compare()

    def render_compare(self):
        """刷新"同标的、多策略"对比表 + 对比柱图（柱图由结果区画）。"""
        p = self.page
        symbol = p.current_symbol or ""
        snapshots = p.store.metrics_snapshot(symbol)
        p.compare_table.setRowCount(len(snapshots))
        for row, snap in enumerate(snapshots):
            strategy = snap["strategy"]
            metrics = snap["metrics"]
            name_item = QTableWidgetItem(str(strategy.get("name", "-")))
            cum = metrics.get("cumulative_return")
            win = metrics.get("win_rate")
            if cum is not None:
                name_item.setForeground(QColor(
                    settings.COLOR_PROFIT_TEXT if cum > 0 else settings.COLOR_LOSS_TEXT))
            p.compare_table.setItem(row, 0, name_item)
            p.compare_table.setItem(row, 1, QTableWidgetItem(str(metrics.get("total_trades", "-"))))
            p.compare_table.setItem(row, 2, QTableWidgetItem(
                f"{win * 100:.1f}%" if win is not None else "-"))
            p.compare_table.setItem(row, 3, QTableWidgetItem(
                f"{cum * 100:+.1f}%" if cum is not None else "-"))
            p.compare_table.setItem(row, 4, QTableWidgetItem(str(metrics.get("recorded_at", "-"))))
        p.result.render_compare_chart(snapshots)
