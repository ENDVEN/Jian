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
| 版本 | **1.94**（`version.json` / `config/settings.py` / commit 首词 三处一致） |
| HEAD | 本版提交（`git log -1`）· `1.94 文档分层 开源准备 依赖合并` |
| 推送 | ✅ `main == origin/main`（已推送） |
| 最近三版 | `1.94` 文档分层 + 开源准备 + 依赖合并 · `1.93` 架构与性能评估 · `1.92` 下载耗时三件 + 场内基金方案 |

---

## 2. 冒烟基线（最近一次全绿，2026-10-29）

| 命令 | 结果 |
|---|---|
| `python -u tests/smoke_chart.py` | **1076 / 0** |
| `python -u tests/smoke_pages_overlay.py` | **1236 / 0** |

> ⚠ **已知假红**：本机有下载在跑时（数据湖 parquet 的 mtime 每几秒变），两条"缓存命中"断言必红（§11.5-79）。**先停下载再跑**。
> ⚠ **已知硬崩**：`smoke_pages_overlay` 有约 1/2 概率在固定点 `0xC0000409` 崩（§11.5-102，已用 worktree 基线证实是**既存**问题，非某次改动引入）。它是将来上 CI 的**前置阻塞**。

---

## 3. 在途任务（active，只有两件）

| 任务 | 方案书 | 状态 | 一句话 |
|---|---|---|---|
| **场内基金 ETF/LOF 接入** | `docs/plans/active/ETF-LOF.md` | **未实现**，方案已拍板 | 只做场内 ETF/LOF；`etf_daily` 独立分区；用新浪分红表**本地等比前复权**补跳空；不进 A 股扫描/广度 |
| **架构与性能（启动）优化** | `docs/plans/active/ARCH-PERF.md` | **未实现**，方案已出 | 启动实测 4.05s；9 个页面全在 `__init__` 建好；P0 四件目标 ≤2.2s |

---

## 4. 下一步（按顺序，别跳）

### P0 · 启动优化四件（≈0.9 轮）
1. **惰性建页**：`ui/main_window.py` 9 个页面改工厂 + `page_*` property + 只读 `_PAGES`（已核实全仓 0 处下标路由、132 处外部引用语义不变）；
2. **roster 向量化**：`core/engine.py` 去掉 `iterrows`（15,055 次 → 一次）；
3. **日历批量**：`data/trade_calendar.py` 日期解析（`strptime` 26,391 次）；
4. **footer LRU**：`data/readiness.py` 用 `(path,size,mtime_ns)` 做键（2,673 次 footer 解析）；
5. 新增 `scripts/probe_startup.py` 当"同一把尺子"。

**验收用行为断言**（已建页面集合 / `os.stat` 调用数 / 逐位一致），**不用墙钟**（会 flaky）。目标 4.05s → ≤2.2s。

### 之后
- **ETF/LOF P1-1…P1-8**（`docs/plans/active/ETF-LOF.md` §5，≈1.5 轮）；
- **测试分层**（unit / integration / ui_smoke）+ **文档分卷**（本文件所属的 D2/D3，见 §7）；
- B13 深色主题（需先定范围）· 多组合对比（用户未提）。

---

## 5. 已知债（带数字，别凭感觉）

| 类别 | 事实 | 影响 |
|---|---|---|
| 测试形态 | `tests/` **2 个脚本 14,389 行 = 全仓 22%**；无 unit / 无 pytest / 无 CI | 反馈 ~3 分钟；失败靠行眼找 |
| 视图层 | `ui/` 37,388 行（57%）· `widgets/` **94 个平铺** · ≥800 行文件 **11 个** | 改动要读多处 |
| 启动 | **4.05s** = import 1.36 + 构造 2.48 + 首绘 0.16 | 见 §4 P0 |
| 文档 | 总计 **740k 字符**（RULES 97.8k · ARCHIVE 242k · HISTORY 173k · PLAYBOOK 87k · CODEMAP 61k） | 见 §7 |
| 目录 | `models/`（103 行）与 core 并列；`samples/` 是用户样例数据 | 归类瑕疵，不影响功能 |
| 文档 | `§11.5-106` **无正文**（RULES §7-B17 引用了它，历史遗漏） | 补写一条，或改引相邻编号 |

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

**D2 必须顺手修的 6 处 RULES 漂移**（`docs/RULES.md` 行号 2026-11-02 实测）：

| 行 | 现在写的 | 应为 |
|---|---|---|
| 16 | APP 版本 `1.89` | 1.93（或直接改成"见 version.json"） |
| 17 | 上一版 `1.88` | 1.92 |
| 20 | 最近三版 1.92/1.91/1.90 | 补 1.93 |
| 21 | 主线"下一步 = B15 完整版" | 池化已落地，主线应指向 §4 |
| 24 | `portfolio_view.py` ~1350 行 | 1463 |
| 25 | "待决：1.90 提交时机" | 已提交推送 |

另：第 18–19 行的表格已被并坏（第 18 行从"冒烟"不许复活"…"半句开始，缺行首），D2 一并修。

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
