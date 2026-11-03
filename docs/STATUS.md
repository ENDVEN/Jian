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
| 版本 | **2.04**（`version.json` / `config/settings.py` / commit 首词 三处一致） |
| HEAD | 本版提交（`git log -1`）· `2.04 测试提速 工程拆件 CI单测` |
| 推送 | ⬜ **已提交、未推送**（`main` 领先 `origin/main` **3 个提交**：2.02 / 2.03 / 2.04） |
| 工作区 | ✅ 干净（2.04 提交后） |
| 最近三版 | `2.04` 测试提速 + 工程拆件（unit / 并行 runner / CI / workers 拆分）· `2.03` 启动优化 P0 · `2.02` 测试基建 fastfail 根因修复 |

---

## 2. 冒烟基线（最近一次全绿，2026-11-04）

| 命令 | 结果 |
|---|---|
| `python -u tests/smoke_chart.py` | **1080 / 0**（+4 条 P0 内核断言） |
| `python -u tests/smoke_pages_overlay.py` | **1244 / 0**（+5 条惰性建页断言） |
| `py tests/run_smoke.py`（并行） | **56–100s**（实测 56.3 / 80.5 / 100.2s；逐个相加 88.7–150.1s），两份均 0 失败 |
| `py -m unittest discover -s tests/unit -v` | **41 tests / 0.05s**（日期 / roster / footer / 缓存键 / 文案 / 组合 / merge_tail / 指标与净额 / 风险与格式化） |
| `.github/workflows/ci.yml` | `unit` job：41 条，**不读数据湖、不联网**；冒烟仍本地跑 |

> ⚠ **已知假红**：本机有下载在跑时（数据湖 parquet 的 mtime 每几秒变），两条"缓存命中"断言必红（§11.5-79）。**先停下载再跑**。
> ✅ **fastfail 已收口**（2026-11-03）：根因 = `ReadinessFlow.start()` 覆盖 `self._probe` 时旧 `ReadinessWorker` 仍在运行 ⇒ 引用归零 ⇒ QThread 析构 ⇒ `0xC0000409`。修法见 `plans/active/TEST-HARNESS.md` §4；连跑 10/10 通过。
> ✅ **退出挂死已复现并收口**（2026-11-03）：退出时仍有 **2 个 `ScanWorker`**；`os._exit` 卡在 `ExitProcess`、主线程持 GIL（watchdog 也跑不起来）⇒ 冒烟改 `TerminateProcess` 硬退出；带 2 个存活线程仍 **57s 正常返回**。线程来源另立。

---

## 3. 在途任务（active，三件）

| 任务 | 方案书 | 状态 | 一句话 |
|---|---|---|---|
| **场内基金 ETF/LOF 接入** | `docs/plans/active/ETF-LOF.md` | **未实现**，方案已拍板 | 只做场内 ETF/LOF；`etf_daily` 独立分区；用新浪分红表**本地等比前复权**补跳空；不进 A 股扫描/广度 |
| **架构与性能（启动）优化** | `docs/plans/active/ARCH-PERF.md` | **P0 已完成**（2.03）· P1/P2 未做 | 构造 3.6s→0.27s；已建页面 9→1；真机探针 **2.145s**（目标 ≤2.2s） |
| **测试基建** | `docs/plans/active/TEST-HARNESS.md` | **进行中**（2.02 已提交） | fastfail 10/10 绿；挂死已复现并收口（存活 QThread + `ExitProcess` 死锁 ⇒ 硬退出）；2 个 ScanWorker 来源另立 |

---

## 4. 下一步（按顺序，别跳）

### 已完成（2.02 / 2.03 / 2.04）
- **测试基建 S1–S6**（2.02）：fastfail 根因修复 + 挂死改硬退出；仅剩"2 个 ScanWorker 来源"（测试侧）。
- **启动优化 P0 四件**（2.03）：惰性建页 / roster 向量化 / 日历批量 / footer LRU + `probe_startup.py`；
  行为断言 9 条（chart +4、overlay +5）；实测 3.6s → 0.27s、9 → 1 页、真机探针 **2.145s**。
- **测试提速 + 工程拆件**（2.04）：`tests/unit` **41 条**（0.05s）+ `tests/run_smoke.py`
  并行 **56–100s** + CI `unit` job；`workers.py` 拆为 58 行门面 + 7 个领域件，运行历史/
  下载文案/横截面/回测预览等大文件按领域拆分，旧导入路径不变。

### P0 · 下一件：ETF/LOF 接入（≈1.5 轮）
- `docs/plans/active/ETF-LOF.md` §5 的 **P1-1 … P1-8**：分区/schema → 基金取数 → 名册独立表 →
  下载入口 → 组合接入 → 数据管理分区名 → 本地等比前复权 → 10 条断言 + 文档。
- 前置已具备：A 股日历复用、`load_daily` 统一出口、组合页已接 `load_daily`。

### P1 · 启动优化第二批（ARCH-PERF P1，≈0.5 轮）
1. `data/akshare_feed.py` 顶层 `import akshare` → 惰性（启动省 ~0.4s）；
2. `ui/views/portfolio_view.py` `refresh()` 延迟到首次可见 + `_save_ui` 300ms 防抖；
3. `data/market_db.py` `get_lake()` 单例（去掉每次 `new` + `makedirs`）。

### 之后
- **测试分层**（unit / integration / ui_smoke）：CI **unit job 已接**（41 条，与静态检查并行）；integration/ui_smoke 与冒烟子集待"CI 数据种子"；
- **B17 组合剩余**：行业覆盖率（`industry_map` 302/5169 ≈5.8%）· 多组合对比（用户未提）；
- **B13 外观/深色主题**（需先定范围）· **S2-5 迁移 / B12「修回历史」已拍板不做**（2026-11-03）。

---

## 5. 已知债（带数字，别凭感觉）

| 类别 | 事实 | 影响 |
|---|---|---|
| 测试形态 | `tests/` 2 个脚本 **16.4k 行** + `tests/unit` **41 条**（秒级）；无 pytest。`tests/run_smoke.py` 并行 **56–100s**（逐个相加 89–150s）。overlay fastfail 已修；"跑完不退出"已复现并硬退出（2 个 `ScanWorker` 来源另立） | 日常 ~80s；unit 秒级；失败仍靠行眼找 |
| 视图层 | `ui/` 37,388 行（57%）· `widgets/` **94 个平铺** · ≥800 行文件 **11 个** | 改动要读多处 |
| 启动 | P0 后构造 **0.27s**、已建页 **1/9**、真机探针 **2.145s**（旧基线 4.05s = import 1.36 + 构造 2.48 + 首绘 0.16） | 见 §4 P1（首次切页有一次性 0.3~0.5s） |
| 文档 | 总计约 700k 字符（RULES **87.6k** · ARCHIVE 242k · HISTORY · PLAYBOOK · CODEMAP） | 见 §7 |
| 目录 | `models/`（103 行）与 core 并列；`samples/` 是用户样例数据 | 归类瑕疵，不影响功能 |

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
| **samples/** | ✅ **真实数据已移出仓库**（→ 本机 `~/.jian_data/samples/`）；作者确认交割单是**真实交易记录**。**历史核对：仓库里只提交过 `samples/README.md`，4 个 xlsx 从未入库**（`git log --all --name-only -- samples` 实测）⇒ **无需重写历史** | ✅ 已完成：`.gitignore` 用 `samples/*` + `!samples/README.md`（整目录忽略 + 只放行说明） |
| **截图** | ✅ 已有 `docs/assets/market.png` / `portfolio.png`，README 两处引用均有效；`overview.png` 是历史上有意删除（空界面） | 无（新增截图仍放 `docs/assets/`，不塞根目录） |
| **隐私扫描** | `docs/` 中邮箱 / 手机 / 绝对路径命中 **0**；24 处 "cookie" 仅为说明文字 | 每次公开前重扫一遍（含 HISTORY/ARCHIVE 里的用户原话） |
| **根目录文件** | **6 个**：README / LICENSE / main.py / requirements.txt / version.json / .gitignore（`RULES.md` 已在 `docs/` 下） | 保持；新增文件一律先问"能不能放进 docs/" |
| **依赖清单** | ✅ 已合并为**单一** `requirements.txt`（35 项全 `==` 锁定；原 `requirements.lock.txt` 删除，SETUP 已改写为"一份文件"口径） | — |
