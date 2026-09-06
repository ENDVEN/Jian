# core/database.py
import os
import logging
import sqlite3
import uuid
import pandas as pd
from models.trade import TradeRecord
from core.preferences import TIME_SOURCE_MANUAL
from config import settings

logger = logging.getLogger(__name__)

# 交易流水表结构定义 (单一事实来源：建表、插入、迁移全部由此派生)
# v1.1: entry_time / exit_time 已合并为单一 trade_time
# v1.2: 新增成交价 / 成交时刻 / 合约乘数 / 孤儿标记，全部可空，向后兼容
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
    # ---------------- v1.2 新增 ----------------
    ('entry_time',        'TIMESTAMP'), # 开仓腿真实成交时刻（孤儿单为 NULL）
    ('entry_price',       'REAL'),      # 开仓成交价（过月遗留单为 NULL）
    ('exit_price',        'REAL'),      # 平仓成交价
    ('entry_fill_time',   'TEXT'),      # 开仓成交时刻 HH:MM:SS（可空）
    ('exit_fill_time',    'TEXT'),      # 平仓成交时刻 HH:MM:SS（可空）
    ('time_source',       'TEXT'),      # DATE_ONLY / STATEMENT / MANUAL
    ('multiplier',        'REAL'),      # 合约乘数（每点价值）
    ('is_orphan',         'INTEGER DEFAULT 0'),  # 1 = 开仓腿缺失，待缝合
]

# 除主键外的业务列 (保持与 TradeRecord 一致的写入顺序)
TRADES_COLUMNS = [name for name, _ in TRADES_SCHEMA[1:]]

# 兼容迁移：旧备份表中可映射的普通列 (不含被合并的时间列)
_MIGRATABLE_COLUMNS = [
    'trade_id', 'account', 'symbol', 'direction', 'lots',
    'net_profit', 'commission', 'strategy_tag',
    'entry_reason', 'reflection', 'screenshot_paths',
    # v1.2：老备份表若已存在这些列则一并带回，否则自动跳过（新列留 NULL）
    'entry_time', 'entry_price', 'exit_price',
    'entry_fill_time', 'exit_fill_time', 'time_source',
    'multiplier', 'is_orphan',
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
            self._ensure_extra_columns(conn)
            self._ensure_open_legs_table(conn)
            self._ensure_coverage_tables(conn)
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
    def _ensure_extra_columns(cls, conn: sqlite3.Connection):
        """
        【v1.2 增量加列迁移】为已存在的 trades 表补齐新增列。

        与 v1.1 的"整表重建"不同，加列属于纯增量场景，
        必须走 ALTER TABLE ADD COLUMN —— 绝不能重建表，否则会丢失 internal_id
        (导致防重失效) 与用户已有的复盘文字。
        """
        existing = cls._table_columns(conn, 'trades')
        if not existing:
            return
        for name, type_ in TRADES_SCHEMA:
            if name in existing:
                continue
            logger.info(f"正在为 trades 表补充 v1.2 新列: {name}")
            conn.execute(f"ALTER TABLE trades ADD COLUMN {name} {type_}")
        conn.commit()

    @classmethod
    def _ensure_open_legs_table(cls, conn: sqlite3.Connection):
        """
        持仓腿暂存表：保存"截至上次导入仍未平仓的开仓腿"。

        【为什么必须持久化】FIFO 队列原本只活在内存里，导入结束即丢，
        导致用户分月导入时上月末的仓位无法延续到下月，凭空制造大量"假的孤儿单"。
        持久化后，分批导入与一次性导入的结果完全一致，且与导入顺序无关。
        """
        conn.execute('''
            CREATE TABLE IF NOT EXISTS open_legs (
                leg_id       TEXT PRIMARY KEY,
                account      TEXT,
                symbol       TEXT,
                direction    TEXT,
                open_date    TEXT,
                open_time    TEXT,
                price        REAL,
                lots         INTEGER,
                commission   REAL,
                multiplier   REAL,
                source_month TEXT
            )
        ''')

    @classmethod
    def _ensure_coverage_tables(cls, conn: sqlite3.Connection):
        """
        月度覆盖表：记录每个账户已导入哪些月份，以及该月的资金勾稽数据。
        配合 gaps 表实现"漏月检测"与"用户确认跳过"。
        """
        conn.execute('''
            CREATE TABLE IF NOT EXISTS import_coverage (
                account       TEXT,
                month         TEXT,
                prev_balance  REAL,
                equity        REAL,
                month_pnl     REAL,
                month_fee     REAL,
                month_deposit REAL,
                has_trades    INTEGER DEFAULT 0,
                source_file   TEXT,
                PRIMARY KEY (account, month)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS coverage_gaps (
                account TEXT,
                month   TEXT,
                PRIMARY KEY (account, month)
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
                # 【健壮性】逐列用 getattr 取值：无论 TradeRecord 来自哪个来源
                # (交割单 / 手工录入 / 旧版本代码)，缺失的新字段都会安全写入 NULL，
                # 而不会抛 AttributeError 让整次导入失败。
                values = [t.internal_id] + [
                    self._serialize_value(col, getattr(t, col, None))
                    for col in TRADES_COLUMNS
                ]
                cursor.execute(insert_sql, tuple(values))
                # cursor.rowcount 为 1 表示成功插入，为 0 表示因为 IGNORE 被忽略
                if cursor.rowcount > 0:
                    stats['inserted'] += 1
                else:
                    stats['ignored'] += 1
            conn.commit()

        return stats

    @staticmethod
    def _serialize_value(column: str, value):
        """按列语义做入库前序列化（时间戳转字符串，其余原样）"""
        if column in ('trade_time', 'entry_time'):
            if value is None or pd.isna(value):
                return None
            return pd.to_datetime(value).strftime('%Y-%m-%d %H:%M:%S')
        return value

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
    # 持仓腿操作 (Open Legs CRUD)
    # ==========================================
    def load_open_legs(self, account: str = None) -> pd.DataFrame:
        """读取截至上次导入仍未平仓的开仓腿；无记录时返回空 DataFrame。"""
        with sqlite3.connect(self.db_path) as conn:
            sql = "SELECT * FROM open_legs"
            params = ()
            if account:
                sql += " WHERE account = ?"
                params = (account,)
            return pd.read_sql_query(sql, conn, params=params)

    def replace_open_legs(self, account: str, legs: list[dict]) -> int:
        """
        用"本次导入结束后的真实持仓"全量覆写某账户的持仓腿。

        【为什么是全量覆写而非增量追加】持仓腿是"当前状态"而非"历史流水"，
        全量覆写天然幂等：无论同一批文件重复导入多少次，结果都只反映最新状态，
        不会像追加那样把仓位越滚越多。
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM open_legs WHERE account = ?", (account,))
            if legs:
                conn.executemany(
                    "INSERT OR REPLACE INTO open_legs "
                    "(leg_id, account, symbol, direction, open_date, open_time, "
                    " price, lots, commission, multiplier, source_month) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    [
                        (leg['leg_id'], leg['account'], leg['symbol'], leg['direction'],
                         leg.get('open_date', ''), leg.get('open_time', ''),
                         leg.get('price'), leg.get('lots', 0), leg.get('commission', 0.0),
                         leg.get('multiplier', 0.0), leg.get('source_month', ''))
                        for leg in legs
                    ],
                )
            conn.commit()
        return len(legs)

    # ==========================================
    # 月度覆盖与漏月检测 (Import Coverage CRUD)
    # ==========================================
    def upsert_coverage(self, record: dict):
        """登记某账户某月的资金勾稽数据（重复导入同一月时安全覆盖）"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO import_coverage "
                "(account, month, prev_balance, equity, month_pnl, month_fee, "
                " month_deposit, has_trades, source_file) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (record['account'], record['month'],
                 record.get('prev_balance'), record.get('equity'),
                 record.get('month_pnl'), record.get('month_fee'),
                 record.get('month_deposit'), int(bool(record.get('has_trades'))),
                 record.get('source_file', '')),
            )
            conn.commit()

    def load_coverage(self, account: str = None) -> pd.DataFrame:
        with sqlite3.connect(self.db_path) as conn:
            sql = "SELECT * FROM import_coverage"
            params = ()
            if account:
                sql += " WHERE account = ?"
                params = (account,)
            return pd.read_sql_query(sql, conn, params=params)

    def add_gap(self, account: str, month: str):
        """将某月登记为"用户确认的有意跳过"，后续不再重复提醒"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO coverage_gaps (account, month) VALUES (?, ?)",
                (account, month),
            )
            conn.commit()

    def load_gaps(self, account: str = None) -> set:
        with sqlite3.connect(self.db_path) as conn:
            sql = "SELECT account, month FROM coverage_gaps"
            params = ()
            if account:
                sql += " WHERE account = ?"
                params = (account,)
            rows = conn.execute(sql, params).fetchall()
        return {(row[0], row[1]) for row in rows}

    # ==========================================
    # 孤儿单操作 (Orphan / Pending Stitch)
    # ==========================================
    def load_orphans(self, account: str = None) -> pd.DataFrame:
        """读取所有开仓腿缺失、等待缝合的平仓记录"""
        with sqlite3.connect(self.db_path) as conn:
            sql = "SELECT * FROM trades WHERE is_orphan = 1"
            params = ()
            if account:
                sql += " AND account = ?"
                params = (account,)
            return pd.read_sql_query(sql, conn, params=params)

    def stitch_orphan(self, internal_id: str, entry_price: float,
                      entry_time=None, entry_fill_time: str = "",
                      extra_commission: float = 0.0) -> int:
        """
        手工补录开仓信息，把孤儿单缝合为完整闭环交易。

        【诚实原则】只写入用户明确填写的内容，绝不猜测或推算开仓价；
        时间来源一律标记为 MANUAL，与交割单原生数据严格区分。
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE trades SET is_orphan = 0, entry_price = ?, entry_time = ?, "
                " entry_fill_time = ?, commission = commission + ?, time_source = ? "
                "WHERE internal_id = ?",
                (entry_price, self._serialize_value('entry_time', entry_time),
                 entry_fill_time, extra_commission,
                 TIME_SOURCE_MANUAL, internal_id),
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
