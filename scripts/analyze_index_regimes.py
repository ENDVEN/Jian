# scripts/analyze_index_regimes.py
"""
上证指数切块 · 离线脚本（§7-B15 SW-2 · 方案书 §11 决议 3）。

读数据湖 `index_daily/sh000001.parquet`（**只读，不联网**），切块 + 配对后
打印给人看，并写缓存 `~/.jian_data/index_regimes.json`（幂等，重跑安全）。
算法与口径唯一真源 = `core/index_regimes.py`，本脚本只做"喂序列 + 打印 + 落缓存"。

用法（在仓库根目录）：
    py scripts/analyze_index_regimes.py                    # 默认参数
    py scripts/analyze_index_regimes.py --window 40 --min-len 30 --force
    （参数与数据末日写进缓存；同末日同参数直接命中，不重算）

没有数据 / 缺 close 列 ⇒ 诚实退出（退出码 2）并指引去哪补 —— 绝不造数据（§10-4）。
"""
import argparse
import os
import sys

import pandas as pd

# 【§10-13】子目录脚本必须由 __file__ 反推仓库根，否则 from data.xxx 直接 ImportError
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from data.market_db import DataLakeManager          # noqa: E402
from core import index_regimes as ir                # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="上证指数切块 → 参数研究的区间预设")
    ap.add_argument("--window", type=int, default=ir.DEFAULT_WINDOW,
                    help=f"滚动窗口（交易日），默认 {ir.DEFAULT_WINDOW}")
    ap.add_argument("--up", type=float, default=ir.DEFAULT_UP_THR,
                    help=f"单边上涨阈值，默认 {ir.DEFAULT_UP_THR}")
    ap.add_argument("--down", type=float, default=ir.DEFAULT_DOWN_THR,
                    help=f"单边下跌阈值，默认 {ir.DEFAULT_DOWN_THR}")
    ap.add_argument("--min-len", type=int, default=ir.DEFAULT_MIN_LEN,
                    help=f"段最短交易日数，默认 {ir.DEFAULT_MIN_LEN}")
    ap.add_argument("--force", action="store_true", help="忽略缓存强制重算")
    args = ap.parse_args()

    lake = DataLakeManager()
    # ⚠ DataLakeManager 的文件名参数**不含 .parquet 后缀**（_get_filepath 自补；
    #   list_zone 返回的也是裸代码）—— 照 breadth_flow.load_data(ZONE_INDEX, code) 的既有惯例。
    code = ir.SHANGHAI_INDEX_SYMBOL
    if not lake.exists(ir.ZONE_INDEX, code):
        print(f"[!] 数据湖里没有 {ir.ZONE_INDEX}/{code}.parquet（上证指数日线）。")
        print("    先去 🗄 数据管理 / 批量预下载 把指数日线补齐，再跑本脚本。")
        return 2
    df = lake.load_data(ir.ZONE_INDEX, code)
    if df is None or df.empty or "close" not in df.columns or "date" not in df.columns:
        # §9.1 纪律：按"列是否存在"判定，缺列 ⇒ 诚实说缺什么，绝不假装能切
        print(f"[!] {code}.parquet 读出来是空的，或缺 date/close 列（实际列：{list(df.columns) if df is not None else '—'}）。")
        print("    去 🗄 数据管理 对该分区「重新全量下载」后再跑。")
        return 2

    s = df.set_index(pd.to_datetime(df["date"]))["close"]
    payload, hit = ir.ensure_payload(
        s, force=args.force, window=args.window,
        up_thr=args.up, down_thr=args.down, min_len=args.min_len)

    if hit:
        print(f"✓ 缓存命中（数据末日 {payload['data_end']} + 参数未变），未重算。"
              f"  强制重算请加 --force。")
    print(f"\n切块参数：窗口={payload['params']['window']} 日 · "
          f"涨≥{payload['params']['up_thr']:+.0%} · 跌≤{payload['params']['down_thr']:+.0%} · "
          f"段最短={payload['params']['min_len']} 日")
    print(f"数据范围：{payload['data_start']} → {payload['data_end']}")
    print(f"\n—— 状态段（{len(payload['segments'])} 段；更短的毛刺不成段）——")
    for seg in payload["segments"]:
        bar = "█" * max(1, seg["n_days"] // 20)
        print(f"  {seg['start']} → {seg['end']}  {ir.REGIME_LABELS[seg['regime']]:<4} "
              f"{seg['n_days']:>4} 日  {bar}")
    print(f"\n—— 区间预设（{len(payload['presets'])} 对；★ = 默认）——")
    for p in payload["presets"]:
        star = "★" if p.get("default") else " "
        print(f" {star} {p['label']}   {p['is_start']}~{p['is_end']} 调 → "
              f"{p['oos_start']}~{p['oos_end']} 验")
    print(f"\n缓存已写入：{ir.cache_path()}")
    print("（app 的「🧪 参数研究」页与切块时间轴都读这一份；改参数重跑即可刷新）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
