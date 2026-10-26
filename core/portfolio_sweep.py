# core/portfolio_sweep.py
"""组合层级的**池化研究**（★1.85 / §7-B17 **P4**）—— 纯计算，零 Qt、零 IO。

【它解决什么】参数研究原来是"一只票一只票做"：在 A 股上挑出来的参数，换到 B 股就崩。
池化 = 把**一个组合的全部成分**当"小池"，逐只 × 逐折跑，最后给：
  · **每只票一行**（跨折中位数 IC / 中位数样本外收益 / 亏损折数）；
  · **一行组合加权**（按组合权重加权，回答"这一篮子整体怎么样"）；
  · 跨折分布（每折一行），用于看"是不是只有某一折好看"。

【折怎么切】用户口径（2026-10-26）：**默认 4 折、walk-forward**：
  把交易日按时间顺序切成 4 段，第 k 折用"第 k 段之外的历史"做样本内？—— 不。
  这里的 walk-forward 是**滚动前推**：第 k 折 = 用第 k 段做样本内、**紧随其后的那一段**做样本外
  （最后一折的样本外 = 最后一段）。**绝不把未来数据当前史**（这是这类研究唯一不能错的地方）。

【为什么内核只收"每折每只的结果"】真正的回测在 `core.param_sweep.run_sweep` 里跑（贵、要线程）；
本模块只做切分与聚合 ⇒ 可以用假数据把"聚合口径"钉死（冒烟就是这么做）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

FOLDS_DEFAULT = 4


@dataclass
class Fold:
    """一折的时间窗（**都是升序交易日**；`is_days` 在前、`oos_days` 紧随其后）。"""

    index: int
    is_days: list = field(default_factory=list)
    oos_days: list = field(default_factory=list)

    @property
    def is_start(self):
        return self.is_days[0] if self.is_days else ""

    @property
    def is_end(self):
        return self.is_days[-1] if self.is_days else ""

    @property
    def oos_start(self):
        return self.oos_days[0] if self.oos_days else ""

    @property
    def oos_end(self):
        return self.oos_days[-1] if self.oos_days else ""


def make_folds(days, folds: int = FOLDS_DEFAULT) -> list:
    """把交易日切成 `folds` 段；第 k 折 = 第 k 段（样本内）+ 第 k+1 段（样本外）。

    · 段数不足（`len(days) < folds*2`）⇒ **返回空列表**（界面据此说"数据太短，别硬跑"，不伪造折）；
    · 第 `folds-1` 折的样本外 = 第 `folds` 段 ⇒ **最后一折也只用"它之后的数据"**。
    """
    ds = [str(d) for d in (days or [])]
    n = len(ds)
    k = int(folds or 0)
    if k < 2 or n < (k + 1) * 2:                  # 要 k 折 ⇒ 需要 k+1 段
        return []
    segs_n = k + 1
    size = n // segs_n
    segs = [ds[i * size:(i + 1) * size] for i in range(segs_n)]
    segs[-1] = ds[(segs_n - 1) * size:]           # 余数并进最后一段（不丢交易日）
    out = []
    for i in range(k):
        # ★扩张窗口：第 i 折的样本内 = 前 i 段累积，样本外 = 紧随其后的第 i+1 段
        #   ⇒ **绝不把未来数据当历史**（这是这类研究唯一不能错的地方）
        out.append(Fold(index=i + 1, is_days=[d for seg in segs[:i + 1] for d in seg],
                        oos_days=segs[i + 1]))
    return out


def _median(xs):
    vals = sorted(float(x) for x in xs if x is not None and not (isinstance(x, float) and math.isnan(x)))
    if not vals:
        return float("nan")
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0


def aggregate(per_symbol: dict, weights: dict, symbols=None) -> dict:
    """把 `{symbol: [{'ic':…, 'ret':…}, …]}` 聚成"每只 + 组合加权"。

    返回 `{rows, weighted, folds, n_folds}`：
      · `rows`：`[{symbol, name?, weight, ic_med, ret_med, loss_folds, folds}]`（按权重降序）
      · `weighted`：`{ic_med_cross, ret_med_cross, ret_weighted, loss_folds}` ——
        **"组合加权"回答"这一篮子整体怎么样"**：各票逐折收益按权重加权后，再取跨折中位数；
        IC 同理（权重 × 各票跨折中位数）。
      · `loss_folds` = 有任一票为负的折数（**跨票最差情况**，不是平均，避免"平均掩盖暴雷"）。
    """
    syms = [str(s) for s in (symbols if symbols is not None else per_symbol.keys())]
    syms = [s for s in syms if s in per_symbol]
    rows = []
    fold_ic, fold_ret = {}, {}
    for s in syms:
        recs = per_symbol.get(s) or []
        ics = [r.get("ic") for r in recs]
        rets = [r.get("ret") for r in recs]
        rows.append({"symbol": s, "weight": round(float((weights or {}).get(s) or 0.0), 2),
                     "ic_med": _median(ics), "ret_med": _median(rets),
                     "loss_folds": sum(1 for v in rets if v is not None and float(v) < 0),
                     "folds": len(recs)})
        for i, r in enumerate(recs):
            fold_ic.setdefault(i, []).append(r.get("ic"))
            fold_ret.setdefault(i, []).append(r.get("ret"))
    rows.sort(key=lambda r: -r["weight"])

    w_sum = sum(r["weight"] for r in rows) or 0.0
    weighted_ret_series = []
    fold_rows = []
    for i in sorted(fold_ret):
        # 每一折：先把各票收益按权重加权（缺值的按"剩下的权重"归一，**不拿 0 顶**）
        pairs = [(float(rows[j]["weight"]), fold_ret[i][j]) for j in range(len(rows))
                 if j < len(fold_ret[i]) and fold_ret[i][j] is not None]
        ww = sum(w for w, _v in pairs)
        if ww > 0 and pairs:
            weighted_ret_series.append(sum(w * float(v) for w, v in pairs) / ww)
        fold_rows.append({"fold": i + 1, "ic_med": _median(fold_ic.get(i, [])),
                          "ret_med": _median(fold_ret.get(i, []))})
    weighted = {
        "ret_weighted": (sum(r["weight"] * r["ret_med"] for r in rows) / w_sum)
        if w_sum and all(isinstance(r["ret_med"], float) for r in rows) else float("nan"),
        "ret_med_cross": _median(weighted_ret_series),
        "ic_med_cross": (sum(r["weight"] * r["ic_med"] for r in rows) / w_sum)
        if w_sum and all(isinstance(r["ic_med"], float) for r in rows) else float("nan"),
        "loss_folds": sum(1 for r in fold_rows if r["ret_med"] is not None and float(r["ret_med"]) < 0),
    }
    return {"rows": rows, "weighted": weighted, "folds": fold_rows,
            "n_folds": len(fold_rows)}


CSV_HEADER = ["类型", "代码", "权重%", "IC中位数", "收益中位数", "亏损折数", "折数"]


def csv_rows(result: dict) -> list:
    """把 `aggregate()` 的结果展平成 CSV 行（**含"组合加权"那一行**）。"""
    out = [list(CSV_HEADER)]
    for r in result.get("rows") or []:
        out.append(["标的", r["symbol"], f"{r['weight']:.2f}", _fmt(r["ic_med"]),
                    _fmt(r["ret_med"]), str(r["loss_folds"]), str(r["folds"])])
    w = result.get("weighted") or {}
    out.append(["组合加权", "（全部成分）", "100.00", _fmt(w.get("ic_med_cross")),
                _fmt(w.get("ret_med_cross")), str(w.get("loss_folds") or 0),
                str(result.get("n_folds") or 0)])
    for f in result.get("folds") or []:
        out.append([f"第 {f['fold']} 折", "（跨票）", "", _fmt(f["ic_med"]), _fmt(f["ret_med"]), "", ""])
    return out


def _fmt(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    return "—" if math.isnan(f) else f"{f:+.4f}"


__all__ = ["FOLDS_DEFAULT", "Fold", "make_folds", "aggregate", "csv_rows", "CSV_HEADER"]
