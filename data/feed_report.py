# data/feed_report.py
"""交割单的**结算月报页签解析**（1.25 自 `data/data_feed.py` 拆出 · §9-L）。

【职责】只解析「客户交易结算月报」的资金勾稽区：
  · `_scan_labeled_values`：二维表「标签 → 数值」扫描（左右双块布局，靠标签名定位，
    不硬编码列号）；
  · `_parse_monthly_report`：产出 `MonthlySummary`；任何字段缺失都回落到 0.0，
    **绝不抛异常**（月度对账允许缺失，不能拖垮整次导入）。

【纯粹性约束】同 `data_feed.py`：**不碰数据库、不碰 UI**（迁移逐字保留）。
"""
import logging

import pandas as pd

from data.feed_cells import REPORT_LABELS, REPORT_SHEET, _to_float, clean_str
from data.feed_fifo import MonthlySummary

logger = logging.getLogger(__name__)


def _scan_labeled_values(df: pd.DataFrame, label_map: dict) -> dict:
    """
    扫描二维表，找出「标签 → 数值」映射。

    结算月报的资金区采用左右双块布局（左块 标签在第0列、右块 标签在第5列），
    与其硬编码列号，不如直接扫描：命中标签后取该行右侧第一个可解析的数值。
    """
    found = {}
    for _, row in df.iterrows():
        values = row.tolist()
        for i, cell in enumerate(values):
            key = label_map.get(clean_str(cell))
            if not key or key in found:
                continue
            for candidate in values[i + 1:]:
                # 用 None 作为默认值以区分"解析失败"与"数值就是 0"
                num = _to_float(candidate, default=None)
                if num is not None:
                    found[key] = num
                    break
    return found


def _parse_monthly_report(xls: pd.ExcelFile, account: str,
                          source_file: str) -> MonthlySummary:
    """解析结算月报的资金勾稽区；任何字段缺失都回落到 0.0，绝不抛异常"""
    blank = MonthlySummary(account, "", 0.0, 0.0, 0.0, 0.0, 0.0, source_file)
    try:
        if REPORT_SHEET not in xls.sheet_names:
            return blank
        df = pd.read_excel(xls, sheet_name=REPORT_SHEET, header=None)
        values = _scan_labeled_values(df, REPORT_LABELS)
        return MonthlySummary(
            account=account,
            month="",  # 月份由 _infer_months 依据成交日期 / 资金链推断
            prev_balance=values.get('prev_balance', 0.0),
            equity=values.get('equity', 0.0),
            month_pnl=values.get('month_pnl', 0.0),
            month_fee=values.get('month_fee', 0.0),
            month_deposit=values.get('month_deposit', 0.0),
            source_file=source_file,
        )
    except Exception as e:
        logger.warning(f"{source_file}: 结算月报解析失败 ({e})，月度对账将跳过该文件")
        return blank
