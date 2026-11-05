---
status: reference
topic: 逐文件清单（自动生成，勿手改）
read_when: 想知道"哪个文件干什么"（先看这里，再看 CODEMAP）
skip_if: 已知文件位置
verified: auto
---

# 模块清单（自动生成）

> 由 `scripts/gen_codemap.py` 生成；**只写"文件干什么"**，设计理由在 `CODEMAP.md` / `docs/RULES.md`。
> 改了文件就重跑：`py scripts/gen_codemap.py`；校验：`py scripts/gen_codemap.py --check`。

| 文件 | 一句话 | 顶层符号 | 行数 |
|---|---|---|---|
| `config/__init__.py` | — | 0 | 0 |
| `config/settings.py` | — | 0 | 332 |
| `core/__init__.py` | — | 0 | 0 |
| `core/analyzer.py` | — | 1 | 110 |
| `core/backtest.py` | 单股事件模式回测引擎 (A股仅做多 LONG)。 | 14 | 558 |
| `core/conditions.py` | 买卖条件配置 → DSL 表达式（**唯一真源**，§7-B15 SW-3 补）。 | 4 | 90 |
| `core/cross_section.py` | M2 全市场横截面筛选 / M3 广度统计 —— 纯计算内核（§7-B1/B2 主案 · D2 / D5） | 15 | 661 |
| `core/database.py` | — | 1 | 456 |
| `core/engine.py` | — | 1 | 169 |
| `core/formula/__init__.py` | 通达信(优先)/Pine 兼容 公式引擎。 | 3 | 41 |
| `core/formula/draw.py` | 公式绘图的契约层（IR）—— 引擎侧唯一「绘图语义」定义处（§7-B3 B① · P1）。 | 6 | 143 |
| `core/formula/parser.py` | 通达信(兼容类 Pine)公式方言的 语法分析器 (Parser)。 | 10 | 180 |
| `core/formula/program.py` | 通达信式「整段函数」解析与执行 (多语句 + 绘图指令 → 绘图 IR)。 | 21 | 359 |
| `core/formula/runtime.py` | 通达信公式方言的 运行时函数库 与 求值上下文 (EvalContext)。 | 12 | 323 |
| `core/formula/tokens.py` | 通达信(兼容类 Pine)公式方言的 词法分析器 (Lexer)。 | 3 | 69 |
| `core/index_regimes.py` | 参数稳健性研究（§7-B15）· 上证指数切块（SW-2）。 | 19 | 277 |
| `core/indicators.py` | — | 1 | 71 |
| `core/param_sweep.py` | 参数稳健性研究（§7-B15）· 编排层（SW-3）。 | 10 | 277 |
| `core/portfolio_stats.py` | 🧺 组合的**统计内核**（★1.85 / §7-B17 **P1**）—— 纯计算，零 Qt、零 IO。 | 15 | 293 |
| `core/portfolio_sweep.py` | 组合层级的**池化研究**（★1.85 / §7-B17 **P4**）—— 纯计算，零 Qt、零 IO。 | 6 | 131 |
| `core/preferences.py` | 用户偏好持久化 (User Preferences Store)。 | 1 | 153 |
| `core/relation_stats.py` | ★1.73 / §7-B16 期 0：把 M3「与指数的关系」这件事的**判据与切分**收成纯函数。 | 13 | 381 |
| `core/scan_filters.py` | 扫描阈值 / 帧准备 / 读数人话（★2.04 / P2 拆件）。 | 5 | 109 |
| `core/sweep_plan.py` | 参数稳健性研究（§7-B15）· 网格纯计算（SW-0）。 | 9 | 228 |
| `core/sweep_stats.py` | 参数稳健性研究（§7-B15）· 统计唯一真源（SW-1）。 | 15 | 257 |
| `core/updater.py` | — | 1 | 57 |
| `core/utils.py` | 通用无副作用工具函数集合 (Pure Helpers)。 | 24 | 369 |
| `data/__init__.py` | — | 0 | 0 |
| `data/akshare_feed.py` | — | 8 | 716 |
| `data/annotations.py` | 用户手绘标注：对象模型 + 持久化 CRUD（§7-B3 ④ · P6）。 | 19 | 524 |
| `data/backfill.py` | 历史补全计划（★2.05 / DATA-PLATFORM P1）。 | 4 | 109 |
| `data/backtest_archive.py` | 回测结果历史存档 (v1.37 / §7-A4) —— 每次回测落一份**不可变快照**。 | 9 | 556 |
| `data/bootstrap_once.py` | 一次性全历史 bootstrap 授权（★2.06 / DATA-PLATFORM P2）。 | 8 | 67 |
| `data/daily_store.py` | 日快照中转（★2.05 / DATA-PLATFORM P1）。 | 7 | 116 |
| `data/data_feed.py` | 交易账单解析层 (Bill Parsing Layer)。 | 9 | 365 |
| `data/em_auth.py` | 东财**登录态凭据**的唯一出口（★v6.73）—— 存储、有效性判据、Cookie 头、每日预算。 | 17 | 206 |
| `data/em_history.py` | 东财单只历史直连（登录档，★2.06 / DATA-PLATFORM P2）。 | 2 | 83 |
| `data/em_market.py` | 东财 `push2` 的**两条取数通道**（★v6.69）—— 全仓库唯一的东财行情明细出口。 | 27 | 526 |
| `data/em_throttle.py` | 东财取数的**退避闸门**（★v6.69 起；★v6.74 改为**按通道**）—— 全仓库唯一出处。 | 16 | 169 |
| `data/feed_cells.py` | 交割单解析的**单元格 / 工作表工具层**（1.25 自 `data/data_feed.py` 拆出 · §9-L）。 | 12 | 208 |
| `data/feed_fifo.py` | 交割单解析的**数据模型 + FIFO 配对引擎**（1.25 自 `data/data_feed.py` 拆出 · §9-L）。 | 7 | 218 |
| `data/feed_months.py` | 交割单的**月份推断与资金链对账**（1.25 自 `data/data_feed.py` 拆出 · §9-L）。 | 3 | 63 |
| `data/feed_report.py` | 交割单的**结算月报页签解析**（1.25 自 `data/data_feed.py` 拆出 · §9-L）。 | 2 | 56 |
| `data/fetch_messages.py` | 取数失败的**人话文案唯一出口**（★2.04 / P2 拆件）。 | 4 | 91 |
| `data/formula_store.py` | 公式配方库（函数资产化）—— §7-B3 P7。 | 8 | 252 |
| `data/hub_assets.py` | ƒ 函数总库的**数据层助手**（★1.61 / §7-B16 · 实现方案书 `docs/plans/done/HUB.md`）。 | 10 | 190 |
| `data/hub_migration.py` | ƒ 函数总库的**一次性资产收编**（★1.61 / §7-B16 · H1 · 方案书 `docs/plans/done/HUB.md` §3）。 | 4 | 97 |
| `data/industry_store.py` | M2 结果表「细分行业」本地缓存 (JSON，位于用户数据目录，物理隔离不随代码分发)。 | 2 | 79 |
| `data/lake_schema.py` | 数据湖**列合约**（★1.78 · §9.1 收口：让"湖里有哪些列算数"由**一处**说了算）。 | 3 | 69 |
| `data/market_db.py` | — | 2 | 208 |
| `data/market_store.py` | 统一读门面（★2.05 / DATA-PLATFORM P1）。 | 1 | 50 |
| `data/net_env.py` | 行情取数的**网络环境策略**（★v6.72）—— **地址族**与**代理指纹**两件事的唯一出处。 | 11 | 175 |
| `data/portfolio_store.py` | 🧺 组合的**存储层**（★1.85 / §7-B17 P0）。 | 7 | 216 |
| `data/provider_caps.py` | 匿名 / 登录能力表（★2.06 / DATA-PLATFORM P2）。 | 5 | 57 |
| `data/provider_registry.py` | Provider 能力注册表（★2.06 / DATA-PLATFORM P2）。 | 2 | 35 |
| `data/provider_router.py` | 历史取数 provider 顺序（★2.06 / DATA-PLATFORM P2）。 | 3 | 33 |
| `data/quality.py` | 日线数据质量闸门（★2.07 修复 bootstrap 污染）。 | 1 | 46 |
| `data/readiness.py` | 就绪度体检（§7-B1/B2 主案 D6-1 · v6.39）—— 扫描之前，先告诉用户 | 6 | 228 |
| `data/roster_sync.py` | 花名册同步的**唯一入口**（app 内一键按钮 / 运维脚本共用 · ★1.70 / §11.5-125）。 | 2 | 54 |
| `data/scan_store.py` | M2 / M3 的**会话内存缓存**（§7-B1/B2 主案 D3 · v6.35） | 14 | 406 |
| `data/scan_strategy_store.py` | M2/M3「筛选方案」本地持久化 (JSON，位于用户数据目录，物理隔离不随代码分发)。 | 2 | 90 |
| `data/sina_market.py` | 新浪批量报价（★2.06 / DATA-PLATFORM P2 备源）。 | 4 | 82 |
| `data/storage_maintenance.py` | 存储与维护（★v6.75 · §7-B13 · **S2-5**）—— 数据目录 / 缓存清理 / 配置导出导入的**唯一实现处**。 | 9 | 143 |
| `data/strategy_store.py` | 回测策略本地持久化 (JSON, 位于用户数据目录，物理隔离不随代码分发)。 | 8 | 183 |
| `data/sweep_archive.py` | 参数研究快照存档（§7-B15 SW-4）· 照抄 `data/backtest_archive.py` 范式。 | 6 | 281 |
| `data/sync_service.py` | 行情同步服务 (Market Sync Service) —— 数据湖「增量维护」的统一门面 (v5.8)。 | 19 | 832 |
| `data/tencent_market.py` | 腾讯历史日线备源（★2.06 / DATA-PLATFORM P2）。 | 4 | 73 |
| `data/trade_calendar.py` | A 股交易日历获取件（v6.45 / §7-B10 · 用户拍板引入真交易日历）。 | 9 | 134 |
| `data/watchlist_change.py` | 自选分组的「组合当日涨跌」（§7-B8 R3）—— **零 Qt**：纯函数 + 一层带 TTL 的快照缓存。 | 7 | 155 |
| `data/watchlist_store.py` | 自选股（Watchlist）—— 用户关心的标的清单，JSON 原子写（§7-B3 P8）。 | 5 | 340 |
| `main.py` | — | 5 | 208 |
| `models/__init__.py` | — | 0 | 0 |
| `models/trade.py` | — | 1 | 103 |
| `scripts/analyze_index_regimes.py` | 上证指数切块 · 离线脚本（§7-B15 SW-2 · 方案书 §11 决议 3）。 | 1 | 73 |
| `scripts/bench_data.py` | 数据下载 / 存储布局基准（★2.05 / DATA-PLATFORM P0）。 | 19 | 460 |
| `scripts/bootstrap_history.py` | 一次性全历史 bootstrap（★2.06 / DATA-PLATFORM P2）。 | 1 | 146 |
| `scripts/check_docs.py` | 文档契约自检（秒级、不依赖 Qt）：写完/搬完文档跑一次。 | 9 | 100 |
| `scripts/gen_codemap.py` | 生成 `docs/reference/MODULE_INDEX.md`：**每个 .py 一行**（路径 · 一句话 · 公共符号 · 行数）。 | 4 | 81 |
| `scripts/probe_startup.py` | 启动耗时探针（★2.03 / ARCH-PERF P0-5）—— **同一把尺子**，不参与运行。 | 1 | 63 |
| `scripts/repair_history.py` | 修复被 bootstrap 污染的日线（★2.07）。 | 1 | 97 |
| `scripts/sync_roster.py` | — | 2 | 37 |
| `tests/run_smoke.py` | 一键跑两份冒烟（默认**并行**）+ 分段耗时 + 紧凑汇总（★2.04 / B1 测试提速）。 | 6 | 245 |
| `tests/smoke_chart.py` | — | 14 | 5844 |
| `tests/smoke_pages_overlay.py` | 「回测页 + 行情工作台」公式叠层 / 标注 / 配方 / 自选 / 周期 / 成交模型（§7-B5）的**页面级**验收（P3–P8）。 | 35 | 8920 |
| `tests/unit/test_backfill.py` | — | 2 | 64 |
| `tests/unit/test_bootstrap_once.py` | — | 1 | 33 |
| `tests/unit/test_core_math_and_store.py` | 指标 / 净额 / 参数文本 / 组合成分 diff 的纯函数测试（★2.04 / B1 第四层）。 | 4 | 105 |
| `tests/unit/test_core_p0.py` | 纯函数单元测试（★2.04 / B1 测试分层第一层）。 | 4 | 91 |
| `tests/unit/test_daily_store.py` | — | 1 | 73 |
| `tests/unit/test_em_history.py` | — | 1 | 23 |
| `tests/unit/test_market_store.py` | — | 1 | 66 |
| `tests/unit/test_portfolio_and_merge.py` | 组合统计 / 横截面增量续接的纯函数测试（★2.04 / B1 第三层）。 | 6 | 102 |
| `tests/unit/test_provider_caps.py` | — | 2 | 35 |
| `tests/unit/test_quality.py` | — | 3 | 37 |
| `tests/unit/test_scan_and_texts.py` | 缓存键 / 数据版本 / 批量耗时文案 / 交易日定稿的纯函数测试（★2.04 / B1 第二层）。 | 3 | 102 |
| `tests/unit/test_sina_market.py` | — | 1 | 54 |
| `tests/unit/test_tencent_market.py` | — | 1 | 27 |
| `ui/__init__.py` | — | 0 | 0 |
| `ui/dialogs/__init__.py` | — | 0 | 0 |
| `ui/dialogs/bulk_download.py` | 批量预下载弹窗 (v5.8 · §7-A3)。 | 2 | 524 |
| `ui/dialogs/em_login.py` | 东财登录（**粘贴凭据**）对话框（★v6.73 / §7-B13 · S2-1）—— **唯一的登录入口**。 | 2 | 128 |
| `ui/dialogs/fill_model_help.py` | 「成交模型怎么选？」用户教学弹窗 (v6.17 · §7-B5)。 | 1 | 139 |
| `ui/dialogs/formula_overlay.py` | 行情页「公式叠加」编辑器（§7-B3 P4/P5 · v6.8 支持多副图）。 | 2 | 259 |
| `ui/dialogs/import_futures.py` | — | 1 | 171 |
| `ui/dialogs/indicator_params.py` | `⚙` 指标参数窗口（v6.24 · §7-B8 R16）—— **内置项与用户配方共用同一个组件**。 | 2 | 240 |
| `ui/dialogs/list_manager.py` | — | 1 | 43 |
| `ui/dialogs/manual_entry.py` | — | 1 | 181 |
| `ui/dialogs/portfolio_edit.py` | 🧺 组合「编辑成分」对话框（★1.87 补漏：**手工增删改成分**）。 | 1 | 439 |
| `ui/dialogs/watchlist_picker.py` | 从自选股里挑选 → 批量移入某个分组（§7-B8 R2 的**第二种添加入口**）。 | 1 | 98 |
| `ui/download_hub.py` | 全局后台下载调度器 (v1.43 · §7-B11) —— 把"下载任务"的归属从**弹窗**搬到**主窗口**。 | 2 | 456 |
| `ui/download_jobs.py` | 下载任务的"数据与判据"件（★v6.70 / §4 体积债：从 `ui/download_hub.py` 拆出）。 | 3 | 168 |
| `ui/main_window.py` | — | 2 | 974 |
| `ui/settings_registry.py` | 设置项的**唯一真源**（★v6.73 / §7-B13 · S2 路径表 **S2-0**）。 | 37 | 579 |
| `ui/views/__init__.py` | — | 0 | 0 |
| `ui/views/backtest.py` | 📐 市场回测 视图 —— 策略工作台（UI 1.22 = 「样板 A」：摘要条 + 右侧遮罩抽屉 + 结果吃满）。 | 2 | 876 |
| `ui/views/backtest_history.py` | 🗂 运行历史（§7-A4 · v1.37 立 · **v1.46 按样板重做**）—— 市场回测页第 4 个子页。 | 1 | 272 |
| `ui/views/backtest_module.py` | 📐 市场回测 —— 模块容器（子页全部上线）： | 1 | 64 |
| `ui/views/breadth_view.py` | 📊 M3「广度统计」—— 页面本体（§7-B1/B2 主案 STEP 5）。 | 1 | 330 |
| `ui/views/dashboard.py` | — | 1 | 247 |
| `ui/views/data_manager.py` | 🗄 数据管理 (v5.8 · §7-A3；v5.10 UX 加固；v5.11 勾选重设计) | 2 | 594 |
| `ui/views/formula_hub.py` | ƒ 函数总库 —— 页面本体（★1.61 / §7-B16 · 方案书 `docs/plans/done/HUB.md`）。 | 1 | 115 |
| `ui/views/param_sweep.py` | 🧪 参数研究 —— 页面装配（§7-B15 SW-5/6/7 · 薄壳 · ★v6.86 视觉返工版）。 | 1 | 397 |
| `ui/views/portfolio_view.py` | 🧺 组合页（★1.85 / §7-B17 · **P0 已交付 + P1 净值/持仓**）。 | 2 | 1475 |
| `ui/views/records.py` | — | 1 | 346 |
| `ui/views/review.py` | 🧭 复盘工作台（ReviewView）—— §9-U 版式收口 + §9-L 拆分（1.25）。 | 1 | 173 |
| `ui/views/scan_view.py` | 🌐 M2「全市场筛选」—— 页面本体（§7-B1/B2 主案 STEP 4）。 | 1 | 215 |
| `ui/views/settings_view.py` | ⚙ 设置页（★v6.73 / §7-B13 · 主案 **S2「系统设置双栏」** · 本文件 = 路径表 **S2-0** 的壳）。 | 2 | 272 |
| `ui/views/trading_desk.py` | 📈 行情工作台（Trading Desk）—— §7-B3 **P8 行情页整体重做** + §7-B6 **1.23 版式收口**。 | 1 | 498 |
| `ui/widgets/__init__.py` | — | 0 | 0 |
| `ui/widgets/adaptive_axis.py` | 坐标轴自适应公共件（§7-B4 · 全 App 唯一的"刻度/量程"来源）。 | 17 | 396 |
| `ui/widgets/annotation_catalog.py` | 画线类型的**目录**（v6.24 · §7-B8 R10/R11）—— **零 Qt、纯数据**。 | 7 | 118 |
| `ui/widgets/annotation_decos.py` | 画线类型的**附属图元**（v6.25 · §7-B8 R11）—— 档位 / 标签 / 箭头头这类"衍生画法"。 | 20 | 342 |
| `ui/widgets/annotation_draw_session.py` | 「在图上点出来」的**绘制会话**（v6.26 · §7-B9 STEP 1）—— 纯交互状态机，零业务。 | 1 | 138 |
| `ui/widgets/annotation_icons.py` | 画线类型的**图标绘制**（v6.24 · §7-B8 R10）—— 纯矢量、**不引入任何图片资源**。 | 3 | 133 |
| `ui/widgets/annotation_items.py` | 标注的**可复用图元小件**（v6.25 · §7-B8 R11）—— 与具体画线类型**无关**的底层零件。 | 14 | 261 |
| `ui/widgets/annotation_layer.py` | 用户标注交互层（§7-B3 ④ · P6）—— 画线 / 选中 / **逐个独立删除**。 | 1 | 612 |
| `ui/widgets/annotation_layouts.py` | 画线类型的**落点 / 回读 / 规范化**（v6.29 · §4 体积铁律的拆分，非新能力）。 | 36 | 360 |
| `ui/widgets/annotation_shapes.py` | 画线类型的**图元规格表**（v6.25 · §7-B8 R11「30+ 类型」落地）。 | 23 | 297 |
| `ui/widgets/annotation_tiles.py` | 画线类型目录的**可视件**（v6.24 · §7-B8 R10/R11）。 | 4 | 175 |
| `ui/widgets/backtest_export.py` | 📐 回测结果导出（1.22 · 自 `ui/views/backtest.py` 拆出，§9-L 体积债）。 | 6 | 159 |
| `ui/widgets/backtest_flow.py` | 📐 回测「运行流程」（1.22 自 `ui/views/backtest.py` 拆出 · §9-L 第二批后半）。 | 2 | 436 |
| `ui/widgets/backtest_history_ui.py` | 🗂 运行历史「版式 + 渲染」（§7-A4 · v1.37 立 · **v1.46 按样板重做**）。 | 9 | 664 |
| `ui/widgets/backtest_panes.py` | 📐 回测页「编辑卡片 + 配置抽屉」（1.22 · 样板 A 的 L3 层 · §9-L 拆分）。 | 9 | 460 |
| `ui/widgets/backtest_preview.py` | 回测页的**只读回放 / 复用参数 / 手动存档**（★2.04 / P2 拆件）。 | 1 | 101 |
| `ui/widgets/backtest_report.py` | 回测结果报告图 —— 单页 PNG「一图看懂」(v5.15 · §7-A2)。 | 6 | 239 |
| `ui/widgets/backtest_result.py` | 📐 回测「结果区」（L0 主角 · 1.22 自 `ui/views/backtest.py` 拆出 · §9-L 第二批）。 | 2 | 492 |
| `ui/widgets/backtest_strategy.py` | 📐 回测「策略库桥接」（1.22 自 `ui/views/backtest.py` 拆出 · §9-L 第二批后半）。 | 1 | 265 |
| `ui/widgets/backtest_summary_bar.py` | 📐 回测页「配置摘要条」（1.22 · 样板 A · 渐进披露的 L2 层）。 | 1 | 128 |
| `ui/widgets/backtest_xlsx.py` | 📊 回测结果导出为 .xlsx（§7-A2 · v1.36）—— 用 openpyxl **内嵌真正的图表**。 | 6 | 136 |
| `ui/widgets/breadth_chart.py` | 📊 M3 图表的**显示选项目录**（★1.73 起：图本体已搬到 `ui/widgets/breadth_rows.py`）。 | 0 | 25 |
| `ui/widgets/breadth_flow.py` | 📊 M3「广度统计」—— 运行流程（范围解析 / 扫描 / ⚡增量 / ⟳全量重算 / 区间切片 / 指数链）。 | 1 | 979 |
| `ui/widgets/breadth_items.py` | 📋 M3「统计项」面板：一行一个**判定变量**（★1.73 / §7-B16 期 1）。 | 2 | 190 |
| `ui/widgets/breadth_layout.py` | 📊 M3「广度统计」—— 版式装配（§7-B1/B2 主案 E 节 · 样板 A，与 M2 `scan_layout` 同款） | 5 | 490 |
| `ui/widgets/breadth_plan_flow.py` | M3「多方案」流程（★1.77 从 `breadth_flow` 拆出 · RULES §4 拆件候选①）。 | 1 | 301 |
| `ui/widgets/breadth_relation_flow.py` | M3「与指数的关系」视图流程（★1.77 从 `breadth_flow` 拆出 · 拆件候选①）。 | 1 | 184 |
| `ui/widgets/breadth_result.py` | 📊 M3「广度统计」—— 结果区状态（空态 / 忙碌态；L0 的图表本体在 `breadth_rows.BreadthRowsChart`）。 | 1 | 58 |
| `ui/widgets/breadth_rows.py` | 📊 M3「多统计项」：**多行小图**（每项一行：柱 + 5 周均线）+ 底部固定指数副图（★1.73 / §7-B16 期 1）。 | 2 | 421 |
| `ui/widgets/calendar_heatmap.py` | GitHub 风格「每日净额日历热力图」(Dashboard · C1)。 | 1 | 260 |
| `ui/widgets/chart_host.py` | 图表宿主「多窗格」（§7-B3 B② · P2）。 | 2 | 447 |
| `ui/widgets/chart_layers.py` | 「图层协议」的公共件（§7-B3 D4 · v6.7）。 | 3 | 77 |
| `ui/widgets/chart_pane.py` | 图表宿主的「单个窗格」最小抽象（§7-B3 B② · P0）。 | 1 | 107 |
| `ui/widgets/chart_style.py` | 图表外观与常用绘制的唯一收敛点 (v5.12 · §9-O7)。 | 12 | 238 |
| `ui/widgets/chip_mru.py` | 工具行 chips 的「最近使用优先」解析（v6.21 · §7-B6 STEP 3c）—— **纯函数、零 Qt、零状态**。 | 6 | 85 |
| `ui/widgets/condition_gate.py` | ② 买卖「条件组 Gate」控件 (v2) —— 支持多条件积木行 + 满足计数。 | 2 | 289 |
| `ui/widgets/custom_widgets.py` | — | 24 | 781 |
| `ui/widgets/desk_annotations.py` | ✎ 用户标注（画线）行为（1.23 自 `ui/views/trading_desk.py` 拆出 · §7-B6 STEP 6）。 | 1 | 152 |
| `ui/widgets/desk_chips.py` | 工具行 chips（"最近使用优先"）（1.23 自 `ui/views/trading_desk.py` 拆出 · §7-B6 STEP 6）。 | 1 | 228 |
| `ui/widgets/desk_data.py` | 行情取数与口径（周期 / 复权 / 分钟档位）（1.23 自 `ui/views/trading_desk.py` 拆出 · §7-B6 STEP 6）。 | 1 | 585 |
| `ui/widgets/desk_formula.py` | ƒ 用户公式：编辑 / 编译 / 资产化 / 互送（1.23 自 `ui/views/trading_desk.py` 拆出 · §7-B6 STEP 6）。 | 1 | 409 |
| `ui/widgets/desk_layers.py` | 行情工作台的"渲染装配"：显示用行情 + 统一图层 + 自适应坐标轴（1.23 自 `ui/views/trading_desk.py` 拆出 · §7-B6 STEP 6）。 | 1 | 340 |
| `ui/widgets/desk_layout.py` | 行情工作台的**版式装配**：顶栏两行 + 左栏（图标轨 + 四页）（1.23 自 `ui/views/trading_desk.py` 拆出 · §7-B6 STEP 6）。 | 3 | 625 |
| `ui/widgets/desk_panel.py` | 行情工作台的「图标轨 + 分页面板」（v6.21 · §7-B6 STEP 4）—— **纯容器、零业务**。 | 3 | 220 |
| `ui/widgets/desk_readout.py` | 读数条的业务翻译（1.23 自 `ui/views/trading_desk.py` 拆出 · §7-B6 STEP 5/6）。 | 1 | 80 |
| `ui/widgets/desk_watch.py` | ★ 自选股（1.23 自 `ui/views/trading_desk.py` 拆出 · §7-B6 STEP 6；v6.24 加分组 · §7-B8 R1/R2）。 | 1 | 486 |
| `ui/widgets/download_bar.py` | 主窗口底部的**下载状态条** (v1.43 · §7-B11) —— 后台下载时的唯一全局可见出口。 | 1 | 193 |
| `ui/widgets/download_queue_panel.py` | 下载队列面板 (v1.43 · §7-B11) —— **主窗口内的浮层**，不是独立窗口。 | 4 | 332 |
| `ui/widgets/draw_overlay.py` | 公式叠层的**唯一渲染器**（§7-B3 B③ · P3）。 | 4 | 238 |
| `ui/widgets/formula_hub_panel.py` | ƒ 函数总库的**统一浮窗**（★1.61 / §7-B16 · H7「用户实测后重做」）。 | 2 | 160 |
| `ui/widgets/function_segments.py` | ① 多函数段编辑器 (阶段A) —— 把单段粘贴升级为「多段共享变量池」。 | 1 | 156 |
| `ui/widgets/gate_hint.py` | 🚦 三道闸的**"看得见"部件**（★1.74 / §7-B16 期 2）。 | 3 | 224 |
| `ui/widgets/history_kinds.py` | 「🗂 运行历史」的 kind **声明式注册表**（§7-A4 · v1.46 重做）。 | 18 | 134 |
| `ui/widgets/history_parts.py` | 运行历史页的**纯显示小件**（★2.04 / P2 拆件）。 | 3 | 169 |
| `ui/widgets/hub_editor.py` | ƒ 函数总库的**编辑器**（★1.61 / §7-B16 · H2 · 方案书 `docs/plans/done/HUB.md`）。 | 1 | 165 |
| `ui/widgets/hub_float_list.py` | 浮窗里的**统一列表**：本页方案 + 函数资产（★1.61 / §7-B16 · H7「用户实测后重做交互」）。 | 1 | 387 |
| `ui/widgets/hub_flow.py` | ƒ 函数总库的**行为层**（★1.61 / §7-B16 · H2；约定同 scan_flow：状态在页面，行为在这）。 | 3 | 251 |
| `ui/widgets/hub_latest.py` | 「总库有更新版」的**提示 + 显式更新**（★1.61 / §7-B16 H4 · 两处桥接共用一份口径）。 | 1 | 81 |
| `ui/widgets/hub_layout.py` | ƒ 函数总库的**版式装配**（★1.61 / §7-B16 · H2 · 设计稿 = `design/1.60-formula-hub/a-双栏管理台`）。 | 7 | 316 |
| `ui/widgets/indicator_panes.py` | 行情页「内置副图」的内容构建（v6.8 从当时的 `ui/views/market.py` 搬出，SRP）。 | 2 | 36 |
| `ui/widgets/kpi_card.py` | 小号 KPI 卡的**唯一实现**（★R1：从 `scan_result` 抽出来，给参数研究页共用）。 | 3 | 49 |
| `ui/widgets/layer_model.py` | 配方库 / 图层的**单一真源**（v6.24 · §7-B8 R13/R5）—— **零 Qt、纯数据 + 纯规则**。 | 4 | 337 |
| `ui/widgets/portfolio_changes.py` | 🧺 组合「调仓记录」的**列表渲染件**（★1.90 从富文本改成控件，用户 2026-10-28： | 4 | 189 |
| `ui/widgets/portfolio_parts.py` | 🧺 组合页的**零件**（★1.90 从 `ui/views/portfolio_view.py` 拆出：那页已 1391 行）。 | 4 | 106 |
| `ui/widgets/readiness_flow.py` | 「就绪度体检 + 补齐数据」的**两页共用控制器**（§7-B1/B2 主案 D6 · v6.39）。 | 5 | 528 |
| `ui/widgets/relation_card.py` | 🧮 M3「与指数的关系」量化卡（★1.75 / §7-B16 期 3 · 设计稿 D 页右半）。 | 1 | 227 |
| `ui/widgets/relation_chart.py` | 🔗 M3「与指数的关系」两张小图（★1.75 / §7-B16 期 3）。 | 4 | 150 |
| `ui/widgets/review_charts.py` | 复盘页的**图表渲染（日历 / 月度 / 持仓时长）**（1.25 自 `ui/views/review.py` 拆出 · §9-L）。 | 1 | 244 |
| `ui/widgets/review_editor.py` | 复盘页的**当日清单 + 编辑卡 + 孤儿单缝合**（1.25 自 `ui/views/review.py` 拆出 · §9-L）。 | 1 | 310 |
| `ui/widgets/review_flow.py` | 复盘页的**筛选 + 时间导航 + 视图刷新**（1.25 自 `ui/views/review.py` 拆出 · §9-L）。 | 1 | 197 |
| `ui/widgets/review_layout.py` | 复盘页的**版式装配**（1.25 自 `ui/views/review.py` 拆出 · §9-L 拆分 + §9-U 收口）。 | 1 | 310 |
| `ui/widgets/review_playback.py` | 复盘页的**交易回放渲染**（1.25 自 `ui/views/review.py` 拆出 · §9-L）。 | 1 | 238 |
| `ui/widgets/scan_enrich.py` | 扫描后**分批补全**行业/估值（★v6.74 · §7-B13）—— 用户 2026-09-27 拍板。 | 2 | 149 |
| `ui/widgets/scan_enrich_flow.py` | 扫描后的**行业 / 估值补全调度**（★2.04 / P2 拆件）。 | 1 | 175 |
| `ui/widgets/scan_flow.py` | 🌐 M2「全市场筛选」—— 运行流程（范围解析 / 后台线程 / 进度回执 / 切日期 / 跳行情）。 | 3 | 694 |
| `ui/widgets/scan_layout.py` | 🌐 M2「全市场筛选」—— 版式装配（§7-B1/B2 主案 E 节 · 样板 A） | 5 | 518 |
| `ui/widgets/scan_result.py` | 🌐 M2「全市场筛选」—— 结果渲染（KPI 行 + 结果表 + 空态）。 | 4 | 283 |
| `ui/widgets/scan_strategy_bridge.py` | M2/M3「筛选方案」载入 / 存为 / 管理 桥接（§7-B12 P3）。 | 1 | 160 |
| `ui/widgets/screenshot_gallery.py` | — | 1 | 172 |
| `ui/widgets/settings_render.py` | 设置项**控件工厂**（★v6.73 / §7-B13 · S2-0）—— "类型 → 控件" 的**唯一映射**。 | 6 | 80 |
| `ui/widgets/styles.py` | 全站**样式唯一定义处**（★1.59 / §7-B14 批3 自 `custom_widgets.py` 原样搬出）。 | 12 | 496 |
| `ui/widgets/summary_chip.py` | 摘要条胶囊（chip）的**唯一样式来源**（★1.64 · M2/M3 视觉重塑 STEP 1）。 | 3 | 41 |
| `ui/widgets/sweep_chart.py` | 参数稳健性研究（§7-B15）· 图表区四件（SW-6）。 | 11 | 976 |
| `ui/widgets/sweep_compare.py` | 🧪 参数研究 —— **研究快照 A/B 对比**（★1.79 / §7-B15 第二轮③ · 用户 2026-10-16「就开 B15 第二轮」）。 | 5 | 152 |
| `ui/widgets/sweep_cost.py` | 🧪 参数研究 —— **成交成本与成本敏感性**（★1.79 / §7-B15 第二轮① · 用户 2026-10-17 重做）。 | 4 | 346 |
| `ui/widgets/sweep_form.py` | 参数稳健性研究（§7-B15）· 左栏研究设置面板（SW-5）。 | 1 | 630 |
| `ui/widgets/sweep_input.py` | 🧪 参数研究 —— **输入侧**（★1.66 拆件：页面刷新 + 策略/标的联动）。 | 1 | 197 |
| `ui/widgets/sweep_parts.py` | 🧪 参数研究 —— **表单构件原语**（★R2 拆件）。 | 9 | 100 |
| `ui/widgets/sweep_pool.py` | 池化（组合层）—— **设置进「研究设置」，结果进结果区**（★1.87 重做）。 | 7 | 290 |
| `ui/widgets/sweep_regimes.py` | 🧪 参数研究 —— **切块与区间**（★R3 拆件：时间轴卡 + 区间预设的组织 + 「⟳ 重新切块」）。 | 2 | 187 |
| `ui/widgets/sweep_results.py` | 🧪 参数研究 —— **结果装配与渲染**（★R0 拆件；原 `ui/views/param_sweep.py` 的"统计装配 + 展示 + 存快照"）。 | 1 | 352 |
| `ui/widgets/sweep_run_form.py` | 🧪 参数研究 —— **运行面板**（★R2 拆件；左栏第 ⑤ 步「交易次数门槛」+ 第 ⑥ 步「运行」）。 | 1 | 113 |
| `ui/widgets/sweep_snap_card.py` | 🧪 参数研究 —— ⑨ **研究快照卡**（★R5b · 设计稿 p2 的 `#p2-hist`）。 | 2 | 294 |
| `ui/widgets/symbol_pick.py` | 选标的的**共用件**（★用户 2026-10-01 追加需求：*"标的要像 M1 一样 —— 手输 + 额外一个「选择」按钮， | 6 | 142 |
| `ui/widgets/watch_row_delegate.py` | 自选清单的**行绘制**（v6.24 · §7-B8 R15 / 2b 余项）：`名称 · 代码（右对齐）· 涨跌列`。 | 3 | 115 |
| `ui/widgets/watch_sort_list.py` | 自选清单的**拖拽排序列表**（v6.24 · §7-B8 R15）—— 用"三道闸"防误触。 | 1 | 70 |
| `ui/widgets/yearly_review.py` | — | 1 | 124 |
| `ui/workers.py` | 全 app 的 QThread 门面（★2.04 / P2 拆件后只做再导出）。 | 0 | 54 |
| `ui/workers_backtest.py` | 回测 / 参数扫描 / 组合池化类 QThread（★2.04 / P2 拆件）。 | 3 | 150 |
| `ui/workers_core.py` | 任务竞态守卫（★2.04 / P2 拆件）。 | 1 | 34 |
| `ui/workers_download.py` | 批量下载 / 网络自检 / 缓存清理 / 更新检查类 QThread（★2.04 / P2 拆件）。 | 6 | 526 |
| `ui/workers_imports.py` | 期货交割单解析 worker（★2.04 / P2 拆件）。 | 1 | 28 |
| `ui/workers_scan.py` | 扫描 / 成分股 / 就绪度 / 日历类 QThread（★2.04 / P2 拆件）。 | 7 | 207 |
| `ui/workers_sync.py` | 同步类小 worker（★2.04 / P2 拆件）。 | 6 | 158 |
| `ui/workers_throttle.py` | 下载节流 / 交易日历注入的**无 Qt 辅助件**（★2.04 / P2 拆件）。 | 4 | 98 |

> 共 233 个 .py 文件。
