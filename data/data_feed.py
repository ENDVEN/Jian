# data/data_feed.py
import uuid
import re
import logging
from abc import ABC, abstractmethod
from datetime import datetime

import pandas as pd

from models.trade import TradeRecord

# CFMMC 交割单中用于判定“开仓/平仓”与“买/卖”的合法取值
BUY, SELL = '买', '卖'

# 结算单中存放成交流水的工作表名
TRADE_SHEET = '成交明细'
DEFAULT_ACCOUNT = "CFMMC真实账户"


def clean_str(s):
    """强力清洗字符串中的所有空白字符（包括前后空格、制表符等）"""
    if pd.isna(s): return ""
    return re.sub(r'\s+', '', str(s))


def _to_float(value, default=0.0) -> float:
    """安全转浮点数，遇到 '1,234.5'、空值或脏数据一律回落到默认值"""
    try:
        result = pd.to_numeric(str(value).replace(',', ''), errors='coerce')
        return default if pd.isna(result) else float(result)
    except Exception:
        return default


def _extract_account_name(xls: pd.ExcelFile, fallback: str) -> str:
    """从结算月报页签中容错提取客户名称，失败时回落到默认账户名"""
    try:
        if '客户交易结算月报' not in xls.sheet_names:
            return fallback
        df_info = pd.read_excel(xls, sheet_name='客户交易结算月报', header=None)
        for _, row in df_info.iterrows():
            if '客户名称' in str(row.values):
                for cell in row.values[1:]:
                    if pd.notna(cell) and str(cell).strip():
                        return str(cell).strip()
                break
    except Exception as e:
        logging.debug(f"未能从结算月报提取客户名称，使用默认账户: {e}")
    return fallback


def _locate_header_row(df_raw: pd.DataFrame) -> int:
    """在原始无表头数据中定位真正的表头行 (包含“交易日期”或“成交日期”)"""
    for idx, row in df_raw.iterrows():
        if '交易日期' in str(row.values) or '成交日期' in str(row.values):
            return idx
    return -1


def _build_dataframe(df_raw: pd.DataFrame, header_idx: int) -> pd.DataFrame:
    """
    【性能要点】整个文件只读一次 Excel。
    用定位到的表头行手动重建 DataFrame，避免二次 IO 解析同一张表。
    """
    raw_header = df_raw.iloc[header_idx].tolist()

    columns, seen = [], {}
    for i, cell in enumerate(raw_header):
        name = clean_str(cell) or f"__unnamed_{i}"
        # 同名列去重，防止后续 row.get() 取到 DataFrame 而非标量
        if name in seen:
            seen[name] += 1
            name = f"{name}.{seen[name]}"
        else:
            seen[name] = 0
        columns.append(name)

    df = df_raw.iloc[header_idx + 1:].copy()
    df.columns = columns
    return df.reset_index(drop=True)


# ==========================================
# 解析器抽象层 (Extension Boundary)
# ==========================================
class BaseTradeParser(ABC):
    """
    交易账单解析器抽象基类。

    【扩展点】未来接入新的券商 / 期货公司账单，只需：
      1. 继承本类并实现 parse()
      2. 声明 name 与 supported_extensions
      3. 登记进 PARSER_REGISTRY
    UI 层通过 get_parser(name) 取用，完全无需改动。
    """
    name = "未命名解析器"
    supported_extensions: tuple = ()

    @abstractmethod
    def parse(self, file_path) -> list[TradeRecord]:
        """解析账单文件，返回已配对闭环的交易记录列表"""

    @classmethod
    def supports(cls, file_path) -> bool:
        """按扩展名粗筛，用于导入向导自动推荐解析器"""
        return str(file_path).lower().endswith(cls.supported_extensions)


class CFMMCTradeParser(BaseTradeParser):
    """中国期货市场监控中心 (CFMMC) 结算单解析器"""
    name = "CFMMC 期货结算单"
    supported_extensions = ('.xls', '.xlsx')

    def parse(self, file_path) -> list[TradeRecord]:
        # 【资源安全】ExcelFile 持有文件句柄，必须显式关闭，
        # 否则 Windows 下会锁死文件，导致用户无法删除或覆盖源文件。
        xls = pd.ExcelFile(file_path)
        try:
            return _match_trades_fifo(xls)
        finally:
            xls.close()


# 解析器注册表：名称 -> 解析器类 (新增账单格式时在此登记)
PARSER_REGISTRY: dict[str, type[BaseTradeParser]] = {
    parser.name: parser for parser in (CFMMCTradeParser,)
}


def get_parser(name: str) -> BaseTradeParser:
    """按名称实例化解析器，未注册时给出明确的可选清单"""
    if name not in PARSER_REGISTRY:
        raise ValueError(f"未注册的解析器 '{name}'，当前可用: {list(PARSER_REGISTRY)}")
    return PARSER_REGISTRY[name]()


def parse_cfmmc_excel(file_path) -> list[TradeRecord]:
    """解析 CFMMC 格式 Excel (向后兼容门面，UI 层已有调用)"""
    return CFMMCTradeParser().parse(file_path)


# ==========================================
# CFMMC 解析实现
# ==========================================
def _read_trade_sheet(xls: pd.ExcelFile) -> pd.DataFrame:
    """一次性读入成交明细页签 (无表头，由调用方动态定位)"""
    if TRADE_SHEET not in xls.sheet_names:
        available = "、".join(xls.sheet_names) or "空"
        raise ValueError(
            f"交割单中缺少 '{TRADE_SHEET}' 工作表（当前包含: {available}），请确认文件来源。"
        )
    return pd.read_excel(xls, sheet_name=TRADE_SHEET, header=None)


def _match_trades_fifo(xls: pd.ExcelFile) -> list[TradeRecord]:
    """核心 FIFO 配对：将开平仓流水缝合成完整的交易记录"""
    account_name = _extract_account_name(xls, fallback=DEFAULT_ACCOUNT)

    df_raw = _read_trade_sheet(xls)
    header_idx = _locate_header_row(df_raw)
    if header_idx == -1:
        raise ValueError("无法在交割单中找到包含 '交易日期' 的表头行，请检查文件格式。")

    df_trades = _build_dataframe(df_raw, header_idx)

    # 清理空行和合计行
    date_col = df_trades.columns[0]
    df_trades = df_trades[df_trades[date_col].notna() & (~df_trades[date_col].astype(str).str.contains('合计'))]

    open_positions = {}
    matched_trades = []

    for _, row in df_trades.iterrows():
        # 【核心修复】：必须使用 clean_str 去除原始数据中首尾隐藏的空格 (如 ' 卖', ' 平')
        symbol = clean_str(row.get('合约', row.get('品种', '')))
        action = clean_str(row.get('开/平', ''))
        direction = clean_str(row.get('买/卖', ''))

        # 【健壮性】方向字段异常时无法参与 FIFO 配对，跳过该行而不是让程序崩溃
        if direction not in (BUY, SELL):
            continue

        # 强制仅提取日期进行匹配
        date_str = clean_str(row[date_col]).split(' ')[0]
        try:
            trade_date = pd.to_datetime(date_str)
        except Exception:
            trade_date = datetime.now()

        if pd.isna(trade_date):
            trade_date = datetime.now()

        lots = int(_to_float(row.get('手数', 0)))
        if lots == 0 or not symbol:
            continue

        # 提取手续费和盈亏
        commission = _to_float(row.get('手续费', 0.0))
        profit = _to_float(row.get('平仓盈亏', 0.0))
        trade_id = clean_str(row.get('成交序号', f"C_{uuid.uuid4().hex[:8]}"))

        # ===== 核心 FIFO 匹配逻辑 =====
        if '开' in action:
            positions = open_positions.setdefault(symbol, {BUY: [], SELL: []})
            # 开仓队列只关心剩余手数与手续费摊薄，无需 (也不可能) 保存开仓时分
            positions[direction].append({
                'lots': lots,
                'commission': commission
            })

        elif '平' in action:
            opposite_dir = SELL if direction == BUY else BUY
            lots_to_close = lots

            pending = open_positions.get(symbol, {}).get(opposite_dir, [])

            # FIFO 执行匹配
            while lots_to_close > 0 and pending:
                open_trade = pending[0]
                matched_lots = min(lots_to_close, open_trade['lots'])

                prop_profit = profit * (matched_lots / lots) if lots > 0 else 0.0
                prop_comm = (commission * (matched_lots / lots)
                             + open_trade['commission'] * (matched_lots / open_trade['lots']))

                # v1.1：交割单只有"成交日期"，闭环交易以平仓/结算日作为唯一时间锚点
                record = TradeRecord(
                    trade_id=trade_id,
                    account=account_name,
                    symbol=symbol,
                    direction='LONG' if opposite_dir == BUY else 'SHORT',
                    trade_time=trade_date,
                    lots=matched_lots,
                    net_profit=prop_profit,
                    commission=prop_comm
                )
                matched_trades.append(record)

                lots_to_close -= matched_lots
                open_trade['lots'] -= matched_lots
                if open_trade['lots'] == 0:
                    pending.pop(0)

            # 【过月持仓处理】：当有单子要平，但在当前导入的文件里找不到开仓记录时
            if lots_to_close > 0:
                prop_profit = profit * (lots_to_close / lots) if lots > 0 else 0.0
                prop_comm = commission * (lots_to_close / lots)
                # 【过月持仓】本文件内找不到开仓记录时，同样以结算日作为时间锚点，
                # 绝不虚构一个不存在的"进场时间"。
                record = TradeRecord(
                    trade_id=trade_id,
                    account=account_name,
                    symbol=symbol,
                    direction='LONG' if opposite_dir == BUY else 'SHORT',
                    trade_time=trade_date,
                    lots=lots_to_close,
                    net_profit=prop_profit,
                    commission=prop_comm
                )
                matched_trades.append(record)

    return matched_trades
