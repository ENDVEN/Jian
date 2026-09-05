# sync_roster.py
import time
import pandas as pd
from data.akshare_feed import AkShareFeed
from core.database import DatabaseManager

def main():
    print("========================================")
    print("🚀 Jian 系统 - 正在初始化股期双市场花名册")
    print("========================================")
    
    t1 = time.time()
    
    # 1. 拉取 A 股
    df_a = AkShareFeed.fetch_a_share_roster()
    print(f"✅ 获取到 {len(df_a)} 只 A 股代码。")
    
    # 2. 拉取 期货
    df_f = AkShareFeed.fetch_futures_roster()
    print(f"✅ 获取到 {len(df_f)} 只 期货代码。")
    
    # 3. 缝合兵力并入库
    df_roster = pd.concat([df_a, df_f], ignore_index=True)
    if df_roster.empty:
        print("❌ 双市场花名册均为空 (疑似断网)，已中止入库以避免覆盖既有名册。")
        return
    
    db = DatabaseManager()
    db.update_market_roster(df_roster)
    
    t2 = time.time()
    print(f"✅ 成功将双市场花名册写入底层数据库！总耗时: {t2-t1:.2f} 秒")
    
    print("\n--- 🔍 期货模糊搜索测试 ---")
    test_keywords = ["RB", "螺纹钢", "IF"]
    for kw in test_keywords:
        print(f"\n搜索关键词: '{kw}'")
        res = db.search_symbol(kw)
        if not res.empty:
            print(res.to_string(index=False))

if __name__ == "__main__":
    main()