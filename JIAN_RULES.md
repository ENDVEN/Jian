# Jian — 开发规范与上下文记忆 (文档 v5.11)

> **本文档是"给未来的你看"的唯一权威记忆**。功能开发前先读：
> §11 速查表（30 秒找回手感）→ §5 数据契约/铁律 → §4 代码地图 → §6/§7 完成度清单。
> 本文档于 v5.0 全面重排：完成项按模块归类核对，未完成项按**优先级 + 依赖**重新分类。
> v5.1：记录「市场回测·阶段A」落地（多函数段共享池 + 条件组 Gate）。
> v5.2：记录「市场回测·阶段B」落地（引擎风控离场器 + exit_reason 全链路）。
> v5.3：记录「市场回测·阶段C」落地（大盘指数 regime 门控）。
> v5.4：记录「单股回测 UX 硬化」（指数预设扩充 / 防滚轮 / 角标弱化 / 编辑区滚动）。
> v5.5：**全仓逐文件通读核对产出** —— 修正 §4 目录树遗漏；新增 §9-F~L 七项实测发现的技术债
> （年度面板口径漂移、花名册半成功覆写风险、UI 边界松动等）；新增 **§11 速查表**。
> v5.6：修「风控行箭头与条件组不一致 + 上箭头只有右半边可点」（根因=Qt 复合控件半截 QSS，
> 见 §10-9 / §6.6-U5）；回测区间下沿 2018→**2016** 并新增近3个月/近6个月/近5年三档（§5.3-H）。
> v5.7：**甲方案收尾** —— 修 §9-F 年度面板净额口径 / §9-G 花名册半成功覆写 / §9-K 注释失真 /
> §9-A 版本号滞后（APP 升 **v1.4.0** 并同步 `version.json`）；
> 新增 **C1 Dashboard 每日净额日历热力图**（`ui/widgets/calendar_heatmap.py`，GitHub 风格 53×7）。
> v5.8：**§7-A3 数据管理页落地 + §9-H 架构债清账** —— 数据湖补删除/清点原语；
> 同步逻辑收敛到 `data/sync_service.py`（增量合并 + 温柔抓取 ThrottlePolicy 防封 IP）；
> UI 线程统一到 `ui/workers.py`；第 6 导航页「🗄 数据管理」+ 批量预下载弹窗。
> APP 版本升 **v1.4.1**（`config/settings.py` 与 `version.json` 已同步）。
> v5.9：**对 v5.8 的独立复查（第二双眼睛）** —— 因会话中更换过语言模型，把上一批改动
> 当作陌生代码重新审查，发现并修复 4 个隐患（见 §9-M）：①增量"时效滞后一天" ②休市空增量
> 误判失败+白重试 ③数据起点 2010→2016 的静默缩水回归 ④扫描线程/关窗线程的竞态与崩溃风险。
> 全部以冒烟测试断言固化后回写本文件。
> v5.10：**数据管理页 UX 加固（用户实测反馈驱动）** —— 修"勾选框点击后直接消失"
> （根因：勾选列 ResizeToContents 算出≈0 宽，指示器不可见/点不中）+ 过滤下单元格行错位；
> 「清空分区」从主操作行**隔离**到左侧栏底部并要求键入「清空」二次确认；按钮/文案改用户语言
> （"增量更新"→「更新到最新」、"强制全量重拉"→「重新全量下载」）；
> 同步失败**按原因分类提示**，退市股（无数据源）不再被误报为"代码不存在/网络抖动"。
> 详见 §9-N；新增 §10-10 按钮层级与文案铁律。
> v5.11：**勾选框最终重设计** —— v5.10 用"原生 indicator + cellClicked"出现**双重触发**：
> Qt 对 indicator 自动切换一次、cellClicked 又切一次 → 点一次净效果=没点（永远打不出勾），
> 且 `ItemIsSelectable`+`SelectRows` 带来蓝色行高亮。最终方案：**彻底放弃 Qt 原生 checkbox**，
> 第 0 列自绘 ☐/☑ 字符 + 整格点击=唯一切换入口 + `NoSelection`（消除行高亮）。
> 已用 QTest **真实鼠标事件**验证单点/连点/取消均稳定（§9-N1 修订）。
> v5.12：**第二次全仓通读核对（模型切换后的"陌生代码"复查）**。本次**未改任何业务代码**，
> 只做"文档 ↔ 磁盘"的逐项对账，产出 §9-O 系列 10 项发现：
> ① 口径漂移：流水/复盘的「仅盈利/仅亏损」过滤器仍用毛利（O-1）；
> ② 架构债残留：`ui/workers.py` 只收口了"行情同步类"线程，回测/成分股/导入/版本检测
>   4 个 QThread 仍散落在各自文件（O-2）；③ `sync_service` 的 docstring 把数据起点写成
>   2016，与实际的 2010 冲突，是 §9-M3 的**回归隐患**（O-3）；
> ④ 行情页「☁️ 云端同步」恒为全量重拉、与管理页双按钮体验不一致（O-4）；
> ⑤ 回测页同步结果缺竞态守卫（O-5）；⑥ §4 目录树行数/版本号全面过时（O-6）；
> ⑦ 图表样式重复从 2 处变成 3 处（O-7）；⑧ §9-J 小坑确认仍在 + 一处文档描述有误（O-8）；
> ⑨ Dashboard KPI 实为 17 项非 18 项（O-9）；⑩ 复盘页回放 K 线反复全量读 Parquet（O-10）。
> **本节最底部的 §11.6 已据此刷新"下一步推荐顺序"。**
> v5.13：**第一 / 第二梯队全部落地**（用户已批准"筛选改净额"，并明确云端同步语义
> = "本地有数据就更新、没数据就抓取"）。改动清单（全部通过 25 项冒烟断言 +
> 离屏构造主窗口/全部弹窗）：
>   · **O-3** `data/sync_service.py` docstring 起点改回 2010-01-01 并写明"数据窗≠评估窗"；
>   · **O-5** `backtest.py` `_on_synced` / `_on_index_synced` 补竞态守卫（照抄 market.py）；
>   · **O-7** 新增 **`ui/widgets/chart_style.py`**，把**四份**重复的 Pokorny 轴样式与
>     资金/净值曲线绘制收敛为 `apply_pokorny_style` + `plot_equity_curve` 两个函数；
>     （⚠ 通读时漏数了一份：`ui/views/market.py` 也有，且它传的是 **PlotItem** 不是
>     PlotWidget —— 新函数两种类型都兼容）；
>   · **O-2** 三个 UI 线程（`_BacktestRunThread` / `_ConstituentsWorker` /
>     `FuturesImportWorker`）迁入 `ui/workers.py`，改名 `BacktestRunWorker` /
>     `ConstituentsWorker` / `FuturesImportWorker`；§2 表述已改为准确版本；
>   · **O-8** 四项小坑：`review.py` 空数据也刷新时间选择器 / `days=0` 改 `continue` /
>     切年视图清空回放图 / 画廊不再静默丢弃失效截图路径（改为标注「⚠ 已丢失」）；
>   · **O-1（用户拍板）** 流水页 + 复盘页「仅盈利/仅亏损」改为 **净额** 口径，
>     两处下拉加 tooltip 说明口径；
>   · **O-4（用户拍板）** 行情页 `force_sync_cloud` → 改名 `sync_cloud`，
>     `force_full` 恒为 **False**：本地有数据=增量、没数据=全量；
>     新增 `lbl_sync_status` 回执（已是最新 / 已更新新增 N 行 / 同步失败）。
>     "重新全量下载"仍只存在于「🗄 数据管理」页（§10-10 危险动作隔离）。
>     **v5.13 修订**：O-4 新增的同步状态 QLabel 触发了 Qt 布局坑（顶部栏末尾 QLabel
>     会把富余高度全吞掉、标题被拉成 400px），已给 main_splitter 显式 `stretch=1` 根治，
>     固化为 §11.5 第 13 条。
> v5.14：**回测结果导出落地（§7-A2 半程）** —— 用户拍板"**只做导出、不做删除**"，
> 并把「结果历史存档」列为**远期方案**（见 §7-A4，留给后续会话）。
>   · 回测页「K线控制行」右侧新增「导出明细」按钮；
>   · 新增 **`_last_meta` 参数快照**：`start_backtest` 发起瞬间定格 标的/区间/策略名/
>     函数段/参数/买卖表达式/风控/指数门控，导出永远对应当前 `_last_result`，
>     不掺导出瞬间的编辑框内容；
>   · **`_compose_result_csv`**（纯函数，14 项断言全过）= 注释头 + 逐笔明细；
>     `utf-8-sig` 落盘，Excel 可直接打开。
>     ⚠ **v5.16 推翻 v5.14 的"注释头裸写"方案**：裸写会让含英文逗号的函数源码行
>     （如 `STICKLINE(A, B, C, 3, 0), COLORFF0000;`、`MA(C, 5)`）被 Excel/WPS
>     当多列拆开 → 用户实测"第三部分：图形绘制"乱码不可读。正确做法见 v5.16。
> v5.15：**导出升级 · PNG 报告图 + 共享常量上收**（用户拍板：CSV 移除净值行 /
> PNG 加离场原因饼图 / 下拉菜单入口）。
>   · **CSV 精简**：移除 200+ 行「每日净值明细」段 —— 它既是可读性低的主因、又可由
>     引擎用相同参数复现；溯源义务交给『参数 + 逐笔』，净值曲线视觉化由 PNG 承担。
>   · **新增 `ui/widgets/backtest_report.py`**（SRP，218 行，零新增第三方依赖）：
>     单页 PNG 报告图 = 标题（品种/区间/策略）+ KPI 四卡 + 净值曲线 + **离场原因饼图** +
>     参数/风控/指数门控简表；复用 `chart_style.plot_equity_curve`；QWidget 离屏
>     grab() 渲染，中文依赖系统字体（沙箱缺 CJK 字体会显方框，属环境非代码问题）。
>   · **共享常量上收到 `core/backtest.py`**：`EXIT_REASON_LABELS` / `EXIT_REASON_COLORS`
>     / `risk_summary(...)` —— 明细表着色、CSV 表头、PNG 图例与饼图色彩**三处同源**，
>     禁止任何 UI 文件再各写一份（§9-O7 教训）。
>   · **下拉菜单取代单按钮**：`📄 导出 CSV 明细…` / `🖼 导出结果图 PNG…`，
>     未来加 XLSX 只需在 `_export_menu` 新增 action。
>   · **16 项断言全过**（CSV 无净值段且数据行=逐笔数、PNG 尺寸 1120×660、菜单结构、
>     共享常量、空 equity 容错）。报告图单页 1120×660。
> v5.16：**CSV 导出兼容性修复（用户用 WPS 实测反馈）** —— "函数源码第三部分含英文
> 逗号的行在表格软件里被拆列成乱码"。
>   · 根因：v5.14/5.15 把"注释/表头行"**裸写**（不走 csv 转义），而函数源码里
>     `STICKLINE(..., DYN_INDEX, DYN_INDEX, 3, 0), COLORFF0000;` 这类行含英文逗号，
>     Excel/WPS 打开时会当成多列拆分，表现为"图像绘制段看不到内容"。
>   · 修法：`_compose_result_csv` 里**每一行都作为单格字段走 csv.writer**
>     （含逗号行自动加引号 → 表格软件还原为单格；不含逗号行保持裸写；空行用
>     `writerow([])` 产生真·空行，不再出现 `""` 假空行）。
>   · 校验：**9 项断言** —— csv.reader 严格重解析整份文件：表头区每非空行 = 1 格、
>     逐笔区 = 8 列 × 成交数、中文离场原因可解析、无 `""` 假空行。
>   · **导出文件对任何遵循 CSV 规范的软件（Excel / WPS / 编辑器）均适配**。
> v6.0（规划定稿）：**§7-B3 公式统一绘图（引擎级 · 最高优先级 P0 · 无代码变更）** ——
> 用户复盘发现"函数里 STICKLINE/DRAWICON 画出的指标从没出现过"，根因是 `program.py`
> 长期 SKIP 绘图语句（历史 §7-B3 欠账），而 CSV/PNG/回测K线都没有能画它的底层管线。
> 用户定稿：以"**引擎产出统一绘图 IR + 唯一渲染器 OverlayPainter**"为长远架构，
> 避免未来优化各图表时逐图一对一手改；M0 契约层 / M1 求值层 / M2 渲染+回测页 /
> M3 收尾 / M4 远期全图复用。完整规格与验收见 §7-B3 主案，优先级见 §11.6。
> 状态图例：`[x]` 完成 · `[~]` 部分/半成品 · `[ ]` 未开始/占位。

---

## 1. 项目定位

- **项目名:** Jian（专业量化交易复盘与分析系统），桌面端（PyQt6）。
- **产品形态:** 期货交割单驱动的**复盘主链路**（交易流水/深度复盘/资金表现）
  + **股票行情浏览与市场回测**（扬长避短，见 §5.3-C）。
- **铁三角理念:** ① 代码高内聚低耦合（SRP，严禁大而全的模块）；
  ② 程序本体与用户数据**物理隔离**（数据主权）；③ 操作**绝对幂等/防呆/防手残**。

## 2. 技术栈与关键设施（与代码现状对齐）

| 层 | 选型 | 落点 |
|---|---|---|
| UI | PyQt6 | `ui/`（全部组件继承自 PyQt6，非 PySide6） |
| 图表 | pyqtgraph + 自研 `CandlestickItem` | `ui/widgets/custom_widgets.py`；全局强制抗锯齿（`main.py`） |
| 行情源 | AkShare：A股日线 **新浪主源 + 东财兜底**；期货 `futures_main_sina` 主连 | `data/akshare_feed.py` |
| 指标 | 纯 Pandas 向量化 `TAEngine`（MA/BOLL/MACD） | `core/indicators.py` |
| 公式 | 通达信方言 DSL：词法/语法/运行时/整段程序 | `core/formula/*` |
| 业务库 | SQLite，`INSERT OR IGNORE` 幂等 + MD5 确定性主键 | `core/database.py` |
| 时序湖 | pyarrow Parquet 分区数据湖（DataLake） | `data/market_db.py` |
| 偏好/策略库 | JSON 原子写（tmp + os.replace） | `core/preferences.py`、`data/strategy_store.py` |
| 并发 | 耗时 I/O 一律 QThread Worker | ✅ v5.13 已收口：`ui/workers.py` 是全 app **唯一的 QThread 定义处**（ScanWorker / SyncWorker / SingleSyncWorker / BacktestRunWorker / ConstituentsWorker / FuturesImportWorker），页面与弹窗一律不自造线程类。**唯一例外**：`core/updater.py` 的 `UpdateCheckerThread` 属 core 层（版本检测不是 UI 职责），不搬进 ui/ |

**用户数据目录（物理隔离，勿在仓库存业务数据）:** `~/.jian_data/`
（`jian_trades.db`、`preferences.json`、`backtest_strategies.json`、`data_lake/`、`screenshots/`）。

## 3. 产品全景：5 页导航 + 弹窗（已实现 UI 总览）

导航路由极简（`ui/main_window.py` 仅做组件装配与事件分发，不含业务逻辑）：

| 导航页 | 类（文件） | 完成度 | 能力摘要 |
|---|---|---|---|
| 📊 资金与表现 | `DashboardView` | [x] | **17 项**净额口径 KPI 网格（v5.12 实测，非 18 项，见 §9-O9）+ **每日净额日历热力图(53×7, 可切年份)** + 净值曲线 + 单笔净额分布直方图 |
| 📝 交易流水 | `RecordsView` | [x] | 11 列明细表、五维过滤器、孤儿黄条、CSV 全量导出、时间精度切换 |
| 💡 深度复盘 | `ReviewView` | [x] | 月/年双模态、月历热力图、累计盈亏/交易回放/资金K线/持仓时长四页签、孤儿手工补录、截图画廊 |
| 📈 市场行情 | `MarketView` | [x] | 代码查询、数据湖优先+联网兜底、K线+MA/BOLL+量+MACD、趋势线(不持久) |
| 📐 市场回测 | `BacktestModule` | [~] | M1 单股回测完整；M2 全市场筛选 / M3 广度统计为 **ComingSoon 占位** |
| 🗄 数据管理 | `DataManagerView` | [x] | 数据湖 8 分区清单(行数/日期范围/体积/更新时间)、搜索过滤、勾选删除、清空分区(隔离+键入确认)、「更新到最新」「重新全量下载」、批量预下载 |

| 弹窗 | 文件 | 完成度 | 摘要 |
|---|---|---|---|
| 期货交割单导入 | `dialogs/import_futures.py` | [x] | QThread 后台解析；inserted/ignored 防重报告；孤儿提醒；时间精度强选 |
| 手工录入 | `dialogs/manual_entry.py` | [x] | 账户仅真实列表+可新建；开仓时间选填(勾选才生效)；LONG/SHORT |
| 账户/策略管理 | `dialogs/list_manager.py` | [x] | 通用删除列表（带危险确认） |
| 批量预下载 | `dialogs/bulk_download.py` | [x] | 来源：指数预设(29)/指数成分股/粘贴代码列表/全市场A股；参数：起点/间隔/抖动/熔断/跳过已最新；进度+失败清单+中断 |

---

## 4. 目录结构与代码地图（v5.12 与磁盘逐文件核对，行数为实测值）

```text
Jian/
├── main.py              # 34行 唯一启动入口：建数据目录、pg 抗锯齿、装配 MainWindow
├── sync_roster.py       # 47行 独立花名册同步脚本(__main__)：A股+期货名册→DB market_symbols，纯手动运行
├── requirements.txt     #     PyQt6 / pyqtgraph / pandas / numpy / pyarrow / akshare / openpyxl
├── version.json         #     ⚠ 远端版本探测用；必须与 settings.APP_VERSION 同步（见 §9-A）
├── JIAN_RULES.md        #     本文件
├── .gitignore           #     已忽略 __pycache__ / screenshots / *.db / 实例*.xlsx / 实例函数.txt 等隐私
├── config/
│   └── settings.py      # 51行 全局常量：APP_NAME、APP_VERSION=1.4.1(与 version.json 同步)、颜色、
│                        #      INITIAL_CAPITAL=1e6、USER_DATA_DIR=~/.jian_data、UPDATE_CHECK_URL
├── models/
│   └── trade.py         # 103行 TradeRecord dataclass —— 全链路唯一闭环交易契约（字段见 §5.1）
├── core/                # 【纯计算层：零 UI 零网络】
│   ├── engine.py        # 158行 DataEngine 中央门面：UI唯一数据入口，编排解析→落库→报告；
│   │                    #      reload/clear/delete/stitch/coverage + search_symbol/list_stock_symbols
│   ├── database.py      # 437行 DatabaseManager：trades+open_legs+import_coverage+coverage_gaps
│   │                    #      +market_symbols 五表 DAO；INSERT OR IGNORE；旧库自动迁移(备份/加列)
│   ├── indicators.py    #  66行 TAEngine：MA(5/20/60)/BOLL/MACD 向量化注册表
│   ├── analyzer.py      # 110行 TradeAnalyzer：净额口径统计(raw_report) + 持仓时长三级口径聚合
│   ├── backtest.py      # 289行 BacktestEngine/BacktestTrade/BacktestResult：LONG-only 单股回测；
│   │                    #      条件为真即触发 + 阶段B风控离场器(risk参数/exit_reason)
│   │                    #      + 离场原因 标签/配色/risk_summary 共享常量（v5.15 上收于此）
│   ├── formula/         # 695行 通达信 DSL 共 5 文件（详见 §5.2）
│   │   ├── __init__.py  #  39行 FormulaEngine 门面：validate/parse/evaluate/signal
│   │   ├── tokens.py    #  67行 词法
│   │   ├── parser.py    # 178行 递归下降 → AST（优先级 NOT > 比较 > AND > OR）
│   │   ├── runtime.py   # 298行 EvalContext + FUNCTIONS(17)/ARITY 注册表
│   │   └── program.py   # 113行 整段程序：assign/output/skip 三态 + execute_programs 共享变量池
│   ├── utils.py         # 230行 无副作用纯函数：品种去根/诚实时间/持仓秒/交易日跨度/格式化/align_by_date
│   ├── preferences.py   #  85行 Preferences 单例：~/.jian_data/preferences.json（唯一键 time_precision）
│   └── updater.py       #  62行 UpdateCheckerThread(QThread)：远端 version.json 异步比对，静默失败
├── data/                # 【数据获取/存储层】
│   ├── data_feed.py     # 827行 CFMMC 解析：纯函数无副作用；成交/持仓/结算月报三页签；
│   │                    #      BaseTradeParser+PARSER_REGISTRY(扩展预留，无人调用，见 §9-K)；
│   │                    #      FIFO 缝合与孤儿分配；漏月检测
│   ├── akshare_feed.py  # 254行 AkShareFeed：A股新浪/东财兜底、期货主连、指数日线(阶段C)、花名册、清洗路由
│   │                    #      ⚠ 供 UI 引用的仅限纯函数：is_stock_code/is_index_symbol/INDEX_PRESETS(29项)
│   ├── market_db.py     # 201行 DataLakeManager：parquet 分区存取(exists/save/load/get_latest_date)
│   │                    #      + v5.8 清点删除(delete_data/clear_zone/list_zone/inventory 只读footer/zone_stats)
│   ├── sync_service.py  # 224行 MarketSyncService(v5.8)：行情同步唯一门面 = 增量合并去重 + 温柔抓取
│   │                    #      ThrottlePolicy(间隔/抖动/重试/熔断/断点续传)；纯 Python 零 Qt 依赖
│   │                    #      + friendly_fetch_message / short_fetch_reason 失败分类文案
│   └── strategy_store.py# 139行 StrategyStore：回测策略 JSON CRUD + 每标的 metrics 档案(同股对比)
└── ui/                  # 【表现层：只做展示，禁 SQL/爬虫】(见 §3)
    ├── main_window.py   # 233行 JianMainWindow：6页装配 + 弹窗调度 + render_all_data + CSV导出 + 漏月告警
    ├── workers.py       # 153行 全 app 唯一的 QThread 定义处(v5.13)：ScanWorker(扫湖)/
    │                    #      SyncWorker(批量)/SingleSyncWorker(单只)/BacktestRunWorker(回测)/
    │                    #      ConstituentsWorker(成分股)/FuturesImportWorker(交割单)
    ├── widgets/         # custom_widgets.py(119 K线图元/NoWheel控件族/悬浮删除/SPINBOX_QSS)
    │                    #   / screenshot_gallery.py(161) / yearly_review.py(118)
    │                    #   / condition_gate.py(295 买卖条件组Gate)
    │                    #   / function_segments.py(121 多段函数编辑器)
    │                    #   / calendar_heatmap.py(245 Dashboard 每日净额日历热力图, C1)
    │                    #   / chart_style.py(63 ★v5.13 图表样式唯一收敛点，见 §9-O7)
    │                    #   / backtest_report.py(218 ★v5.15 PNG 报告图渲染, 见 §7-A2)
    ├── dialogs/         # import_futures(169) / manual_entry(192) / list_manager(48)
    │                    #   / bulk_download(399 批量预下载)
    └── views/           # dashboard(259) / records(361) / review(1119) / market(346)
                         #   / backtest_module(83) + backtest(1427, ⚠ 超 1400 待拆分, §9-L)
                         #   / data_manager(473 🗄数据管理, v5.8)
```

**体积红黑榜（v5.15 实测，>400 行即需警惕继续堆功能）：**
`ui/views/backtest.py 1427` > `ui/views/review.py 1119` > `data/data_feed.py 827` >
`ui/views/data_manager.py 473` > `ui/views/records.py 361` > `ui/views/market.py 346` >
`ui/widgets/backtest_report.py 218`（新模块）、`ui/widgets/condition_gate.py 295`。
（v5.15 增量：backtest +10（入口/方法壳，PNG 渲染逻辑全在新模块）、
core/backtest +33（离场原因标签/配色/risk_summary 共享常量）。）

---

## 5. 数据契约、铁律与关键口径（改代码前必读，防回归）

### 5.1 TradeRecord 字段语义（`models/trade.py` 为准）

| 字段 | 类型 | 语义/约束 |
|---|---|---|
| `trade_time` | datetime | **唯一主时间锚点** = 平仓/盈亏实现日，恒为纯日期 00:00:00，禁止自动填充时分 |
| `account` / `symbol` / `direction` | str | 账户；合约代码；LONG/SHORT（方向四象限由买卖动作推导，不单独存） |
| `lots` | int | 手数 |
| `net_profit` / `commission` | float | 平仓盈亏(毛) / 手续费；**净额 = net_profit − commission** |
| `internal_id` | str | MD5(账户_单号_交易日期_数量) 确定性哈希；FIFO 切片追加 `#索引` 盐防撞 —— 幂等基石 |
| `trade_id` | str | 展示用 `M_{uuid8大写}` |
| `entry_time` | datetime? | 开仓腿真实时刻（可空；孤儿/纯日期为 None，绝不填 0） |
| `entry_price`/`exit_price` | float? | 开/平仓价（待缝合孤儿 entry_price=None，UI 显示 —） |
| `entry_fill_time`/`exit_fill_time` | str | 原生成交时刻 `HH:MM:SS`（原始数据，完整入库） |
| `time_source` | str | DATE_ONLY / STATEMENT / MANUAL（时刻来源可追溯） |
| `multiplier` | float | 合约乘数：由 `成交额/(价×手数)` 反推（IF=300/IM=200），非近整数则 0 |
| `is_orphan` | int | 1=开仓腿缺失待缝合（CFMMC 专属概念，手工录入不卷入） |
| `strategy_tag`/`entry_reason`/`reflection`/`screenshot_paths` | str | 复盘语义字段；截图路径以 `;` 拼接 |

**DB 附表（`core/database.py`）:**
`trades`（主表）、`open_legs`（未平开仓腿，跨月延续，全量覆写幂等）、
`import_coverage` + `coverage_gaps`（月度资金勾稽 + 用户确认跳过月）、`market_symbols`（花名册）。
**数据湖 zones（`market_db.py`）:** `kline_daily`、`kline_min`(预留)、`index_daily`、`macro_eco`、
`fin_report`、`valuation`、`sentiment`、`hot_topic`。

### 5.2 通达信公式引擎（`core/formula/`）

- 分层：`tokens`(词法) → `parser`(递归下降→AST) → `runtime`(函数求值) → `program`(整段程序)。
- 门面 `FormulaEngine`：`validate/parse/evaluate/signal`；报错分 `FormulaCompileError`/`FormulaEvalError`。
- 内置函数（16 个）：MA EMA SMA REF HHV LLV COUNT SUM IF EVERY CROSS BARSLAST ABS MAX MIN
  **COUNT_TRUE**；多输出内置 MACD(DIF/DEA/HIST,×2) 与 KDJ(K/D/J)；列别名 C/O/H/L/V；
  `=`/`<>` 走容差近似。
  - **`COUNT_TRUE(条件1, 条件2, ...)`**：逐日统计 N 个条件同时成立的数量（变参 1~99）。
    它是「条件组 Gate · 至少 N 个满足」的翻译目标：表达式恒定一行，任意条件数都不爆炸。
    （等效：`>=1` 即 OR，`>=条件总数` 即 AND。）
- 整段程序三态语句：`X:=...` 赋值、`X:...,COLOR...` 输出（**属性被忽略，仅取值**）、
  `STICKLINE/DRAWICON/...` **一律 SKIP 跳过不执行**（⚠ 绘制尚未实现）。
- **多函数段共享执行（阶段A）**：`program.execute_programs(programs, df, params)` 让多段函数
  在【同一个 EvalContext】按序执行 ⇒ 共享变量池；后段可引用前段产出变量；同名后者覆盖，
  语义 = 各段文本以分号拼接成一段后执行，完全一致。`execute_program` 单段入口兼容保留。
- 缺参探测：UI 对全部函数段试运行，捕获"未定义的名称"→ 正则提取参数名 → 占位 5.0 复测
  （见 §7-B3）；`runtime._period` 对窗口类函数校验 `周期≥1`，非法给出友好错误而非裸抛。

### 5.3 产品决策与口径（禁止回归的既定结论）

- **A. 时间双轨制**：`trade_time` 永远纯日期；原生 `*_fill_time` 完整入库；
  用户「时间精度」偏好只控显示/排序（`preferences.time_precision`：DATE_ONLY/FILL_TIME），
  首次导入**强制选择**、流水页可随时切换。
- **B. 净额口径**：胜率/盈亏比/单笔极值/净值曲线/**盈亏筛选**一律用 `net_profit − commission`；
  毛利与手续费单列对照（实测净额胜率 45.2% vs 毛利 51.6%）。
  ✅ v5.13：流水页 / 复盘页的「仅盈利 / 仅亏损」筛选器已由毛利改净额（§9-O1 已修），
  现在**全站再无例外**。新建任何"盈利/亏损"判定时，务必先算 `net_amount`。
- **C. 范围聚焦**：**交易流水/深度复盘只做期货**（股票导入链路已整体删除）；
  股票仅保留「市场行情」「市场回测」侧的行情/回测能力。
- **D. 持仓时长三级口径（v1.3 回归）**：① 开仓带时分→精确计时；② 仅日期→本地交易日历
  `trading_day_count`（无行情回退自然日并标注）；③ 无开仓时间→显示 `—` 绝不猜。
  统计必须标注覆盖样本（covered/total，UI 放 tooltip）。
- **E. 买卖分类**：面向个人，不做投机/套保/套利；只留买入开仓/卖出开仓等四象限文案，
  由 `direction` 推导并在 UI 呈现。
- **F. 孤儿单四层防御（不阻断）**：① 持仓明细页签→下月期初腿；② open_legs 持久化 +
  **全局按(日期,时刻,序号)排序后只跑一次 FIFO ⇒ 分批导入≡一次性导入**；③ 资金链
  `上月结存↔客户权益` 对账 + 漏月告警（最早导入月豁免；用户可登记"确无交易"）；
  ④ `is_orphan=1` 显式标记 + 复盘页手工补录(开仓日期/价,来源 MANUAL)，补导早月自动缝合。
- **G. 交易回放双点锚定**：完整闭环(entry/exit 齐全)→开/平双虚线+价格点线+盈绿亏红高亮带；
  孤儿/老数据→诚实降级单点，标题标"开仓信息缺失"，绝不硬凑坐标。
- **H. 回测铁律**：A股单市场、LONG-only。**信号语义 = 条件布尔为真即触发**（"金叉"类瞬时信号由
  `CROSS` 规则制造；持续为真的条件会在离场后再次进场），收盘评估次日开盘成交；末根K线当日收盘强平
  （`force_close`）；**默认数据窗口 2016-01-01**（v5.6 由 2018 放宽，三处必须同源：
  `core/backtest.DEFAULT_START_DATE`、`ui/views/backtest.py` 的「全部(2016起)」预设、
  起始日期控件的 `setMinimumDate`）；通达信优先级最高（Python 沙箱=远期第二作者）。
  区间快捷档：近3个月 / 近6个月 / 近1年 / 近3年 / 近5年 / 全部(2016起)（顺序即下拉顺序）。
  阶段B 硬性风控（止损/止盈/移动止盈/最长持仓）**盘中触发当日即离场、优先于卖出信号**，
  `max_bars` 超时按当日收盘强平——口径详见 §6.5-B。
- **I. 防呆幂等**：DB 一律 `INSERT OR IGNORE`；任何导入必须向 UI 反馈 `inserted/ignored` 统计。

---

## 6. 已完成能力清单（逐模块核对结果，[x]=代码验证通过）

### 6.1 复盘主链路（期货交割单）
- [x] CFMMC `.xls/.xlsx` 解析：成交明细(第9行表头起)/持仓明细/结算月报三页签，脏数据清洗
  （隐藏空格、`'--'`→0、成交时间非法→空串不造假）；`交易月份` 元信息不可信→以成交日期众数为准。
- [x] FIFO 缝合：理论盈亏加权分配、孤儿片承接余额；多文件合并**顺序无关**。
- [x] 幂等入库 + 防重统计报告（inserted/ignored）+ 跨月连续索引。
- [x] 资金链漏月检测 + 非阻断告警弹窗（立即补导 / 确无交易 / 稍后处理）。
- [x] 孤儿单全链路：标记→黄条提醒(流水页)→手工补录缝合(复盘页)→补导自动缝合。
- [x] 流水页五维过滤(账户/品种主体/方向/盈亏/完整度) + 常驻孤儿黄条 + CSV 全量导出。
- [x] 复盘月/年双模态 + 日/月历热力图 + 复盘记录(策略/进场理由/反思/截图) CRUD。
- [x] 绩效统计全净额口径 + 持仓时长三级口径卡片（覆盖数 tooltip 标注）。

### 6.2 市场行情（股票/期货浏览）
- [x] 花名册检索（`search_symbol` 模糊）+ 数据湖优先 → 联网兜底(AkShare 智能路由) → 自动回写数据湖。
- [x] pyqtgraph K线(`CandlestickItem`)+MA/BOLL+成交量+MACD 联动渲染（本地缓存数据正常渲染）。
- [~] 趋势线绘制（`LineSegmentROI` 添加/清除）—— **仅内存态，重渲染即清空，未持久化**（见 §7-A1）。

### 6.3 市场回测 M1 单股（`ui/views/backtest.py`）
- [x] **多函数段编辑（阶段A）**：① 卡为 `ui/widgets/function_segments.py`，可增删多段；检测时
  逐段解析、错误精确到"函数段 N"，在共享变量池上试运行，缺参探测对全段生效。
- [x] **条件组 Gate（阶段A）**：买卖侧各为 `ui/widgets/condition_gate.py` 的 `ConditionGate`，
  每侧可配**多行**积木条件（变量+规则+数值），组合逻辑用「满足计数」统一表达：
  全部满足(AND) / 任一满足(OR) / 至少 N 个满足 → 自动翻译为
  `COUNT_TRUE(cond1, cond2, ...) >= N` 单行 DSL，引擎零改动。
- [x] 整段函数粘贴编辑 → 一键检测（语法 / 哑数据试运行 / 缺参探测并用 5.0 占位复测）。
- [x] `BacktestEngine` 条件为真即触发回测：KPI(总成交/胜率/累计收益/平均单笔) + 净值曲线 +
  K线买卖点标注(三角买/菱形卖) + 9 列成交明细(含离场原因) + 参数区间快捷档 + 折叠专注编辑区。
- [x] **风控离场器（阶段B）**：`run(..., risk=)` 支持 最长持仓N根 / 固定止损 / 固定止盈 /
  移动止盈回撤；盘中触发、硬规则优先；`BacktestTrade.exit_reason` 全链路记录，
  UI 明细表按原因着色（止损/超时/强平等），策略快照随存随载。
- [x] 策略工作台：`StrategyStore` 保存/选用/删除；同股跨策略对比（`metrics_snapshot` 表格+曲线）。
- [x] **策略快照兼容（阶段A）**：payload 新增 `segments`(多段文本) + `function`(分号归并，供
  `find_same` 签名与旧版载入)；`condition_buy/sell` 升级为 `{logic, n, conditions[]}`，
  `ConditionGate.load_config` 兼容旧版单条件平铺 dict。
- [x] **签名含风控（阶段B）**：`_signature` 计入 `risk`，全 0 与旧档(无 risk)等价；
  任一风控启用即视为不同策略，避免不同风控配置相互污染对比。
- [x] **指数 regime 门控（阶段C）**：③ 卡可选启用；指数下拉预设/手输新浪代码；买卖指数 Gate
  用 `IDX_` 前缀变量；数据就绪链(先指数后个股)；门控列拼入个股 df 后引擎零改动生效
  （详见 §6.5-C）。
- [x] **签名含指数门控（阶段C）**：`_signature` 计入 `index`；未启用/条件空与旧档等价。
- [x] 稳定性：缺参友好提示；非法周期不穿透 UI；UI 始终 QThread 执行拉数与回测
  （含指数日线同步）。
- [x] **回测结果导出（v5.14/v5.15 · §7-A2 半程）**：结果区「导出结果 ▾」下拉菜单 =
  `📄 导出 CSV 明细…`（表头参数块 + 逐笔明细，**无净值行**，utf-8-sig，溯源用）+
  `🖼 导出结果图 PNG…`（`ui/widgets/backtest_report.py`：KPI + 净值曲线 + 离场饼图 +
  参数简表，1120×660）。均基于 `_last_meta`（发起回测瞬间定格的配置快照）。
  **不做删除 / 不做存档**，详见 §7-A2 与 §7-A4。

### 6.4 基础设施与演进
- [x] SQLite 迁移链：旧双时间表自动备份重建（COALESCE 归并）；v1.2 增量列走 `ALTER TABLE` 零损加列。
- [x] 纯 Pandas 指标引擎（零编译依赖，兼容 Py3.14+）。
- [x] Parquet 数据湖基础原语（读写/探针/最新日期探测）。
- [x] **数据湖治理（v5.8 / §7-A3）**：补 `delete_data` / `clear_zone` / `list_zone` /
  `inventory`（行数与日期范围一律只读 parquet footer 的列统计，**不把数据读进内存**，
  全市场 5000+ 文件也能秒级清点）/ `zone_stats`。
- [x] **行情同步唯一门面（v5.8）**：`data/sync_service.py` 的 `MarketSyncService`。
  增量 = 本地末日+1 天起拉 → concat → 按 `date` 去重(keep=last，**新数据优先=顺带修正前复权漂移**)
  → 排序落盘；「强制全量重拉」入口必须保留（增量修不回历史价格）。
  `ThrottlePolicy` 温柔抓取：间隔+随机抖动 / 指数退避重试 / 连续失败熔断 / 跳过已最新(断点续传)。
- [x] **代码物理拆分纪律**（v5.13 复核）：
  - [x] **弹窗全独立、`DataEngine` 单一门面**；
  - [x] **UI 直连底层已收敛**（§9-H）：`market.py` / `backtest.py` 均走 `SingleSyncWorker`，
    两处 `engine.db.search_symbol` 已改走 `engine.search_symbol`。
  - [x] **线程收口完成（v5.13 · §9-O2）**：`ui/workers.py` 是全 app 唯一 QThread 定义处，
    唯一例外是 core 层的 `UpdateCheckerThread`（非 UI 职责）。
  - [x] **图表样式 4 合 1（v5.13 · §9-O7）**：统一到 `ui/widgets/chart_style.py`。
  - [ ] **大文件拆分未动**：`backtest.py 1417`（⚠ v5.14 因导出重回 1400+）/ `review.py 1119`（§9-L，第三梯队）。

---

## 6.5 市场回测·升级迭代路线（阶段 A/B/C 已落地，远期排期）

> 2026-09 定稿的产品口径：**信号语义 = 多条件满足计数**，OR/AND 只是"至少N"的两个特例，
> 不做传统意义上的单一"事件"二分。以下阶段由用户分期批准，逐批实施。

- **[x] 阶段 A（已落地）** —— 静态多条件信号：
  - A-1 `COUNT_TRUE` 计数原语（runtime 注册表，变参 1~99）。
  - A-2 多函数段共享变量池（`execute_programs`）——覆盖"MACD金叉 + KDJ<20 + 自研>20"。
  - A-3 UI 条件组 Gate（多行积木 + 全部/任一/至少N）——覆盖"多个卖点任一满足就卖"。
  - A-4 策略快照结构升级 + 老档兼容读取。
- **[x] 阶段 B（已落地）** —— 引擎风控离场器（治"指标滞后、盈利单变亏"的**动态**痛点）：
  - B-1 `core/backtest.py`：`normalize_risk()` 归一百分比口径；`BacktestTrade.exit_reason` 记录
    离场来源（`signal`/`stop_loss`/`take_profit`/`trailing`/`max_bars`/`force_close`）。
  - B-2 引擎硬性规则（与信号正交）：固定止损/止盈/移动止盈基于当日 low/high **盘中触发即离场**
    （触发价=预设线，跳空越线则按开盘价，不占便宜）；下沿止损与移动止盈同根都触及取更高线先成交；
    `max_bars` 第 N 根收盘仍持仓则**当日收盘强平**；**硬规则优先于卖出信号**；净值/成交记录不变形。
  - B-3 `BacktestEngine.run(..., risk=dict)` 全零=关闭，默认行为与旧版完全一致（回归已验）。
  - B-4 UI：下区新增「🛡 风控离场」参数行（最长持仓/固定止损/固定止盈/移动止盈，0=关闭）；
    成交明细表新增「离场原因」列（按原因着色 + tooltip）。
  - B-5 `strategy_store`：策略 payload 新增 `risk` 字段；`_signature` 计入风控
    （全 0 等价旧档空字段，签名兼容已验证）。
- **[x] 阶段 C（已落地）** —— 大盘/指数 regime 门控（"不能把个股与大盘分离"）：
  - C-1 `data/akshare_feed.py`：新增 `fetch_index_daily(symbol, min_date)` 新浪指数接口
    （`ak.stock_zh_index_daily`，代码须带前缀如 `sh000001`/`sz399001`，附 `INDEX_PRESETS` 预设表
    与 `is_index_symbol` 校验）；数据落盘数据湖 **`index_daily` zone**。
  - C-2 `core/utils.align_by_date()`：把指数侧(外部日历)序列对齐到个股交易日轴
    —— reindex + ffill（指数停牌日沿用前值），前导空洞按 0 兜底。
  - C-3 UI ③「大盘/指数 regime 门控」卡（可折叠）：启用勾选 + 指数下拉/手输 +
    买卖两个指数 Gate（`gate_index_buy` 买入许可 / `gate_index_sell` 卖出破位）。
    指数 Gate 变量池 = 同一批函数段的 `IDX_` 前缀变量（同一段函数既算个股也算大盘）。
  - C-4 回测链路零引擎改动：指数函数段在大盘上求值 → 指数 Gate 表达式求布尔 →
    `align_by_date` 对齐 → 门控列 `IDX_GATE_BUY/SELL` 拼入个股 df →
    最终表达式 = 原买入 `AND` 许可门控 / 原卖出 `OR` 破位门控。
  - C-5 数据就绪链：先指数后个股（各自本地缺则 QThread 同步后再续跑）；
    `_signature` 计入指数门控（未启用/条件空等价旧档空字段）。
  - 边界纪律：指数求值失败（函数段依赖个股独有列）→ 明确提示，不静默放行。
- **[ ] 远期** —— 组合级多标的引擎（指数择时后全市场挑股 + 资金分配）= 全新模块，勿并入 M1。

### 6.6 单股回测 UX 硬化（文档 v5.4）

> 高信息密度工作台的防误触与可读性改造，由用户实测反馈驱动。

- **[x] U1 指数选择广度**：`INDEX_PRESETS` 从 8 项扩到 **29 项**（分组：大盘核心 / 风格红利 /
  科创创业板 / 热门行业主题 / 北交所），覆盖 `sh000688 科创50`、`sh000698 科创100`、
  `bj899050 北证50`、`sz399997 中证白酒`、`sz399975 证券公司` 等；全部经真实接口代测可用。
  `is_index_symbol` 前缀白名单扩展到 `sh/sz/bj`。行业板块(东财源)当前网络不稳定，未纳入预置。
- **[x] U2 防滚轮误触**：新增 `ui/widgets/custom_widgets.py` 的 **NoWheel 控件族**
  （`NoWheelComboBox/NoWheelDoubleSpinBox/NoWheelSpinBox/NoWheelDateEdit`），
  wheelEvent 直接 ignore —— 悬停参数控件滚动不再误改值，滚动权交还给父级滚动容器。
  已统一替换：回测页全部下拉/日期/风控数值、ConditionGate 全部行内控件、
  流水页 5 个过滤下拉、复盘页 7 个下拉、手工录入 3 个下拉。
- **[x] U3 灰字弱化**：把占版面的长说明文字收敛为「?」小角标 `_hint_icon`(hover 出 tooltip)：
  工具栏提示、②组合逻辑说明、③指数说明、风控行说明；风控各项已有独立 tooltip。
- **[x] U4 编辑区可滚动**：①/②/③ 卡片包进 `QScrollArea`；新增很多函数段/条件不再撑爆页面，
  超高超限时编辑区内部滚动；  `_resync_config_split` 重写为配合滚动容器 + 上区高度上限
  (`max(total*0.55, 320)`)，折叠卡片仍可把空间让给结果区。
- **[x] U5 数值控件视觉/热区统一（v5.6 · 修长期 Bug）**：风控离场行的 4 个
  `QDoubleSpinBox` 原先就地写了「只含控件本体」的半截 QSS，导致 Qt 用默认度量重绘
  子控件 ⇒ ① 上下箭头图标与买卖条件组的原生箭头不一致；② **上箭头只有右半边可点**。
  根治方案：新增 `ui/widgets/custom_widgets.SPINBOX_QSS`（空串 = 原生渲染）作为
  **数值控件唯一可改点**，风控行改为引用它，与条件组完全同源；
  并把宽度 64→72 留足箭头空间。纪律固化见 §10-9。

---

## 7. Roadmap：未完成项（按优先级与依赖重新分类）

### A 类 · 半成品闭环（有代码入口/雏形，缺最后一公里 —— 建议优先）
- **A1 [~] 行情涂鸦板持久化** `ui/views/market.py`：画线已可交互，但 `drawn_lines` 随重渲染清空、
  无落盘。**收尾定义**：选定存储(DB 附表或 JSON) + 代码维度去重 + 复盘页/行情页复用。
- **A2 [~] 回测结果导出（半程）** `ui/views/backtest.py`：
  ✅ **v5.14 已做"导出当前结果"**（§6.3）：CSV 含表头参数块 + 逐笔明细 + 净值曲线。
  **明确不做**：结果删除 —— 用户判断"当前没有显式保存、结果会被覆盖，删除没有对象可删"。
  `StrategyStore.record_result` 仍是自动归档的缩略指标（同股对比用），不属于"可管理的结果集"。
- **A4 [ ] 回测结果历史存档（远期 · 由用户 v5.14 明确"找机会再做"）**：
  **为什么**：结果本质上是"易逝的"（同 策略×标的 每次回测静默覆盖旧缩略指标），
  用户迟早会问"上周那组参数跑出来的明细去哪了"。
  **设计要点（动工前先与用户对齐，勿直接照做）**：
  ① 每次回测生成一份**不可变存档**：`_last_meta`（配置快照，v5.14 已就绪）+
    `BacktestResult`（逐笔明细 + 净值）序列化到 `~/.jian_data/backtest_results/`
    （JSON 或 CSV，文件命名 = 时间戳 + 策略 + 标的 + 区间）；
  ② UI 新增「回测历史」列表（可参考「策略对比」页签的入口，或独立页签）：
    查看/复用参数（载入回编辑器）/打开明细，删除放这里但按 §10-10 做隔离 + 二次确认
    （此时"删除"才有明确对象 = 一份存档文件，可与"保存"配对）；
  ③ 若只想要"可复现"，也可只存档轻量 JSON（参数 + 函数文本）以便"一键重跑"，
     不必把整份净值曲线也存了 —— 先问用户要的是"复现"还是"留档"。
  **前置**：§6.3 的导出（v5.14）已把 `_last_meta` / `_compose_result_csv` 铺好路。

- **[x] A3 P0 数据管理页（v5.8 已完成）**：`DataLakeManager` 补删除/清点原语 +
  第 6 导航页 `ui/views/data_manager.py` + 批量预下载弹窗 `ui/dialogs/bulk_download.py` +
  同步门面 `data/sync_service.py`。
  **遗留（属 B1，非 A3 欠账）**：`scan_cache` zone 仍不存在 —— M2 横截面筛选落地时再建。

### B 类 · 市场回测扩展（规格 §9 已定稿，占位就绪待填充）
- **B1 [ ] M2 全市场单日横截面筛选**：`backtest_module.py` `page_scan` 现为 `_ComingSoonPage`。
  依赖 A3（预下载全市场湖）。需 `scan_cache` zone（公式哈希+日期维中间结果缓存）。
- **B2 [ ] M3 全市场广度家数折线 + 指数双轴叠加**：`page_breadth` 占位；指数日线能力已就绪
  （阶段C：`fetch_index_daily`/`index_daily`），缺广度统计实现与双轴 UI。
- **B3 [ ] ⭐最高优先级（P0 · v6.0 用户定稿）公式统一绘图** ——
  完整主案见下方「§7-B3 主案规格」，含 引擎 IR → 统一渲染器 → 回测页接入 三步。
  现状（待消除）：`program.py` 把 `STICKLINE/DRAWICON/颜色线型` 一律 SKIP，
  导致用户的 QSD/GLX/状态柱"算得出、没得画"——K线页签与导出 PNG 均看不到。
- **B4 [ ] P1c 回测进阶（部分）**：结果长期入库已有雏形(A2)，缺 复用 `TradeAnalyzer` 绩效维度
  与每回合明细的持久化侧写。

### C 类 · 体验升级（有明确规格，尚未动工）
- **[x] C1 Dashboard GitHub 风格日历热力图**（v5.7 已完成）`ui/widgets/calendar_heatmap.py` +
  `ui/views/dashboard.py`：整年 53×7 网格（周一为首行），颜色 = **当日净额**
  （绿盈红亏，5 档分位），灰色 = 无交易/净额为 0；支持年份下拉切换（默认停在最近有数据年）、
  年度摘要（交易日数 / 盈利天数 / 亏损天数 / 年度净额）、悬停 tooltip（日期+净额+笔数）。
  **注意**：复盘页的「月历热力图」是另一个东西（单月 6×7、可点选交易），勿混淆、勿互相替换。

### D 类 · 远期（设计预留，暂不排期）
- **D1 [ ] Python 脚本沙箱（AST 白名单）第二作者模式**：接入点预留在 `core/formula`。
- **D2 [ ] 期货侧回测**：`BacktestEngine` 明确 LONG-only/A股，做空与期货为远期。
- **D3 [ ] `kline_min` 高频分时数据湖 zone**（已 mkdir，功能预留）。

### §7-B3 主案规格：统一绘图 IR（v6.0 设计稿 · 最高优先级 P0 · 用户 2026-09-10 定稿）

> **定位一句话**：让"公式怎么画"从一行行散落在各 UI 文件里的手工绘图，变成
> **引擎产出统一"绘图指令"（IR）→ 唯一渲染器解释** —— 以后任何图表
> （回测 K线 / 市场行情 / 未来其它图）要展示公式叠层，都走同一条底层管线，
> 想改样式/改语义只改引擎 IR 或渲染器一处，绝不对着每个页面挨个改。

**为什么是引擎级（而不是在 UI 层"读函数文本再猜"）**
- 绘图语句依赖**同一共享变量池**（STATE_BLUE/DYN_INDEX/最终优选…），只能在
  `EvalContext` 求值现场拿到真值；UI 层事后重读文本 = 二次解析 + 语义分裂。
- 引擎不画图，只产出**数据**；UI 不解析函数，只**消费 IR**。职责与 §10-3 一致。

**1) 语句分类（`core/formula/program.py` 改造）**
`_classify` 由 3 态扩为 **4 态**（ASSIGN / OUTPUT / **DRAW** / SKIP→移除）：
- `DRAW` = 语句以已知绘图函数开头：一期 **STICKLINE / DRAWICON**；预留 DRAWTEXT。
- OUTPUT 语句（`NAME: expr`）逗号后缀解析出绘制属性 → 得到 **line 输出**：
  `QSD: DYN_INDEX, COLORWHITE, LINETHICK2;` = kind=line + color=白 + thickness=2；
  `最终优选: ..., NODRAW, COLORRED;` = kind=hidden（NODRAW 只算不画，但变量照常供 Gate 用）。
- 属性后缀（颜色/线型/NODRAW）用轻量 tokenize，不引入第二套解析。
- 未知绘图函数名（如 DRAWTEXT 未实现前）→ 明确报错并列出已支持清单，**绝不静默跳过**
  （这正是用户踩的坑：现在 SKIP 让 DRAW 静默消失）。
- 变量语义零回归：ASSIGN/OUTPUT 产生的变量名照旧进共享池（`execute_programs` 契约不变）。

**2) 契约层（新增 `core/formula/draw.py`，纯计算，零 Qt）**
- `COLOR_TABLE`：通达信颜色名→hex（RED/GREEN/BLUE/YELLOW/WHITE/BLACK/GRAY/LIGRAY…）
  + `COLORRRGGBB` 直通；未知颜色抛友好错。
- `@dataclass DrawSpec`（编译期）：kind∈{line,stick,icon,hidden}、color、thickness、
  style(预留 DOTLINE 等)、各表达式的 AST。
- `@dataclass DrawData`（运行期）：kind、color、x(date/np)、数组
  （line: y；stick: cond×lo×hi×width；icon: cond×pos×icon_id）+ 常量备注。
- 执行 API（**与现有 execute_programs 兼容并存**）：
  - `execute_programs(...)` 保持不变（只出变量，供检测/条件）；
  - 新增 `execute_programs_with_draws(programs, df, params) -> (variables, draws)`
    —— 同一 EvalContext 顺序执行一遍同时产出两者，**不二次求值**；
  - 绘制语句的 cond/price 求值错误与变量同样以 `FormulaProgramError` 抛给 UI 展示。

**3) 渲染层（新增 `ui/widgets/draw_overlay.py`，本软件的"图表叠层唯一窗口"）**
- 对外唯一入口：`OverlayPainter(plot_item, bars_x, draws)` —— bars_x 是宿主已切好的
  x（bar 序号数组），draws 在整段数据轴求值、由宿主按 date_index 切片后喂入，
  防止"画错位/跨窗口漂移"（复用回测页 K线切窗那一套日期→索引映射思路）。
- 内部实现（与 CandlestickItem 同一套 Pokorny 画法：QPicture + 抗锯齿 + 去描边）：
  - line → `pg.PlotDataItem`（color/thickness）；预留 DOTLINE 样式表；
  - stick → 自绘 GraphicsObject（cond 为真处画 lo→hi 竖段，width=1 画细线、
    width>1 画小实体），K线配色纪律（去描边、单色高对比）照旧；
  - icon → `ScatterPlotItem`：`DRAWICON(cond, price, id)` 的 id→符号映射表（一期常用子集），
    未知 id 用默认菱形并 tooltip 提示，不崩溃；
  - 一律走 `chart_style` 的配色/抗锯齿约定，禁就地 inline 样式。
- 宿主只负责三件事：切窗口、喂 x 数组、把 y 范围扩到能盖住叠层（stick/icon 超出K线
  高低价时要纳入 range）。

**4) 消费方接入（首个落地点 = 回测页「🕯 K线买卖点」页签）**
- `_on_data_ready` 已把输出变量 merge 成整段 df 列（.values 与整段对齐）；
  执行时改调 `execute_programs_with_draws`，把 draws 与 `_last_df` 一并保存。
- `_render_kline` 切窗口时按 date_index 抽取出窗口内 draws，调 `OverlayPainter` 一次；
  提供「显示公式叠层」开关（默认开）；stack 顺序：K线→叠层线→状态柱→买卖点标记。
- y 自适应：叠层最大/最小纳入视口范围计算。

**5) 验收 / 冒烟断言（必须，参照历史 §9-N1 风格）**
- 编译期：STICKLINE/DRAWICON 正反宽度、COLOR 名/hex、LINETHICK、NODRAW、未知颜色与
  未知函数各自报友好错；
- 求值期：draws 与变量同一次执行、分批/重复执行结果稳定；空 cond 不产出图形对象；
- 渲染期：离屏构造回测页 → 叠加 QSD/GLX/状态柱后 grab PNG 非空，x 对齐与 K线窗口一致
  （抽样断言若干 bar 的像素色/位置）。
- 回归：`execute_programs` 旧调用方（检测/条件/指数门控）行为不变（同断言）。

**6) 里程碑（按此顺序推进，每个完成即回写本文档）**
- **M0 契约层**：`core/formula/draw.py`（dataclass + COLOR_TABLE + 校验）+ program.py
  4 态分类与 attrs 解析；纯单测（无 UI）。
- **M1 求值层**：`execute_programs_with_draws` 产出 draws（含 STICKLINE/DRAWICON 求值），
  断言覆盖清单见上。
- **M2 渲染层 + 回测页接入**：`ui/widgets/draw_overlay.py` + K线页签叠层 + 开关 + y 自适应；
  离屏截图验收。
- **M3 收尾**：错误文案收敛；§11.4 速查表登记"以后给图表加叠层 = 引擎 draw.py +
  draw_overlay.py 两处"；B3 标 [x]。
- **M4（远期 hook）**：市场行情页等其余图表接入同一 `OverlayPainter`（用户未来
  优化行情图表时的统一修改窗口已就位，不需逐图改）。

---

## 8. 版本演进备忘（压缩 changelog）

| 版本 | 里程碑 | 一句话备注 |
|---|---|---|
| Phase 1~3 | 基础 MVP | UI 组件物理隔离、SQLite 防重、CFMMC 跨月缝合 |
| Phase 4.1 | 基础设施 | Parquet 湖、TAEngine、AkShare 封装 |
| v1.1 | 数据契约重构 | 双时间→单一 `trade_time` 锚点；旧库自动无损迁移；删虚构"时长分析" |
| v1.2 | 交割单字段补全 | 补 entry/exit 价与 `*_fill_time`/乘数/time_source；持仓与月报解析；
        FIFO 加权分配；跨月真缝合(顺序无关)；漏月告警；孤儿显式化；净额口径；时间双轨 |
| v1.2.1 | 微观测算修正 | 盈亏分配"点数×乘数×手数"自洽、孤儿片接余额；孤儿语义收敛(CFMMC专属)；
        手工录入账户仅真实+可新建 |
| v1.3 | 范围聚焦+时长回归 | 删股票导入链路；持仓时长三级口径回归(卡+复盘页签)；手工录入补开仓时间(选填) |
| 阶段A(文档v5.1) | 回测信号升级 | 多函数段共享变量池；条件组 Gate(全部/任一/至少N→COUNT_TRUE)；策略快照兼容 |
| 阶段B(文档v5.2) | 回测风控落地 | 引擎风控离场器(止损/止盈/移动止盈/最长持仓,盘中触发硬规则优先) + exit_reason 全链路 + 明细着色 |
| 阶段C(文档v5.3) | 指数门控落地 | 新浪指数接口 + index_daily 数据湖 + align_by_date 对齐 + ③指数Gate(买许可AND/卖破位OR)，引擎零改动 |
| v5.6(文档v5.6) | 回测 UX 补强 | 风控行箭头统一为原生（根治"上箭头只有右半边可点"）+ 区间下沿 2018→2016 + 新增近3月/近6月/近5年三档；新增 §10-9 控件一致性铁律 |
| v1.4.0 | 回测总集 + 甲方案收尾 | 多函数段共享池 / 条件组 Gate / 风控离场器 / 指数 regime 门控；年度面板净额口径统一；花名册覆写安全闸；Dashboard 每日净额日历(C1)；`APP_VERSION` 与 `version.json` 同步升 1.4.0 |
| v1.4.1 | 数据管理页 + 同步收敛 | A3 落地：数据湖删除/清点原语；`MarketSyncService` 同步门面（增量合并 + 温柔抓取 ThrottlePolicy）；`ui/workers.py` 统一线程；第 6 导航页 + 批量预下载弹窗；§9-H 架构债清账；**含 v5.9 独立复查加固**（§9-M1~M4 时效/空增量/起点/竞态） |
| v5.12(文档v5.12) | 全仓通读对账（**无代码变更**） | 第二次"陌生代码"复查：核对 30 个 .py，产出 §9-O 系列 10 项发现；校正 §3/§4 的 KPI 项数与全量行数；§4 补 `.gitignore` 与 `core/formula/` 五个子文件；刷新 §11.6 下一步顺序 |
| v5.13(文档v5.13) | 第一/第二梯队落地 | O-1 盈亏筛选改净额（用户拍板）；O-2 三个 UI 线程迁入 `ui/workers.py`；O-3 同步 docstring 起点改 2010；O-4 云端同步改默认增量（本地有=增量/没数据=全量，改名 `sync_cloud`）+ 状态回执；O-5 回测页补竞态守卫×2；O-7 新增 `ui/widgets/chart_style.py`（4 合 1，PlotWidget/PlotItem 兼容）；O-8 复盘页三小坑 + 画廊失效路径不再静默丢弃。**25 项冒烟断言 + 离屏构造主窗口/全部弹窗通过**。APP_VERSION 未动（仍 1.4.1）。**修订**：O-4 新增的同步状态 QLabel 触发了 Qt 布局坑（顶部栏末尾 QLabel 会吞掉主区高度），已给 main_splitter 加 `stretch=1` 根治，并固化为 §11.5 第 13 条 |
| v5.14(文档v5.14) | §7-A2 导出落地（半程） | 回测页「导出明细」按钮 + `_last_meta` 配置快照（start_backtest 定格）+ `_compose_result_csv`（逐笔明细 + 净值曲线，utf-8-sig）。**只导出、不删除**（用户拍板）；「结果历史存档」列为 §7-A4 远期方案。**14 项导出断言全过** + 全仓编译通过。APP_VERSION 未动（仍 1.4.1）。⚠ 其"注释头裸写"做法已被 v5.16 推翻 |
| v5.15(文档v5.15) | 导出升级：PNG 报告图 | 用户拍板：① CSV 移除 200+ 行净值段（溯源=参数+逐笔，曲线由图承担）；② PNG 报告图含离场原因饼图；③ 导出按钮改下拉菜单（CSV/PNG 两动作）。新增 `ui/widgets/backtest_report.py`（单页 1120×660 = 标题 + KPI + 净值曲线 + 饼图 + 参数简表，离屏 grab 渲染）；离场原因 标签/配色/风控文案上收 `core/backtest.py` 三处同源。**16 项断言全过** + 全仓编译通过。APP_VERSION 未动（仍 1.4.1） |
| v5.16(文档v5.16) | CSV 兼容性修复（WPS 实测） | 用户用 WPS 打开 CSV 发现"函数段·第三部分图形绘制"被拆列成乱码：根因 = 表头注释行裸写，含英文逗号的 `STICKLINE(...), COLORFF0000;` 被表格软件当多列。修复：`_compose_result_csv` **逐行单格 csv 转义**（含逗号自动引号、空行 writerow([])）。**9 项 csv.reader 重解析断言全过**。APP_VERSION 未动（仍 1.4.1） |
| v6.0(规划) | §7-B3 公式统一绘图（**P0 · 设计定稿，无代码**） | 用户复盘定位"绘图语句从没被画出来"= `program.py` 长期 SKIP 的历史欠账；定稿"引擎产出统一绘图 IR + 唯一 OverlayPainter"为全图表统一修改窗口（避免未来逐图一对一改）。里程碑 M0 契约层 / M1 求值层 / M2 渲染+回测页 / M3 收尾 / M4 远期全图复用。完整规格见 §7-B3 主案；优先级见 §11.6 |
| 远期 | 排期 | 组合级多标的引擎（指数择时后全市场挑股+资金分配，见 §6.5） |

---

## 9. 审计发现：文档 ↔ 代码不一致 / 技术债（本次 v5.0 核对产出）

- **A. ✅ 已修（v5.7）版本号滞后**：`config/settings.py` 的 `APP_VERSION` 与 `version.json`
  已统一升到 **1.4.0**，notes 补齐 v1.2 / v1.2.1 / v1.3 / v1.4.0 全量变更。
  【纪律】改版本号必须**两处同步**：`APP_VERSION`（本地比对基准）与 `version.json`（远端清单），
  不同步会导致自动更新误报或漏报（见 `core/updater.py`）。
- **B. zone 命名口径漂移**：历史规格曾规划 `market_index` / `scan_cache` 两 zone；
  实际 `market_db.py` zones 为 `index_daily`/`sentiment`/`hot_topic` 等 8 个，且无 `scan_cache`。
  **以代码为准**，新增需求按现有 zone 命名体系扩展并回写本文档。
- **C. §4 文档树过时**：早前目录树缺 `sync_roster.py`、`core/formula/` 实际为 5 个 py；
  本文档 §4 已重绘为磁盘一致版。根目录 `screenshots/` 为历史遗留空壳目录，正式截图目录在
  `~/.jian_data/screenshots`。
- **D. `preferences.json` 目前唯一键为 `time_precision`**：偏好系统已留好读写骨架，
  后续新增用户偏好（图表主题等）直接加 key 即可。
- **E. 无显式代码债务**：全仓库扫描无 `TODO/FIXME/NotImplementedError`；所有"占位"
  均为 ComingSoon 页面或规格预留在注释/文档。（v5.5 复扫确认仍成立，唯一命中是
  `core/indicators.py` 注释里的 "add_xxx" 占位示例，非真实债务。）

### v5.5 全仓通读新增发现（按「会不会伤到用户数据」排序）
- **F. ✅ 已修（v5.7）~~【口径 Bug】年度面板未扣手续费，违反 §5.3-B 净额铁律~~**：
  `ui/widgets/yearly_review.py`：`:136` 年度净值曲线、`:111` 月度盈亏卡片、
  `:145` 策略贡献度条形图，**三处都用 `net_profit` 裸值**；
  而 `ui/views/review.py:518/577`、`core/analyzer.py:30` 一律用 `net_profit − commission`。
  后果：**同一批数据切到「年视图」看到的资金曲线比「月视图」系统性偏高**（差 = 总手续费）。
  修法（已实施）：`YearlyReviewPanel.render()` 统一先算
  `net_amount = net_profit − commission.fillna(0)`，三处消费点全改用它，
  标题补「(已扣手续费)」。冒烟断言：年度曲线末值 == 该年净额之和（与毛利差额 = 手续费）。
- **G. ✅ 已修（v5.7）~~【数据安全】`sync_roster.py` 半成功会毁掉 A 股名册~~**：`update_market_roster` 是
  `if_exists='replace'` 全量覆写（`core/database.py:456`）；`fetch_a_share_roster()` 断网返回
  空 DF，而期货名册是硬编码必然非空 → `sync_roster.py:24` 只判断 concat 后的整体是否为空，
  于是**A 股拉取失败时仍会用「只剩期货」的名册覆盖全表**，A 股名称全丢。
  修法（已实施）：改为**分市场各自判空**，任一为空即打印缺失方并 `return`，
  数据库既有名册原样保留。
- **H. ✅ 已修（v5.8）~~【架构边界松动】UI 层 3 处直连底层~~**：
  修法 = 新增 `data/sync_service.py` 门面 + `ui/workers.py` 统一线程 + `DataEngine` 检索门面：
  ① `market.py` → `SingleSyncWorker(zone=…)`，删掉本地 `FetchDataThread`；
  ② `backtest.py` → 同一 `SingleSyncWorker`，删掉 `_StockSyncThread` / `_IndexSyncThread`；
  ③ 两处 `engine.db.search_symbol` → `engine.search_symbol`（新增 `engine.list_stock_symbols` 供全市场下载）。
  【仍然允许】UI 直接 import `akshare_feed` 的**纯常量/纯函数**（`INDEX_PRESETS` /
  `is_index_symbol` / `is_stock_code`）—— 它们无副作用、不联网；
  **任何联网抓取必须经 `MarketSyncService`**，这是本次划定的新红线。
- **I. 【重复代码】`_apply_pokorny_style` 一字不差重复两份**：
  `review.py:51-69` 与 `yearly_review.py:30-47`（约 19 行）。
  另有「排序→cumsum→按盈亏选色→plot+fillLevel」净值绘制逻辑重复于
  `review.py:576-585` 与 `yearly_review.py:135-143`。
  收尾：下沉到 `ui/widgets/chart_style.py`（建议新增公共模块）。
- **J. 【小坑合集】**（不改也不崩，但值得知道）：
  - `review.py:658-665`：持仓时长「仅日期」分支异常时把 0 天计入均值，与该文件
    注释宣称的"算不出来就不参与统计"自相矛盾。
  - `review.py:454`：`engine.df` 为空时提前 return，未刷新 `cb_time_picker`，留下陈旧月份项。
  - `review.py:497-499`：切到年视图不清空 `playback_chart`，可能残留上次 K 线回放。
  - `screenshot_gallery.py:143`：无扩展名文件 `rsplit('.')` 会 IndexError；
    `:84-88` 静默丢弃磁盘上已失效的截图路径（用户无感知，且会被写回库=变相删数据）。
  - `manual_entry.py:189`：`value() or None` 使真实 0 价无法录入（设计取舍，非 Bug）。
  - `import_futures.py`：`engine.parse_cfmmc` 在子线程内会读 SQLite（`load_open_legs`），
    且 `self.worker` 无 `wait()` 生命周期管理，提前关窗可能留下悬空线程。
- **K. ✅ 已修（v5.7）~~【文档与代码不一致】`data/data_feed.py` 注释称「UI 层已有调用」已失真~~**：
  `BaseTradeParser` / `CFMMCTradeParser` / `PARSER_REGISTRY` / `get_parser` /
  `parse_cfmmc_excel` 全仓**无外部引用**，是纯粹的扩展预留。真实对外 API 只有 3 个：
  `parse_cfmmc_files` / `legs_from_payload` / `detect_coverage_gaps`（均被 `core/engine.py` 调用）。
  已在 `parse_cfmmc_excel` 的 docstring 里写明事实，避免未来的我误用。
- **L. 【体积预警】**：`ui/views/backtest.py` 1403 行、`ui/views/review.py` 1248 行、
  `data/data_feed.py` 964 行。三者都还是"单一大类 + 长方法"形态，继续加功能前建议先拆
  （回测页可按「编辑区 / 运行管线 / 结果渲染」拆 3 个私有子构件）。

### v5.9 独立复查产出（在 v5.8 基础上新发现并修复，全部有断言）
> 背景：会话中段更换过语言模型。为保证"两模型交替合作"不出夹生代码，把上一批改动当作
> 陌生代码整体重审。以下 4 个隐患都真实存在且已修复 —— 教训：**跨会话/跨模型的改动，
> 提交前必须做一次"不信自己人"的复查**。
- **M-1【时效 Bug】"增量永远滞后一天"**：原 `fresh_within_days=1` 会让"昨天收盘后已同步"
  的标的在今天的收盘后窗口被 `skip_fresh` 跳过 —— 而 A 股当日 bar 恰恰是收盘后才发布。
  **修复**：`fresh_within_days` 改为 **0**（只有末日==今天才算最新），宁可多花一次轻量增量，
  也不让当日数据漏掉。代价由"空增量不算失败"（M-2）兜住。
- **M-2【语义 Bug】休市/盘中的空增量被误判为失败**：增量区间拉不到新 bar（周末/节假日/
  未开盘）会被当成失败：白做 3 次退避重试、还计入熔断计数。**修复**：增量模式只请求一次、
  空返回即按 `skipped=True` 返回（非失败）；首拉/强制全量仍保留重试语义（坏代码=真的失败）。
- **M-3【数据回归】起点 2010→2016 的静默缩水**：迁移到 `MarketSyncService` 时默认起点写成
  "回测评估窗 2016"，但市场行情页"云端同步"历史上拉的是 2010 起 —— 用户曾经能看到的
  2010~2016 历史 K 线会凭空消失。**修复**：`DEFAULT_MIN_DATE=20100101`（数据窗与评估窗解耦：
  数据窗=2010 全历史，评估窗=`core/backtest.DEFAULT_START_DATE`=2016）。批量预下载默认仍给
  2016 平衡下载量，但起点控件下沿放宽到 2010 让用户可选。
- **M-4【竞态/崩溃】**：① `ScanWorker` 结果不带 zone，数据管理页快速切换分区时旧扫描结果
  晚到会覆盖新分区 → 信号改为携带 `(zone, items)`，接收方校验；② 勾选集合曾存在表内、
  搜索过滤即丢失 → 独立 `_checked: set` 并跨过滤保留；③ 批量下载弹窗右上角 X 关闭时
  QThread 仍在运行、随对话框销毁会崩溃 → `closeEvent` 走"取消→wait(15s)→仍不停则保持窗口
  存活并提示"，绝不带着活线程销毁；④ 成分股解析按钮连点 → token 序号只认最后一次结果。

【固化到 §11.5 的第 8 条坑，禁止回退】同步语义两大铁则：
  A. "本地已最新"的判据是 **末日==今天**（`fresh_within_days=0`），任何放宽都会制造滞后一天；
  B. **空增量 = 已最新，不是失败**（增量模式不重试、不计熔断、`skipped=True`）。
  数据窗起点 2010 不得再缩水（§9-H 同源红线）。

### v5.10 UX 加固产出（用户实测反馈驱动，均已断言）
- **N-1【复选框 Bug】"点不出勾 / 点了就消失" —— v5.11 最终方案**：
  第一轮修法（v5.10）只解决了"列宽≈0 看不到指示器"，改用"原生 indicator + cellClicked 整格
  切换"后反而引入**双重触发**：点击 indicator 时 Qt 自动切换一次、`cellClicked` 又切一次
  → 净效果等于没点，怎么点都打不出勾；且加 `ItemIsSelectable` + `SelectRows` 出现蓝色行高亮。
  **最终方案（v5.11，已用 QTest 真实鼠标事件断言）**：
  ① **彻底不用 Qt 原生 checkbox** —— 第 0 列自绘 `☐/☑` 字符，颜色区分（勾=主题蓝/未勾=浅灰），
  ② `cellClicked` 是**唯一切换入口**（点击一次 = 状态翻转一次，绝无双路径），
  ③ `setSelectionMode(NoSelection)` —— 整表无行/格选中，彻底消除蓝色高亮。
  表头「☑」提示列用途。教训写进 §11.5 第 9 条坑。
- **N-2【行错位 Bug】过滤搜索时单元格错位/漏填**：`_render_items` 用
  `enumerate(self._items)` 再跳过不匹配项来定行号，过滤后行号与 `setRowCount` 的真实行不一致。
  **修复**：直接对「过滤后的可见列表」按 0..n-1 铺行。
- **N-3【防呆层级】"清空分区"与"删除选中"同排、区分度不足**：大面积不可逆操作必须物理隔离。
  **修复**：右侧主操作行只留「更新到最新 → 重新全量下载 → | 删除选中」（高频、有选中才可点）；
  「清空当前分区…」**移到左侧分区栏底部**的低调小字链接，且执行前先弹后果说明、
  再要求键入「清空」二字 —— 双重闸门。
- **N-4【文案】用户看不懂"增量更新/强制全量重拉"**：一律改用户语言并给 tooltip：
  「🔄 更新到最新」= 只下缺失的最新几天（日常）；
  「⟳ 重新全量下载」= 丢弃本地从 2010 整段重拉（慢，仅数据异常时用，tooltip 说明前复权）。
- **N-5【误导文案】退市股报错像"代码错了"**：600277（2024-06 退市）这类股行情源不再提供，
  原提示"代码不存在/网络抖动"纯属误导。**修复**：`refresh_one` 结果增加 `reason` 维度
  （`ok/fresh/no_new/network/no_data/error`），新增 `friendly_fetch_message()` /
  `short_fetch_reason()` 统一生成人话文案；行情页 / 回测页 / 批量弹窗 / 管理页全部接入，
  `no_data` 明确列出"①代码有误 ②已退市/长期停牌（本地缓存历史仍可用）③行情源未收录"。

【固化到 §10-10 的新铁律】危险动作物理隔离 + 面向用户说人话（见下）。

### v5.12 全仓通读核对产出（第二次"陌生代码"复查，10 项）

> 背景：会话中再次更换过语言模型。按 §9-M 立下的规矩——**跨会话/跨模型的改动，
> 提交前必须做一次"不信自己人"的复查**——本次把全部 30 个 .py 重读一遍，
> 逐项对账"文档说的"与"代码做的"。结论：**核心链路（净额/幂等/FIFO/孤儿/同步语义）
> 全部健在**，下面 10 项都是"边缘漂移"，不影响主链路正确性。

> **✅ v5.13 状态：O-1 ~ O-8 全部已修**（共 25 项冒烟断言 + 离屏构造主窗口/全部弹窗通过）。
> 下面保留原文是为了让未来的我知道"当时为什么这么改"；每项标题后标了最终做法。

- **O-1【口径漂移】✅ 已修（改为净额）** —— 流水页 / 复盘页的「仅盈利 / 仅亏损」过滤器
  用的是毛利 `net_profit`，违反 §5.3-B 净额铁律：
  - `ui/views/records.py:274-275`（`仅盈利`→`net_profit > 0`；`仅亏损`→`net_profit <= 0`）
  - `ui/views/review.py:491-492`（同样的两行）
  - 后果：一笔"毛利 +100、手续费 150"的交易真实净额是 **−50**，却会被算进「仅盈利」，
    与 Dashboard / `core/analyzer.py` 的净额口径**自相矛盾**（用户会看到"盈利筛选里
    混着亏钱的单子"）。
  - 修法：改为先算 `net_amount = net_profit − commission.fillna(0)` 再判正负。
  - ✅ **v5.13 用户拍板：改净额**。两处均先算 `net_amount` 再判正负，
    并给下拉加 tooltip「按净额 = 平仓盈亏 − 手续费判断」。断言：毛利 +100 / 手续费 150
    的单子现在正确落进「仅亏损」。

- **O-2【架构债残留】✅ 已修（三个线程迁入 workers.py）** ——
  `ui/workers.py` 只收口了"行情同步类"线程，§2 的宣称不成立：
  以下 4 个 QThread 仍定义在各自业务文件里 ——
  | 线程 | 位置 | 用途 |
  |---|---|---|
  | `_BacktestRunThread` | `ui/views/backtest.py:121` | 回测计算 |
  | `_ConstituentsWorker` | `ui/dialogs/bulk_download.py:47` | 指数成分股解析 |
  | `FuturesImportWorker` | `ui/dialogs/import_futures.py:19` | 交割单解析（子线程内还读 SQLite） |
  | `UpdateCheckerThread` | `core/updater.py:9` | 版本检测（落点在 core，非 UI） |

  **现状判定**：`ui/workers.py` 现有 `ScanWorker` / `SyncWorker` / `SingleSyncWorker` 三个，
  全是"数据湖同步"这一类。所以准确说法是**"行情同步类线程已收口"**，不是"线程已收口"。
  ✅ **v5.13 修法：② 全搬**（三个 UI 线程都进 workers.py，`UpdateCheckerThread` 留在
  core/updater.py 因为它本就不属于 UI 层；§2 表述已同步改成准确版本）。
  新名字：`BacktestRunWorker` / `ConstituentsWorker` / `FuturesImportWorker`。

- **O-3【文档字符串失真 · 回归隐患】✅ 已修** ——
  `data/sync_service.py:118` 把数据起点写成了 2016-01-01：
  `refresh_one` 的 docstring 写着 `默认 DEFAULT_MIN_DATE(2016-01-01)`，而该文件第 47 行的
  实际值是 `DEFAULT_MIN_DATE = "20100101"`（§9-M3 修正后的正确值）。
  **危害不在当下在未来**：下一个人（或下个模型的我）照着 docstring 就会把起点"修"回 2016，
  §9-M3 的数据静默缩水**原样复发**。
  ✅ **v5.13 已改**：docstring 改成 2010-01-01，并显式注明"数据窗 2010 ≠ 评估窗 2016"。

- **O-4【行为与文案不符】✅ 已修（改默认增量）** ——
  行情页「☁️ 云端同步」恒为全量重拉，用户没有增量选项：
  `ui/views/market.py:174-184` 的 `force_sync_cloud()` 固定传 `force_full=True`，
  所以对**已缓存**的标的点一次 = 从 2010 整段重下一次（慢、浪费请求、有被限流风险）。
  这与数据管理页已经做好的「🔄 更新到最新 / ⟳ 重新全量下载」双按钮体验**不一致**。
  ✅ **v5.13 已修**：`force_sync_cloud` 改名 `sync_cloud`（名字不再撒谎），
  `force_full` 恒为 **False** —— 本地有数据=增量补最新、没数据=自动全量。
  另加 `lbl_sync_status` 回执（「已是最新，无需更新」/「已更新，新增 N 行」/「同步失败」），
  杜绝"点了没反应"。全量下载仍只在「🗄 数据管理」页（§10-10）。

- **O-5【竞态防护缺失】✅ 已修** —— 回测页的同步结果没有"标的是否已被切换"的校验：
  `ui/views/backtest.py:1042-1053` `_on_synced` 拿到结果就直接落库渲染；
  而 `market.py:190-192` 有一模一样场景却写了守卫（`if symbol != self.current_symbol: return`）。
  后果：拉取期间用户切了标的，旧标的的数据会渲染到新标的上。
  ✅ **v5.13 已修**：`_on_synced` 比对 `symbol != self.current_symbol` 即丢弃并复位 busy；
  `_on_index_synced` 比对 `result["symbol"] != self._pending_index["symbol"]` 即丢弃。
  **这是"同一类防护只做了一半"的典型** —— 加防护时务必全局搜一遍同一场景还有几处
  （已固化为 §11.5 第 11 条）。

- **O-6【文档过时】✅ 已修** —— §4 目录树的行数与版本号全面与磁盘不符：
  `data_feed.py` 文档 965 / 实际 827，`database.py` 479/437，`backtest.py` 1403/1253，
  `review.py` 1248/1122，`engine.py` 157/158；`config/settings.py` 的 `APP_VERSION`
  早就是 **1.4.1**，旧文档仍写 1.1.0(⚠)。**§4 现在带行数，每次大改后务必重跑一次行数统计。**

- **O-7【重复代码】✅ 已修（4 合 1）** —— 图表样式函数被复制了 **四份**（通读时只数出三份，
  漏了 market.py；**教训：数重复要全局 grep 函数名，别靠记忆**）：
  - `_apply_pokorny_style`：`ui/views/review.py` 与 `ui/widgets/yearly_review.py`
  - `_apply_pokorny_axis`：`ui/views/backtest.py` 与 `ui/views/market.py`
  - 净值"排序→cumsum→按盈亏选色→plot+fillLevel"：review / yearly_review / backtest / dashboard
  - ✅ **v5.13**：新增 **`ui/widgets/chart_style.py`**，收敛为
    `apply_pokorny_style(chart, title, background, grid_alpha, margins)` 与
    `plot_equity_curve(chart, values, fill_base, width, positive)`。
    ⚠ **坑**：行情页的 `GraphicsLayoutWidget.addPlot()` 返回的是 **PlotItem** 不是 PlotWidget，
    所以新函数两种类型都要能吃（`hasattr(chart,'getPlotItem')` 分流）。
    改外观请只改 chart_style.py。

- **O-8【小坑】✅ 已修（4 项全清）** —— §9-J 三项未修 + 一处文档描述有误：
  - ✅ `review.py`：`engine.df` 为空时也走 `refresh_time_picker`（不再残留陈旧月份项）。
  - ✅ `review.py`：「仅日期」分支解析异常改为 `continue`（算不出就不参与统计，绝不塞 0）。
  - ✅ `review.py`：`toggle_review_mode` 切到年视图时先 `playback_chart.clear()`，
    杜绝回放残留。
  - 文档纠错（v5.12 已记录，v5.13 顺带处理）：`screenshot_gallery.py` 的
    `path.rsplit('.', 1)[-1]` 对无扩展名文件**不会抛 IndexError**（`rsplit` 返回整串），
    只是拿到错误的"扩展名"。
  - ✅ `screenshot_gallery.py`：`set_paths` 不再静默丢弃磁盘上已失效的截图路径 ——
    现在**保留条目并标注「⚠ 已丢失」+ tooltip 给出文件路径**，由用户自己决定是否删除；
    `get_paths` 照常序列化，杜绝"用户无感知、保存时把路径写没"的变相删数据。

- **O-9【文档过时】✅ 已修（§3 改 17 项）** —— Dashboard KPI 是 17 项，不是 18 项：
  `ui/views/dashboard.py` 的 `metric_keys` 实测 17 个
  （净额/毛利/手续费/收益率/胜率/盈亏比/最大回撤/交易次数/盈利次数/亏损次数/初始资金/
  平均盈利/平均亏损/最大单笔赚/最大单笔亏/平均持仓/最长持仓）。

- **O-10【性能 · 未动，列入第三梯队】复盘页回放与交易日历反复全量读 Parquet**：
  `_render_trade_playback`（`review.py:999-1007`）每选中一笔交易就
  `data_lake.load_data("kline_daily", root)` 读整份历史；
  `_trading_dates_for`（`:607-621`）首次访问某品种时也要读一份（虽有 `_trading_cal` 缓存日期，
  但读文件这一步没省）。同月内连点 20 笔交易 = 20 次全量 IO。
  建议：按 symbol 做一份 LRU 缓存（只缓存 df 或只缓存 date 列），或至少复用
  `_trading_dates_for` 已经读过的那份。

- **✅ v5.12 已逐项核对"通过"（未来的我不必再查）**：
  ① 净额口径：`analyzer.py` / `dashboard.py` / `review.py` 图表 / `yearly_review.py` 四处全对；
  ② 幂等：`INSERT OR IGNORE` + `internal_id` MD5（切片 `#i` 盐）仍在；
  ③ FIFO 全局排序只跑一次（`data_feed.py:767-771`）；
  ④ 孤儿四层防御齐全（标记/黄条/补录/自动缝合）；
  ⑤ 同步两大铁则：`fresh_within_days=0`、空增量=skipped 均健在（`sync_service.py:68/159-186`）；
  ⑥ 数据起点 2010 未被改回；
  ⑦ 勾选中自绘 ☐/☑ + 唯一切换入口 + `NoSelection`（`data_manager.py:202/360/403`）；
  ⑧ 危险动作隔离 + 键入「清空」二次确认；
  ⑨ 退市/无数据的人话文案（`friendly_fetch_message`）已接入 4 处；
  ⑩ 版本号两处同步（1.4.1 = 1.4.1）；⑪ `scan_cache` zone 仍不存在（属 B1 前置，非欠账）。

---

## 10. AI 协作最高指令（不可妥协）

1. **Michael Pokorny UI 准则**：任何新增图表元素必须"抗锯齿、去描边、单色高对比"。
2. **防阻塞底线**：涉及 Parquet 读取或网络拉取，一律封装 QThread 异步，UI 丝滑优先。
3. **架构纪律**：新功能先想落点——`core`(纯计算) / `data`(获取存储) / `ui`(展示)；
   **绝不在 ui 写 SQL 或爬虫**，UI 一律经 `DataEngine`/`StrategyStore` 等门面取数。
4. **幂等与诚实**：DB 插入保持 `INSERT OR IGNORE`；任何"看起来能填其实源里没有"的数据
   宁可显示 `—`/降级，**绝不虚构**（时间、价格、持仓一律适用）。
5. **全量输出兜底**：修改核心文件尽量给全量代码或明确插入锚点，防小白复制缩进灾难。
6. **隐私铁律**：用户私有公式/示例不得写入仓库、示例与占位；`.gitignore` 已忽略私密函数文件。
7. 完成一项功能后，**回写本文档 §6/§7** 的状态，保持记忆与磁盘一致。
8. **每次会话结束前**，把本次改动摘要追加进 §8 版本表 + §9 债务表（若有新发现），
   让下一次的"我"打开这份文档就能接上，不需要重新通读 6400 行代码。
9. **【控件一致性铁律 · v5.6 新增】同一类控件必须同一张脸，且点击热区必须 == 视觉区域**：
   - **复用优先**：数值输入一律用 `ui/widgets/custom_widgets.py` 的
     `NoWheelSpinBox` / `NoWheelDoubleSpinBox` / `NoWheelComboBox` / `NoWheelDateEdit`，
     样式一律引用该文件导出的常量（当前 `SPINBOX_QSS` = 空串 = 原生渲染）。
   - **禁止半截 QSS**（本条由真实 Bug 倒逼产生，务必牢记）：
     `QSpinBox` / `QDoubleSpinBox` / `QComboBox` / `QDateEdit` 都是 Qt **复合控件**。
     只给控件本体写 QSS（例 `QDoubleSpinBox { padding…; border-radius… }`）而**不写全
     子控件**（`::up-button` / `::down-button` / `::up-arrow` / `::down-arrow` /
     `::drop-down` / `::down-arrow` …），Qt 会用默认度量重绘子控件，必然导致
     **图标样式漂移** 与 **热区与视觉错位**（历史 Bug：风控行上箭头只有右半边能点，
     长期未解）。
     → 要美化就写**完整**的 QSS，且必须收敛到 `custom_widgets.py` 统一导出，
     由所有调用方共用，**绝不在业务页面就地 `setStyleSheet`**。
   - **尺寸要给足**：窄控件会挤压箭头/下拉按钮，同样造成热区异常；
     数值控件最小宽度不得小于 72px。
   - **新增任何输入控件后自检**：① 与同类控件图标是否一致？② 上下/下拉按钮整块是否
     都能点？③ 是否复用了统一常量而非就地写样式？
10. **【按钮层级 + 文案铁律 · v5.10 新增】**：
   - **危险动作物理隔离**：会造成大范围/不可逆损失的操作（清空、批量删除）不能与
     日常高频按钮同排。低危=正常按钮；中危=同排但红色+二次确认；**高危=另找角落 + 低调呈现
     + 键入确认词**（如清空分区要求输入「清空」）。做得越费事，误操作率越低。
   - **面向用户说人话**：绝不在界面上甩内部术语（"增量更新 / 强制全量重拉 / 断点续传 /
     前复权 / 熔断"都不许直接当按钮名）。规则：动作动词 + 用户能猜到的对象（「更新到最新」
     「重新全量下载」），细节差异放 tooltip / 次要文案。
   - **报错要"分类安抚"而非"统一吓唬"**：失败提示必须区分"网络/限流"与"数据本身没有
     （退市、停牌、代码错）"，后者明确告诉用户这不是他的错、且本地历史仍可用（§9-N5）。
11. **【统一绘图窗口 · v6.0 B3】凡"公式驱动的叠层"只能走一条底层管线**：
   引擎侧 = `core/formula/draw.py`（语句分类 + DrawSpec/DrawData IR + COLOR_TABLE），
   渲染侧 = `ui/widgets/draw_overlay.py`（唯一 `OverlayPainter`）。
   **任何页面（回测 K线、市场行情、未来新图）展示 STICKLINE/DRAWICON/公式线/状态柱，
   都禁止自己写绘图逻辑**；想改样式/语义 = 改引擎 IR 或 OverlayPainter 一处，
   杜绝"每个图表一对一地改"。底层契约见 §7-B3 主案规格。

---

## 11. 速查表：给"刚醒来的我"的 30 秒重启手册

> 以下内容是从 v5.5 全仓通读里提炼的**最高密度结论**。
> 如果你只有 30 秒，只看这一节；如果你要动刀，再按指引去翻对应章节。

### 11.1 一句话概括这个软件
一个**期货交割单驱动的复盘系统**（本地 SQLite + PyQt6 桌面端），
顺带挂了一个**A 股行情浏览 + 单股公式回测**的工作台。
两条链路几乎不交叉：**复盘链路只认期货，回测链路只认 A 股（且只能做多）**。

### 11.2 数据往哪流（记住这 4 跳就够了）
```
Excel(交割单) →data/data_feed.py 解析+FIFO缝合→ models/trade.py TradeRecord
             →core/engine.py DataEngine(唯一门面)→ core/database.py SQLite
             →core/analyzer.py 算指标 → ui/** 只负责画

AkShare →data/akshare_feed.py→ ~/.jian_data/data_lake/*.parquet (数据湖)
        →core/formula 通达信 DSL 求值 → core/backtest.py 单股回测 → ui/views/backtest.py
```
**UI 永远不许跳过 DataEngine 去碰 SQL**（v5.12 复核：§9-H 的 3 处违规**已全部修完**，
`market.py` / `backtest.py` 现在都走 `engine.search_symbol` + `SingleSyncWorker`，**保持住**）。

### 11.3 用户数据在哪（改代码时别把仓库当数据库）
| 内容 | 路径 |
|---|---|
| 业务库（流水/持仓腿/覆盖/名册 5 表） | `~/.jian_data/jian_trades.db` |
| 偏好（目前只有 `time_precision`） | `~/.jian_data/preferences.json` |
| 回测策略 + 每标的指标档案 | `~/.jian_data/backtest_strategies.json` |
| 行情数据湖（8 个 zone，parquet） | `~/.jian_data/data_lake/` |
| 复盘截图 | `~/.jian_data/screenshots/` |
| 仓库根目录 `screenshots/` | **空壳历史遗留，勿用** |
| 仓库根目录 `实例*.xlsx` / `实例函数.txt` | **用户隐私，已被 .gitignore 忽略，勿提交勿引用** |

### 11.4 我要改 X，该动哪个文件？
| 想改的东西 | 落点 |
|---|---|
| 加一个统计指标 | `core/analyzer.py`（加 key）→ `ui/views/dashboard.py`（加一行 `metric_keys`） |
| 改交割单解析/缝合规则 | `data/data_feed.py`（纯函数，改完务必验"分批导入 ≡ 一次性导入"） |
| 加一个公式函数 | `core/formula/runtime.py`：`FUNCTIONS` 注册 + `ARITY` 声明元数 |
| 改回测撮合/风控 | `core/backtest.py`（`_run_on_signals` 是纯函数，好测） |
| 加一个技术指标（画图用，非公式） | `core/indicators.py`：`REGISTRY` + `OUTPUTS` |
| 加一个数据湖 zone | `data/market_db.py` 的 `self.zones` 字典 |
| 加一个用户偏好 | `core/preferences.py`：`DEFAULTS` 加 key 即可 |
| 改数值控件外观 | `ui/widgets/custom_widgets.py` 的 `SPINBOX_QSS`（**唯一可改点**，勿就地写 QSS，§10-9） |
| 改回测区间档位 | `ui/views/backtest.py` 的 `_PRESET_ORDER` + `_date_from_preset`（含 2016 下沿） |
| 改 Dashboard 日历热力图 | `ui/widgets/calendar_heatmap.py`（纯手绘控件）+ `dashboard.py` 的 `_prepare_calendar` / `_render_calendar` |
| 增删/清理数据湖缓存 | 原语在 `data/market_db.py`；页面在 `ui/views/data_manager.py`（⚠ 删完要 `_rescan` 刷新） |
| 改行情同步/抓取节流 | `data/sync_service.py`（增量合并 + `ThrottlePolicy` 都在这里，**勿在 UI 里另起炉灶**） |
| 给页面加后台任务 | `ui/workers.py` —— 全 app 唯一 QThread 定义处（Scan/Sync/SingleSync/BacktestRun/Constituents/FuturesImport 六个 Worker），**禁止页面自造线程类**（§9-O2） |
| 改版本号 | `config/settings.py` 的 `APP_VERSION` **和** 仓库 `version.json`（两处必须同步） |
| 回测页 UI | `ui/views/backtest.py`（⚠ **1417 行**，先想清楚插在哪一段；结构顺序=顶部工具栏→①函数→②条件→③指数→运行条→风控行→KPI→K线控制→结果页签→导出按钮） |
| 复盘页 UI | `ui/views/review.py`（⚠ **1119 行**；`_build_monthly_mode` 月视图 / `YearlyReviewPanel` 年视图 / `_render_trade_playback` 回放三块最重） |
| M2/M3 新子页 | `ui/views/backtest_module.py` 里换掉 `_ComingSoonPage` |
| 改图表轴样式 / 净值曲线绘制 | **`ui/widgets/chart_style.py`（唯一来源，v5.13）** —— `apply_pokorny_style`（PlotWidget/PlotItem 都兼容）+ `plot_equity_curve`；业务页面**禁止就地写轴样式** |
| 给图表加"公式叠层"（STICKLINE/公式线/状态柱/DRAWICON） | **两条路都唯一**：引擎语义改 `core/formula/draw.py`；画图改 `ui/widgets/draw_overlay.py` 的 `OverlayPainter`（§7-B3 主案，v6.0 P0）。**禁止任何页面自己读函数文本再画** |
| 改行情页"云端同步"行为 | `ui/views/market.py` 的 `sync_cloud`（v5.13 起默认增量：本地有数据=增量、没数据=全量；全量重下在「🗄 数据管理」页） |
| 改回测结果导出 | CSV：`ui/views/backtest.py` `_compose_result_csv`（纯函数）+ `_last_meta`（配置快照，`start_backtest` 定格）；PNG 报告图：**`ui/widgets/backtest_report.py`**（离屏 grab 渲染）；标签/配色/风控文案只改 **`core/backtest.py`**（三处同源） |

### 11.5 最容易踩的坑（血泪，别重犯，持续累积到 12 条）
1. **净额 = `net_profit − commission`**。任何"结果类"指标（胜率/盈亏比/极值/净值曲线）
   漏掉手续费就是造假。已知 `yearly_review.py` 就踩了这个坑（§9-F）。
2. **`trade_time` 永远是纯日期 00:00:00**，绝不自动填时分；真实时刻放 `*_fill_time`。
   没有开仓时间就显示 `—`，**绝不猜**。
3. **任何"看起来能填其实源里没有"的值，一律 `—`/降级**，不要 0、不要 00:00、不要编。
4. **DB 一律 `INSERT OR IGNORE`**，`internal_id` = MD5 确定性哈希（FIFO 切片会追加 `#i` 盐）。
   改哈希规则 = 让老库防重失效，**千万别动**。
5. **FIFO 必须全局排序后只跑一次**（按 日期→时刻→序号），这是"分批导入 ≡ 一次性导入"的地基。
6. **耗时 I/O 一律 QThread**：导入解析、拉个股行情、拉指数、回测计算、版本检测，共 5 处。
7. **别给复合控件写半截 QSS**（§10-9）：`QSpinBox/QDoubleSpinBox/QComboBox/QDateEdit`
   只写本体不写子控件 ⇒ 箭头图标漂移 + 点击热区错位。要美化就写全，并收敛到
   `custom_widgets.py`。
8. **行情同步两大铁则**（§9-M，改 `sync_service.py` 前必读）：
   ① "已最新"判据必须是**末日==今天**（`fresh_within_days=0`）——放宽=增量永远滞后一天拿不到当日 bar；
   ② **空增量 = 已最新不是失败**——增量模式只请求一次、空返回即 `skipped`，不重试不熔断。
   数据起点保持 2010（个股全历史），评估窗才是 2016，两者别混。
9. **别让两套机制同时 toggle 同一个选择状态**（§9-N1）：Qt 原生 indicator 点击会**自动切换**，
   若你再监听 `cellClicked` 手动切换一次 = 双重触发 = 等于没点。要么只用原生、要么（推荐）
   完全自绘（☐/☑ 字符 + 整格点击唯一入口），且关掉行选择以免出现难看的选中高亮。
10. **别照着 docstring 改常量**（§9-O3 血的教训）：`sync_service.refresh_one` 的 docstring
    一度把数据起点写成 2016 而实际常量是 2010（v5.13 已改正）。**改任何常量前先看代码本体，
    再从代码反向修文档**；反过来做就是"静默回归"。
11. **同类防护要做就做全套**：`market.py` 有"同步结果 vs 当前标的"的竞态守卫，
    `backtest.py` 同场景却漏了（§9-O5，v5.13 已补齐）。加防护时全局搜一遍同一场景还有几处。
12. **图表样式只改 `ui/widgets/chart_style.py`**（§9-O7）：此前 4 处重复、改一处漏三处。
    且行情页传的是 **PlotItem**（`GraphicsLayoutWidget.addPlot()` 的返回值）不是 PlotWidget ——
    给图表封装公共函数前先想清楚"调用方手里到底是哪种类型"。
13. **【v5.13 修订 · Qt 布局坑】顶部栏末尾的 `QLabel` 会"吞掉"主区高度**：
    页面顶部一条 `QHBoxLayout`（搜索栏/标题/工具按钮），下方是 `QSplitter` 主区，
    只要顶部栏的**末尾**多了一个 `QLabel`（vertical sizePolicy = Preferred，而按钮/复选框是 Fixed），
    Qt 会把整段富余垂直空间全部分给顶部栏，标题会被拉到几百像素高、主区被压成 sizeHint。
    触发条件是"QLabel 在末尾"，换位置/换按钮都不会。
    **根治**：主区 widget 永远显式 `layout.addWidget(main_widget, 1)` 给 stretch>0，
    富余空间才不受 Qt 启发式影响。`backtest.py` 本来就这么写所以没翻车，
    `market.py` 原本忘了写，被 v5.13 新增的同步状态 QLabel 一脚踢翻。

### 11.6 当前"下一步做什么"的推荐顺序（v6.0 刷新）

> ✅ ~~第一梯队 O-3/O-5/O-7/O-2/O-8~~（v5.13） · ✅ ~~第二梯队 O-1/O-4~~（v5.13）
> ✅ ~~§7-A2 导出当前结果（CSV+PNG）~~（v5.14/5.15/5.16）
> **→ ⭐ [P0] §7-B3 公式统一绘图（引擎级，2026-09-10 用户定稿为最高优先级）** ——
> 规格见 §7-B3 主案：M0 契约层 → M1 求值层 → M2 渲染层+回测页接入 → M3 收尾 →
> M4 远期（市场行情等全图复用同一 OverlayPainter）。
> 之后才是下面**常规功能清单**（每项先聊方案再动手）：

- 2. §7-A1 行情涂鸦板持久化（需先定存储；可复用「🗄 数据管理」页做删除入口）。
- 3. **§7-A4 回测结果历史存档** —— 设计要点见 §7-A4，动工前先问要"复现"还是"留档"。
- 4. §9-O10 复盘页 Parquet 读取加 LRU 缓存（体验向）。
- 5. §9-L 大文件拆分（`backtest.py` / `review.py`）—— 与功能改动错开窗口做纯重构。
- 6. §7-B1/B2（M2/M3 真实功能）—— A3 前置已清；B1 需先建 `scan_cache` zone。
- 7. §6.5「远期」组合级多标的引擎 —— 全新模块，勿并入 M1。

### 11.7 收工前自检清单
- [ ] 改动的模块状态（`[x]` / `[~]` / `[ ]`）在 §6 / §7 同步了吗？
- [ ] 有没有引入新的"UI 直连 SQL/爬虫"？（§9-H）
- [ ] 净额口径有没有被绕过？（§5.3-B）
- [ ] 虚构数据了吗？（时间 / 价格 / 持仓）
- [ ] 耗时 I/O 走 QThread 了吗？
- [ ] 新发现的技术债写进 §9 了吗？本次摘要写进 §8 了吗？
- [ ] **改了常量/数值，同文件与跨文件的 docstring / 注释同步改了吗？**（§9-O3、§11.5-10）
- [ ] **改了文件规模，§4 的行数要不要重刷？**（§4 现在带实测行数）
- [ ] 同类防护（竞态守卫 / 口径 / 文案）是不是只改了一处、漏了另一处？（§11.5-11）
