# tests/run_smoke.py
"""一键跑两份冒烟（默认**并行**）+ 分段耗时 + 紧凑汇总（★2.04 / B1 测试提速）。

用法（仓库根目录）：
    py tests/run_smoke.py              # 并行（推荐，日常）
    py tests/run_smoke.py --serial     # 串行（排障 / 单核机器）
    py tests/run_smoke.py --only overlay
    py tests/run_smoke.py --no-log     # 不落日志（只看汇总）

为什么可以并行：两份脚本的**单实例锁已按脚本分开**（`jian_smoke_chart.lock` /
`jian_smoke_overlay.lock`），互不共享窗口/临时目录；两者都只读数据湖，测试自身的
写盘已重定向到临时目录（见 `smoke_pages_overlay.py` 头部四条打桩）。

退出码：0 = 两份都过；1 = 有失败/崩；2 = 同脚本已有实例在跑（busy）。
完整日志落在系统临时目录（路径会打印），失败时先看 `FAIL:` 行。
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from typing import TextIO

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Windows 控制台默认 GBK：FAIL 文案里的 ⇒ / ↔ 会让汇总打印直接 UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    _reconf = getattr(_stream, "reconfigure", None)
    if callable(_reconf):
        try:
            _reconf(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 —— 被重定向的流不支持就跳过
            pass

SCRIPTS = {
    "chart": os.path.join("tests", "smoke_chart.py"),
    "overlay": os.path.join("tests", "smoke_pages_overlay.py"),
}
_SUMMARY_RE = re.compile(r"=====\s*通过\s*(\d+)\s*·\s*失败\s*(\d+)\s*=====")
_FAIL_RE = re.compile(r"^\s+FAIL:\s*(.+)$")


class Result:
    def __init__(self, name: str):
        self.name = name
        self.rows: list[tuple[float, str]] = []
        self.rc: int | None = None
        self.wall = 0.0
        self.log_path = ""
        self.busy = False
        self.timed_out = False
        self.exit_forced = False
        self._logf: TextIO | None = None
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._start: float = 0.0

    @property
    def ok_count(self) -> int | None:
        for _t, line in reversed(self.rows):
            m = _SUMMARY_RE.search(line)
            if m:
                return int(m.group(1))
        return None

    @property
    def fail_count(self) -> int | None:
        for _t, line in reversed(self.rows):
            m = _SUMMARY_RE.search(line)
            if m:
                return int(m.group(2))
        return None

    @property
    def fails(self) -> list[str]:
        out = []
        for _t, line in self.rows:
            m = _FAIL_RE.match(line)
            if m:
                out.append(m.group(1).strip())
        return out

    def sections(self) -> list[tuple[float, str]]:
        """按 `== 标题 ==` 聚合耗时（含启动段）。"""
        out: list[tuple[float, str]] = []
        current = "(启动/导入)"
        start = 0.0
        for t, line in self.rows:
            if line.startswith("== ") and line.rstrip().endswith(" =="):
                if t > start:
                    out.append((t - start, current))
                current = line.strip("= ").strip()
                start = t
        if self.rows:
            out.append((self.rows[-1][0] - start, current))
        return sorted(out, reverse=True)


def _reader(res: Result, start: float) -> None:
    assert res._proc is not None and res._proc.stdout is not None
    for line in res._proc.stdout:
        t = time.perf_counter() - start
        res.rows.append((t, line.rstrip("\n")))
        if res._logf is not None:
            try:
                res._logf.write(f"{t:8.3f} {line}")
                res._logf.flush()          # 卡住时也能看到最后一句
            except OSError:
                pass
        if "另一个冒烟实例" in line:
            res.busy = True


def _launch(name: str, log_dir: str | None) -> Result:
    res = Result(name)
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["JIAN_AUTO_DAILY"] = "0"       # 冒烟不触发启动自动日快照
    env["JIAN_EM_DIRECT"] = "0"        # 冒烟不受本机登录态影响
    env["JIAN_TEST_IGNORE_BUDGET"] = "1"  # 开发测试不读本机登录额度；生产仍受限
    env["JIAN_SCHEDULER"] = "0"        # 测试不启动进程级调度器状态
    env["JIAN_CATALOG"] = "0"          # 测试不写真实 catalog
    res.log_path = ""
    if log_dir:
        res.log_path = os.path.join(log_dir, f"{name}.log")
        res._logf = open(res.log_path, "w", encoding="utf-8")
    start = time.perf_counter()
    res._proc = subprocess.Popen(
        [sys.executable, "-u", SCRIPTS[name]],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    res._start = start
    res._thread = threading.Thread(target=_reader, args=(res, start), daemon=True)
    res._thread.start()
    return res


def _finish(res: Result, timeout: float) -> None:
    thread, proc = res._thread, res._proc
    assert thread is not None and proc is not None
    thread.join(timeout=timeout)
    if thread.is_alive():
        # 到时还在输出/完全没动静 ⇒ 真超时（没有汇总行）
        res.timed_out = True
        try:
            proc.kill()                    # Windows = TerminateProcess（不会卡 loader lock）
        except OSError:
            pass
    elif proc.poll() is None:
        # stdout 已 EOF，但进程仍在收尾（已知的"跑完不退出"）：
        # 给 5s 自然退出；仍不退才强杀。**断言已完成 ⇒ 不算失败**，只标注。
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            res.exit_forced = True
            try:
                proc.kill()
            except OSError:
                pass
    proc.wait()
    res.rc = proc.returncode
    res.wall = time.perf_counter() - res._start
    if res._logf is not None:
        try:
            res._logf.close()
        except OSError:
            pass


def _report(res: Result, top: int = 5) -> None:
    ok, bad = res.ok_count, res.fail_count
    if res.busy:
        status = "另一个实例在跑（busy）"
    elif res.timed_out:
        status = f"**超时（>{res.wall:.0f}s）已强杀**"
    elif ok is None:
        status = "**没有汇总行（崩了 / 被强杀）**"
    elif bad:
        status = f"通过 {ok} · **失败 {bad}**"
    else:
        status = f"通过 {ok} · 失败 0"
    if res.exit_forced:
        status += "（退出慢，已强杀；断言已完成）"
    print(f"\n[{res.name}] RC={res.rc} · {status} · 用时 {res.wall:.1f}s")
    if res.log_path:
        print(f"  日志: {res.log_path}")
    for d, sec in res.sections()[:top]:
        print(f"  慢段 {d:6.2f}s · {sec[:80]}")
    if res.fails:
        print("  失败项：")
        for item in res.fails[:10]:
            print(f"    - {item}")
        if len(res.fails) > 10:
            print(f"    … 另有 {len(res.fails) - 10} 条，见日志")
    if res.rc not in (0, None) or res.busy:
        tail = [line for _t, line in res.rows[-6:] if line.strip()]
        if tail:
            print("  最后几行：")
            for line in tail:
                print(f"    {line[:150]}")


def main() -> int:
    ap = argparse.ArgumentParser(description="跑两份冒烟（默认并行）")
    ap.add_argument("--serial", action="store_true", help="串行跑（默认并行）")
    ap.add_argument("--only", choices=sorted(SCRIPTS), help="只跑一份")
    ap.add_argument("--no-log", action="store_true", help="不写完整日志")
    ap.add_argument("--no-unit", action="store_true", help="跳过 unit 层（默认先跑，秒级失败快）")
    ap.add_argument("--timeout", type=float, default=180.0,
                    help="单份脚本超时秒数（默认 180；超时强杀并判失败）")
    args = ap.parse_args()

    names = [args.only] if args.only else list(SCRIPTS)
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    if not args.no_unit:
        print("先跑 unit 层（秒级；失败就不浪费 1 分钟跑冒烟）…")
        t_u = time.perf_counter()
        rc_u = subprocess.call(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests/unit", "-q"],
            cwd=ROOT, env=env)
        print(f"unit: {'OK' if rc_u == 0 else 'FAIL'} · {time.perf_counter() - t_u:.1f}s")
        if rc_u != 0:
            print("\n结论：**不通过**（unit 层先红，冒烟未跑）")
            return 1
    log_dir = None
    if not args.no_log:
        log_dir = tempfile.mkdtemp(prefix="jian_smoke_")
        print(f"日志目录: {log_dir}")
    mode = '串行' if args.serial or len(names) == 1 else '并行'
    print(f"运行模式: {mode} · {', '.join(names)}")

    t0 = time.perf_counter()
    results: list[Result] = []
    if args.serial or len(names) == 1:
        for name in names:
            res = _launch(name, log_dir)
            _finish(res, args.timeout)
            results.append(res)
    else:
        for name in names:
            results.append(_launch(name, log_dir))
        for res in results:
            _finish(res, args.timeout)
    total = time.perf_counter() - t0

    for res in results:
        _report(res)
    serial_sum = sum(r.wall for r in results)
    print(f"\n合计：{total:.1f}s（并行）" if len(results) > 1 and not args.serial
          else f"\n合计：{total:.1f}s")
    if len(results) > 1 and not args.serial:
        print(f"（逐个相加 = {serial_sum:.1f}s，并行省下 {max(0.0, serial_sum - total):.1f}s）")

    if any(r.busy for r in results):
        print("\n有脚本因『同脚本已有实例』退出 —— 先关掉在跑的冒烟再试。")
        return 2
    failed = [r for r in results
              if r.rc != 0 or r.timed_out or r.fail_count not in (0, None) or r.ok_count is None]
    if failed:
        print(f"\n结论：**不通过**（{', '.join(r.name for r in failed)}）")
        return 1
    print("\n结论：**全部通过**")
    return 0


if __name__ == "__main__":
    sys.exit(main())
