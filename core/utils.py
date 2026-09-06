# core/utils.py
"""
通用无副作用工具函数集合 (Pure Helpers)。
只放置被多个模块复用的、与业务状态无关的纯函数，避免出现循环依赖。
"""
import re

import pandas as pd


def extract_root_symbol(symbol) -> str:
    """
    从完整合约代码中提取“品种主体”。
    例: "RB2410" -> "RB"；"600519" -> "600519"；"IF2309" -> "IF"
    """
    text = str(symbol)
    match = re.match(r'^[A-Za-z]+', text)
    return match.group().upper() if match else text.upper()


def format_trade_time(value) -> str:
    """
    将交易时间渲染成可读文本 (v1.1 数据契约)。
    - 交割单只有日期 (当天零点) -> 显示 "YYYY-MM-DD"，避免出现虚假的 00:00
    - 手工/外部数据带有具体时分 -> 显示 "YYYY-MM-DD HH:MM"
    """
    if value is None:
        return "-"
    try:
        t = pd.to_datetime(value)
    except Exception:
        return "-"
    if pd.isna(t):
        return "-"
    if t.hour or t.minute or t.second:
        return t.strftime("%Y-%m-%d %H:%M")
    return t.strftime("%Y-%m-%d")


def format_price(value) -> str:
    """
    渲染成交价 (v1.2)。

    【诚实原则】过月遗留单没有开仓价，一律渲染为 "—"，
    绝不显示 0.00 —— 那会让用户误以为自己是在 0 元开的仓。
    """
    if value is None:
        return "—"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "—"
    if pd.isna(num) or num == 0:
        return "—"
    # 按实际精度显示（最多 4 位小数），避免 6012.40 这类画蛇添足的补零
    return f"{num:,.4f}".rstrip('0').rstrip('.')


def format_points(value) -> str:
    """渲染点数盈亏（带正负号）；开仓价缺失时返回 "—" """
    if value is None:
        return "—"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "—"
    if pd.isna(num):
        return "—"
    return f"{num:+,.1f}"


def row_points(record) -> float | None:
    """
    从一条记录（Series / dict / TradeRecord 均可）计算点数盈亏。
    LONG : 平仓价 - 开仓价；SHORT : 开仓价 - 平仓价。
    开仓价缺失时返回 None，交由上层渲染成 "—"。
    """
    entry = record.get('entry_price') if hasattr(record, 'get') else getattr(record, 'entry_price', None)
    exit_ = record.get('exit_price') if hasattr(record, 'get') else getattr(record, 'exit_price', None)
    if entry is None or exit_ is None:
        return None
    try:
        entry, exit_ = float(entry), float(exit_)
    except (TypeError, ValueError):
        return None
    if pd.isna(entry) or pd.isna(exit_) or not entry or not exit_:
        return None
    diff = exit_ - entry
    direction = record.get('direction') if hasattr(record, 'get') else getattr(record, 'direction', 'LONG')
    return diff if direction == 'LONG' else -diff


def format_fill_time(value) -> str:
    """渲染成交时刻；无时分信息时返回空串（配合主时间列显示纯日期）"""
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() in ('nan', 'nat', 'none'):
        return ""
    return text[:5]  # HH:MM 足够，秒级精度对复盘意义不大


# ==========================================
# v1.3 持仓时长工具 (Holding Duration)
# ==========================================
def _as_date(value):
    """安全转成 datetime.date；失败返回 None"""
    try:
        parsed = pd.to_datetime(value)
        return None if pd.isna(parsed) else parsed.date()
    except Exception:
        return None


def _has_clock(value) -> bool:
    """该时间点是否带有具体时分（非 00:00）"""
    try:
        t = pd.to_datetime(value)
        if pd.isna(t):
            return False
        return bool(t.hour or t.minute or t.second)
    except Exception:
        return False


def record_entry_has_clock(record) -> bool:
    """开仓侧是否带有时分 —— 决定能否做精确到小时的时长计时"""
    return _has_clock(record.get('entry_time'))


def record_exit_has_clock(record) -> bool:
    """平仓侧是否带有时分（exit_fill_time 优先，其次 trade_time 自身）"""
    if format_fill_time(record.get('exit_fill_time')):
        return True
    return _has_clock(record.get('trade_time'))


def record_holding_seconds(record) -> float | None:
    """
    精确持仓秒数：仅当开仓侧携带具体时分时才可精确计时。

    【诚实原则】
      - 开仓侧带时分、平仓侧有完整时刻 → 返回精确秒数
      - 开仓侧只有日期（无时分）→ 返回 None，
        因为"开仓在当天几点"未知，绝不能用 00:00 冒充，交给天级口径处理。
    """
    if not record_entry_has_clock(record):
        return None
    entry_raw = record.get('entry_time')
    trade_raw = record.get('trade_time')
    if entry_raw is None or trade_raw is None:
        return None
    try:
        entry_dt = pd.to_datetime(entry_raw)
        exit_dt = pd.to_datetime(trade_raw)
        if pd.isna(entry_dt) or pd.isna(exit_dt):
            return None
        # 平仓若带时分（exit_fill_time），合成完整时刻；否则取当天零点（date-only）
        fill = format_fill_time(record.get('exit_fill_time'))
        if fill:
            exit_dt = pd.to_datetime(f"{exit_dt:%Y-%m-%d} {fill}")
        return float((exit_dt - entry_dt).total_seconds())
    except Exception:
        return None


def trading_day_count(start, end, trading_dates) -> int | None:
    """
    在给定交易日历中，统计从 start 日到 end 日的「持仓跨度」（相隔多少个交易日）。

    例：周五开仓、下周一平仓 → 跨 1 个交易日（自然日会误算成 3）。
    当日开平 → 0（若开仓侧无时分，0 应显示为"当日·时分未知"，不得冒充精确）。
    【诚实边界】start/end 任一不在日历中（停牌/本地无行情）时返回 None，
    由调用方回退到自然日口径并如实标注，绝不硬凑。
    """
    start_d = _as_date(start)
    end_d = _as_date(end)
    if start_d is None or end_d is None:
        return None
    try:
        dates = sorted({pd.to_datetime(d).date() for d in trading_dates})
    except Exception:
        return None
    if not dates:
        return None
    if start_d not in dates or end_d not in dates:
        return None
    idx_start = dates.index(start_d)
    idx_end = dates.index(end_d)
    if idx_end < idx_start:
        return None
    return idx_end - idx_start


def format_duration(seconds) -> str:
    """
    把持仓秒数渲染成人类可读文本：
      <60 秒  → "N秒"
      分钟级  → "N分" / "N分M秒"
      小时级  → "N小时" / "N小时M分"
      天级    → "N天N小时"
    """
    if seconds is None:
        return "—"
    try:
        total = float(seconds)
    except (TypeError, ValueError):
        return "—"
    if total < 0:
        total = 0.0
    if total < 60:
        return f"{int(total)}秒"
    if total < 3600:
        minutes = int(total // 60)
        secs = int(total % 60)
        return f"{minutes}分{secs}秒" if secs else f"{minutes}分"
    days = int(total // 86400)
    hours = int((total % 86400) // 3600)
    minutes = int((total % 3600) // 60)
    if days:
        return f"{days}天{hours}小时" if hours else f"{days}天"
    if minutes:
        return f"{hours}小时{minutes}分"
    return f"{hours}小时"


def format_days_count(days) -> str:
    """渲染"跨 N 个交易日/自然日"的天级时长"""
    if days is None:
        return "—"
    return f"{int(days)}个交易日" if days else "当日"


def align_by_date(values: dict[str, pd.Series], anchor_dates,
                  default: float = 0.0) -> dict[str, pd.Series]:
    """
    【日期对齐工具 (阶段C)】把"外部日历"的序列(如指数函数输出)对齐到"个股交易日"。

    背景：指数交易日与个股交易日不完全一致(停牌/节假日)，
    回测引擎只认识个股行情 df 的日期轴。这里把指数侧每个变量：
      1) 以自身日期为索引；
      2) reindex 到 anchor_dates (个股交易日)：缺失日期用最近前值 ffill；
      3) 仍早于序列首日的前导空洞用 default 兜底 (默认 0)。

    使用场景：指数 regime 门控列 = align_by_date(指数变量, 个股df['date'])[var]，
    随后作为普通列拼入个股 df，即可被公式引擎/买卖表达式引用 (引擎零改动)。

    :param values: {变量名: 以日期为索引的 Series}
    :param anchor_dates: 对齐目标日期 (个股交易日，datetime 可转换，允许乱序)
    :param default: 前导空洞填充值 (门控列建议 False->0)
    :return: {变量名: 与 anchor_dates 原顺序等长的 Series}
    """
    try:
        anchor_raw = list(pd.to_datetime(list(anchor_dates)))
        anchors_sorted = pd.DatetimeIndex(sorted(anchor_raw))
    except Exception:
        return {k: pd.Series([default] * len(list(anchor_dates))) for k in values}

    out = {}
    for name, series in values.items():
        s = series.copy()
        # 规范日期索引：排序 + 去重(保留最后一个)
        s.index = pd.to_datetime(s.index)
        s = s[~s.index.duplicated(keep="last")].sort_index()
        aligned = s.reindex(anchors_sorted, method="ffill").fillna(default)
        # 还原到调用方给定的原顺序 (DataFrame 按 index 赋值可自动对齐)
        out[name] = aligned.reindex(pd.DatetimeIndex(anchor_raw))
    return out
