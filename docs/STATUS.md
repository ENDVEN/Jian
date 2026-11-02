---
status: active
topic: 项目当前状态（版本 / 在途 / 下一步 / 已知债）
read_when: 每次开工的第一读；回答"现在什么状态、下一步做什么"
skip_if: 已经在做具体某个文件的改动（那时只需本文件的"在途任务"一条）
verified: 2026-11-02
---

# STATUS · 当前状态（唯一状态源）

> 本文件是 **L1**：读完 `README.md` 再读这里，就够回答"现在到哪了、下一步干什么"。
> 版本号本体只有一个真源：`version.json`（+ commit 首词）。本文件不再抄第二份。

---

## 1. 版本与提交

| 项 | 值 |
|---|---|
| 版本 | **2.02**（`version.json` / `config/settings.py` / commit 首词 三处一致） |
| HEAD | 本版提交（`git log -1`）· `2.02 测试基建 fastfail 根因修复 文档` |
| 推送 | ⬜ **已提交、未推送**（2026-11-03 用户只要求提交） |
| 工作区 | ✅ 2.02 提交时干净；随后开始 **ARCH-PERF P0 四件**（未提交、未 bump） |
| 最近三版 | `2.02` 测试基建 fastfail 根因修复（QThread 被 GC）· `2.01` 测试基建问题立项 · `2.0` 1.0 收官（启动占位 / 同步兜底 / CI） |

---

## 2. 冒烟基线（最近一次全绿，2026-10-29）

| 命令 | 结果 |
|---|---|
| `python -u tests/smoke_chart.py` | **1076 / 0** |
| `python -u tests/smoke_pages_overlay.py` | **1239 / 0**（2026-11-03 连跑 10 次全绿，最长 49.1s） |

> ⚠ **已知假红**：本机有下载在跑时（数据湖 parquet 的 mtime 每几秒变），两条"缓存命中"断言必红（§11.5-79）。**先停下载再跑**。
> ✅ **fastfail 已收口**（2026-11-03）：根因 = `ReadinessFlow.start()` 覆盖 `self._probe` 时旧 `ReadinessWorker` 仍在运行 ⇒ 引用归零 ⇒ QThread 析构 ⇒ `0xC0000409`。修法见 `plans/active/TEST-HARNESS.md` §4；连跑 10/10 通过。
> ⚠ **退出挂死未复现**（修复后 10 次都没出现）：退出路径已加存活线程清单 + 30s watchdog（卡住 ⇒ `RC=4` + 全线程栈），复现时按 `TEST-HARNESS.md` §7 收口。

---

## 3. 在途任务（active，三件）

| 任务 | 方案书 | 状态 | 一句话 |
|---|---|---|---|
| **场内基金 ETF/LOF 接入** | `docs/plans/active/ETF-LOF.md` | **未实现**，方案已拍板 | 只做场内 ETF/LOF；`etf_daily` 独立分区；用新浪分红表**本地等比前复权**补跳空；不进 A 股扫描/广度 |
| **架构与性能（启动）优化** | `docs/plans/active/ARCH-PERF.md` | **未实现**，方案已出 | 启动实测 4.05s；9 个页面全在 `__init__` 建好；P0 四件目标 ≤2.2s |
| **测试基建** | `docs/plans/active/TEST-HARNESS.md` | **进行中**（2.02 已提交） | fastfail 已定位并修复（10/10 绿）；"跑完不退出"未复现，退出路径已加 watchdog + 线程清单 |

---

## 4. 下一步（按顺序，别跳）

### P0 · 测试基建收尾（S1–S6 已随 2.02 提交）
- 已做：行缓冲 / `faulthandler` / 全局超时 / 退出 watchdog / 线程清单 / fastfail 根因修复 / 3 条新断言；
- 剩：**观察"跑完不退出"是否复现**（复现 ⇒ 按 `TEST-HARNESS.md` §7 收口）；确认后再定 CI 冒烟子集（当前 CI 只跑静态检查）。

### P1 · 启动优化四件（≈0.9 轮）
1. **惰性建页**：`ui/main_window.py` 9 个页面改工厂 + `page_*` property + 只读 `_PAGES`（已核实全仓 0 处下标路由、132 处外部引用语义不变）；
2. **roster 向量化**：`core/engine.py` 去掉 `iterrows`（15,055 次 → 一次）；
3. **日历批量**：`data/trade_calendar.py` 日期解析（`strptime` 26,391 次）；
4. **footer LRU**：`data/readiness.py` 用 `(path,size,mtime_ns)` 做键（2,673 次 footer 解析）；
5. 新增 `scripts/probe_startup.py` 当"同一把尺子"。

**验收用行为断言**（已建页面集合 / `os.stat` 调用数 / 逐位一致），**不用墙钟**（会 flaky）。目标 4.05s → ≤2.2s。

### 之后
- **ETF/LOF P1-1…P1-8**（`docs/plans/active/ETF-LOF.md` §5，≈1.5 轮）；
- **测试分层**（unit / integration / ui_smoke）；
- B13 深色主题（需先定范围）· 多组合对比（用户未提）。

---

## 5. 已知债（带数字，别凭感觉）

| 类别 | 事实 | 影响 |
|---|---|---|
| 测试形态 | `tests/` **2 个脚本 14.4k 行**；无 unit / 无 pytest。overlay 的 `0xC0000409` **已随 2.02 修复**（`ReadinessFlow` 旧线程被 GC）；"跑完不退出"未复现（`plans/active/TEST-HARNESS.md`） | 反馈 ~1–3 分钟；失败靠行眼找 |
| 视图层 | `ui/` 37,388 行（57%）· `widgets/` **94 个平铺** · ≥800 行文件 **11 个** | 改动要读多处 |
| 启动 | **4.05s** = import 1.36 + 构造 2.48 + 首绘 0.16 | 见 §4 P0 |
| 文档 | 总计 **740k 字符**（RULES 97.8k · ARCHIVE 242k · HISTORY 173k · PLAYBOOK 87k · CODEMAP 61k） | 见 §7 |
| 目录 | `models/`（103 行）与 core 并列；`samples/` 是用户样例数据 | 归类瑕疵，不影响功能 |
| 文档 | `§11.5-106` **已有正文**（2026-11-03 核对：在 `docs/RULES.md` §11.5，内容 = 按代码升序补齐的覆盖错觉） | 原"无正文"记录作废，无需补写 |

---

## 6. 环境前提（做验证前先确认）

- 用户数据目录 `~/.jian_data/`：`portfolios.json` / `preferences.json` / `data_lake/`（日线 5169 只）/ `logs/app.log`。
- **下载期间不要跑全量冒烟**（见 §2 假红）。
- 匿名访问东财会被整段 RST ⇒ 行业/估值类功能要登录东财（设置 → 账号）；新浪日线不受影响。

---

## 7. 文档迁移进度（D1–D3 全部完成）

| 批次 | 内容 | 状态 |
|---|---|---|
| **D1** | `README.md`（**产品页**，作者要求根目录少留文件）· `docs/AGENTS.md`（开发者/AI 入口）· 本文件（L1）· `docs/plans/README.md`（计划总表）· `docs/_TEMPLATE.md`（头部契约） | ✅ 已完成（2026-11-02 随 1.94 提交） |
| **D2a** | `RULES` 移入 `docs/RULES.md` + 全仓 76 处引用替换（README 链接按根相对写） | ✅ 已完成（2026-11-02） |
| **D2b** | 7 份方案书分流 `plans/active`（2）/ `plans/done`（5）+ 头部补 `status:` + 全仓 49 处引用 | ✅ 已完成（2026-11-02） |
| **D2c** | HISTORY / PLAYBOOK / ARCHIVE 分卷（4+5+5 册）+ 索引 + 全仓引用 | ✅ 已完成（2026-11-02，字数与条目守恒已核） |
| **D3** | RULES 瘦身（98.8k → **89.6k**）· `scripts/gen_codemap.py`（模块清单）· `scripts/check_docs.py`（5 项契约自检）· 20 份文档补 front-matter | ✅ 已完成（2026-11-02） |

**D2 的 6 处 RULES 漂移：✅ 2026-11-03 已修**（APP 版本 / 上一版 / 最近三版 / 主线指向 §4 / 行数改指 CODEMAP / 删掉已过期的"1.90 提交时机"；被并坏的第 18–19 行表格一并重整）。

---

## 8. 相关文档（按用途）

| 想知道 | 看 |
|---|---|
| 计划总表（active / done） | `docs/plans/README.md` |
| 逐文件职责 | `docs/reference/CODEMAP.md`（D2 后 → `docs/reference/CODEMAP.md`） |
| 踩过的坑（149 条） | `docs/playbook/INDEX.md`（D2 后 → `docs/playbook/INDEX.md`） |
| 换机 / 迁移 | `docs/reference/SETUP.md` |
| 当年为什么这么定 | `docs/history/README.md` / `docs/archive/README.md` |
| 全部纪律（红线细则） | `docs/RULES.md` §5 / §10 |
| 开发者 / AI 入口（路由 + 硬规定） | `docs/AGENTS.md` |

---

## 9. 开源准备（2026-11-02：License 与隐私已落地）

| 项 | 现状 | 要做 |
|---|---|---|
| **LICENSE** | ✅ **已定 GPLv3**（2026-11-02 作者拍板）：根目录 `LICENSE` = 完整 GPLv3 文本（35,147 字符，取自本机 PyQt6 附带文本逐字复制）；README 已有「许可证」一节 | 无（PyQt6 在 GPLv3 下合规）。将来若要闭源分发，需另购 PyQt 商业授权 |
| **samples/** | ✅ **真实数据已移出仓库**（→ 本机 `~/.jian_data/samples/`）；作者确认交割单是**真实交易记录**。**历史核对：仓库里只提交过 `samples/README.md`，4 个 xlsx 从未入库**（`git log --all --name-only -- samples` 实测）⇒ **无需重写历史** | 忽略规则改成 `samples/*` + `!samples/README.md`（只按扩展名忽略会漏 `.md`/`.json`） |
| **截图** | 无 | README 产品页需要截图 ⇒ 建 `docs/assets/`，图放那里（不塞根目录） |
| **隐私扫描** | `docs/` 中邮箱 / 手机 / 绝对路径命中 **0**；24 处 "cookie" 仅为说明文字 | 每次公开前重扫一遍（含 HISTORY/ARCHIVE 里的用户原话） |
| **根目录文件** | **6 个**：README / LICENSE / main.py / requirements.txt / version.json / .gitignore（`RULES.md` 已在 `docs/` 下） | 保持；新增文件一律先问"能不能放进 docs/" |
| **依赖清单** | ✅ 已合并为**单一** `requirements.txt`（35 项全 `==` 锁定；原 `requirements.lock.txt` 删除，SETUP 已改写为"一份文件"口径） | — |
