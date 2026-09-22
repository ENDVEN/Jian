# ui/widgets/backtest_xlsx.py
"""
📊 回测结果导出为 .xlsx（§7-A2 · v1.36）—— 用 openpyxl **内嵌真正的图表**。

【为什么要它】CSV 是纯文本，物理上装不了渲染图；用户要"打开文件就见图"，只能走
  .xlsx（openpyxl 支持 LineChart + marker 系列）。本模块只负责"结果 → xlsx 文件"，
  与 CSV/PNG 导出并列（页面只连按钮，§9-L 体积债：不把渲染堆进 `backtest.py`）。

【图里画什么】按用户拍板：净值曲线 + 买卖点标记（不含 K线/收盘价、不含公式指标线）。
  买卖点用"成交当日的净值"定位（点落在曲线上），而非成交价——成交价与净值不同量纲，
  直接画会跑出坐标轴。数据源与 CSV 共用 `build_daily_series`（单一事实来源）。

【分层】纯装配 `write_result_xlsx(result, meta, path_or_stream)` 与 IO 入口
  `export_result_xlsx_file`（文件对话框 + 回执）分离，便于在内存 BytesIO 上断言、
  不污染用户目录。
"""
from __future__ import annotations

from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.chart.marker import Marker
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.drawing.line import LineProperties
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from core.backtest import EXIT_REASON_LABELS, T1_SUMMARY, fill_summary
from ui.widgets.backtest_export import (build_daily_series, _default_stem,
                                        risk_readable)


def _append_detail_sheet(ws, result, meta: dict) -> None:
    """Sheet「回测明细」：参数快照 + KPI + 逐笔成交（与 CSV 同源字段）。"""
    ws.append(["交易品种", f"{meta.get('name') or '-'} ({meta.get('symbol') or '-'})"])
    ws.append(["回测区间", f"{meta.get('start_date')} ~ {meta.get('end_date')}"])
    ws.append(["策略", meta.get("strategy_name") or "（未保存）"])
    if meta.get("segments"):
        ws.append(["函数段", ""])
        for seg in meta["segments"]:
            for line in str(seg).splitlines():
                ws.append(["", line.strip()])
    ws.append(["函数参数", meta.get("params_text") or "（无）"])
    ws.append(["买入表达式", meta.get("buy_expr") or "—"])
    ws.append(["卖出表达式", meta.get("sell_expr") or "—"])
    ws.append(["风控", risk_readable(meta.get("risk") or {})])
    fill = meta.get("fill") or {}
    ws.append(["成交模型", fill_summary(fill.get("fill_mode"), fill.get("trigger_tick"))])
    ws.append(["", T1_SUMMARY])
    index = meta.get("index")
    if index:
        ws.append(["指数门控", "已启用 {}（买入许可: {} / 卖出破位: {}）".format(
            index.get("symbol"), index.get("expr_buy") or "—", index.get("expr_sell") or "—")])
    else:
        ws.append(["指数门控", "未启用"])
    s = result.summary()
    ws.append(["KPI", "总成交 {} 笔 | 胜率 {:.2f}% | 累计收益 {:+.2f}% | 平均单笔 {:+.2f}%".format(
        s["total_trades"], s["win_rate"] * 100, s["cumulative_return"] * 100,
        s["avg_return_pct"] * 100)])
    ws.append([])
    ws.append(["买入日期", "买入价", "卖出日期", "卖出价", "持有天数",
               "盈亏", "收益率", "离场原因"])
    for t in result.trades:
        ws.append([
            _fmt_date(t.entry_date), round(float(t.entry_price), 2),
            _fmt_date(t.exit_date), round(float(t.exit_price), 2),
            t.days_held if t.days_held is not None else "",
            round(float(t.pnl), 2), round(float(t.return_pct), 4),
            EXIT_REASON_LABELS.get(getattr(t, "exit_reason", "signal"), "卖出信号")
            + ("（T+1 顺延）" if getattr(t, "deferred_t1", False) else ""),
        ])


def _fmt_date(value) -> str:
    import pandas as pd
    try:
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    except (ValueError, TypeError):  # noqa: BLE001
        return str(value or "")


def _append_equity_chart(wb, result) -> None:
    """可见 sheet「净值曲线」只放图；逐日数据放**隐藏** sheet「净值数据」（图表引用它）。

    这样主表打开只见一张干净的净值曲线图（+买卖点），不被几千行逐日数字刷屏；
    数据仍在（隐藏 sheet），图照常渲染。
    """
    ws = wb.create_sheet("净值曲线")            # 可见：只放图
    data = wb.create_sheet("净值数据")           # 隐藏：逐日数据（图表源）
    data.sheet_state = "hidden"
    data.append(["日期", "净值", "买点", "卖点"])
    daily = build_daily_series(result)
    if daily is None or daily.empty:
        return
    import pandas as pd
    for r in daily.itertuples(index=False):
        eq = round(float(r.equity), 4)
        buy_at = eq if pd.notna(r.buy_price) else None      # 买卖点用成交日净值定位（落在曲线上）
        sell_at = eq if pd.notna(r.sell_price) else None
        data.append([r.date, eq, buy_at, sell_at])
    n = len(daily) + 1                       # 含表头行
    chart = LineChart()
    chart.title = "净值曲线（含买卖点）"
    chart.style = 2
    chart.y_axis.title = "归一净值"
    chart.x_axis.title = "日期"
    chart.height, chart.width = 12, 26
    chart.plotVisOnly = False                # 数据在隐藏 sheet，仍要画出来
    ref = Reference(data, min_col=2, max_col=4, min_row=1, max_row=n)   # 净值/买点/卖点
    cats = Reference(data, min_col=1, min_row=2, max_row=n)               # 日期
    chart.add_data(ref, titles_from_data=True)
    chart.set_categories(cats)
    # 买点(idx1)/卖点(idx2)：只画标记、不连线，点落在净值曲线上
    for idx, sym in ((1, "circle"), (2, "diamond")):
        if idx < len(chart.series):
            s = chart.series[idx]
            s.marker = Marker(symbol=sym, size=8)
            s.graphicalProperties = GraphicalProperties(ln=LineProperties(noFill=True))
    ws.add_chart(chart, "B2")


def _build_workbook(result, meta: dict) -> Workbook:
    """构建 workbook（回测明细 + 可见「净值曲线」图 + 隐藏「净值数据」）。与存盘解耦，
    便于内存断言（openpyxl 读回会丢图表，只能对**构建时**的 Workbook 对象断言）。"""
    wb = Workbook()
    ws_detail = wb.active
    ws_detail.title = "回测明细"
    _append_detail_sheet(ws_detail, result, meta)
    _append_equity_chart(wb, result)
    return wb


def write_result_xlsx(result, meta: dict, path_or_stream) -> None:
    """把一次回测结果写成 .xlsx（两个 sheet：明细 + 内嵌净值曲线图）。

    `path_or_stream` 可为文件路径或 BytesIO（测试用后者，不落真实目录）。
    """
    _build_workbook(result, meta).save(path_or_stream)


def export_result_xlsx_file(parent, *, result, meta: dict, symbol: str, name: str) -> bool:
    """导出入口：文件对话框 + 落盘 + 回执（渲染在 `write_result_xlsx`）。"""
    default_name = f"回测图表_{_default_stem(meta, symbol, name)}.xlsx"
    file_path, _ = QFileDialog.getSaveFileName(
        parent, "导出 Excel 图表", default_name, "Excel 工作簿 (*.xlsx)")
    if not file_path:
        return False
    try:
        write_result_xlsx(result, meta, file_path)
    except Exception as e:  # noqa: BLE001 —— 写盘异常必须出声，绝不静默
        QMessageBox.critical(parent, "导出失败", f"生成 Excel 时发生错误：\n{e}")
        return False
    QMessageBox.information(
        parent, "导出成功",
        f"回测结果已导出为 Excel（含净值曲线图 + 买卖点，共 {len(result.trades)} 笔成交）：\n\n{file_path}")
    return True
