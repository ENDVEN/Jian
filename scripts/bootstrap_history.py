# scripts/bootstrap_history.py
"""一次性全历史 bootstrap（★2.06 / DATA-PLATFORM P2）。

用法（仓库根目录）：
    py scripts/bootstrap_history.py --status
    py scripts/bootstrap_history.py --arm-once
    py scripts/bootstrap_history.py --run --workers 16 --limit 100
    py scripts/bootstrap_history.py --run --workers 16 --overwrite

规则：
- 必须 `--arm-once` 显式授权；`--run` 一开始就 consume，跑一次即失效；
- 只对本次脚本的请求使用 `allow_over_budget=True`，**不计入/不改变日常 300 次预算**；
- 默认只补本地缺失的标的；`--overwrite` 才覆盖已有文件；
- `--dry-run` 只打印计划；`--data-dir` 可指向临时目录做验证。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

for _stream in (sys.stdout, sys.stderr):
    _reconf = getattr(_stream, "reconfigure", None)
    if callable(_reconf):
        try:
            _reconf(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    ap = argparse.ArgumentParser(description="一次性全历史 bootstrap（显式 arm/consume）")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--arm-once", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 只（0=全部）")
    ap.add_argument("--start", default="20100101")
    ap.add_argument("--overwrite", action="store_true", help="覆盖已有文件")
    ap.add_argument("--data-dir", default="", help="临时用户目录（验证用）")
    ap.add_argument("--max-errors", type=int, default=100)
    args = ap.parse_args()

    if args.data_dir:
        from config import settings
        settings.USER_DATA_DIR = args.data_dir

    from data import bootstrap_once, em_auth, em_history
    from data.market_db import DataLakeManager
    from data.sync_service import ZONE_KLINE

    if args.status:
        print(bootstrap_once.text())
        print("登录档：", "已登录" if em_auth.is_logged_in() else "未登录")
        return 0
    if args.arm_once:
        path = bootstrap_once.arm("user authorized one-time bootstrap 2026-11-05")
        print(f"已授权一次性 bootstrap：{path}")
        return 0
    if not args.run:
        ap.print_help()
        return 0
    if not bootstrap_once.allowed():
        print("未授权或已消费 —— 先用 --arm-once 显式授权")
        return 1
    if not em_auth.is_logged_in():
        print("未登录：一次性 bootstrap 需要东财登录档")
        return 1

    from core.engine import DataEngine
    symbols = DataEngine().list_stock_symbols()
    if args.limit > 0:
        symbols = symbols[:args.limit]
    lake = DataLakeManager()
    if not args.overwrite:
        todo = [s for s in symbols if not lake.exists(ZONE_KLINE, s)]
    else:
        todo = list(symbols)
    print(f"计划 {len(todo)} 只（花名册 {len(symbols)}，overwrite={args.overwrite}）")
    if args.dry_run:
        print("dry-run：不写盘、不消耗授权")
        return 0
    if not todo:
        print("没有需要补的标的（已有文件默认跳过；--overwrite 可覆盖）")
        return 0

    bootstrap_once.consume()          # 先消费：本次跑完即失效
    print(f"一次性授权已消费；开始 {len(todo)} 只，workers={args.workers}")
    t0 = time.perf_counter()
    ok = fail = skipped = 0
    errors = []
    done = 0

    def one(sym):
        # ★2.06：东财 push2his 不支持 920xxx 北交所；这批走新浪（不占登录预算）
        if str(sym).startswith("920"):
            from data.akshare_feed import AkShareFeed
            df = AkShareFeed.fetch_a_share_daily(sym, start_date=args.start, adjust="qfq")
        else:
            df = em_history.fetch_daily(sym, start_date=args.start, adjust="qfq",
                                        allow_over_budget=True)
        if df is None or df.empty:
            return sym, False, "empty"
        if not lake.save_data(ZONE_KLINE, sym, df):
            return sym, False, "save_failed"
        return sym, True, ""

    with ThreadPoolExecutor(max_workers=max(1, int(args.workers))) as ex:
        futures = {ex.submit(one, sym): sym for sym in todo}
        for fut in as_completed(futures):
            sym = futures[fut]
            done += 1
            try:
                _sym, good, err = fut.result()
            except Exception as e:  # noqa: BLE001
                good, err = False, f"{type(e).__name__}: {e}"
            if good:
                ok += 1
            else:
                fail += 1
                if len(errors) < 50:
                    errors.append([sym, err])
            if done % 50 == 0 or done == len(todo):
                rate = done / max(1e-9, time.perf_counter() - t0)
                print(f"  {done}/{len(todo)} ok={ok} fail={fail} "
                      f"{rate:.1f} 只/s", flush=True)
            if fail == args.max_errors:
                # 所有任务都已提交；继续收结果，避免“停止统计但任务仍在跑”的假账。
                print(f"错误达到 {fail}，继续收集已提交任务的结果…", flush=True)

    result = {
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(todo), "ok": ok, "fail": fail, "skipped": skipped,
        "seconds": round(time.perf_counter() - t0, 1),
        "errors": errors,
    }
    out = os.path.join(os.path.dirname(bootstrap_once.flag_path()), "bootstrap_result.json")
    try:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
