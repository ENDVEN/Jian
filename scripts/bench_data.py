# scripts/bench_data.py
"""数据下载 / 存储布局基准（★2.05 / DATA-PLATFORM P0）。

用法（仓库根目录）：
    py scripts/bench_data.py --quick                 # 安全小样本，网络 + 存储
    py scripts/bench_data.py --network --quick       # 只测取数
    py scripts/bench_data.py --storage --quick       # 只测存储
    py scripts/bench_data.py --network --providers all --symbols 100 --concurrency 1,4,8
    py scripts/bench_data.py --storage --storage-symbols 5000 --storage-days 250

约定：
- **不写用户数据**：存储测试只用 `tempfile`；网络测试只读、不落库。
- 默认小样本；`--full` 才跑 100/500 只与全市场 56 页。
- 网络请求会受本机代理/账号档位影响；结果里记录 `em_market.current_tier()` 与冷却状态。
- 本脚本只用于选型/排障，不参与生产运行。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

for _stream in (sys.stdout, sys.stderr):
    _reconf = getattr(_stream, "reconfigure", None)
    if callable(_reconf):
        try:
            _reconf(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 固定、可重复的样本（避免每次抽样不同导致数字不可比）
_SYMBOLS = [
    "600000", "600004", "600009", "600010", "600011", "600015", "600016",
    "600018", "600019", "600028", "600029", "600030", "600031", "600036",
    "600038", "600048", "600050", "600104", "600111", "600150", "600276",
    "600309", "600519", "600585", "600690", "600809", "601318", "601398",
    "601857", "601988", "603259", "688981", "000001", "000002", "000063",
    "000100", "000333", "000651", "000858", "002415", "300750",
]


def _symbols(n: int) -> list[str]:
    out = list(_SYMBOLS)
    i = 0
    while len(out) < n:
        out.append(f"{600000 + i:06d}")
        i += 1
    return out[:n]


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    data = sorted(values)
    idx = min(len(data) - 1, max(0, int(round((len(data) - 1) * q))))
    return data[idx]


def _summary(times: list[float], rows: list[int], errors: list[str]) -> dict:
    return {
        "calls": len(times),
        "errors": len(errors),
        "error_rate": round(len(errors) / max(1, len(times)), 4),
        "total_s": round(sum(times), 3),
        "p50_ms": round(statistics.median(times) * 1000, 1) if times else 0.0,
        "p95_ms": round(_pct(times, 0.95) * 1000, 1),
        "rows": sum(rows),
        "rows_per_s": round(sum(rows) / max(1e-9, sum(times)), 1),
        "errors_sample": errors[:3],
    }


def _run_pool(fn, items, concurrency: int):
    """逐项计时；返回 (times, rows, errors)。K=1 时直接循环，避免线程池干扰。"""
    times, rows, errors = [], [], []

    def one(item):
        t0 = time.perf_counter()
        try:
            n = fn(item)
            return time.perf_counter() - t0, int(n or 0), None
        except Exception as e:  # noqa: BLE001 —— 基准要把错误率算进去
            return time.perf_counter() - t0, 0, f"{type(e).__name__}: {e}"

    if concurrency <= 1:
        for item in items:
            dt, n, err = one(item)
            times.append(dt)
            rows.append(n)
            if err:
                errors.append(err)
        return times, rows, errors

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = [ex.submit(one, item) for item in items]
        for fut in futures:
            dt, n, err = fut.result()
            times.append(dt)
            rows.append(n)
            if err:
                errors.append(err)
    return times, rows, errors


# ==========================================
# 网络 provider
# ==========================================
def _bench_clist(pages: int, pz: int = 100) -> dict:
    from data import em_market

    times, rows, errors = [], [], []
    for p in range(1, pages + 1):
        t0 = time.perf_counter()
        try:
            data, _total = em_market.clist_page(p, pz)
            rows.append(len(data))
        except Exception as e:  # noqa: BLE001
            rows.append(0)
            errors.append(f"page {p}: {type(e).__name__}: {e}")
        times.append(time.perf_counter() - t0)
    out = _summary(times, rows, errors)
    out["pages"] = pages
    out["page_size"] = pz
    return out


def _bench_ulist(symbols: list[str]) -> dict:
    from data import em_market

    times, rows, errors = [], [], []
    for i in range(0, len(symbols), 100):
        chunk = symbols[i:i + 100]
        t0 = time.perf_counter()
        try:
            df = em_market.fetch_quotes(chunk, interval=0.0)
            rows.append(0 if df is None else len(df))
        except Exception as e:  # noqa: BLE001
            rows.append(0)
            errors.append(f"{type(e).__name__}: {e}")
        times.append(time.perf_counter() - t0)
    return _summary(times, rows, errors)


def _bench_sina(symbols: list[str], concurrency: int, start: str) -> dict:
    from data.akshare_feed import AkShareFeed

    def one(sym):
        df = AkShareFeed.fetch_a_share_daily(sym, start_date=start)
        return 0 if df is None else len(df)

    times, rows, errors = _run_pool(one, symbols, concurrency)
    return _summary(times, rows, errors)


def _tencent_prefix(sym: str) -> str:
    return ("sh" if str(sym)[:1] in ("5", "6", "9") else "sz") + str(sym)


def _bench_tencent(symbols: list[str], concurrency: int, start: str) -> dict:
    import requests

    start_iso = f"{start[:4]}-{start[4:6]}-{start[6:8]}"

    def one(sym):
        key = _tencent_prefix(sym)
        url = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
               f"?param={key},day,{start_iso},,640,qfq")
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        obj = r.json()
        node = ((obj or {}).get("data") or {}).get(key) or {}
        rows = node.get("qfqday") or node.get("day") or []
        return len(rows)

    times, rows, errors = _run_pool(one, symbols, concurrency)
    out = _summary(times, rows, errors)
    out["limit"] = 640
    return out


def _netease_prefix(sym: str) -> str:
    return ("0" if str(sym)[:1] in ("5", "6", "9") else "1") + str(sym)


def _bench_netease(symbols: list[str], concurrency: int, start: str) -> dict:
    import requests

    def one(sym):
        url = ("https://quotes.money.163.com/service/chddata.html"
               f"?code={_netease_prefix(sym)}&start={start}&end=20991231"
               "&fields=TCLOSE;HIGH;LOW;TOPEN;VOTURNOVER;VATURNOVER")
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        text = r.content.decode("gbk", errors="replace")
        if "日期" not in text and "date" not in text.lower():
            raise ValueError("返回不是 CSV（可能被限流/改版）")
        return max(0, len(text.strip().splitlines()) - 1)

    times, rows, errors = _run_pool(one, symbols, concurrency)
    return _summary(times, rows, errors)


def _bench_em_hist(symbols: list[str], concurrency: int, start: str) -> dict:
    import akshare as ak

    def one(sym):
        df = ak.stock_zh_a_hist(symbol=sym, period="daily", start_date=start,
                                end_date=time.strftime("%Y%m%d"), adjust="qfq")
        return 0 if df is None else len(df)

    times, rows, errors = _run_pool(one, symbols, concurrency)
    return _summary(times, rows, errors)


def _bench_baostock(symbols: list[str], concurrency: int, start: str) -> dict:
    try:
        import baostock as bs  # type: ignore
    except Exception as e:  # noqa: BLE001
        return {"calls": 0, "errors": 1, "error_rate": 1.0,
                "errors_sample": [f"baostock 未安装：{e}"], "skipped": True}

    start_iso = f"{start[:4]}-{start[4:6]}-{start[6:8]}"
    login = bs.login()
    if getattr(login, "error_code", "0") != "0":
        return {"calls": 0, "errors": 1, "error_rate": 1.0,
                "errors_sample": [f"baostock 登录失败：{getattr(login, 'error_msg', '')}"],
                "skipped": True}

    def one(sym):
        code = ("sh." if str(sym)[:1] in ("5", "6", "9") else "sz.") + str(sym)
        rs = bs.query_history_k_data_plus(
            code, "date,open,high,low,close,volume,amount",
            start_date=start_iso, frequency="d", adjustflag="2")
        n = 0
        while rs.error_code == "0" and rs.next():
            n += 1
        if rs.error_code != "0":
            raise RuntimeError(rs.error_msg)
        return n

    try:
        times, rows, errors = _run_pool(one, symbols, concurrency)
        return _summary(times, rows, errors)
    finally:
        try:
            bs.logout()
        except Exception:  # noqa: BLE001
            pass


def bench_network(args) -> dict:
    from data import em_market, em_throttle

    syms = _symbols(args.symbols)
    out = {
        "meta": {
            "tier": em_market.current_tier(),
            "cooling": em_throttle.describe() or "",
            "symbols": len(syms),
            "start": args.start,
            "concurrency": args.concurrency,
        },
        "providers": {},
    }
    wanted = [p.strip() for p in args.providers.split(",") if p.strip()]
    if "all" in wanted:
        wanted = ["em_clist", "em_ulist", "sina_daily", "tencent_daily",
                  "netease_daily", "em_hist", "baostock"]

    for name in wanted:
        if name == "em_clist":
            print(f"[网络] em_clist pages={args.clist_pages} ...", flush=True)
            out["providers"][name] = _bench_clist(args.clist_pages)
        elif name == "em_ulist":
            print(f"[网络] em_ulist batches={max(1, (len(syms) + 99) // 100)} ...", flush=True)
            out["providers"][name] = _bench_ulist(syms)
        elif name == "sina_daily":
            for k in args.concurrency:
                print(f"[网络] sina_daily K={k} n={len(syms)} ...", flush=True)
                out["providers"][f"{name}@K{k}"] = _bench_sina(syms, k, args.start)
        elif name == "tencent_daily":
            for k in args.concurrency:
                print(f"[网络] tencent_daily K={k} n={len(syms)} ...", flush=True)
                out["providers"][f"{name}@K{k}"] = _bench_tencent(syms, k, args.start)
        elif name == "netease_daily":
            for k in args.concurrency:
                print(f"[网络] netease_daily K={k} n={len(syms)} ...", flush=True)
                out["providers"][f"{name}@K{k}"] = _bench_netease(syms, k, args.start)
        elif name == "em_hist":
            for k in args.concurrency:
                print(f"[网络] em_hist K={k} n={len(syms)} ...", flush=True)
                out["providers"][f"{name}@K{k}"] = _bench_em_hist(syms, k, args.start)
        elif name == "baostock":
            for k in args.concurrency:
                print(f"[网络] baostock K={k} n={len(syms)} ...", flush=True)
                out["providers"][f"{name}@K{k}"] = _bench_baostock(syms, k, args.start)
        else:
            out["providers"][name] = {"skipped": True, "errors_sample": ["未知 provider"]}
            print(f"[网络] 跳过未知 provider: {name}", flush=True)
    return out


# ==========================================
# 存储布局
# ==========================================
def _make_panel(n_symbols: int, n_days: int) -> "pd.DataFrame":
    import numpy as np
    import pandas as pd

    dates = pd.bdate_range("2020-01-01", periods=n_days)
    symbols = _symbols(n_symbols)
    rng = np.random.default_rng(20261104)
    close = 10 + np.cumsum(rng.normal(0, 0.05, n_symbols * n_days))
    close = np.maximum(1.0, close)
    df = pd.DataFrame({
        "date": np.tile(dates.to_numpy(), n_symbols),
        "symbol": np.repeat(symbols, n_days),
        "open": close * 0.99,
        "high": close * 1.02,
        "low": close * 0.98,
        "close": close,
        "volume": np.full(n_symbols * n_days, 1_000_000.0),
        "amount": np.full(n_symbols * n_days, 1e8),
    })
    return df


def _timeit(fn, repeat: int = 3) -> float:
    times = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return round(statistics.median(times) * 1000, 1)


def _storage_bench(n_symbols: int, n_days: int) -> dict:
    import pandas as pd
    import pyarrow.dataset as ds

    panel = _make_panel(n_symbols, n_days)
    symbols = sorted(panel["symbol"].unique().tolist())
    dates = sorted(panel["date"].unique().tolist())
    last_date = dates[-1]
    next_date = pd.Timestamp(last_date).to_pydatetime() + timedelta(days=1)
    out = {"meta": {"symbols": len(symbols), "days": len(dates),
                    "rows": len(panel)}, "layouts": {}}

    # ---------- A：symbol 历史 + 当日 date 快照 ----------
    root = tempfile.mkdtemp(prefix="jian_bench_A_")
    try:
        hist = os.path.join(root, "hist")
        snap = os.path.join(root, "snap")
        os.makedirs(hist)
        os.makedirs(snap)
        t0 = time.perf_counter()
        for sym, g in panel.groupby("symbol", sort=False):
            g.drop(columns=["symbol"]).to_parquet(os.path.join(hist, f"{sym}.parquet"), index=False)
        setup_a = time.perf_counter() - t0
        last = panel[panel["date"] == last_date].drop(columns=[]).copy()
        last.to_parquet(os.path.join(snap, f"{pd.Timestamp(last_date).date()}.parquet"), index=False)

        def a_read_one():
            g = pd.read_parquet(os.path.join(hist, f"{symbols[0]}.parquet"))
            s = pd.read_parquet(os.path.join(snap, f"{pd.Timestamp(last_date).date()}.parquet"))
            s = s[s["symbol"] == symbols[0]].drop(columns=["symbol"])
            return len(g) + len(s)

        def a_cross():
            return len(pd.read_parquet(os.path.join(snap, f"{pd.Timestamp(last_date).date()}.parquet")))

        def a_append():
            row = panel[panel["date"] == last_date].copy()
            row["date"] = next_date
            row["close"] = row["close"] * 1.001
            row.to_parquet(os.path.join(snap, f"{next_date.date()}.parquet"), index=False)

        out["layouts"]["A_hybrid"] = {
            "setup_s": round(setup_a, 3),
            "read_one_ms": _timeit(a_read_one),
            "cross_section_ms": _timeit(a_cross),
            "append_day_ms": _timeit(a_append),
            "files": len(os.listdir(hist)) + len(os.listdir(snap)),
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # ---------- B：按日期分区 ----------
    root = tempfile.mkdtemp(prefix="jian_bench_B_")
    try:
        t0 = time.perf_counter()
        for d, g in panel.groupby("date", sort=False):
            g.drop(columns=[]).to_parquet(
                os.path.join(root, f"{pd.Timestamp(d).date()}.parquet"), index=False)
        setup_b = time.perf_counter() - t0
        dataset = ds.dataset(root, format="parquet")

        def b_read_one():
            table = dataset.to_table(filter=ds.field("symbol") == symbols[0],
                                     columns=["date", "close"])
            return table.num_rows

        def b_cross():
            return len(pd.read_parquet(os.path.join(root, f"{pd.Timestamp(last_date).date()}.parquet")))

        def b_append():
            row = panel[panel["date"] == last_date].copy()
            row["date"] = next_date
            row["close"] = row["close"] * 1.001
            row.to_parquet(os.path.join(root, f"{next_date.date()}.parquet"), index=False)

        out["layouts"]["B_date"] = {
            "setup_s": round(setup_b, 3),
            "read_one_ms": _timeit(b_read_one),
            "cross_section_ms": _timeit(b_cross),
            "append_day_ms": _timeit(b_append),
            "files": len(os.listdir(root)),
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # ---------- C：按 symbol 分区（当前结构） ----------
    root = tempfile.mkdtemp(prefix="jian_bench_C_")
    try:
        t0 = time.perf_counter()
        for sym, g in panel.groupby("symbol", sort=False):
            g.drop(columns=["symbol"]).to_parquet(os.path.join(root, f"{sym}.parquet"), index=False)
        setup_c = time.perf_counter() - t0

        def c_read_one():
            return len(pd.read_parquet(os.path.join(root, f"{symbols[0]}.parquet")))

        def c_cross():
            n = 0
            for sym in symbols:
                g = pd.read_parquet(os.path.join(root, f"{sym}.parquet"))
                n += int((g["date"] == last_date).sum())
            return n

        def c_append():
            row = panel[panel["date"] == last_date].copy()
            row["date"] = next_date
            row["close"] = row["close"] * 1.001
            for sym, r in row.groupby("symbol", sort=False):
                p = os.path.join(root, f"{sym}.parquet")
                old = pd.read_parquet(p)
                pd.concat([old, r.drop(columns=["symbol"])], ignore_index=True).to_parquet(p, index=False)

        out["layouts"]["C_symbol"] = {
            "setup_s": round(setup_c, 3),
            "read_one_ms": _timeit(c_read_one),
            "cross_section_ms": _timeit(c_cross, repeat=1),
            "append_day_ms": _timeit(c_append, repeat=1),
            "files": len(os.listdir(root)),
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)

    return out


# ==========================================
# 输出
# ==========================================
def _print_table(results: dict) -> None:
    net = results.get("network")
    if net:
        print("\n== 网络 provider ==")
        print(f"tier={net['meta']['tier']} cooling={net['meta']['cooling'] or '-'} "
              f"symbols={net['meta']['symbols']}")
        print(f"{'provider':28} {'calls':>5} {'err':>4} {'p50ms':>8} {'p95ms':>8} {'rows/s':>8}")
        for name, r in net["providers"].items():
            if r.get("skipped"):
                print(f"{name:28} SKIP {r.get('errors_sample')}")
                continue
            print(f"{name:28} {r.get('calls',0):5d} {r.get('errors',0):4d} "
                  f"{r.get('p50_ms',0):8.1f} {r.get('p95_ms',0):8.1f} "
                  f"{r.get('rows_per_s',0):8.1f}")

    st = results.get("storage")
    if st:
        print("\n== 存储布局 ==")
        print(f"symbols={st['meta']['symbols']} days={st['meta']['days']} rows={st['meta']['rows']}")
        print(f"{'layout':12} {'setup_s':>8} {'read1ms':>8} {'crossms':>8} {'appendms':>9} {'files':>6}")
        for name, r in st["layouts"].items():
            print(f"{name:12} {r['setup_s']:8.3f} {r['read_one_ms']:8.1f} "
                  f"{r['cross_section_ms']:8.1f} {r['append_day_ms']:9.1f} {r['files']:6d}")


def main() -> int:
    ap = argparse.ArgumentParser(description="数据下载 / 存储布局基准（只读，不写用户库）")
    ap.add_argument("--mode", choices=("all", "network", "storage"), default="all")
    ap.add_argument("--quick", action="store_true", help="安全小样本（默认）")
    ap.add_argument("--full", action="store_true", help="100 只 / 全市场 56 页 / 大存储")
    ap.add_argument("--providers", default="em_clist,em_ulist,sina_daily",
                    help="逗号分隔；all = 全部候选")
    ap.add_argument("--symbols", type=int, default=20)
    ap.add_argument("--concurrency", default="1,4,8",
                    help="逗号分隔并发梯度")
    ap.add_argument("--clist-pages", type=int, default=3)
    ap.add_argument("--storage-symbols", type=int, default=2000)
    ap.add_argument("--storage-days", type=int, default=250)
    ap.add_argument("--start", default="20240101")
    ap.add_argument("--out", default="", help="写入 JSON 的路径（可选）")
    args = ap.parse_args()

    if args.full:
        args.symbols = max(args.symbols, 100)
        args.clist_pages = 56
        args.storage_symbols = max(args.storage_symbols, 5000)
        args.storage_days = max(args.storage_days, 250)
    if args.quick:
        args.symbols = min(args.symbols, 20)
        args.clist_pages = min(args.clist_pages, 3)
        args.storage_symbols = min(args.storage_symbols, 500)
        args.storage_days = min(args.storage_days, 120)

    args.concurrency = [int(x) for x in str(args.concurrency).split(",") if x.strip()]
    results = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
               "quick": bool(args.quick), "full": bool(args.full)}

    if args.mode in ("all", "network"):
        results["network"] = bench_network(args)
    if args.mode in ("all", "storage"):
        print(f"\n[存储] {args.storage_symbols} 只 × {args.storage_days} 天 ...", flush=True)
        results["storage"] = _storage_bench(args.storage_symbols, args.storage_days)

    _print_table(results)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\nJSON: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
