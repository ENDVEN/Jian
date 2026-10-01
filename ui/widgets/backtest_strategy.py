# ui/widgets/backtest_strategy.py
"""
📐 回测「策略库桥接」（1.22 自 `ui/views/backtest.py` 拆出 · §9-L 第二批后半）。

【职责】页面上的编辑器状态 ⇄ 磁盘上的策略存档之间的那层：
  · `payload()`  —— 把当前编辑器状态打包成可持久化快照（含买卖条件 / 风控 / 指数门控 /
                    成交时点 / 区间 / 标的），**签名与旧档兼容**的约定都在这里；
  · `plans()` / `load_plan()` / `save()` / `delete_plan()` —— 策略库的列 / 载 / 存 / 删
    （★1.61：页内那条策略下拉已退役，统一入口 = 「ƒ 库」浮窗的「📚 本页方案」区）；
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
# ★1.61 / §7-B16 红线②：载入只认**内联快照**（绝不静默换函数）；资产有更新版时
#   `stale_snapshot` 把资产带回给调用方，由它决定提示方式（提示可见、更新要显式动作）。
from data.formula_store import SOURCE_BACKTEST, get_formula_store
from data.hub_assets import stale_snapshot, upsert_asset
from data.strategy_store import segments_of   # ★1.66：旧档"段"落回的**唯一出口**
from ui.widgets.hub_latest import LatestFunctionPrompt   # ★1.61 §7-B16 H4 公共件（M1 与 M2/M3 共用）


class StrategyBridge:
    """策略库桥接（页面持有状态，本类提供行为）。"""

    def __init__(self, page):
        self.page = page
        # ★1.61 / §7-B16 H4：「总库有更新版」的提示与显式更新 —— **公共件**
        #   （与 M2/M3 逐行相同的逻辑只此一份，见 `ui/widgets/hub_latest.py`）。
        self._latest = LatestFunctionPrompt(
            page, subject='本策略', noun='函数段与参数',
            kept='买卖条件 / 风控 / 大盘门控 / 成交口径 / 区间',
            fill=self._fill_latest, receipt='lbl_run_status')

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

    def active_plan_id(self) -> str:
        """当前生效的策略 id（空串 = 没有）—— 浮窗列表据此标「● 当前」。"""
        return str(self.page._active_strategy_id or "")

    def load_plan(self, plan_id: str) -> bool:
        """按 id 载入策略 —— 把快照整体还原进编辑器（旧档字段缺失一律回落默认）。

        ★1.61 / §7-B16：**页内那条策略下拉已退役**（用户口径：M1 的「保存当前 / 移除」
        与 M2/M3 的「载入 / 存为 / 管理」本质是同一件事 ⇒ 统一收进「ƒ 库」浮窗的方案区）。
        本方法就是浮窗「📚 载入」的落点；`_active_strategy_id` 仍是"当前生效策略"的唯一真源。

        :return: 是否真的载入（id 不存在 = False，供浮窗回执说人话）
        """
        p = self.page
        strategy = p.store.get(str(plan_id))
        if not strategy:
            return False
        p._active_strategy_id = strategy.get("id")
        stale = self.apply_payload(strategy)     # 只读内联快照（红线②）
        self.prompt_stale(stale)
        p.lbl_run_status.setText(f"已载入策略「{strategy.get('name')}」，请选择股票后运行。"
                                 f"{self.stale_tip(stale)}")
        return True

    # ==========================================
    # ★1.61 / §7-B16：**函数总库浮窗的「📚 本页方案」区**用的三件事
    #   策略库仍在本文件；浮窗只是**另一个入口** —— 载入 / 保存 / 删除一律复用同一套实现
    #   （页内一套、浮窗一套 = 迟早分叉，§11.5-11）。
    # ==========================================
    def plans(self) -> list[dict]:
        """全部策略（浮窗列表用）。"""
        return self.page.store.list_strategies()

    @staticmethod
    def plan_label(plan: dict) -> str:
        """列表行的第二行文案（段数 + 条件数 + 区间）—— 与浮窗里其它行的口径一致。"""
        segs = [s for s in (plan.get('segments') or []) if str(s).strip()]
        if not segs and str(plan.get('function') or '').strip():
            segs = [plan.get('function')]
        n_cond = (len((plan.get('condition_buy') or {}).get('conditions') or [])
                  + len((plan.get('condition_sell') or {}).get('conditions') or []))
        return (f"{len(segs)} 段 · 条件 {n_cond} · "
                f"{plan.get('start_date') or '—'} ~ {plan.get('end_date') or '—'}")

    def delete_plan(self, plan_id: str) -> bool:
        """按 id 删策略（浮窗用）—— 先选中再走 `delete()`（同一套二次确认与收尾）。"""
        p = self.page
        p._active_strategy_id = plan_id
        self.delete()
        return p.store.get(plan_id) is None

    # ==========================================
    # ★1.61 / §7-B16 H4：「总库有更新版」—— 提示可见 + 更新要显式动作
    #   实现全在公共件 `ui/widgets/hub_latest.LatestFunctionPrompt`（M1 与 M2/M3 同一份口径）；
    #   这里只留三个同名薄壳，页面与冒烟照旧调它们。
    # ==========================================
    def _fill_latest(self, texts, params_text: str) -> int:
        """把最新版回填进 M1 编辑器并复检（**只碰函数段与参数**）。"""
        p = self.page
        p.segments.set_texts(texts)
        p.txt_params.setText(params_text)
        p.detect_function(quiet=True)      # 换完立刻自检：缺参 / 语法当场可见
        return len(texts)

    def stale_tip(self, stale) -> str:
        """统一的一句人话（不点按钮 = 保持原样，这是默认动作，必须在文案里说出来）。"""
        return self._latest.tip(stale)

    def prompt_stale(self, stale) -> bool:
        """记下待更新的资产并显隐摘要条上的「⤒ 用最新版」（None = 收起）。

        ⚠ **只显隐按钮，绝不改编辑器** —— 红线②：已存方案的函数要么保持原样（默认），
          要么由用户点一下才换成新版。这里是"提示面"，动作在 `apply_latest_function`。
        """
        return self._latest.prompt(stale)

    def apply_latest_function(self) -> int:
        """「⤒ 用最新版」：**只**替换函数段与参数，其余配置一字不动（红线②）。

        这是**显式动作**（用户点了才发生），所以允许读资产内容；载入路径（`apply_payload`）
        依旧只读内联快照 —— 护栏的源码级断言盯的是"读资产"这个动作只许出现在公共件里。

        :return: 实际替换的段数（0 = 没有待更新的资产 / 资产内容为空）
        """
        return self._latest.apply()

    def apply_payload(self, strategy: dict):
        """把一份配置快照（策略 payload / 历史存档 config 同构）整体还原进编辑器。

        旧档字段缺失一律回落默认；与 `load_plan` 共用同一套还原口径（单一事实源）。
        不负责切标的（symbol 由调用方按需设），也不写回执（便于历史页自定义提示）。
        ★1.61 / §7-B16 红线②：还原**只读内联快照**（`segments`/`function`），绝不静默换函数；
        :return: 总库更新版资产（无引用 / 内容一致 / 资产已删 = None）
        """
        p = self.page
        # ★1.66：旧档回落（只有 `function`）收到 `strategy_store.segments_of` 一处 ——
        #   参数研究页当初各写一份"只读 segments"，旧策略在那边直接空转（实测事故）。
        segments = list(segments_of(strategy))
        p.segments.set_texts(segments)
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
        # ★1.61 / §7-B16：内联快照 vs 总库资产是否分叉（分叉 = 返回更新版资产，提示由调用方出）
        return stale_snapshot(str(strategy.get("asset_id") or ""),
                              [s for s in segments if str(s).strip()],
                              str(strategy.get("params_text", "")))

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
        # ★1.61 / §7-B16：函数**收编进资产库**（内容命中即复用；同名不同内容 ⇒ 后缀新建，
        #   绝不覆盖用户手存配方），并把引用挂到本策略 —— 引用计数 / 更新提示由此有据可查。
        asset = upsert_asset(get_formula_store(), name,
                             payload.get("segments"), payload.get("params_text", ""),
                             SOURCE_BACKTEST)
        payload["asset_id"] = asset["id"]
        strategy_id = p.store.upsert(payload)
        p._active_strategy_id = strategy_id
        # 刚把当前内容存成策略 ⇒ 快照与资产的关系已重新建立，「有更新版」提示随之作废。
        self.prompt_stale(None)
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
