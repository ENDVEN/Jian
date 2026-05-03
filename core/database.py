# core/database.py
import sqlite3
import pandas as pd
import os
import uuid
from models.trade import TradeRecord
from config import settings

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
            cursor = conn.cursor()
            
            # --- 交易流水表 (Trades) ---
            cursor.execute("PRAGMA table_info(trades)")
            columns = cursor.fetchall()
            if columns:
                has_internal_id = any(col[1] == 'internal_id' for col in columns)
                if not has_internal_id:
                    print("检测到旧版数据库结构，正在执行安全迁移...")
                    cursor.execute("ALTER TABLE trades RENAME TO trades_v1_backup")
                    conn.commit()

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    internal_id TEXT PRIMARY KEY,
                    trade_id TEXT,
                    account TEXT,
                    symbol TEXT,
                    direction TEXT,
                    entry_time TIMESTAMP,
                    exit_time TIMESTAMP,
                    lots INTEGER,
                    net_profit REAL,
                    commission REAL,
                    strategy_tag TEXT,
                    entry_reason TEXT,
                    reflection TEXT,
                    screenshot_paths TEXT
                )
            ''')
            conn.commit()
            
            cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='trades_v1_backup'")
            if cursor.fetchone()[0] == 1:
                print("正在从备份表恢复数据...")
                cursor.execute("SELECT * FROM trades_v1_backup")
                old_rows = cursor.fetchall()
                if old_rows:
                    for row in old_rows:
                        new_id = str(uuid.uuid4())
                        cursor.execute('''
                            INSERT INTO trades 
                            (internal_id, trade_id, account, symbol, direction, entry_time, exit_time, lots, net_profit, commission, strategy_tag, entry_reason, reflection, screenshot_paths)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (new_id,) + row)
                cursor.execute("DROP TABLE trades_v1_backup")
                conn.commit()
                print("数据库迁移完成！")

            # --- 市场花名册表 (Market Symbols) ---
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS market_symbols (
                    symbol TEXT PRIMARY KEY,
                    name TEXT
                )
            ''')
            conn.commit()

    # ==========================================
    # 交易流水操作 (Trades CRUD)
    # ==========================================
    def insert_trades(self, trades: list[TradeRecord]):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            for t in trades:
                cursor.execute('''
                    INSERT OR REPLACE INTO trades 
                    (internal_id, trade_id, account, symbol, direction, entry_time, exit_time, lots, net_profit, commission, strategy_tag, entry_reason, reflection, screenshot_paths)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    t.internal_id, t.trade_id, t.account, t.symbol, t.direction, 
                    t.entry_time.strftime('%Y-%m-%d %H:%M:%S'), 
                    t.exit_time.strftime('%Y-%m-%d %H:%M:%S'), 
                    t.lots, t.net_profit, t.commission, 
                    t.strategy_tag, t.entry_reason, t.reflection, t.screenshot_paths
                ))
            conn.commit()

    def load_all_trades(self) -> pd.DataFrame:
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query("SELECT * FROM trades", conn)
            if not df.empty:
                df['entry_time'] = pd.to_datetime(df['entry_time'])
                df['exit_time'] = pd.to_datetime(df['exit_time'])
            return df

    def delete_trade(self, internal_id: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM trades WHERE internal_id = ?", (internal_id,))
            conn.commit()

    def delete_account(self, account: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM trades WHERE account = ?", (account,))
            conn.commit()

    def update_strategy(self, internal_id: str, strategy_tag: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE trades SET strategy_tag = ? WHERE internal_id = ?", (strategy_tag, internal_id))
            conn.commit()

    def clear_strategy(self, strategy_tag: str, default_tag: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE trades SET strategy_tag = ? WHERE strategy_tag = ?", (default_tag, strategy_tag))
            conn.commit()

    def update_review(self, internal_id: str, reason: str, reflection: str, paths: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE trades SET entry_reason = ?, reflection = ?, screenshot_paths = ? WHERE internal_id = ?", 
                           (reason, reflection, paths, internal_id))
            conn.commit()

    # ==========================================
    # 市场花名册操作 (Market Symbols CRUD)
    # ==========================================
    def update_market_roster(self, df: pd.DataFrame):
        """一键覆写全市场股票/期货花名册"""
        if df.empty: return
        with sqlite3.connect(self.db_path) as conn:
            df.to_sql('market_symbols', conn, if_exists='replace', index=False)
            
    def search_symbol(self, keyword: str) -> pd.DataFrame:
        """智能模糊搜索代码或中文名称"""
        with sqlite3.connect(self.db_path) as conn:
            query = f"SELECT * FROM market_symbols WHERE symbol LIKE '%{keyword}%' OR name LIKE '%{keyword}%' LIMIT 20"
            return pd.read_sql_query(query, conn)