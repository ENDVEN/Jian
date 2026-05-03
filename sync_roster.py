# sync_roster.py
import time
from data.akshare_feed import AkShareFeed
from core.database import DatabaseManager

def main():
    print("========================================")
    print("🚀 Jian 系统 - 正在初始化全市场花名册")
    print("========================================")
    
    t1 = time.time()
    
    # 1. 启动抽水机拉取云端数据
    df_roster = AkShareFeed.fetch_a_share_roster()
    
    if df_roster.empty:
        print("❌ 拉取失败，请检查网络连接！")
        return
        
    print(f"✅ 成功从云端拉取到 {len(df_roster)} 只 A 股代码。")
    
    # 2. 存入底层 SQLite 数据库
    db = DatabaseManager()
    db.update_market_roster(df_roster)
    
    t2 = time.time()
    print(f"✅ 成功将花名册写入底层数据库！总耗时: {t2-t1:.2f} 秒")
    
    print("\n--- 🔍 数据库模糊搜索测试 ---")
    # 测试一下咱们刚才写的智能搜索功能
    test_keywords = ["600519", "茅台", "银行"]
    for kw in test_keywords:
        print(f"\n搜索关键词: '{kw}'")
        res = db.search_symbol(kw)
        if not res.empty:
            print(res.to_string(index=False))
        else:
            print("未找到结果。")

if __name__ == "__main__":
    main()