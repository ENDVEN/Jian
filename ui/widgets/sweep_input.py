# ui/widgets/sweep_input.py
"""
🧪 参数研究 —— **输入侧**（★1.66 拆件：页面刷新 + 策略/标的联动）。

【为什么单独成件】`ui/views/param_sweep.py` 在修完 1.67（实验身份/结果作废）后到 **494 行**
（§4 越线）。本件收两部分**同一类**关注点：
  · **页面刷新**（切页签时重读策略库与切块缓存）；
  · **输入联动**：策略存档 → 参数 chips / 标的带入 / 「选择」按钮（与 M1 同款口径
    `ui.widgets.symbol_pick`）。
页面因此回到"装配 + 编排 + 闸门"。

【形态】与前几件同一范式：**混入类** `SweepInputMixin`（宿主 = `ParamSweepView`），
公共面（`refresh_page` / `_refresh_strategies` / `_on_strategy_changed` / `_pick_symbol` /
`_refresh_symbol_receipt`）**一字不变** ⇒ 既有断言与调用点不动。
"""
from __future__ import annotations

import logging

import pandas as pd

from core.formula.program import parse_program, probe_missing_parameters
from core.utils import synthetic_bars      # ⚠ 参数探测要用"合成样本"，随块一起搬过来
from data.strategy_store import segments_of
from ui.widgets.symbol_pick import pick_symbol

logger = logging.getLogger(__name__)


class SweepInputMixin:
    """输入侧方法集（宿主 = `ui.views.param_sweep.ParamSweepView`）。"""

    # ================= 页面刷新 =================
    def refresh_page(self) -> None:
        """子页签切入时刷新（策略列表 / 切块缓存 / ★R5b 快照列表）。"""
        self._refresh_strategies()
        self._load_regimes()
        self._refresh_snapshots()

    def _refresh_strategies(self) -> None:
        try:
            payloads = [p for p in self._store.list_strategies()
                        if isinstance(p, dict) and p.get("condition_buy")]
        except Exception as e:  # noqa: BLE001 —— 库坏了不拖垮页面
            logger.warning(f"策略库读取失败：{e}")
            payloads = []
        self.form.set_strategies(payloads)
        self._on_strategy_changed()

    # ================= 策略 → 参数与标的的联动 =================
    def _on_strategy_changed(self) -> None:
        payload = self.form.strategy_payload()
        # ★1.66：标的**从策略保存值带入**（只在空着时填，绝不覆盖用户刚敲的）——
        #   策略本来就是在某个标的上配的，让用户重新敲一遍纯属白费；且空着时页面只会
        #   回一句"先填标的代码"，第一次用的人根本不知道要填什么。
        if payload and not self.form.symbol() and str(payload.get("symbol") or "").strip():
            sym = str(payload.get("symbol")).strip()
            self.form.set_symbol(sym)
            self.form.set_symbol_hint(f"按该策略保存的 {sym} 带入 —— 可点「选择」换一只")
            self._refresh_symbol_receipt(sym)
        names, hint = [], ""
        if payload is None:
            hint = "还没有已保存的策略 —— 先在「📈 单股回测」里保存一个带参数的配方"
        elif payload.get("index"):
            hint = "⚠ 该策略带指数门控，本页暂不支持（请用不带门控的配方）"
        else:
            try:
                # ★1.66：走 `segments_of`（旧档回落 = `function`）—— 只读 `segments` 的话，
                #   2026-09-06 之前保存的策略在这里全是"0 段 ⇒ 无参数"⇒ 整页空转（实测事故：
                #   用户"功能什么的都没办法实现"，根因就是读档口径比 M1 少了一条回落）。
                programs = [parse_program(t) for t in segments_of(payload)]
                # 缺参探测与 M1 同一入口（probe_missing_parameters）；哑行情只做"能不能算"
                probe, _ = probe_missing_parameters(programs, {}, synthetic_bars(120))
                names = sorted(probe)
                hint = (f"可扫描参数：{'、'.join(names)}" if names
                        else "该配方没有可扫描参数 ⇒ 本页用不上（参数研究需要带参数的配方）")
            except Exception as e:  # noqa: BLE001 —— 编译失败如实说
                hint = f"函数编译失败：{e}"
        self.form.set_param_chips(hint)
        self.form.set_param_options(names)
        self.form.set_dim2_visible(len(names) >= 2)

    # ================= 选标的（★用户 2026-10-01 追加需求：与 M1 同款） =================
    def _pick_symbol(self) -> None:
        """「选择」按钮 / 回车 —— 查花名册 → 校验 A 股 → 回填 + **M1 同款文字提示**。

        ⚠ 搜索/校验/提示文案**全在** `ui.widgets.symbol_pick`（M1 的 `select_symbol` 也调它）——
          本方法只做"回填本页控件 + 刷新本地数据回执"，绝不另写一套提示语。
        """
        picked = pick_symbol(self, self.form.symbol(), lake=self._lake)
        if picked is None:
            return
        symbol, _name, hint = picked
        self.form.set_symbol(symbol)
        self.form.set_symbol_hint(hint)
        self._refresh_symbol_receipt(symbol)

    def _refresh_symbol_receipt(self, symbol: str) -> None:
        """把"这只票本地有没有数据"写在数据回执里（有 ⇒ 给区间；没有 ⇒ 明确指向预下载）。"""
        symbol = str(symbol or "").strip()
        df = self._lake.load_data("kline_daily", symbol) if symbol else None
        if df is None or df.empty:
            self.form.set_data_receipt(
                f"{symbol or '该标的'}：本地没有前复权日线 —— 先去 🗄 数据管理 预下载，"
                "否则区间校验过不去")
            return
        d = pd.to_datetime(df["date"])
        self.form.set_data_receipt(
            f"{symbol} 本地数据 {d.min().date()} → {d.max().date()}（{len(df)} 根日线）"
            " —— 样本内/样本外都要落在这段里")
        # ★R7：把范围推给表单 ⇒「合并全部」只收**本机有数据**的窗口（并如实标注筛掉了多少对）
        self.form.set_data_range(str(d.min().date()), str(d.max().date()))
