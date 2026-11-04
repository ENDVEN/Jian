---
status: reference
topic: 开发者 / AI 协作入口（路由 + 硬规定 + 别做什么）
read_when: 任何 agent 或新开发者接手这个仓库的第一读
skip_if: 只是普通用户（只看 README 就够了）
verified: 2026-11-02
---

# AGENTS · 接手须知（60 行内）

> 读完这一页 + `docs/STATUS.md`（约 4k 字符），你就能回答"这是什么 / 现在到哪了 / 下一步干什么"，**不要**先去读 98k 的 `docs/RULES.md`。

## 1. 30 秒事实

- **是什么**：PyQt6 桌面单体，期货交割单复盘 + A 股行情/回测/组合。两条链路几乎不交叉。
- **技术栈**：PyQt6 · pyqtgraph · pandas · SQLite · Parquet 数据湖 · AkShare（行情源）。
- **代码分布**：`ui/` ~37k 行 · `data/` ~7.7k · `core/` ~5.7k · `models/` ~0.1k · `tests/` 两个冒烟脚本 ~14k。
- **用户数据**（**不在仓库里**）：`~/.jian_data/` —— `jian_trades.db` · `preferences.json` · `portfolios.json` · `watchlist.json` · `data_lake/` · `logs/app.log` · `screenshots/`。

## 2. 数据流（记 4 跳就够）

```
交割单 Excel → data/data_feed.py（解析 + FIFO 缝合）→ models/trade.py
             → core/engine.py（DataEngine 唯一门面）→ SQLite → core/analyzer.py → ui/ 只负责画

AkShare → data/akshare_feed.py → ~/.jian_data/data_lake/*.parquet（Parquet 湖）
        → core/formula（通达信 DSL）→ core/backtest.py → ui/views/backtest.py

组合：data/portfolio_store.py（portfolios.json）→ core/portfolio_stats.py → ui/views/portfolio_view.py
```

## 3. 现在到哪了

| 想知道 | 看 |
|---|---|
| 版本 / 下一步 / 已知债 | `docs/STATUS.md`（**唯一状态源**） |
| 哪份计划还在办 | `docs/plans/README.md`（`active` 只应有 1~2 份） |
| 逐文件职责 | `docs/reference/CODEMAP.md` |
| 踩过的坑（149 条） | `docs/playbook/INDEX.md`（按关键词搜，别通读） |

## 4. 五条硬规定（不可妥协）

1. **UI 不碰 SQL / 不直接调爬虫**：一律走 `core/engine.py` 或 `data/sync_service.py` 门面。
2. **QThread 只在 `ui/workers*.py`**：`ui/workers.py` 是门面，领域件为 `workers_scan/download/backtest/sync/imports/core/throttle.py`；
   页面/弹窗不许自造线程类（下载调度在 `ui/download_hub.py`）。
3. **数据三层不许混**：A 层（湖内就地算）/ B 层（当日快照，仅"基准日 == 最新定稿日"才填）/ C 层（无源就不做）。
4. **单一真源**：版本号 → `version.json`；断言数 → `docs/STATUS.md`；文件行数 → `CODEMAP`；写用户数据一律**原子写**（tmp + `os.replace`）。
5. **诚实边界**：不造数。缺数据写「数据不足」，不填 0、不猜、不假装实时、不承诺"推荐/最优"。

## 5. 别做什么

- ❌ **别通读 `docs/RULES.md`（98k 字符）** —— 只读 §5（数据契约）与 §10（协作指令）。
- ❌ 别读 `docs/archive/README.md` / `docs/history/README.md`，除非用户明确问"当年为什么这么定"（那是历史）。
- ❌ 别改历史文档里的冻结数字（§10-14 第 2 条：历史行永不回改）。
- ❌ 别把业务数据、截图、日志放进仓库（`~/.jian_data/` 才是它们的家）。
- ❌ 别在未获作者同意时提交（同一个版本只提交一次，三处版本号同步，备注 ≤60 字符）。

## 6. 验证怎么跑

```bash
py tests/run_smoke.py                      # 两份冒烟**并行** + 分段耗时（约 60–100s，日常推荐）
py -m unittest discover -s tests/unit -v   # 纯函数 unit 层（秒级）

# 单项排障（不走 runner）
python -u tests/smoke_chart.py
python -u tests/smoke_pages_overlay.py
```

两条冒烟都必须 **0 失败**（runner 只在两份都过时返回 0）；若本机有下载在跑，
"缓存命中"类断言会假红（先停下载）。改了纯内核（`core/` / `data/`）先跑 unit，
页面改动再跑 overlay；`run_smoke.py` 会打印**最慢的 5 个区段**，便于继续优化。

unit 当前 **59 条**，覆盖：日期批量解析 / roster 向量化 / footer LRU / 缓存键与数据版本 /
批量耗时文案 / 组合统计与权重 / 横截面 `merge_tail` / 指标与净额 / 成分 diff / 风险文案与格式化。纯内核改动**不必等两份冒烟**。

按改动选测试，别每次都等全量：

| 改了什么 | 先跑 |
|---|---|
| `core/` / `data/` 纯函数 | unit（秒级）；触及取数/缓存再加 chart |
| 图表件 / 公式渲染 | `py tests/run_smoke.py --only chart` |
| 页面 / 交互 / 样式 | `py tests/run_smoke.py --only overlay` |
| 提交前 | `py tests/run_smoke.py`（unit + 两份并行） |

CI（push / PR）跑 **静态检查 + unit** 两个 job，都**不读数据湖、不联网**；两份冒烟仍只在本地/发布前跑
（CI 冒烟子集要等"数据种子"方案，见 `docs/STATUS.md` §4）。

文档/文件改动后另跑两条（各 <2 秒）：

```bash
py scripts/check_docs.py      # front-matter / 计划登记 / 链接 / RULES 体积 / 模块清单
py scripts/gen_codemap.py     # 改了 .py 就重生成 MODULE_INDEX（--check 只校验）
```
接口/口径改动还要补断言——**没有断言的行为改动视为没做完**。
