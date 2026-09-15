# ui/widgets/backtest_export.py
"""
📐 回测结果导出（1.22 · 自 `ui/views/backtest.py` 拆出，§9-L 体积债）。

【为什么单独成模块】导出属于"把已有结果变成文件"，与页面版式/交互无关：
  · `compose_result_csv` 是**纯函数**（结果 + 参数快照 → 文本），最容易断言；
  · 两个 `export_*` 只负责文件对话框 + 落盘回执（页面只连按钮）。
拆出后页面不再为"导出"这一件事承担 140 行，且未来「回测结果历史存档」可复用同一渲染。

【铁律】导出的必须是 `meta` 这份**参数快照**（start_backtest 时定格），
而不是导出瞬间编辑框里的内容 —— 否则"导出的东西"与"跑出来的东西"会不一致。
"""
import csv
import io

import pandas as pd
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from core.backtest import EXIT_REASON_LABELS, T1_SUMMARY, fill_summary, risk_summary
from ui.widgets.backtest_report import render_result_png


def risk_readable(risk: dict) -> str:
    """风控人话文案 —— 唯一来源 core/backtest.risk_summary，禁止在此另写一份"""
    return risk_summary(risk)


def compose_result_csv(result, meta: dict) -> str:
    """把一次回测结果渲染成规范 CSV 文本（表头参数块 + 逐笔成交明细）。

    拆成纯函数便于断言：导出的东西必须等于"这次跑出来的结果"，不掺现编。
    v5.15 起**不再输出每日净值行**（用户拍板，见文件尾注释）。

    【v5.16 为什么连"注释头行"都走 csv.writer 转义】
    函数源码里很多行含**英文逗号**（`STICKLINE(A, B, C, 3, 0), COLORFF0000;`、
    `MA(C, 5)`）。若像 v5.15 那样"裸写"，Excel/WPS 打开时会把这类行
    按逗号拆成多列，"第三部分：图形绘制"看起来就是碎成一格格的乱码。
    正确做法：每个逻辑行作为一个**单格字段**交给 csv.writer —— 含逗号的
    行被规范加引号（任何表格软件都把它还原成"一格"），不含逗号的行原样单格；
    空行用 `writerow([])`（真·空行，不会产生 `""` 假空行）。
    """
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")

    def row(text: str):
        writer.writerow([text])   # 单格行：csv 自动决定是否加引号

    def blank():
        writer.writerow([])       # 真·空行，避免产生 `""`

    # ---- 表头：参数快照（来自 start_backtest 定格的那份）----
    row("# 交易品种: {name} ({symbol})".format(
        name=meta.get("name") or "-", symbol=meta.get("symbol") or "-"))
    row(f"# 回测区间: {meta.get('start_date')} ~ {meta.get('end_date')}")
    row(f"# 策略: {meta.get('strategy_name') or '（未保存）'}")
    if meta.get("segments"):
        row("# 函数段:（以下每行一段，多段在同一个变量池顺序执行）")
        for seg in meta["segments"]:
            for seg_line in str(seg).splitlines():
                row("    " + seg_line)
    row(f"# 函数参数: {meta.get('params_text') or '（无）'}")
    row(f"# 买入表达式: {meta.get('buy_expr')}")
    row(f"# 卖出表达式: {meta.get('sell_expr')}")
    row(f"# 风控: {risk_readable(meta.get('risk') or {})}")
    # v6.17：成交时点模型 + T+1 —— 不写进报告，导出内容就"不可复现"
    fill = meta.get("fill") or {}
    row("# 成交模型: " + fill_summary(fill.get("fill_mode"), fill.get("trigger_tick")))
    row(f"# {T1_SUMMARY}")
    index = meta.get("index")
    if index:
        row("# 指数门控: 已启用 {symbol}（买入许可: {b} / 卖出破位: {s}）".format(
            symbol=index.get("symbol"),
            b=index.get("expr_buy") or "—",
            s=index.get("expr_sell") or "—"))
    else:
        row("# 指数门控: 未启用")

    # ---- KPI ----
    summary = result.summary()
    row(f"# KPI: 总成交 {summary['total_trades']} 笔 | 胜率 {summary['win_rate'] * 100:.2f}% | "
        f"累计收益 {summary['cumulative_return'] * 100:+.2f}% | "
        f"平均单笔 {summary['avg_return_pct'] * 100:+.2f}%")
    blank()

    # ---- 逐笔成交明细（数值列保持裸数值，方便 Excel 二次计算）----
    writer.writerow(["买入日期", "买入价", "卖出日期", "卖出价", "持有天数",
                     "盈亏", "收益率", "离场原因"])
    for t in result.trades:
        entry = pd.Timestamp(t.entry_date).strftime("%Y-%m-%d")
        exit_ = pd.Timestamp(t.exit_date).strftime("%Y-%m-%d")
        writer.writerow([
            entry, f"{t.entry_price:.2f}", exit_, f"{t.exit_price:.2f}",
            str(t.days_held if t.days_held is not None else ""),
            f"{t.pnl:.2f}", f"{t.return_pct:.4f}",
            EXIT_REASON_LABELS.get(getattr(t, "exit_reason", "signal"), "卖出信号")
            + ("（T+1 顺延）" if getattr(t, "deferred_t1", False) else ""),
        ])
    # NOTE(v5.15 · 用户拍板)：不再输出 200+ 行的「每日净值明细」——
    #   ① 它是 CSV 可读性低的主因；② 专业投资者要核查的确定性事实是 参数+逐笔，
    #   引擎可用相同参数复现净值序列；③ 净值曲线的可视化由「导出结果图 PNG」承担。
    return buf.getvalue()


def _default_stem(meta: dict, symbol: str, name: str) -> str:
    return f"{name}_{symbol}_{meta.get('start_date') or ''}~{meta.get('end_date') or ''}"


def export_result_csv(parent, *, result, meta: dict, symbol: str, name: str) -> bool:
    """把"当前这份 result"导出为 CSV（仅导出，不落库、不删除 —— 见 §7-A2）。"""
    default_name = f"回测_{_default_stem(meta, symbol, name)}.csv"
    file_path, _ = QFileDialog.getSaveFileName(
        parent, "导出回测明细", default_name, "CSV 数据表 (*.csv)")
    if not file_path:
        return False
    try:
        text = compose_result_csv(result, meta)
        with open(file_path, "w", encoding="utf-8-sig", newline="") as f:
            f.write(text)
    except OSError as e:
        QMessageBox.critical(parent, "导出失败", f"文件写入失败：\n{e}")
        return False
    QMessageBox.information(
        parent, "导出成功",
        f"本次回测明细已导出（共 {len(result.trades)} 笔成交）：\n\n{file_path}")
    return True


def export_result_png_file(parent, *, result, meta: dict, symbol: str, name: str) -> bool:
    """把"当前这份 result"渲染成单页 PNG 报告图（v5.15）。

    只做入口 + 文件对话框；真正的渲染在 `ui/widgets/backtest_report.py`（可被
    未来的「结果历史存档」复用）。
    """
    default_name = f"回测报告_{_default_stem(meta, symbol, name)}.png"
    file_path, _ = QFileDialog.getSaveFileName(
        parent, "导出结果图", default_name, "PNG 图片 (*.png)")
    if not file_path:
        return False
    try:
        ok = render_result_png(meta, result, file_path)
    except Exception as e:  # noqa: BLE001 —— 渲染异常要给反馈，绝不静默
        QMessageBox.critical(parent, "导出失败", f"生成报告图时发生错误：\n{e}")
        return False
    if not ok:
        QMessageBox.critical(parent, "导出失败", f"报告图保存失败：\n{file_path}")
        return False
    QMessageBox.information(
        parent, "导出成功",
        f"回测报告图已导出（共 {len(result.trades)} 笔成交）：\n\n{file_path}")
    return True
