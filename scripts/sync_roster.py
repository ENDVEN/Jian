# scripts/sync_roster.py —— 独立运维脚本（人工运行，不被 app import）
#   用法：py scripts/sync_roster.py  （在仓库根目录执行）
#   ★1.70 / §11.5-125：同步逻辑整块搬进 `data/roster_sync.sync_roster()` ——
#     app 内的「立即同步花名册」按钮与它**同一个门面**（数量安全闸只有一份，
#     且都先 `net_env.apply()` 拿网络策略）；本脚本只做命令行展示与搜索自检。
import os
import sys

# 本文件在 scripts/ 子目录里，**仓库根 = 本文件的父目录**：
# 由 `__file__` 反推而非相对路径 —— 否则 `from data...` 会去 scripts/ 里找包（§10-13）。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.roster_sync import sync_roster  # noqa: E402


def _demo_search() -> None:
    """写完之后立刻自证"搜得到"（A 股按代码/名称 + 期货按品种码）—— 避免"看着成功其实搜不到"。"""
    from core.database import DatabaseManager

    db = DatabaseManager()
    print("\n--- 🔍 搜索自检（A 股 + 期货）---")
    for kw in ("600519", "贵州茅台", "RB", "螺纹钢", "IF"):
        res = db.search_symbol(kw)
        if res is None or res.empty:
            print(f"  ❌ {kw!r} 搜不到")
        else:
            print(f"  ✅ {kw!r} -> {res.iloc[0]['symbol']} {res.iloc[0]['name']}")


def main() -> None:
    print("========================================")
    print("🚀 Jian 系统 - 正在初始化股期双市场花名册")
    print("========================================")

    rep = sync_roster()
    if not rep["ok"]:
        print(f"❌ {rep['reason']}")
        print("   （网络恢复后重试即可；东财额度被拒时约 30 分钟自恢复）")
        return
    print(f"✅ A股 {rep['a_share']} 只 · 期货 {rep['futures']} 只（共 {rep['total']} 条）"
          f" · 耗时 {rep['elapsed']:.1f} 秒")
    print("✅ 成功将双市场花名册写入底层数据库！")
    _demo_search()


if __name__ == "__main__":
    main()
