# core/database.py
import os
import logging
import sqlite3
import uuid
import pandas as pd
from models.trade import TradeRecord
from config import settings

logger = logging.getLogger(__name__)

# 交易流水表结构定义 (单一事实来源：建表、插入、迁移全部由此派生)
# v1.1: entry_time / exit_time 已合并为单一 trade_time
TRADES_SCHEMA = [
    ('internal_id',       'TEXT PRIMARY KEY'),
    ('trade_id',          'TEXT'),
    ('account',           'TEXT'),
    ('symbol',            'TEXT'),
    ('direction',         'TEXT'),
    ('trade_time',        'TIMESTAMP'),
    ('lots',              'INTEGER'),
    ('net_profit',        'REAL'),
    ('commission',        'REAL'),
    ('strategy_tag',      'TEXT'),
    ('entry_reason',      'TEXT'),
    ('reflection',        'TEXT'),
    ('screenshot_paths',  'TEXT'),
]

# 除主键外的业务列 (保持与 TradeRecord 一致的写入顺序)
TRADES_COLUMNS = [name for name, _ in TRADES_SCHEMA[1:]]

# 兼容迁移：旧备份表中可映射的普通列 (不含被合并的时间列)
_MIGRATABLE_COLUMNS = [
    'trade_id', 'account', 'symbol', 'direction', 'lots',
    'net_profit', 'commission', 'strategy_tag',
    'entry_reason', 'reflection', 'screenshot_paths',
]


class DatabaseManager:
    """
    数据库管家 (Data Access Object)。
    管理复盘流水 (trades) 和 市场元数据 (market_symbols)。
    """
    def __init__(self):
        self.db_path = settings.DB_PATH
        self._init_db()

    def _init_db(self):
        """数据库初始化与版本迁移机制"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            self._prepare_schema_upgrade(conn)
            self._ensure_trades_table(conn)
            self._restore_legacy_backup(conn)
            self._ensure_roster_table(conn)
            conn.commit()

    # ==========================================
    # 表结构治理 (Schema Management)
    # ==========================================
    @staticmethod
    def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
        return [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]

    @classmethod
    def _prepare_schema_upgrade(cls, conn: sqlite3.Connection):
        """
        检测旧版 trades 结构 (缺 internal_id，或仍为 entry_time/exit_time 双时间)，
        将其改名为备份表，等待随后重建新表并迁移数据。
        """
        columns = cls._table_columns(conn, 'trades')
        if not columns:
            return
        if 'internal_id' in columns and 'trade_time' in columns:
            return  # 已是 v1.1 结构

        logger.info("检测到旧版交易表结构，正在安全迁移至 v1.1 (合并时间字段)...")
        conn.execute("ALTER TABLE trades RENAME TO trades_v1_backup")
        conn.commit()

    @classmethod
    def _ensure_trades_table(cls, conn: sqlite3.Connection):
        column_defs = ',\n                '.join(f'{name} {type_}' for name, type_ in TRADES_SCHEMA)
        conn.execute(f'''
            CREATE TABLE IF NOT EXISTS trades (
                {column_defs}
            )
        ''')

    @classmethod
    def _ensure_roster_table(cls, conn: sqlite3.Connection):
        conn.execute('''
            CREATE TABLE IF NOT EXISTS market_symbols (
                symbol TEXT PRIMARY KEY,
                name TEXT
            )
        ''')

    @classmethod
    def _restore_legacy_backup(cls, conn: sqlite3.Connection):
        """将备份表历史数据迁移进新结构 (entry_time/exit_time -> trade_time)"""
        exists = conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='trades_v1_backup'"
        ).fetchone()[0]
        if exists != 1:
            return

        logger.info("正在从备份表恢复并归并时间字段...")
        backup_cols = cls._table_columns(conn, 'trades_v1_backup')

        # 构造 目标列 -> 源表达式 的映射
        col_specs = []
        if 'internal_id' in backup_cols:
            # v2 起已具备主键：原样继承，保持引用一致性
            col_specs.append(('internal_id', 'internal_id'))
        else:
            # v1 无主键：逐行生成唯一 internal_id
            col_specs.append(('internal_id', 'lower(hex(randomblob(16)))'))

        if 'trade_time' in backup_cols:
            col_specs.append(('trade_time', 'trade_time'))
        elif 'exit_time' in backup_cols:
            # 旧结构双时间合并：优先取平仓日，其次取开仓日
            if 'entry_time' in backup_cols:
                col_specs.append(('trade_time', 'COALESCE(exit_time, entry_time)'))
            else:
                col_specs.append(('trade_time', 'exit_time'))

        for col in _MIGRATABLE_COLUMNS:
            if col in backup_cols:
                col_specs.append((col, col))

        if not col_specs:
            conn.execute("DROP TABLE trades_v1_backup")
            conn.commit()
            return

        columns_sql = ', '.join(dest for dest, _ in col_specs)
        select_sql = ', '.join(src for _, src in col_specs)
        conn.execute(
            f"INSERT INTO trades ({columns_sql}) "
            f"SELECT {select_sql} FROM trades_v1_backup"
        )
        conn.execute("DROP TABLE trades_v1_backup")
        conn.commit()
        logger.info("历史数据迁移完成！")

    # ==========================================
    # 交易流水操作 (Trades CRUD)
    # ==========================================
    def insert_trades(self, trades: list[TradeRecord]) -> dict:
        """
        批量插入交易记录。
        采用 INSERT OR IGNORE 防呆策略，保护用户已有复盘数据不被覆盖。
        返回统计字典：{'total': 总尝试量, 'inserted': 新增量, 'ignored': 拦截重复量}
        """
        stats = {'total': len(trades), 'inserted': 0, 'ignored': 0}
        if not trades: return stats
        
        col_clause = ', '.join(['internal_id'] + TRADES_COLUMNS)
        placeholders = ', '.join(['?'] * (len(TRADES_COLUMNS) + 1))
        insert_sql = f"INSERT OR IGNORE INTO trades ({col_clause}) VALUES ({placeholders})"

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            for t in trades:
                # 【防呆核心】使用 INSERT OR IGNORE
                cursor.execute(insert_sql, (
                    t.internal_id, t.trade_id, t.account, t.symbol, t.direction, 
                    t.trade_time.strftime('%Y-%m-%d %H:%M:%S'), 
                    t.lots, t.net_profit, t.commission, 
                    t.strategy_tag, t.entry_reason, t.reflection, t.screenshot_paths
                ))
                # cursor.rowcount 为 1 表示成功插入，为 0 表示因为 IGNORE 被忽略
                if cursor.rowcount > 0:
                    stats['inserted'] += 1
                else:
                    stats['ignored'] += 1
            conn.commit()
            
        return stats

    def load_all_trades(self) -> pd.DataFrame:
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query("SELECT * FROM trades", conn)
            if not df.empty:
                df['trade_time'] = pd.to_datetime(df['trade_time'])
            return df

    # 注意：以下写操作全部返回受影响的真实行数，
    # 便于上层以“数据库实际发生了什么”为依据做反馈，而非凭内存状态猜测。
    def delete_trade(self, internal_id: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM trades WHERE internal_id = ?", (internal_id,))
            conn.commit()
            return cursor.rowcount

    def delete_account(self, account: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM trades WHERE account = ?", (account,))
            conn.commit()
            return cursor.rowcount

    def update_strategy(self, internal_id: str, strategy_tag: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE trades SET strategy_tag = ? WHERE internal_id = ?", (strategy_tag, internal_id)
            )
            conn.commit()
            return cursor.rowcount

    def clear_strategy(self, strategy_tag: str, default_tag: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE trades SET strategy_tag = ? WHERE strategy_tag = ?", (default_tag, strategy_tag)
            )
            conn.commit()
            return cursor.rowcount

    def update_review(self, internal_id: str, reason: str, reflection: str, paths: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE trades SET entry_reason = ?, reflection = ?, screenshot_paths = ? WHERE internal_id = ?",
                (reason, reflection, paths, internal_id)
            )
            conn.commit()
            return cursor.rowcount

    # ==========================================
    # 市场花名册操作 (Market Symbols CRUD)
    # ==========================================
    def update_market_roster(self, df: pd.DataFrame):
        """一键覆写全市场股票/期货花名册"""
        if df.empty: return
        with sqlite3.connect(self.db_path) as conn:
            df.to_sql('market_symbols', conn, if_exists='replace', index=False)
            
    def search_symbol(self, keyword: str) -> pd.DataFrame:
        """
        智能模糊搜索代码或中文名称。
        【安全修复】采用参数化查询 + 转义 LIKE 通配符，杜绝 SQL 注入与特殊字符崩溃。
        """
        keyword = (keyword or "").strip()
        if not keyword:
            return pd.DataFrame()

        escaped = keyword.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        pattern = f"%{escaped}%"
        query = """
            SELECT * FROM market_symbols 
            WHERE symbol LIKE ? ESCAPE '\\' OR name LIKE ? ESCAPE '\\' 
            LIMIT 20
        """
        with sqlite3.connect(self.db_path) as conn:
            return pd.read_sql_query(query, conn, params=(pattern, pattern))
