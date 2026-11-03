---
status: active
topic: 冒烟 overlay 偶发 fastfail（0xC0000409）/ 跑完不退出 —— 根因排查与收口
read_when: 要改 tests/smoke_pages_overlay.py 的退出路径、断言编排或线程收尾时
skip_if: 只改业务代码（这条不影响 app 运行）
verified: 2026-11-03
---

# 测试基建专项：固定点 fastfail + 退出挂死

> 触发：2026-11-02 发布 2.0 时，overlay 连续两次 `0xC0000409`，第三次才 1236/0；
> 且第三次进程打印完汇总后**不退出**，独占输出文件句柄，常规手段杀不掉。
> **2026-11-03 更新**：fastfail 根因已定位并修复（10/10 绿）；"跑完不退出"当日**复现**
> （退出时 2 个 `ScanWorker` 存活 ⇒ `os._exit` 卡 `ExitProcess`），已改**硬退出**收口（见 §7）。
> 本文只做**如实记录**；剩余不确定项照实写在 §7。

## 1. 现象（实测）

| 项 | 记录 |
|---|---|
| 崩法 | `RC = -1073740791`（`0xC0000409`，fastfail），**不是断言红** |
| 频率（修复前） | 2026-11-02 三次：崩 / 崩 / 通过；历史记录约 2/5（§11.5-102，baseline worktree 同崩同位） |
| 输出 | 旧记录"两次都停在第 657 行"——**块缓冲导致的假崩点**（S1 实测后推翻） |
| 退出 | 通过那次打印 `===== 通过 1236 · 失败 0 =====` 后**不退出**（CPU 累计 83s），持住 `_tmp_p20_ov2.txt` |
| 杀进程 | `taskkill /F /T` 报"没有运行实例"；`Stop-Process -Force` 无效；**`.NET Process.Kill()` 成功**，随后文件立即可删 |
| **复现（2026-11-03）** | 后台跑的一次 overlay 打印完 `1241/0（3 红）` + 线程清单后**卡住数分钟**；清单显示 **2 个 `ScanWorker` 未结束**；30s watchdog 也没打印 ⇒ 主线程持 GIL 卡在 `os._exit`。`.NET Kill()` 结束 |

## 2. 已经**排除**的（有实验证据）

| 假设 | 实验 | 结论 |
|---|---|---|
| 槽内未捕获 Python 异常触发 fastfail | 离屏：槽里 `raise`，无 hook → `0xC0000409`；装 hook → 事件循环继续 | 机制成立，但**不是本次原因**：1.95 起两份冒烟已装 `_fastfail_guard`，2.0 仍崩 |
| `QThread.run` 异常走 `qFatal` | QThread.run 里 `raise` + hook | hook 能兜住（打印 EXCEPTHOOK、exec 返回 0）⇒ 也不是它 |
| 输出块缓冲导致的"固定点" | S1 加 `line_buffering=True` 后连跑 | **成立**：真崩点比 657 行靠后，旧结论作废 |

## 3. 根因（2026-11-03 确认）

**调用链**：`运行历史._on_rerun()` → `ScanView.apply_config()` → `ScanFlow.resolve_scope()`
→ `ReadinessFlow.start()`。

`ReadinessFlow.start()` 旧写法每次直接覆盖 `self._probe`：

```python
self._probe = ReadinessWorker(job, kline_zone_dir('kline_daily'), scope, min_bars=min_bars)
```

若上一轮 `ReadinessWorker` **仍在运行**，赋值瞬间最后一个 Python 引用归零 ⇒ PyQt/sip
析构 C++ `QThread` ⇒ Qt 报 "QThread: Destroyed while thread is still running" ⇒
**进程 fastfail（0xC0000409）**。是否踩中取决于上一轮是否刚好收尾 ⇒ **约 2/3 概率**。

**证据**（S3 最小复现，连跑 3 次）：

- 行缓冲后最后一条输出是「送行情页被拒」；
- 展开 `_on_rerun()` 逐段打点：`got page` → 崩，`apply_config` 内
  `before resolve_scope` → 崩；`resolve_scope` 内 `after result.set_empty` → 崩；
- `ReadinessFlow.start` 内最后一条 trace = `old probe=ReadinessWorker running=True`，
  下一条（构造新 worker 并赋值）未打印 ⇒ 崩在引用替换。

**同族问题（顺带修复）**：`ScanFlow._on_enrich_rows()` 在迟到回包里直接
`getattr(p, '_outcome', None).result.dates` ⇒ 新扫描已把 `_outcome` 清空时
`AttributeError`（guard 实测抓到）。修法：逐层 `getattr(..., None)`，拿不到就留空。

## 4. 修复（已落到工作区）

| 文件 | 改动 |
|---|---|
| `ui/widgets/readiness_flow.py` | `__init__` 增 `_probes`；`start()` 前先 `old.cancel()` 并把旧线程放进 `_probes`（收尾前一直持有引用）；新线程也入列；下次 start 时清掉已停止的 |
| `ui/widgets/scan_flow.py` | `_on_enrich_rows` 的 `_outcome` 读取改为安全链（`None` ⇒ 不填 `_valuation_date`） |
| `tests/smoke_pages_overlay.py` | 新增 ★2.02 段 3 条断言（旧线程被 cancel 且保住引用 / 新线程照常跑 / 迟到补全不抛异常） |

**没有改**：`ui/workers.py` 的线程模型（`ReadinessWorker` 仍是普通 QThread，不加全局注册表）。

## 5. S1–S6 执行记录

| 步 | 动作 | 结果 |
|---|---|---|
| S1 | 两份冒烟 `sys.stdout/stderr.reconfigure(..., line_buffering=True, write_through=True)` | ✅ 拿到真崩点；旧"657 行"作废 |
| S2 | `faulthandler.enable()` + `dump_traceback_later(900, exit=True)` | ✅ 原生崩溃/超时留栈；已知噪音见下 |
| S3 | 展开 `_on_rerun` + `ScanFlow`/`ReadinessFlow` 内打点，连跑二分 | ✅ 定位到 `readiness.start` 的引用替换 |
| S4 | 审查 `ReadinessWorker` / `JobGuard` / 父对象时序 | ✅ `ReadinessWorker` **无 parent**，唯一的引用就是 `self._probe` |
| S5 | 退出前打印 Python 线程 + 存活 QThread；30s watchdog；`os._exit` 前关 faulthandler | ✅ 线程清单直接抓到"2 个 ScanWorker 未结束"；**但 `os._exit` 卡在 ExitProcess 时主线程持 GIL，watchdog 也跑不起来** ⇒ 改为 `TerminateProcess` 硬退出 |
| S6 | 连跑 10 次 | ✅ **10/10 · RC=0 · 1239/0**；最长 49.1s；`smoke_chart` 1076/0 |

**已知噪音（不是失败，别误判）**：Windows 上 `pyqtgraph` + `os._exit()` 会在 DLL 卸载期
触发一次 access violation（最小对照：只建 `pg.PlotWidget` 再 `os._exit` 即可复现；
退出码仍为 0）。正常收尾前 `faulthandler.disable()` 把它静音；watchdog 触发时会
自己 `enable()` 回来留栈。它与 `0xC0000409` 不是同一回事。

## 6. 验收 / 风险 / 不做

- **验收**：fastfail **10/10** 通过；挂死复现后改为 `TerminateProcess` 硬退出，
  最后两次（其中一次退出时仍有 **2 个 ScanWorker**）都在 **<70s** 正常返回（`RC=0`）。
  两份冒烟仍在本地必跑（CI 依旧只跑静态检查，理由见 `.github/workflows/ci.yml`）。
- **风险**：`TerminateProcess` 跳过 DLL detach / atexit —— **只用于冒烟脚本**，
  生产 app 仍走正常退出 + `hub.shutdown()`（不得照搬）。
- **不做**：不为让测试变绿而删断言；不改 `ui/workers.py` 的线程模型；
  不为"收尾好看"把扫描线程强行 join 到主线程（只 cancel + 最多等 2s）。

## 7. 现状与剩余

1. **挂死根因已确认**（2026-11-03 后台复现）：退出时仍有 **2 个 `ScanWorker`**；
   `os._exit()` 卡在 `ExitProcess`，主线程持 **GIL** ⇒ 30s watchdog 线程也跑不起来。
   修法 = `_hard_exit()`（Windows `TerminateProcess`，绕开 DLL detach），已生效。
2. **那 2 个 ScanWorker 的来源未定位**：属测试自身遗留（异步扫描/回测未收尾）。
   2026-11-04 已加**通用收尾**（`_live_qthreads()` 全量 `cancel/requestInterruption` + 最多等 3s），
   退出不再多花 15s；来源仍待定位，不与业务线程模型混。
3. `taskkill` 报"无实例"而 `.NET Kill` 有效：与第 1 条同族（进程卡在 `ExitProcess`）。
4. CI 何时从静态扩到冒烟子集：需先定"CI 数据种子"方案（空机器上 8 条已知环境失败，
   见 `docs/reference/SETUP.md`）。
