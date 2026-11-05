---
status: active
topic: 数据底层平台与下载提速（provider / 目录 / 调度 / 存储 / 资产扩展）
read_when: 要改数据湖、下载、取数接口，或新增 ETF/港股/期货/财报/分钟数据时
skip_if: 只改某个页面的展示或文案
verified: 2026-11-04
---

# 数据底层重构与下载提速方案 · ★2.09（P1/P2 完成，日更覆盖/新股已补，P3 待开工）

> **用户 2026-11-04 明确**：现有下载链路是早期按 A 股日线设计的，面对港股 / ETF / 期货 /
> ROE·PE·PB·财报 / 分钟线会越来越乱；同时“5000 多只全 A 下载要 1 小时 20 分”不可接受。
> 本文是**架构方案 + 执行清单**，只做设计，不含代码改动；所有数字都来自本机实测（匿名档），
> 不靠估算。目标是**低耦合、高内聚**，不是把更多逻辑堆进 `sync_service.py`。

---

## 0. 结论摘要（先看四条）

1. **80 分钟不是调度参数的小问题**：单只新浪日线 2.2–3.2s；16 只并发 K=1/4/8 的吞吐分别是
   **0.34 / 0.95 / 1.04 只/秒**，加到 8 并发几乎不涨，5000 ÷ 1.04 ≈ **80 分钟**。
   ⇒ 继续加并发只会更接近限流边界，**必须换数据路径**。
2. **全市场当天快照可以 1 分钟内拿完**：东财 `clist` 56 页 / 5563 行实测 **52.4s**，
   106 行/秒，无冷却；单日快照 parquet 写入仅 **17ms**。日更应从“5000 次单只请求”改为
   “56 次分页 + 1 个日分区文件”。
3. **首次全量历史不再阻塞用户**：用户拍板“**打开可用，后台慢慢补**”。首屏只依赖启动与
   最近快照；全历史由后台低优先级队列补齐，UI 显示覆盖率，不要求用户等 80 分钟。
4. **存储不先入为主**：per-symbol / 日期分区 / 混合三种布局做**同数据集 benchmark**，
   按实测分数直接选优；开发期没有长期用户，**不为兼容旧数据而放弃更优结构**，
   迁移失败可回滚。

---

## 1. 已拍板口径（实现时不得再反复）

| 议题 | 决定 | 落地要求 |
|---|---|---|
| **登录态** | **匿名档 + 登录档两条都走** | 每条 provider 明确 `auth_mode` 能力；界面显示当前档位；**必须登录才能用的功能要硬提醒**，不许静默降级成“没数据” |
| **首次全量** | **打开可用，后台补全** | 启动/首屏不等待 5000 只全历史；先给最近快照/自选/当前标的；后台队列补历史并显示进度/覆盖率 |
| **存储迁移** | **benchmark 直接选优** | 不因“怕影响现有数据”而保留明显更差的布局；开发期可重建；保留回滚开关与旧读路径 |
| **候选源** | **允许引入并实测** | 腾讯 / 网易 / Baostock / 东财登录档等都可进 benchmark；先验证许可、稳定性、字段口径，再决定是否进生产 |
| **ETF 口径** | 货币 ETF 保留；复权失败退回不复权 + 标注 | 沿用 `ETF-LOF.md` §8，本方案不重复定义 |
| **不做** | 港股通 / 场外 QDII / 全市场分钟线默认下载 | 见 §9；分钟只做自选/当前标的按需 |

---

## 2. 实测边界（2026-11-04，本机匿名档）

| 路径 | 实测 | 说明 |
|---|---|---|
| 东财 `clist` 全市场快照 | **52.38s / 56 页 / 5563 行**，106 行/秒 | 无冷却；单页 100 行 |
| 东财 `ulist` 100 只 | **2.035s / 批** | 适合小池/自选，不是全市场最优 |
| 新浪单只日线 | **2.2–3.2s / 只** | `stock_zh_a_daily`，2024 起 |
| 新浪 16 只 K=1 | **47.71s**，0.34 只/秒 | 串行基线 |
| 新浪 16 只 K=4 | **16.92s**，0.95 只/秒 | 并发有收益，但开始受源侧约束 |
| 新浪 16 只 K=8 | **15.44s**，**1.04 只/秒** | 单只延迟升到 7.6s，吞吐不再涨 |
| 东财单只历史（匿名） | 0.58–0.67s，**RemoteDisconnected** | 匿名不可用；登录档需另测 |
| 2000 行 parquet（热/冷） | 写 4ms / 读 2ms；冷写 153ms | 单文件读写不是主瓶颈 |
| 5600 行单日快照 parquet | **写 17ms / 读 10ms** | 日期分区写入极便宜 |
| 当前策略 | `interval=0.6s`、默认 K=2 | 5000 只理论/实测均落在 50–80 分钟 |

**结论**：当前链路的瓶颈是“**请求粒度 + 源侧吞吐**”，不是 pandas、不是磁盘。
日更必须走批量快照；首次全量必须异步化或换 provider。

### 2.1 P0 首轮实测（`scripts/bench_data.py`，2026-11-04）

**网络 provider（小样本，匿名档）**

| provider | 实测 | 备注 |
|---|---|---|
| 东财 `clist` | 2 页 p50 **525ms**，190 行/秒；56 页全市场 **52.4s / 5563 行** | 日更首选 |
| 东财 `ulist` | 100 只 **2.0s** | 小池/自选 |
| 新浪单只 K=1 | p50 **4.19s**，173 行/秒（8 只） | 单只历史慢 |
| 新浪单只 K=4 | p50 **3.68s**，186 行/秒（8 只） | 并发收益有限 |
| 腾讯历史 | K=1 p50 **0.59s**，868 行/秒；K=4 p50 1.25s | **可用**；单次 640 根上限 |
| 网易历史 | 3/3 **502 Bad Gateway** | 当前环境不可用，暂不进生产 |
| 东财单只历史 | 2/2 `RemoteDisconnected` | 匿名档不可用；登录档待测 |
| Baostock | 未安装 | 脚本可检测；待引入后实测 |

**存储布局（5000 只 × 250 / 1000 天，合成数据）**

| 布局 | setup（250/1000 天） | 单只读 | 日更 | 横截面 | 文件数 |
|---|---|---|---|---|---|
| **A 混合** | 42.3s / 56.4s | **10.7ms / 7.8ms** | **26.6ms / 34.3ms** | 7.6ms / 4.4ms | 4971 |
| B 日期分区 | 5.2s / 17.1s | 146.8ms / **521.5ms** | 28.3ms / 44.5ms | 4.5ms / 4.1ms | 251/1001 |
| C 纯 symbol | 42.0s / 45.3s | 5.0ms / 4.0ms | **47.2s / 53.0s** | **19.2s / 17.5s** | 4969 |

> 结论：**C 的日更/横截面不可接受**；B 的单只读随历史长度线性恶化（1000 天已 521ms），
> 不满足“单股 <100ms”；**A 混合布局胜出**（setup 是一次性的，日更只写 1 个快照文件）。
> 该结论写入 §5.3，作为最终选型。

---

## 3. 现有链路与根因

当前路径：

```text
UI DownloadHub
  → SyncWorker（逐只循环）
    → MarketSyncService.refresh_one
      → lake.load_data(symbol)
      → AkShareFeed.fetch_a_share_daily（新浪单只，失败降级东财）
      → merge
      → lake.save_data(symbol)
```

| # | 根因 | 证据 |
|---|---|---|
| 1 | **用单只接口做全市场日更** | `data/sync_service.py:533` 每只 `_fetch`；`data/akshare_feed.py:548` 新浪单只 |
| 2 | **快照通道只做“恰好缺一天”的兜底** | `data/sync_service.py:518` `_try_apply_spot`；首次/全量/缺口 >1 天仍逐只 |
| 3 | **按 symbol 存储，日更 = 5000 次文件读写** | `data/market_db.py:25` 每个 zone 下 `symbol.parquet` |
| 4 | **没有 provider / asset 抽象** | `em_market.clist_page` 硬编码 `EM_FS_A`；`secid` 只认 A 股 |
| 5 | **全局一个节流器，通道互相抢额度** | `ThrottlePolicy.interval=0.6`；`RateGovernor` 全局 |
| 6 | **没有目录/清单，无法只补缺口** | 每轮都要 `load_data`/`stat` 才知道本地末日 |

> `data/lake_schema.py` 已有声明式 schema，但文件头自己写明“**没有生产代码读取**”；
> `fin_report` / `valuation` / `kline_min` 只有目录，没有写入管线。这不是“补一个下载函数”，
> 而是缺一层数据平台。

---

## 4. 目标架构（六层）

保持 `core / data / ui` 三层不变，在 `data/` 内长出平台层；UI 仍只经 `SyncService` 门面。

```text
UI (workers_download) → SyncService facade → Pipeline
  ├─ Planner      计划：bootstrap / daily / repair / minute
  ├─ Scheduler    调度：按 provider/channel 限流、优先级、重试、熔断
  ├─ Providers    适配：东财 / 新浪 / 腾讯 / 网易 / Baostock / ...
  ├─ Store        存储：符号历史 + 日期快照（或 benchmark 选出的布局）
  └─ Catalog      清单：dataset/asset/last_date/rows/source/schema_version
```

### 4.1 目录建议

```text
data/
  contracts.py          # AssetId / DatasetSpec / QualityReport / schema_version
  providers/
    base.py             # Provider 协议 + Capabilities + RatePolicy
    eastmoney.py        # clist / ulist / 单只 bars / 财报
    sina.py             # A 股日线 / 分钟 / 批量报价
    tencent.py          # 候选：批量快照 / 历史
    netease.py          # 候选：单只全历史 CSV
    baostock.py         # 候选：历史（需实测）
    registry.py         # dataset+market → provider 优先级与降级链
  catalog.py            # SQLite（stdlib）清单；不新增重型依赖
  store.py              # Store 接口 + 日期/符号分区实现
  planner.py            # 只生成缺口任务
  scheduler.py          # 按 provider/channel 的令牌桶与优先级
  pipeline.py           # 编排；幂等、断点、校验
  sync_service.py       # 保留现有 API，内部改走 pipeline
```

### 4.2 数据契约

不要把股票、ETF、期货、财报塞进同一张宽表。用 `DatasetSpec` 声明：

```text
AssetId(market=CN/HK, code, asset_type=stock/etf/index/future)
DatasetSpec(
  name=bar_daily / bar_minute / quote_snapshot / valuation_daily /
       fin_report / corporate_action / roster / calendar,
  primary_key=(asset, date[, period]),
  partition=date | symbol | month,
  required/optional columns,
  adjust=none/qfq,
  calendar=CN/HK,
  currency=CNY/HKD,
  schema_version
)
```

每行带 `source / fetched_at / asof / adjust / schema_version`；财报另带
`report_date / announce_date / statement_type`。以后加资产/数据集只注册，不改 UI 主逻辑。

### 4.3 Provider 能力表

```text
capabilities:
  bulk_snapshot       # 一次多只/全市场快照
  bulk_history        # 一次多只历史（若有）
  per_symbol_history  # 单只历史
  minute
  fundamentals
  max_batch
  rate_limit
  auth_required
```

编排器只问能力，不写 `if 股票/ETF/期货`。provider 失败返回
`QualityReport(provider, requested, returned, errors, latency, throttled)`，
不再用“空表 = 没数据”混淆网络失败与真没数据。

### 4.4 读门面

`MarketDataStore.history(symbol)` / `cross_section(date)` 是唯一读口：

- 历史文件与日快照在这里合并；
- M2/M3 不直接读目录，避免布局变化传染到页面；
- 旧 `MarketSyncService.status/refresh_one` 保留签名，内部改走新管线。

---

## 5. 存储 benchmark（先测后选）

### 5.1 候选布局

| 方案 | 结构 | 优点 | 风险 |
|---|---|---|---|
| **A. 混合（推荐先测）** | 历史 `symbol.parquet` + 当日 `date.parquet` | 单股查询快；日更只写 1 个文件 | 读要合并两处；需 catalog 指针 |
| **B. 日期分区** | `market/cn/date=YYYY-MM-DD/part.parquet` | 全市场日更/横截面最好 | 单股历史要扫多文件；需列裁剪/索引 |
| **C. 符号分区** | 当前结构 + catalog + 批量追加 | 改动最小 | 日更仍 5000 次写；冷缓存可到 10 分钟 |

### 5.2 Benchmark 工作负载

用合成数据（不依赖用户库）：

- 规模：5000 只 × 250 / 1000 / 4000 个交易日；
- 操作：
  1. 追加一个交易日（全市场）；
  2. 读单只全历史；
  3. 读某日全市场截面；
  4. 500 只自选批量读；
  5. 全市场 250 日扫描；
  6. 冷缓存 / 热缓存各一遍；
- 指标：p50/p95 延迟、文件数、磁盘占用、写入原子性、迁移耗时；
- 评分：按 UI 实际权重（单股读、日更、横截面、磁盘）加权，**直接选总分最高**。

### 5.3 决策（2026-11-04 P0 实测后定稿）

**选 A 混合布局**：

- 5000×250：A 单只读 **10.7ms**、日更 **26.6ms**；B 单只读 **146.8ms**、日更 28.3ms；
- 5000×1000：A 单只读 **7.8ms**、日更 **34.3ms**；B 单只读 **521.5ms**、日更 44.5ms；
- C 纯 symbol 的日更 **47–53s**、横截面 **17–19s**，直接淘汰；
- A 的代价是 setup 42–56s（一次性）和约 5000 个文件；换来的单股历史读与日更都最好。

落地要求：

- 历史仍按 symbol；每天新增一个 `bar_daily_snapshot/YYYY-MM-DD.parquet`（含全市场）；
- `MarketDataStore` 统一做“历史 + 快照”合并读，页面不感知布局；
- catalog 用 SQLite（stdlib）；查询引擎先 pyarrow dataset；DuckDB 仅在后续证明必要时引入；
- 迁移在开发期执行，旧文件保留一个版本做回滚；确认后清理。

---

## 6. 下载提速路线

### P0 · 基准与埋点（1–2 天，不改行为）

- 新增 `scripts/bench_data.py`：provider 矩阵 × 并发梯度（1/2/4/8/16）× 样本量（20/100/500）；
- 路径：东财 `clist` / `ulist`、新浪单只、东财单只（匿名/登录）、腾讯 / 网易 / Baostock；
- 记录 p50/p95、错误率、限流、字段完整性、单只/批量；
- 给现有 `refresh_one` 加阶段计时：HTTP / 解析 / 合并 / 落盘；
- 输出 JSON + Markdown 到临时目录，不写用户库。

**验收**：能在 1 小时内重复跑出同一张边界表；能回答“某接口在 K=8 时是否真的到顶”。

### P1 · 日更批量快照（3–5 天，最大收益）

- 全市场日更走 `clist` 56 页 → 一个日分区（或混合布局的 snapshot）；
- 只对“快照缺的票 / 新股 / 缺口 >1 天 / 除权漂移”走单只；
- `MarketDataStore` 统一读历史 + 快照；
- 首次打开：先读本地/快照；没有就后台拉最近一天，**不阻塞首屏**；
- 目标：**5000 只日更 <2 分钟**；单股按需 <5s；
- 用 100 只样本做新旧路径逐位对比；feature flag 可回滚。

#### P1 首轮落地（2026-11-05，未提交）

已实现：

- `data/daily_store.py`：日快照原子写/读、`merge_row`（同日以新行覆盖、去掉 `prev_close/name/pe/pb` 等快照专属列）；
- `data/em_market.py::fetch_market_quotes`：`clist` 56 页全市场快照（实测 52s）；
- `MarketSyncService.fetch_market_snapshot`：只读门面；
- `DailySnapshotWorker`：>=3000 只用 `clist`，500–2999 用 `ulist`，<500 仍走旧 `SyncWorker`；
  - 快照先落盘；本地恰好缺一天且昨收一致才直接追加；
  - 缺口/除权/缺昨收 ⇒ 该只退回 `refresh_one`，不抄错价；
  - 逐只合并进度照常上报，支持取消。
- `DownloadHub`：`kline_daily` 且非全量、>=500 只走日快照 worker；
  设 `JIAN_BULK_DAILY=0` 可整体回退旧 `SyncWorker`（回滚开关）；
- unit 新增 4 条 `daily_store` 测试（49/0）。
- `data/backfill.py`：把 `ReadinessReport` 转成 `BackfillPlan`（missing → partial → unreadable，
  可分批、可算覆盖率）；`DownloadHub.submit_backfill()` 作为**低优先级**队列通道 ——
  有普通下载任务时绝不抢跑。
- 日快照完成后，`DailySnapshotWorker.stats["symbols_empty"]` 自动投给 backfill 队列；
  `JIAN_AUTO_BACKFILL=0` 可关闭（与 `JIAN_BULK_DAILY=0` 同族回滚开关）。
- 首次启动：主窗口延迟 1.5s 检查；本地全空 ⇒ 直接日快照；有旧数据 ⇒
  `StartupCheckWorker` 只读体检后决定：只缺一天 ⇒ 快照，缺口更大 ⇒ 低优先级 backfill。
  花名册 >=500 只、队列空闲才动作；`JIAN_AUTO_DAILY=0` 关闭（冒烟默认关闭）。
- 数据管理页覆盖率先给文件计数，再由 `ReadinessWorker`（只读 parquet footer、不联网）
  补正式三态（就绪/历史不足/未下载）；不阻塞页面。
- `data/market_store.py`：统一读门面；`history()` 合并最新快照（合并中断时可兜底），
  `cross_section()` 读日快照；`MarketSyncService.status()` 已改走该门面。

**P1 首轮实测（2026-11-05，临时目录，不写用户库）**：

- 全市场 `clist` 拉取 **50.8s / 5563 行**；本地合并 **66.3s / 5220 只**；合计 **117.1s**，
  进入 <2 分钟目标（贴边，16 路本地合并；8 路时 71.2s）。
- 343 只快照无行（停牌/退市/无正价）归 `skipped` + `symbols_missing`，不再算失败。
- 100 只新旧路径逐位对比：新快照合并 vs 旧 `refresh_one(spot_bar=...)`，
  `date/open/high/low/close/volume/amount` **全部一致**。

**P1 收尾说明**：读写门面已接（`history` 快照兜底 / `cross_section` 只读日快照）；
历史反扫、分钟/财报读门面留给 P2/P4。P1 完成，进入 P2。

### P2 · 登录双通道与 provider 扩展（1 周）

#### P2 已落地（2026-11-05，2.07）

- `data/provider_caps.py`：匿名/登录能力表（快照 / 报价 / 新浪历史 / 东财兜底 /
  行业分页 / 财报 / 其他资产），**只写实测或明确未接入**；
- `data/provider_registry.py`：Eastmoney / Sina / Tencent / NetEase / Baostock
  的数据集、认证、批量能力与实测状态（腾讯 limited、网易 unavailable、Baostock 未安装）；
- 设置页账号组新增“当前档位能做什么”，登录状态追加“东财单只历史受限（快照/新浪历史仍可用）”；
  长表放在 tooltip，不把限制藏起来；
- `data/sina_market.py`：新浪批量报价（100 只/批，GBK）；小池日快照在
  东财失败时显式启用备源（`allow_fallback=True`），默认关闭保持旧路径。
  全市场快照失败时也可按花名册回退（`fallback_symbols`）。
- `data/tencent_market.py` + `data/provider_router.py`：近年/增量在 Sina 失败后
  走腾讯 640 根备源（volume 手→股，amount 缺列）；全历史仍走 Sina/东财，避免分页 7 倍请求。
- `scripts/bootstrap_history.py` + `data/bootstrap_once.py`：一次性授权 arm/consume，
  只对脚本请求 `allow_over_budget=True`，不占日常 300 次预算；
  2026-11-05 实跑 4955 只：统计到 **4605 成功 / 343.8s**（12.5–14.3 只/s），
  失败为 `920xxx` 北交所（东财直连不支持；本地原有完整文件未覆盖），预算仍 96/300。
- `data/em_history.py`：登录档东财 `push2his` 直连（带 Cookie、预算记账）；
  实测（2026-11-05，22 条凭据）：20 只短历史 K=1/4/8/16 = 17.4 / 5.78 / 3.07 / 1.93s，
  100 只 2010 起全历史 K=16 = **7.06s / 0 错误**。
  **约束**：登录日预算 300 次；5000 只一次性全历史不可行，当前只接“近年/增量”，
  全量 bootstrap 是否临时提额需用户拍板，绝不静默绕过风控。

- `auth_mode=anon/logged_in`；能力表分别记录；
- 匿名档：保守限速，明确哪些功能不可用；
- 登录档：用现有 `em_auth` Cookie；仍设上限；
- UI：设置页显示“当前匿名/登录”“登录后才可用”的硬提示；
- 把腾讯/网易/Baostock 的实测结果纳入 registry，按 dataset 选主源+备源。

#### 数据事故与修复（2026-11-05，P2 后）

**现象**：用户发现 M3 广度统计图与 P2 前不同。

**根因**：不是广度代码（`cross_section` / `breadth_*` / `market_db` 未改）。
`scripts/bootstrap_history.py --overwrite` 用东财 `fqt=1` **加法前复权**覆盖了
4605 个新浪**比例前复权**历史文件；两者除权日不同，抽样 `000001` 日收益率差异
最高 32%，且 228 个文件出现**负收盘价**（如 `600519` 2010 年 -188.89）。

**修复**：
- 先用新浪重拉 228 个负价文件（93.2s，0 失败）；
- 再把全部非北交所文件按新浪重拉（后台完成）；验收 **5172 文件 / 0 个非正收盘价**，
  抽样 `000001/600519/600000` 与新浪逐值完全一致；
- `data/quality.py` 增加 OHLC 质量闸门；`em_history` 拒收负价/重复日期；
- `bootstrap_history` 默认 `--source sina`；`--source em` 仅作实测；
- `JIAN_EM_DIRECT` 默认 0、`JIAN_TENCENT_HISTORY` 默认 0，避免不同复权口径
  再次拼进新浪历史；需显式 opt-in 并先做一致性校验；
- `scripts/repair_history.py` 可重复审计/修复（`--dry-run` / 默认坏文件 / `--all`）。

**结论**：这是**数据污染**，不是广度算法 bug；修复后需用户重跑一次广度扫描
（旧结果/缓存仍是污染数据算出的，不会自动变）。

#### 2026-11-05 日更覆盖审计

- 快照 `2026-11-05.parquet` 5219 行；100 只随机样本与新浪逐字段一致（量的尾差为源侧取整）。
- 花名册 4955 只中 4597 只已更新且历史最后一根与快照一致；349 只北交所不在
  东财 `clist`，9 只其他票无快照（多数停牌）。
- 已补：北交所 349 只、快照名单外新股 408 只（另 213 只有旧文件）、
  214 只快照有行但历史滞后的标的中的 213 只；花名册增量到 5577。
- 残留：`689009`（CDR，源无历史）与 `301139`（源无历史，且有停牌缺口）；
  不伪造当根，保留待换源。
- 日更已改：全市场快照出现的新股会**增量入册并合并当天一根**；北交所走
  新浪批量报价后置；`sina_market` 的 `920/43/83/87/88` 前缀修正为 `bj`。

### P3 · 目录 + 规划器 + 调度器（1–2 周）

- catalog 记录 `last_date/rows/source/schema_version`；
- planner 只生成缺口任务（bootstrap/daily/repair/minute）；
- scheduler 按 provider/channel 令牌桶、优先级、自适应并发、熔断；
- 盘后 15:10 预取 + 启动检查覆盖率；
- **同时按 §5 benchmark 结果迁移存储**。

### P4 · 资产与数据集扩展（2–3 周）

- ETF/LOF：独立 `etf_daily`，复用基金分红表做本地等比前复权；
- 港股：市场码、港历、港币、汇率字段；不混 A 股分区；
- 期货：主力连续/合约、交易日历、无复权；
- 财报/ROE/PE/PB：**按报告期批量**拉取，不按股票逐个；
- 分钟：只做自选/当前标的，按日期分区；不默认全市场。

### P5 · 质量与运维（1 周）

- schema/单位校验、缺口检测、除权因子版本、重复行；
- 失败重试/修复任务、快照压实、冷热分层；
- 数据管理页显示每个 dataset 的覆盖/来源/最后更新。

---

## 7. 首次打开与后台补全（用户口径落地）

1. 启动只保证“**能用**”：主窗口 + 最近快照/自选/当前标的；不等待全市场历史。
2. 首屏数据优先级：
   - 本地已有 → 直接显示；
   - 本地没有 → 先取**最近一天批量快照**（约 1 分钟）或单只按需；
   - 全历史 → 后台队列，按自选/组合/扫描需求排序。
3. 后台补全：
   - 低优先级、可暂停、可断点；
   - 每完成一批更新 catalog 与 UI 覆盖率；
   - 用户可看到“已补 X/5000”，但不阻塞其他操作。
4. M2/M3 全市场历史扫描：
   - 覆盖不足时明确提示“正在补历史，当前只能扫已有 N 只”，不静默给错分母；
   - 覆盖达标后再允许全市场口径。

---

## 8. 登录 / 匿名双通道

| 项 | 匿名档 | 登录档 |
|---|---|---|
| 凭据 | 无 | `em_auth` 现有 Cookie |
| 能力 | 批量快照可用；单只历史受限 | 可能解锁单只历史/更高额度（待实测） |
| 限速 | 保守（按实测边界） | 可略快，但仍有硬上限 |
| UI | 明确显示“匿名档”；登录专属功能置灰并给原因 | 显示“登录档”与到期/失效提示 |
| 失败 | 不静默降级；说明“该功能需要登录” | 登录失效回匿名档并提示重新登录 |

> 两个档位都跑 benchmark，结果写进 registry；**不允许**“匿名失败后假装没数据”。

---

## 9. 资产 / 数据集扩展表

| 数据集 | 分区建议 | 取数方式 | 备注 |
|---|---|---|---|
| A 股日线 | symbol 历史 + date 快照（待 benchmark） | clist 快照 / 单只历史 | 现有主链路 |
| ETF/LOF 日线 | `etf_daily` 独立 | 新浪基金日线 + 分红表 | 货币 ETF 保留；复权失败退回不复权+标注 |
| 港股日线 | `hk_daily` 独立 | 东财/腾讯/新浪候选 | 港历、港币、汇率；不混 A 股 |
| 期货日线 | `futures_daily` 独立 | 新浪主力连续/东财 | 无复权；合约/主力分开 |
| 分钟线 | date + symbol | 新浪/东财候选 | 只按需；不全市场默认 |
| 每日估值 | date | 东财快照批量 | PE/PB/市值；按日一个文件 |
| 财报/ROE | report_date | 东财 datacenter 批量 | 按报告期，不按股票 |
| 名册/日历 | 单文件/小表 | 现有 roster/calendar | 单独 dataset，不混行情 |

---

## 10. 验收标准

| 项 | 目标 |
|---|---|
| 日更 5000 只 | p95 **<2 分钟**（不含用户网络异常） |
| 首次打开 | 主窗口可用 **<5s**；不等待全历史 |
| 单股按需 | 本地命中 <100ms；联网补齐 <5s |
| 后台补全 | 可暂停/续跑；UI 有覆盖率；不阻塞操作 |
| 存储 benchmark | 有可重复脚本 + 评分表 + 明确选型 |
| 数据一致性 | 新旧路径 100 只样本逐位对比；差异可解释 |
| 登录/匿名 | 两档均有实测表；登录专属功能有硬提示 |
| 回归 | unit + chart + overlay 0 失败；CI unit 绿 |
| 限流 | 连续 7 天不触发账号级封禁；错误率 <1% |

---

## 11. 风险与回滚

- **provider 变更/限流**：每个 dataset 至少两个 provider；失败回退不丢旧缓存。
- **登录态依赖**：登录档只作为加速/扩展，匿名档必须保留基本可用。
- **存储迁移**：开发期可重建；旧布局保留一个版本；catalog 记录 schema_version。
- **首次补全慢**：后台队列 + 明确进度；不把“未补完”说成“没数据”。
- **口径风险**：复权、单位、财报报告期必须进 DatasetSpec，不在各页面重算。

---

## 12. 执行清单

- [x] P0：`scripts/bench_data.py` + provider 矩阵 + 现有链路阶段计时
- [x] P0：存储三布局 benchmark（A/B/C）与评分表 → **选 A 混合**
- [ ] P0 补：登录档 provider 实测（东财单只/腾讯）、Baostock 引入后实测
- [x] P1：日更批量快照 + 混合布局（快照 + 立即合并；全市场 117s；统一读门面已接）
- [x] P1：首次打开可用 + 后台补全队列 + 正式覆盖率体检（启动检查：空/只缺一天 → 快照；缺口更大 → backfill）
- [x] P1：100 只新旧路径逐位对比（临时目录，全部一致）+ `JIAN_BULK_DAILY=0` 回滚
- [x] P2：匿名/登录能力表 + 设置页提示；快照/近年历史/全市场快照备源已接；登录档已实测
      （全量 5000 受 300 次/日预算约束，提额待拍板）
- [x] P2：provider registry 已落地；Sina 报价 + 腾讯近年历史 + 东财登录直连已参与 fallback；
      全历史 planner 归入 P3
- [ ] P3：catalog + planner + scheduler + 盘后预取
- [ ] P3：按 benchmark 结果迁移存储
- [ ] P4：ETF / 港股 / 期货 / 财报 / 分钟数据集接入
- [ ] P5：质量校验、修复任务、压实与数据管理页

---

## 13. 附：本方案不解决的问题

- 不保证任何第三方接口永久可用；provider 会变，registry 必须可替换。
- 不做全市场分钟线默认下载（成本/额度不现实）。
- 不做港股通/场外 QDII（沿用既有边界）。
- 不把“历史全量”伪装成“实时”；后台补全期间 UI 必须显示覆盖率。
- 不在本方案里改 UI 视觉；只改数据层与必要的状态提示。
