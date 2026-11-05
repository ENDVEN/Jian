# scripts/repair_history.py
"""修复被 bootstrap 污染的日线（★2.07）。

默认只修“close <= 0”的明显坏文件，用新浪比例前复权重拉；
`--all` 才重拉全部非北交所标的。绝不静默覆盖：先校验，再写盘。
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("JIAN_EM_DIRECT", "0")

for _stream in (sys.stdout, sys.stderr):
    _reconf = getattr(_stream, "reconfigure", None)
    if callable(_reconf):
        try:
            _reconf(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="重拉全部非北交所标的")
    ap.add_argument("--bj-only", action="store_true", help="只重拉北交所")
    ap.add_argument("--symbols", nargs="*", default=None, help="只修指定代码")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--start", default="20100101")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    import pyarrow.parquet as pq
    from data.akshare_feed import AkShareFeed
    from data.market_db import DataLakeManager
    from data.quality import check_ohlcv
    from data.sync_service import ZONE_KLINE

    lake = DataLakeManager()
    folder = lake.folder_of(ZONE_KLINE)
    names = sorted(os.path.splitext(n)[0] for n in os.listdir(folder)
                   if n.lower().endswith(".parquet"))
    if args.symbols:
        todo = [str(s).strip() for s in args.symbols if str(s).strip()]
    elif args.bj_only:
        todo = [s for s in names if s.startswith(("920", "43", "83", "87", "88"))]
    elif args.all:
        todo = [s for s in names if not s.startswith("920")]
    else:
        todo = []
        for sym in names:
            if sym.startswith("920"):
                continue
            try:
                arr = pq.read_table(os.path.join(folder, f"{sym}.parquet"),
                                    columns=["close"]).column("close").to_pylist()
                if any(v is not None and v <= 0 for v in arr):
                    todo.append(sym)
            except Exception:
                todo.append(sym)
    print(f"待修复 {len(todo)} 只（all={args.all}）")
    if args.dry_run or not todo:
        print("dry-run：不写盘")
        return 0

    t0 = time.perf_counter()
    ok = fail = 0
    errors = []

    def one(sym):
        df = AkShareFeed.fetch_a_share_daily(sym, start_date=args.start, adjust="qfq")
        problems = check_ohlcv(df)
        if problems:
            return sym, False, "quality:" + "；".join(problems[:2])
        if not lake.save_data(ZONE_KLINE, sym, df):
            return sym, False, "save_failed"
        return sym, True, ""

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {ex.submit(one, s): s for s in todo}
        done = 0
        for fut in as_completed(futs):
            sym = futs[fut]
            done += 1
            try:
                _sym, good, err = fut.result()
            except Exception as e:  # noqa: BLE001
                good, err = False, f"{type(e).__name__}: {e}"
            if good:
                ok += 1
            else:
                fail += 1
                if len(errors) < 30:
                    errors.append([sym, err])
            if done % 20 == 0 or done == len(todo):
                print(f"  {done}/{len(todo)} ok={ok} fail={fail}", flush=True)
    print(f"完成 ok={ok} fail={fail} 用时 {time.perf_counter()-t0:.1f}s")
    if errors:
        print("失败样例：", errors)
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
