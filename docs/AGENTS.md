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
2. **QThread 只在 `ui/workers.py`**：页面/弹窗不许自造线程类（下载调度在 `ui/download_hub.py`）。
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
python -u tests/smoke_chart.py          # 内核
python -u tests/smoke_pages_overlay.py  # 页面
```

两条都必须 **0 失败**；若本机有下载在跑，"缓存命中"类断言会假红（先停下载）。

文档/文件改动后另跑两条（各 <2 秒）：

```bash
py scripts/check_docs.py      # front-matter / 计划登记 / 链接 / RULES 体积 / 模块清单
py scripts/gen_codemap.py     # 改了 .py 就重生成 MODULE_INDEX（--check 只校验）
```
接口/口径改动还要补断言——**没有断言的行为改动视为没做完**。
