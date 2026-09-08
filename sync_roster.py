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
    
    # 3. 【安全闸】分市场判空，任一为空即中止
    # 背景：`DatabaseManager.update_market_roster` 是 if_exists='replace' 的**全量覆写**。
    # 期货名册是硬编码的必然非空，因此"只判断 concat 后整体是否为空"根本拦不住事故：
    # A 股拉取一旦失败，就会用"只剩期货"的半份名册把整表覆盖掉，A 股名称全丢且无法自愈。
    # 故这里必须逐个市场校验，任何一半缺失都保留数据库既有名册不动 (见 §9-G)。
    if df_a.empty or df_f.empty:
        missing = "、".join([m for m, d in (("A股", df_a), ("期货", df_f)) if d.empty])
        print(f"❌ {missing}花名册为空 (疑似断网/接口变更)，已中止入库 —— "
              f"数据库既有名册保持原样，未被覆盖。请恢复网络后重试。")
        return

    df_roster = pd.concat([df_a, df_f], ignore_index=True)
    
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