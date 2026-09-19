# data/feed_months.py
"""交割单的**月份推断与资金链对账**（1.25 自 `data/data_feed.py` 拆出 · §9-L）。

【职责】给每个文件确定它"实际属于哪个月"，以及检测导入月份断层：
  · `_infer_months`：以**成交明细里的交易日期众数**为准（不信表头「交易月份」）；
  · `_link_months_by_balance`：用资金恒等式为"零成交的月份"补出归属；
  · `_prev_month`：取上一个月 'YYYY-MM'（漏月检测用）。

【纯粹性约束】只吃/吐普通 dict，**不碰数据库、不碰 UI**（迁移逐字保留）。
"""
# ==========================================
# 月份推断 (Month Inference)
# ==========================================
def _infer_months(per_file: list[dict]) -> list[dict]:
    """
    推断每个文件实际所属的月份。

    【为什么不能信表头的「交易月份」】实测 2025-07 的样例文件里该字段写成了
    `2025-09`，与文件名和真实数据都不符。因此一律以**成交明细里的交易日期众数**
    为准；没有成交的月份（如空仓的 6 月）交给 _link_months_by_balance 用资金链反推。
    """
    for item in per_file:
        dates = [f.trade_date for f in item['fills'] if f.trade_date]
        if dates:
            counter = {}
            for d in dates:
                key = d.strftime('%Y-%m')
                counter[key] = counter.get(key, 0) + 1
            item['month'] = max(counter, key=counter.get)
        else:
            item['month'] = ""
        item['summary'].month = item['month']
    return per_file


def _link_months_by_balance(per_file: list[dict]) -> list[dict]:
    """
    用资金链为"无成交的月份"补出月份归属。

    恒等式（实测四个月全部精确成立）：
        客户权益 = 上月结存 + 当月存取合计 + 当月盈亏 - 当月手续费
    链条关系：第 N 月的「上月结存」 == 第 N-1 月的「客户权益」。
    因此即便某月零成交，也能靠它在链条中的位置锁定月份。
    """
    known = {f['month']: f for f in per_file if f['month']}
    for item in per_file:
        if item['month']:
            continue
        summary = item['summary']
        if not summary.prev_balance:
            continue
        # 找到"客户权益 == 本文件上月结存"的那个月，本文件即排在它之后
        for month, anchor in known.items():
            if anchor['summary'].equity and abs(anchor['summary'].equity - summary.prev_balance) < 0.01:
                year, mon = (int(x) for x in month.split('-'))
                mon += 1
                if mon > 12:
                    year, mon = year + 1, 1
                item['month'] = f"{year:04d}-{mon:02d}"
                item['summary'].month = item['month']
                break
    return per_file


def _prev_month(month: str) -> str:
    """返回上一个月的 'YYYY-MM' 表示"""
    year, mon = (int(x) for x in month.split('-'))
    mon -= 1
    if mon == 0:
        year, mon = year - 1, 12
    return f"{year:04d}-{mon:02d}"
