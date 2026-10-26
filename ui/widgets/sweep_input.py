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

from core.conditions import gate_expression
from core.param_sweep import SweepSpec
from core.sweep_plan import StudyInterval, build_grid, validate_interval
from core.formula.program import parse_program, probe_missing_parameters
from core.utils import synthetic_bars      # ⚠ 参数探测要用"合成样本"，随块一起搬过来
from data.strategy_store import index_gate_enabled, segments_of
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
        elif index_gate_enabled(payload.get("index")):
            # ★1.70 / §11.5-128：判据必须是 `enabled` —— 旧写法 `payload.get("index")` 对
            #   **非空字典恒为真**，于是"门控面板填过、开关没打开"的策略被误判成"带门控"，
            #   参数列表**永远为空**（用户实测："我在 M1 保存的方案，参数研究里看不见"）。
            hint = "⚠ 该策略带指数门控（已启用），本页暂不支持（请用不带门控的配方）"
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

# ================= ★1.81 从 param_sweep 搬来：表单 → 研究规格 =================
#   为什么在输入侧：这三块只做"读表单 / 校验闸门 / 组装 `SweepSpec`+`GridPlan`+区间"，
#   不碰结果；页面源文件因此从 470 行（贴着结构上限）回到 ~390。
    # ================= 闸门要看得见 =================
    def _refresh_run_enabled(self) -> None:
        """网格 / 区间不合规 ⇒ **禁用「▶ 跑样本内」+ 就地写原因**。

        ★用户 2026-10-01 实测根因：`L1 起5 止20 步1` = **16 档 > 上限 15** ⇒ 网格被闸门拒、
        `_build_study()` 直接返回 ⇒ 右边结果图当然不变；但运行按钮**照样能点**、原因只躲在
        一行小灰字里 ⇒ 用户判定"坏了 / 没重构完"。现在：拦住时按钮禁用 + 橙字一行说明 +
        tooltip 同句（一句话：**闸门的拒绝必须落在用户正在看的地方**）。
        """
        self._invalidate_if_changed()        # ★1.66：网格/区间变了 ⇒ 上一轮结果作废
        # ★1.87：标的类型 = 组合 ⇒ **单只流程不适用**（否则会拿上一只个股去跑，结果对不上）
        _blk = getattr(self, "_pool_target", None)
        if _blk is not None and _blk.is_pool_mode():
            self.form.set_run_blocked("标的类型是「组合」⇒ 请点左栏「▶ 跑池化」；"
                                      "「跑样本内/外」只用于个股。")
            self.form.set_oos_enabled(False)
            return
        _dims, err = self.form.grid_dims()
        why = str(err or "")
        if not why:
            problems = validate_interval(self.form.interval())
            why = problems[0] if problems else ""
        self.form.set_run_blocked(why)

    # ================= 实验身份（★1.66）=================
    def _experiment_signature(self):
        """**这一次实验**的身份 = 网格（维名 + 档位）+ 区间四日期（网格不合法 ⇒ None）。"""
        dims, err = self.form.grid_dims()
        if err:
            return None
        iv = self.form.interval()
        return (tuple((d.name, tuple(d.values)) for d in dims),
                iv.is_start, iv.is_end, iv.oos_start, iv.oos_end,
                tuple(getattr(iv, "more", ()) or ()))      # ★R7：合并窗口也算实验身份

    def _build_study(self) -> tuple[SweepSpec, object, StudyInterval] | None:
        payload = self.form.strategy_payload()
        symbol = self.form.symbol()
        if not symbol:
            self.form.set_receipt("先填标的代码")
            return None
        if payload is None:
            self.form.set_receipt("先选一个「单股回测」已保存的策略（只列带条件的配方）")
            return None
        if index_gate_enabled(payload.get("index")):   # ★1.70 / §11.5-128：判 `enabled`，别判字典非空
            self.form.set_receipt("该策略带指数门控（已启用），本页暂不支持（红线：不复刻阶段C 门控）")
            return None
        # ★1.66：条件在**运行前**就地判空 —— 配置 → DSL 是 `core.conditions` 的事，
        #   空条件到不了引擎（否则引擎会抛"不是表达式"的怪错，用户看不懂）。
        if not gate_expression(payload.get("condition_buy")) or \
                not gate_expression(payload.get("condition_sell")):
            self.form.set_receipt("该策略的买卖条件为空（或条件行没配好）⇒ 没有可回测的东西；"
                                  "先在「单股回测」配好买卖条件再存策略")
            return None
        dims, dim_err = self.form.grid_dims()
        if dim_err:
            self.form.set_receipt(f"参数网格：{dim_err}")
            return None
        grid = build_grid(dims)
        if not grid.ok:
            self.form.set_receipt(f"参数网格：{grid.rejection}")
            return None
        iv = self.form.interval()
        df = self._lake.load_data("kline_daily", symbol)
        data_start = data_end = ""
        if df is not None and not df.empty and "date" in df.columns:
            d = pd.to_datetime(df["date"])
            data_start, data_end = str(d.min().date()), str(d.max().date())
        problems = list(validate_interval(iv, data_start, data_end))
        if df is None or df.empty:
            problems.insert(0, f"本地没有 {symbol} 的前复权日线 —— 先去 🗄 数据管理 预下载")
        if problems:
            self.form.set_interval_receipt("；".join(problems))
            self.form.set_receipt("区间没过校验，先解决上面的问题")
            return None
        self.form.set_interval_receipt(f"区间 OK（本地数据 {data_start} → {data_end}）")
        spec = SweepSpec(
            symbol=symbol,
            segments=segments_of(payload),
            params_text=str(payload.get("params_text") or ""),
            # ★1.66：条件**原样**递过去（是**配置 dict**，不是字符串）—— 旧版在这里 `str(...)`，
            #   dict 被转成 repr 文本（"{'rule': 'rise', …}"）⇒ 引擎 `parse` 报
            #   "无法识别的字符 '{'" ⇒ **每一组都失败**（点运行只看到"完成 0 组，失败 N 组"）。
            #   配置 → DSL 的转换由 `core.conditions` 在求值前统一做（唯一真源）。
            condition_buy=payload.get("condition_buy") or "",
            condition_sell=payload.get("condition_sell") or "",
            risk=dict(payload.get("risk") or {}),
            fill_mode=(payload.get("fill") or {}).get("fill_mode"),
            trigger_tick=(payload.get("fill") or {}).get("trigger_tick"),
            has_index_gate=index_gate_enabled(payload.get("index")))   # ★1.70 / §11.5-128
        self._spec, self._grid, self._interval = spec, grid, iv
        self._preset_key = self.form.preset_key()
        return spec, grid, iv

