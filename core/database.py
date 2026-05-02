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
    """
    def __init__(self):
        self.db_path = settings.DB_PATH
        self._init_db()

    def _init_db(self):
        """数据库初始化与版本迁移机制"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 检查是否是存在缺陷的旧版表结构（trade_id 是主键）
            cursor.execute("PRAGMA table_info(trades)")
            columns = cursor.fetchall()
            if columns:
                # 提取主键列名
                pk_cols = [col[1] for col in columns if col[5] == 1]
                has_internal_id = any(col[1] == 'internal_id' for col in columns)
                
                # 如果主键不是 internal_id，说明是 V1 版本的旧表，执行迁移！
                if not has_internal_id:
                    print("检测到旧版数据库结构，正在执行安全迁移...")
                    cursor.execute("ALTER TABLE trades RENAME TO trades_v1_backup")
                    conn.commit()

            # 创建全新的 V2 版本表结构
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    internal_id TEXT PRIMARY KEY,   -- 绝对唯一标识
                    trade_id TEXT,                  -- 业务单号（允许重复）
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
            
            # (可选) 如果有备份表，将旧数据迁移过来
            cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='trades_v1_backup'")
            if cursor.fetchone()[0] == 1:
                print("正在从备份表恢复数据...")
                # 读取旧数据
                cursor.execute("SELECT * FROM trades_v1_backup")
                old_rows = cursor.fetchall()
                
                if old_rows:
                    for row in old_rows:
                        # 生成新的 internal_id
                        new_id = str(uuid.uuid4())
                        # 插入新表
                        cursor.execute('''
                            INSERT INTO trades 
                            (internal_id, trade_id, account, symbol, direction, entry_time, exit_time, lots, net_profit, commission, strategy_tag, entry_reason, reflection, screenshot_paths)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (new_id,) + row)
                # 迁移完成后删除备份表
                cursor.execute("DROP TABLE trades_v1_backup")
                conn.commit()
                print("数据库迁移完成！")

    def insert_trades(self, trades: list[TradeRecord]):
        """批量安全插入交易数据"""
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
        """高速一键拉取整表数据"""
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